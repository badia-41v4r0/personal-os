#!/usr/bin/env python3
"""Proxy de salida del programador. Corre en un contenedor aparte, sin token: el programador no lo ve ni lo puede tocar.

El programador no tiene red. Su única salida es este proxy (por un socket Unix) y solo deja pasar dominios de esta lista.
No descifra el tráfico: filtra por dominio con CONNECT. Reduce mucho la salida del token, pero no la elimina: quien
tenga una cuenta propia en un dominio permitido (por ejemplo, publicar en npm) podría usarlo. Por eso tampoco hay GitHub.
"""
import json
import os
import selectors
import socket
import socketserver
import sys
import time

SOCK = sys.argv[1] if len(sys.argv) > 1 else "/gw/proxy.sock"
LOG = os.environ.get("EGRESS_LOG", "/gw/egress.jsonl")
# Lista por defecto: la del programador. Las sesiones de otros proveedores pasan la suya en EGRESS_ALLOW (separada por comas).
ALLOWED = tuple(d.strip().lower() for d in os.environ.get("EGRESS_ALLOW", "").split(",") if d.strip()) or (
    "api.anthropic.com", "statsig.anthropic.com", "registry.npmjs.org", "registry.yarnpkg.com", "pypi.org", "files.pythonhosted.org")
TIMEOUT = 600


def allowed(host: str) -> bool:
    return host.lower().rstrip(".") in ALLOWED


def log(host: str, ok: bool) -> None:
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.time(), "host": host[:120], "ok": ok}) + "\n")
    except OSError:
        pass


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        line = self.rfile.readline(4096).decode("latin-1").split()
        while self.rfile.readline(4096) not in (b"\r\n", b"\n", b""):
            pass
        if len(line) < 2 or line[0] != "CONNECT" or ":" not in line[1]:
            self.wfile.write(b"HTTP/1.1 405 Solo CONNECT\r\n\r\n")
            return
        host, _, port = line[1].rpartition(":")
        if port != "443" or not allowed(host):
            log(host, False)
            self.wfile.write(b"HTTP/1.1 403 Dominio no permitido\r\n\r\n")
            return
        log(host, True)
        try:
            up = socket.create_connection((host, 443), timeout=30)
        except OSError:
            self.wfile.write(b"HTTP/1.1 502 Sin conexion\r\n\r\n")
            return
        self.wfile.write(b"HTTP/1.1 200 OK\r\n\r\n")
        self.wfile.flush()
        tunnel(self.connection, up)


def tunnel(a: socket.socket, b: socket.socket) -> None:
    sel = selectors.DefaultSelector()
    sel.register(a, selectors.EVENT_READ, b)
    sel.register(b, selectors.EVENT_READ, a)
    try:
        while True:
            events = sel.select(TIMEOUT)
            if not events:
                return
            for key, _ in events:
                data = key.fileobj.recv(65536)
                if not data:
                    return
                key.data.sendall(data)
    except OSError:
        pass
    finally:
        b.close()


class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True


if __name__ == "__main__":
    if os.path.exists(SOCK):
        os.unlink(SOCK)
    with Server(SOCK, Handler) as s:
        os.chmod(SOCK, 0o666)
        s.serve_forever()
