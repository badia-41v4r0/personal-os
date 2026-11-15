"""Addon de mitmproxy: salida a internet de un ordenador sin red, limitada a una lista de dominios.

Campus (perfil canvas): los de la plataforma de estudios del usuario (config estudios.json). Solicitudes de empleo
(perfil aplicaciones): los de esa solicitud. El Host Agent los deja en /data/allow.json (el ordenador no monta ese
volumen, así que el agente no puede cambiarlos). Sin lista, no sale nada.

Corre en un contenedor aparte (el agente no lo ve ni lo puede tocar). El ordenador del campus no tiene red: su única
salida es el socket de este proxy. Solo filtra por dominio; los métodos (GET, POST…) se permiten todos para que se
pueda iniciar sesión y usar Canvas con normalidad. Que el agente no envíe ni suba nada lo marcan sus instrucciones.
Todo queda registrado en /data/egress.jsonl (método, dominio, ruta sin parámetros y decisión).
"""
import json
import time
from pathlib import Path

from mitmproxy import http

LOG = Path("/data/egress.jsonl")
LOG_MAX = 5 * 1024 * 1024
PERMITIDOS: tuple[str, ...] = ()  # sin allow.json no se deja salir a ningún sitio
ALLOW = Path("/data/allow.json")
MSG = b"Bloqueado por el Personal OS: este ordenador solo puede abrir las webs que tiene permitidas."


def permitidos() -> tuple[str, ...]:
    try:
        lista = json.loads(ALLOW.read_text(encoding="utf-8"))
        return tuple(str(d).lower().strip(".") for d in lista if d) or PERMITIDOS
    except (OSError, ValueError):
        return PERMITIDOS


def host_permitido(host: str, lista: tuple[str, ...] | None = None) -> bool:
    host = host.lower().rstrip(".")
    return any(host == d or host.endswith("." + d) for d in (lista if lista is not None else permitidos()))


def _log(method: str, host: str, path: str, ok: bool) -> None:
    try:
        if LOG.exists() and LOG.stat().st_size > LOG_MAX:
            LOG.replace(LOG.with_suffix(".1.jsonl"))
        with LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.time(), "m": method, "host": host, "path": path.split("?")[0][:200],
                                "ok": ok, "motivo": "" if ok else "dominio no permitido"}) + "\n")
    except OSError:
        pass


class Filtro:
    def http_connect(self, flow: http.HTTPFlow) -> None:
        if not host_permitido(flow.request.host):
            _log("CONNECT", flow.request.host, "", False)
            flow.response = http.Response.make(403, MSG, {"Content-Type": "text/plain; charset=utf-8"})

    def requestheaders(self, flow: http.HTTPFlow) -> None:
        r = flow.request
        ok = host_permitido(r.pretty_host)
        _log(r.method, r.pretty_host, r.path, ok)
        if not ok:
            flow.response = http.Response.make(403, MSG, {"Content-Type": "text/plain; charset=utf-8"})


addons = [Filtro()]
