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
        for _ in range(2):
            c, _ = srv.accept()
            msg = json.loads(c.makefile().readline())
            seen.append(msg)
            res = {"codigo": 0, "salida": "42"} if msg["op"] == "exec" else {"png_base64": "AAAA"}
            c.sendall((json.dumps(res) + "\n").encode())
            c.close()

    threading.Thread(target=serve, daemon=True).start()
    monkeypatch.setattr(vc_mcp, "SOCK", str(sock))
    init = vc_mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
    assert init["result"]["protocolVersion"] == "2025-06-18" and "tools" in init["result"]["capabilities"]
    assert vc_mcp.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    names = {t["name"] for t in vc_mcp.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]}
    assert {"vc_request", "vc_exec", "vc_destroy"} <= names
    r = vc_mcp.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "vc_exec", "arguments": {"command": "echo 42"}}})
    assert '"42"' in r["result"]["content"][0]["text"] and seen[0] == {"op": "exec", "args": {"command": "echo 42"}}
    r = vc_mcp.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "vc_screenshot", "arguments": {}}})
    assert r["result"]["content"][0]["type"] == "image"
    bad = vc_mcp.handle({"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "rm_rf", "arguments": {}}})
    assert "error" in bad
