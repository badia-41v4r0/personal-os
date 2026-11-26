import json
import socket
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "virtual-computers/mcp"))
import vc_mcp  # noqa: E402


def test_protocolo_mcp(tmp_path, monkeypatch):
    sock = tmp_path / "vc.sock"
    seen = []
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(sock))
    srv.listen(5)

    def serve():
        for _ in range(3):
            c, _ = srv.accept()
            msg = json.loads(c.makefile().readline())
            if msg["op"] == "vm_list":
                res = {"maquinas": []}
            else:
                seen.append(msg)
                res = {"codigo": 0, "salida": "42"} if msg["op"] == "exec" else {"png_base64": "AAAA"}
            c.sendall((json.dumps(res) + "\n").encode())
            c.close()

    threading.Thread(target=serve, daemon=True).start()
    monkeypatch.setattr(vc_mcp, "SOCK", str(sock))
    monkeypatch.setattr(vc_mcp, "_vm_cache", None)
    init = vc_mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
    assert init["result"]["protocolVersion"] == "2025-06-18" and "tools" in init["result"]["capabilities"]
    assert vc_mcp.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    names = {t["name"] for t in vc_mcp.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]}
    assert {"vc_request", "vc_exec", "vc_destroy"} <= names and not any(n.startswith("vm_") for n in names)
    r = vc_mcp.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "vc_exec", "arguments": {"command": "echo 42"}}})
    assert '"42"' in r["result"]["content"][0]["text"] and seen[0] == {"op": "exec", "args": {"command": "echo 42"}}
    r = vc_mcp.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "vc_screenshot", "arguments": {}}})
    assert r["result"]["content"][0]["type"] == "image"
    bad = vc_mcp.handle({"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "rm_rf", "arguments": {}}})
    assert "error" in bad


def test_herramientas_de_maquina_solo_si_el_agente_tiene(monkeypatch):
    monkeypatch.setattr(vc_mcp, "_vm_cache", None)
    monkeypatch.setattr(vc_mcp, "gateway", lambda op, a: {"maquinas": [{"id": "veriluoc"}]} if op == "vm_list" else {"ok": True})
    names = {t["name"] for t in vc_mcp.tools()}
    assert {"vm_exec", "vm_screenshot", "vm_copy_out", "vm_click"} <= names
    r = vc_mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "vm_exec", "arguments": {"command": "id"}}})
    assert r["result"]["isError"] is False


def test_sin_pasarela_no_hay_herramientas_de_maquina(monkeypatch):
    monkeypatch.setattr(vc_mcp, "_vm_cache", None)
    monkeypatch.setattr(vc_mcp, "SOCK", "/nonexistent/vc.sock")
    assert not any(t["name"].startswith("vm_") for t in vc_mcp.tools())
