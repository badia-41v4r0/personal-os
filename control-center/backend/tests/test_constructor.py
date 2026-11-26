"""Constructor: una personalización a la vez, turnos que se leen de su archivo (y se retoman tras reiniciar), el proxy
de /vista-previa/ y la sesión que adopta la vista previa."""
import asyncio
import dataclasses
import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app import config, constructor
from app import db as dbm
from app import sessions
from app.models import AgentRun, ChatSession, Message

TOKEN_VP = "v" * 40


def _abrir(settings, cid: str, **extra) -> None:
    d = settings.constructor_dir
    d.mkdir(parents=True, exist_ok=True)
    (d / "personalizacion.json").write_text(json.dumps({"conversacion": cid, "estado": "lista", "token": TOKEN_VP,
                                                        "puerto": 1, "creada": "2026-11-26T10:00:00Z", **extra}))


@pytest.fixture()
def host(settings, monkeypatch):
    """Host Agent de mentira: reserva la personalización como el de verdad y escribe la salida de los turnos."""
    llamadas: list[tuple[str, dict | None]] = []
    salida = [
        {"type": "system", "subtype": "init", "session_id": "12345678-1234-1234-1234-1234567890ab"},
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Edit", "input": {"file_path": "control-center/apps/web/src/app/page.tsx"}}]}},
        {"type": "result", "result": "He cambiado el saludo. Míralo en la vista previa.", "session_id": "12345678-1234-1234-1234-1234567890ab",
         "total_cost_usd": 0.01},
        {"type": "_exit", "code": 0, "stderr": ""},
    ]

    def sync(path, method="GET", json=None, timeout=15):
        llamadas.append((path, json))
        if path == "/v1/constructor/abrir":
            p = constructor.personalizacion()
            if p and p["conversacion"] != json["conversacion"]:
                from fastapi import HTTPException
                raise HTTPException(409, "Ya hay una personalización abierta")
            _abrir(settings, json["conversacion"])
            (settings.constructor_dir / "copia/.git").mkdir(parents=True, exist_ok=True)
        return {"ok": True}

    async def call(path, params=None, method="GET", json=None, timeout=15):
        if path == "/v1/constructor/turno":
            t = settings.constructor_dir / "turnos"
            t.mkdir(parents=True, exist_ok=True)
            (t / f"{json['run_id']}.json").write_text("{}")
            (t / f"{json['run_id']}.ndjson").write_text("".join(__import__("json").dumps(e) + "\n" for e in salida))
        return sync(path, method, json, timeout)

    monkeypatch.setattr("app.adapters.hostagent.call_sync", sync)
    monkeypatch.setattr("app.adapters.hostagent.call", call)
    return llamadas


def _crear(client, auth, texto="Cambia el saludo de Inicio"):
    return client.post("/api/v1/conversaciones", json={"asistente": "constructor", "texto": texto}, headers=auth)


def _esperar(cid: str) -> None:
    for _ in range(200):
        with dbm.session_scope() as s:
            if not s.query(AgentRun).filter(AgentRun.session_id == cid, AgentRun.status.in_(("queued", "running"))).count():
                return
        time.sleep(0.02)
    raise AssertionError("el turno no terminó")


def test_una_sola_personalizacion_a_la_vez(client, auth, host, settings):
    r = _crear(client, auth)
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    assert ("/v1/constructor/abrir", {"conversacion": cid}) in host
    r2 = _crear(client, auth, "Otra cosa")
    assert r2.status_code == 409 and "personalización abierta" in r2.json()["detail"]
    e = client.get("/api/v1/constructor").json()
    assert e["personalizacion"]["conversacion"] == cid and "token" not in e["personalizacion"] and e["url"] == "/vista-previa/"


