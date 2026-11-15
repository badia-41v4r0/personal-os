#!/usr/bin/env python3
"""Servidor MCP (stdio, solo librería estándar) que da a un agente su ordenador virtual.

Corre dentro del contenedor de la sesión. No sabe nada de Docker ni del panel: reenvía cada llamada al socket
/run/vc/vc.sock, que el Host Agent abre solo durante el turno y que solo puede tocar el ordenador de esa sesión.
"""
import json
import socket
import sys

SOCK = "/run/vc/vc.sock"
TOOLS = [
    {"name": "vc_info", "description": "Estado de tu ordenador virtual (id, perfil, si está en marcha).",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "vc_request", "description": "Pide tu ordenador virtual si aún no tienes uno (sin internet, caduca a las 2 h). Devuelve su id e instrucciones.",
     "inputSchema": {"type": "object", "properties": {"motivo": {"type": "string"}}, "required": ["motivo"]}},
    {"name": "vc_exec", "description": "Ejecuta un comando bash en tu ordenador virtual (usuario sin privilegios, carpeta ~/trabajo). Devuelve salida y código.",
     "inputSchema": {"type": "object", "properties": {"command": {"type": "string"}, "timeout": {"type": "integer", "default": 60}}, "required": ["command"]}},
    {"name": "vc_read_file", "description": "Lee un archivo de texto de tu ordenador (dentro de /home/vc).",
     "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "vc_write_file", "description": "Escribe un archivo en tu ordenador (dentro de /home/vc).",
     "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "vc_screenshot", "description": "Captura la pantalla de tu ordenador (perfiles browser y desktop).",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "vc_open_url", "description": "Abre una URL en el navegador de tu ordenador (perfiles browser y canvas). Devuelve URL final y título.",
     "inputSchema": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}},
    {"name": "vc_page_text", "description": "Texto visible y enlaces de la pestaña abierta en el navegador. Más barato que una captura: úsalo para leer.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "vc_click", "description": "Clic en la pantalla (coordenadas de la captura, 1280x800). Devuelve una captura después.",
     "inputSchema": {"type": "object", "properties": {"x": {"type": "integer"}, "y": {"type": "integer"},
                     "button": {"type": "string", "enum": ["left", "middle", "right"], "default": "left"},
                     "double": {"type": "boolean", "default": False}}, "required": ["x", "y"]}},
    {"name": "vc_type", "description": "Escribe texto con el teclado donde esté el foco. Devuelve una captura después.",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
    {"name": "vc_key", "description": "Pulsa teclas o atajos separados por espacios (p. ej. «Return», «ctrl+l», «Page_Down», «alt+Left»). Devuelve una captura.",
     "inputSchema": {"type": "object", "properties": {"keys": {"type": "string"}}, "required": ["keys"]}},
    {"name": "vc_scroll", "description": "Desplaza con la rueda en (x, y). Devuelve una captura después.",
     "inputSchema": {"type": "object", "properties": {"x": {"type": "integer", "default": 640}, "y": {"type": "integer", "default": 400},
                     "direction": {"type": "string", "enum": ["up", "down", "left", "right"]}, "amount": {"type": "integer", "default": 3}},
                     "required": ["direction"]}},
    {"name": "vc_form_fields", "description": "Campos (f1, f2…) y botones (b1…) del formulario de la pestaña abierta, con su etiqueta y valor, y bloqueos (captcha, inicio de sesión, SSO).",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "vc_form_fill", "description": "Rellena campos por referencia: {\"f1\": \"texto\", \"f3\": true}. Desplegables con el texto de la opción. No pulsa botones ni envía nada.",
     "inputSchema": {"type": "object", "properties": {"valores": {"type": "object"}}, "required": ["valores"]}},
    {"name": "vc_form_attach", "description": "Adjunta un documento de la solicitud (por su huella SHA-256) a un campo de archivo.",
     "inputSchema": {"type": "object", "properties": {"ref": {"type": "string"}, "documento": {"type": "string"}}, "required": ["ref", "documento"]}},
    {"name": "vc_destroy", "description": "Elimina tu ordenador virtual cuando hayas terminado.",
     "inputSchema": {"type": "object", "properties": {}}},
]


def gateway(op: str, args: dict) -> dict:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(700)
    s.connect(SOCK)
    s.sendall((json.dumps({"op": op, "args": args}) + "\n").encode())
    buf = b""
    while not buf.endswith(b"\n"):
        chunk = s.recv(1 << 20)
        if not chunk:
            break
        buf += chunk
    s.close()
    return json.loads(buf or b'{"error": "sin respuesta"}')


def send(msg: dict) -> None:
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def handle(req: dict) -> dict | None:
    m, rid = req.get("method"), req.get("id")
    if rid is None:
        return None  # notificación
    if m == "initialize":
        ver = (req.get("params") or {}).get("protocolVersion", "2025-06-18")
        return {"jsonrpc": "2.0", "id": rid, "result": {"protocolVersion": ver, "capabilities": {"tools": {}},
                                                         "serverInfo": {"name": "vc", "version": "1.0"}}}
    if m == "ping":
        return {"jsonrpc": "2.0", "id": rid, "result": {}}
    if m == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}}
    if m == "tools/call":
        p = req.get("params") or {}
        name = p.get("name", "")
        if name not in {t["name"] for t in TOOLS}:
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": "herramienta desconocida"}}
        try:
            r = gateway(name.removeprefix("vc_"), p.get("arguments") or {})
        except OSError as e:
            r = {"error": f"pasarela no disponible: {e}"}
        if "png_base64" in r:
            content = [{"type": "image", "data": r["png_base64"], "mimeType": "image/png"}]
        else:
            content = [{"type": "text", "text": json.dumps(r, ensure_ascii=False)[:100_000]}]
        return {"jsonrpc": "2.0", "id": rid, "result": {"content": content, "isError": "error" in r}}
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "método desconocido"}}


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            out = handle(json.loads(line))
        except Exception as e:  # noqa: BLE001
            out = {"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": str(e)[:200]}}
        if out:
            send(out)


if __name__ == "__main__":
    main()
