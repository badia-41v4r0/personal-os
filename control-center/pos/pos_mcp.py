#!/usr/bin/env python3
"""Servidor MCP (stdio, solo librería estándar) con las herramientas del Personal OS.

Corre dentro del contenedor del agente y no sabe nada de la base de datos: reenvía cada llamada al socket /run/pos/pos.sock,
que el Host Agent abre solo durante el turno. La credencial la pone el Host Agent, así que el agente nunca la ve.
"""
import json
import os
import socket
import sys

SOCK = os.environ.get("POS_SOCK", "/run/pos/pos.sock")
MAX = 60_000
TOOLS = [
    {"name": "pos_read", "description": "Lee datos del Personal OS: nombre de la herramienta y argumentos. Mira pos_tools para ver cuáles tienes.",
     "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}, "args": {"type": "object"}}, "required": ["name"]}},
    {"name": "pos_action", "description": "Pide una acción. Puede ejecutarse, quedar pendiente de aprobación del usuario o denegarse: lee siempre `status`. Nunca insistas si se deniega.",
     "inputSchema": {"type": "object", "properties": {"capability": {"type": "string"}, "args": {"type": "object"}, "reason": {"type": "string"},
                                                      "idempotency_key": {"type": "string"}}, "required": ["capability", "reason"]}},
    {"name": "pos_tools", "description": "Lista las lecturas y capacidades de esta ejecución.", "inputSchema": {"type": "object", "properties": {}}},
]


def gateway(msg: dict) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(120)
        s.connect(SOCK)
        s.sendall(json.dumps(msg).encode() + b"\n")
        data = b""
        while not data.endswith(b"\n"):
            part = s.recv(65536)
            if not part:
                break
            data += part
    return json.loads(data or b"{}")


def call(name: str, a: dict) -> dict:
    if name == "pos_tools":
        return gateway({"kind": "tools"})
    if name == "pos_read":
        return gateway({"kind": "read", "name": a.get("name", ""), "args": a.get("args") or {}})
    if name == "pos_action":
        return gateway({"kind": "action", "name": a.get("capability", ""), "args": a.get("args") or {}, "reason": a.get("reason", ""),
                        "idempotency_key": a.get("idempotency_key")})
    return {"error": "herramienta desconocida"}


def handle(req: dict) -> dict | None:
    method, rid = req.get("method"), req.get("id")
    if rid is None:
        return None
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": rid, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                                                       "serverInfo": {"name": "pos", "version": "1"}}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        p = req.get("params") or {}
        try:
            out = json.dumps(call(p.get("name", ""), p.get("arguments") or {}), ensure_ascii=False)[:MAX]
            return {"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": out}]}}
        except OSError as e:
            return {"jsonrpc": "2.0", "id": rid, "result": {"isError": True, "content": [{"type": "text", "text": f"Sin conexión con el Personal OS: {e}"}]}}
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "método desconocido"}}


def main() -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        r = handle(json.loads(line))
        if r is not None:
            sys.stdout.write(json.dumps(r, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