def test_turno_completo(client, auth, host, settings):
    cid = _crear(client, auth).json()["id"]
    r = client.post(f"/api/v1/conversaciones/{cid}/mensajes", json={"texto": "Cambia el saludo de Inicio"}, headers=auth)
    assert r.status_code == 200, r.text
    _esperar(cid)
    d = client.get(f"/api/v1/conversaciones/{cid}").json()
    roles = [(m["rol"], m["texto"]) for m in d["mensajes"]]
    assert ("assistant", "He cambiado el saludo. Míralo en la vista previa.") in roles
    assert any(rol == "tool" and t.startswith("Edit ") for rol, t in roles)
    assert d["respuestas"][-1]["estado"] == "done"
    with dbm.session_scope() as s:
        c = s.get(ChatSession, cid)
        assert c.claude_session_id == "12345678-1234-1234-1234-1234567890ab" and c.status == "idle"
    # el siguiente turno sigue la misma conversación de la CLI
    turno = [j for p, j in host if p == "/v1/constructor/turno"]
    assert turno[0]["proveedor"] == "claude" and turno[0]["modelo"] == "opus" and turno[0]["resume"] is None


def test_retomar_conversacion_cerrada(client, auth, host, settings):
    cid = _crear(client, auth).json()["id"]
    (settings.constructor_dir / "personalizacion.json").unlink()  # aplicada o descartada
    r = client.post(f"/api/v1/conversaciones/{cid}/mensajes", json={"texto": "Y ahora el color"}, headers=auth)
    assert r.status_code == 200
    _esperar(cid)
    assert sum(1 for p, _ in host if p == "/v1/constructor/abrir") == 2
    assert constructor.personalizacion()["conversacion"] == cid


def test_otra_conversacion_no_puede_seguir(client, auth, host, settings):
    cid = _crear(client, auth).json()["id"]
    _abrir(settings, str(uuid.uuid4()))  # ahora la abierta es otra
    r = client.post(f"/api/v1/conversaciones/{cid}/mensajes", json={"texto": "hola"}, headers=auth)
    assert r.status_code == 409


def test_un_reinicio_no_pierde_el_turno(client, auth, settings):
    """El turno sigue vivo fuera del panel: al arrancar no se marca como fallido y se vuelve a leer su salida."""
    cid, run_id = str(uuid.uuid4()), str(uuid.uuid4())
    with dbm.session_scope() as s:
        s.add(ChatSession(id=cid, kind="conversacion", name="x", description="constructor", model="opus", status="running", permissions={}))
    with dbm.session_scope() as s:
        s.add(AgentRun(id=run_id, session_id=cid, channel="web", status="running"))
    t = settings.constructor_dir / "turnos"
    t.mkdir(parents=True)
    (t / f"{run_id}.json").write_text("{}")
    (t / f"{run_id}.ndjson").write_text(json.dumps({"type": "result", "result": "Listo tras el reinicio"}) + "\n" + json.dumps({"type": "_exit", "code": 0}) + "\n")
    sessions.recover()
    with dbm.session_scope() as s:
        assert s.get(AgentRun, run_id).status == "running"

    async def main():
        constructor.recover()
        await asyncio.gather(*list(constructor._tasks))

    asyncio.run(main())
    with dbm.session_scope() as s:
        assert s.get(AgentRun, run_id).status == "done"
        assert s.query(Message).filter(Message.session_id == cid, Message.content == "Listo tras el reinicio").count() == 1


def test_aplicar_y_descartar(client, auth, host, settings, monkeypatch):
    llamadas = []

    async def call(path, params=None, method="GET", json=None, timeout=15):
        llamadas.append((path, json))
        return {"ok": True}

    monkeypatch.setattr("app.adapters.hostagent.call", call)
    assert client.post("/api/v1/constructor/aplicar", json={}, headers=auth).status_code == 409  # nada abierto
    cid = _crear(client, auth, "Cambia el saludo").json()["id"]
    assert client.post("/api/v1/constructor/aplicar", json={}, headers=auth).status_code == 200
    assert ("/v1/cambios/aplicar", {"titulo": "Cambia el saludo"}) in llamadas
    assert client.post("/api/v1/constructor/descartar", headers=auth).status_code == 200
    assert ("/v1/constructor/cerrar", {"motivo": "descartada"}) in llamadas
    assert cid


