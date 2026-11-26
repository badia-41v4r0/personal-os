"""Lee y navega el Chromium de una máquina local por CDP (127.0.0.1:9222 DENTRO de la VM). Solo librería estándar.

No se instala en la VM: el Host Agent lo manda por SSH (`python3 - <op> [url]`) y lee el JSON que imprime.
Recibe la operación por argv, nunca código del agente. Ops: `open <url>` y `text`.
"""
import base64
import json
import os
import socket
import struct
import sys
import time
import urllib.request
from urllib.parse import quote, urlparse

BASE = "http://127.0.0.1:9222"
TEXTO = """JSON.stringify({url: location.href, titulo: document.title,
  texto: (document.body ? document.body.innerText : '').slice(0, 60000),
  enlaces: [...document.querySelectorAll('a[href]')].filter(a => a.innerText.trim()).slice(0, 200)
    .map(a => ({texto: a.innerText.trim().slice(0, 100), url: a.href}))})"""


class WS:
    def __init__(self, url: str):
        u = urlparse(url)
        self.s = socket.create_connection((u.hostname, u.port), timeout=30)
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall((f"GET {u.path} HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\nUpgrade: websocket\r\n"
                        f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.s.recv(4096)
            if not chunk:
                raise OSError("handshake")
            buf += chunk
        if b" 101 " not in buf.split(b"\r\n")[0]:
            raise OSError("handshake rechazado")
        self.rest = buf.split(b"\r\n\r\n", 1)[1]
        self.n = 0

    def _read(self, n: int) -> bytes:
        while len(self.rest) < n:
            chunk = self.s.recv(65536)
            if not chunk:
                raise OSError("cerrado")
            self.rest += chunk
        out, self.rest = self.rest[:n], self.rest[n:]
        return out

    def _frame(self) -> tuple[int, bool, bytes]:
        b0, b1 = self._read(2)
        ln = b1 & 0x7F
        if ln == 126:
            ln = struct.unpack(">H", self._read(2))[0]
        elif ln == 127:
            ln = struct.unpack(">Q", self._read(8))[0]
        mask = self._read(4) if b1 & 0x80 else None
        data = self._read(ln)
        if mask:
            data = bytes(c ^ mask[i % 4] for i, c in enumerate(data))
        return b0 & 0x0F, bool(b0 & 0x80), data

    def recv(self) -> dict:
        msg = b""
        while True:
            op, fin, data = self._frame()
            if op == 8:
                raise OSError("cerrado")
            if op in (0, 1, 2):
                msg += data
                if fin:
                    return json.loads(msg)

    def call(self, method: str, params: dict | None = None) -> dict:
        self.n += 1
        payload = json.dumps({"id": self.n, "method": method, "params": params or {}}).encode()
        head = bytes([0x81])
        ln = len(payload)
        head += bytes([0x80 | ln]) if ln < 126 else bytes([0x80 | 126]) + struct.pack(">H", ln) if ln < 65536 \
            else bytes([0x80 | 127]) + struct.pack(">Q", ln)
        mask = os.urandom(4)
        self.s.sendall(head + mask + bytes(c ^ mask[i % 4] for i, c in enumerate(payload)))
        while True:
            r = self.recv()
            if r.get("id") == self.n:
                if "error" in r:
                    raise OSError(r["error"].get("message", "error CDP"))
                return r.get("result", {})


def evaluate(ws: WS, expr: str):
    r = ws.call("Runtime.evaluate", {"expression": expr, "returnByValue": True})
    return (r.get("result") or {}).get("value")


def pagina(url: str | None = None) -> dict:
    tabs = json.load(urllib.request.urlopen(BASE + "/json", timeout=10))
    pages = [t for t in tabs if t.get("type") == "page" and not t.get("url", "").startswith("devtools://")]
    if not pages:
        req = urllib.request.Request(BASE + "/json/new?" + quote(url or "about:blank", safe=":/?&=%#"), method="PUT")
        pages = [json.load(urllib.request.urlopen(req, timeout=10))]
    return pages[0]


def main() -> None:
    op = sys.argv[1]
    if op == "open":
        url = sys.argv[2]
        if urlparse(url).scheme not in ("http", "https"):
            raise ValueError("Solo http(s)")
        ws = WS(pagina(url)["webSocketDebuggerUrl"])
        ws.call("Page.bringToFront")
        ws.call("Page.navigate", {"url": url})
        for _ in range(40):
            time.sleep(0.5)
            if evaluate(ws, "document.readyState") == "complete":
                break
        out = {"url": evaluate(ws, "location.href"), "titulo": evaluate(ws, "document.title")}
    elif op == "text":
        ws = WS(pagina()["webSocketDebuggerUrl"])
        out = json.loads(evaluate(ws, TEXTO) or "{}")
    else:
        raise ValueError("op")
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"error": f"{type(e).__name__}: {str(e)[:200]}"}))
