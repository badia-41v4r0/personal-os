"""Direcciones antiguas del panel → las nuevas (noviembre de 2026: rutas en español y Ajustes en un solo sitio).

Sirve para marcadores, avisos ya enviados al móvil y enlaces guardados en la vault. Mismo mapa que
apps/web/src/lib/rutas.ts (el panel lo usa para los enlaces que vienen de la base).
"""
from urllib.parse import parse_qsl, urlencode

# Pestañas de la antigua página de Tareas
TAREAS = {"approvals": "/bandeja/", "requests": "/bandeja/?t=solicitudes", "queues": "/ajustes/colas/",
          "timers": "/ajustes/colas/", "tasks": "/tareas/"}

# Prefijo viejo → nuevo. El más largo gana.
PREFIJOS = {
    "/memory/hechos/": "/conocimiento/sobre-ti/",
    "/settings/modulos/": "/ajustes/modulos/",
    "/gym/": "/entrenamiento/",
    "/memory/": "/conocimiento/",
    "/projects/": "/proyectos/",
    "/tasks/": "/tareas/",
    "/chat/": "/conversaciones/",
    "/settings/": "/ajustes/",
    "/agents/": "/ajustes/agentes/",
    "/sistema/": "/ajustes/sistema/",
    "/monitor/": "/ajustes/monitor/",
    "/virtual-computers/": "/ajustes/ordenadores/",
    "/integraciones/": "/ajustes/conexiones/",
    "/automatizaciones/": "/ajustes/automatizaciones/",
    "/avisos/": "/bandeja/",
}


def nueva(path: str, query: str = "") -> str | None:
    """Dirección nueva para una antigua, o None si no es antigua."""
    p = path if path.endswith("/") else path + "/"
    if p == "/tasks/":
        tab = dict(parse_qsl(query)).get("t")
        if tab in TAREAS:
            return TAREAS[tab]
    for viejo in sorted(PREFIJOS, key=len, reverse=True):
        if p.startswith(viejo):
            destino = PREFIJOS[viejo] + p[len(viejo):]
            q = urlencode([(k, v) for k, v in parse_qsl(query) if not (viejo == "/tasks/" and k == "t")])
            return destino + (f"?{q}" if q else "")
    return None