def test_modulo_apagado(client, auth, host, config_instancia):
    (config_instancia / "modulos.json").write_text(json.dumps({"activos": []}))
    assert client.get("/api/v1/constructor").status_code == 404
    assert _crear(client, auth).status_code == 404
    assert client.get("/vista-previa/").status_code == 404


def test_progreso_de_cambios(client, auth, settings):
    assert client.get("/api/v1/cambios/progreso").json() == {"operacion": None}
    settings.cambios_dir.mkdir(parents=True)
    (settings.cambios_dir / "estado.json").write_text(json.dumps({"id": "x", "estado": "en_curso", "paso": "Compilando la web",
                                                                   "commit_antes": "abc"}))
    op = client.get("/api/v1/cambios/progreso").json()["operacion"]
    assert op["paso"] == "Compilando la web" and "commit_antes" not in op


# ---------- proxy de /vista-previa/ ----------

class _Eco(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/redir":
            self.send_response(302)
            self.send_header("Location", "/login/")
            self.end_headers()
            return
        cuerpo = json.dumps({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Set-Cookie", "cc_session=de-la-vista-previa; Path=/")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)


@pytest.fixture()
def eco():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Eco)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1]
    srv.shutdown()


def test_proxy_pasa_la_sesion_y_no_deja_cookies(client, auth, settings, eco):
    _abrir(settings, str(uuid.uuid4()), puerto=eco)
    r = client.get("/vista-previa/api/v1/eco?x=1")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["path"] == "/api/v1/eco?x=1"
    h = d["headers"]
    assert h["x-pos-vista-previa"] == TOKEN_VP and h["x-pos-usuario"] == "ana" and h["x-pos-csrf"] == auth["X-CSRF-Token"]
    assert h["cookie"].startswith("cc_session=")
    assert "set-cookie" not in r.headers  # no pisa la sesión del panel real
    assert (settings.constructor_dir / "uso").exists()
    r = client.get("/vista-previa/redir", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/vista-previa/login/"


def test_proxy_exige_sesion_y_vista_previa(client, settings, eco):
    r = client.get("/vista-previa/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login/"
    assert client.get("/vista-previa/api/v1/eco").status_code == 401


def test_proxy_sin_vista_previa(client, auth, settings):
    assert client.get("/vista-previa/").status_code == 404
    _abrir(settings, str(uuid.uuid4()), estado="preparando", paso="Copiando tus datos")
    r = client.get("/vista-previa/")
    assert r.status_code == 200 and "Copiando tus datos" in r.text and 'http-equiv="refresh"' in r.text
    assert client.get("/vista-previa/api/v1/x").status_code == 503


# ---------- la vista previa adopta la sesión que le pasa el panel ----------

def test_vista_previa_adopta_la_sesion(client, settings):
    config.set_settings(dataclasses.replace(settings, vista_previa=True, vista_previa_token=TOKEN_VP))
    try:
        h = {"x-pos-vista-previa": TOKEN_VP, "x-pos-usuario": "ana", "x-pos-csrf": "csrf-del-panel"}
        client.cookies.set("cc_session", "sesion-del-panel-real")
        r = client.get("/api/v1/auth/me", headers=h)
        assert r.status_code == 200 and r.json()["csrf_token"] == "csrf-del-panel"
        assert client.get("/api/v1/auth/me").status_code == 200  # ya existe en la copia
        client.cookies.set("cc_session", "otra")
        assert client.get("/api/v1/auth/me", headers={**h, "x-pos-vista-previa": "malo"}).status_code == 401
        assert client.get("/api/v1/auth/me", headers={**h, "x-pos-usuario": "nadie"}).status_code == 401
    finally:
        config.set_settings(settings)


def test_panel_real_no_adopta_nada(client, settings):
    client.cookies.set("cc_session", "inventada")
    r = client.get("/api/v1/auth/me", headers={"x-pos-vista-previa": "", "x-pos-usuario": "ana", "x-pos-csrf": "x"})
    assert r.status_code == 401
