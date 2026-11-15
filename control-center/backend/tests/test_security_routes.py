"""Recorre todas las rutas de la API: nada sin sesión (salvo health y login) y nada con efecto sin CSRF."""
import re

from tests.conftest import ORIGIN

PUBLIC = {("GET", "/api/v1/health"), ("POST", "/api/v1/auth/login")}
# No usa cookie: la protege la credencial de la ejecución (test_memory.py)
RUN_TOKEN = {("POST", "/api/v1/internal/pos/call")}
UUID = "12345678-1234-1234-1234-1234567890ab"


def routes():
    """Desde el esquema OpenAPI (los WebSocket se prueban aparte: test_events y test_vcs)."""
    from app.main import app
    for path, ops in app.openapi()["paths"].items():
        for m in ops:
            yield m.upper(), path, re.sub(r"\{[^}]+\}", UUID, path)


def test_hay_rutas():
    assert len(list(routes())) > 60


def test_todo_requiere_sesion(client):
    client.cookies.clear()
    fails = []
    for m, path, url in routes():
        if (m, path) in PUBLIC:
            continue
        r = client.request(m, url, headers={"Origin": ORIGIN}, json={})
        if r.status_code != 401:
            fails.append((m, path, r.status_code))
    assert fails == []


def test_todo_lo_que_modifica_exige_csrf(client, auth):
    fails = []
    for m, path, url in routes():
        if m == "GET" or (m, path) in PUBLIC | RUN_TOKEN:
            continue
        r = client.request(m, url, headers={"Origin": ORIGIN}, json={})  # sesión válida, sin X-CSRF-Token
        if r.status_code != 403:
            fails.append((m, path, r.status_code))
        r = client.request(m, url, headers={"Origin": "https://malo.example", "X-CSRF-Token": auth["X-CSRF-Token"]}, json={})
        if r.status_code != 403:
            fails.append(("origen", m, path, r.status_code))
    assert fails == []


def test_esquema_de_la_api_exige_sesion(client, auth):
    assert client.get("/api/v1/openapi.json").status_code == 200
    client.cookies.clear()
    assert client.get("/api/v1/openapi.json").status_code == 401
