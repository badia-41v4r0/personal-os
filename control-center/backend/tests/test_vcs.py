from datetime import timedelta

import pytest
from starlette.websockets import WebSocketDisconnect

from app import vcs
from app.adapters import hostagent
from app.db import session_scope, utcnow
from app.models import VirtualComputer
from tests.conftest import ORIGIN


class FakeHA:
    def __init__(self):
        self.calls, self.live, self.disk = [], {}, 0

    async def call(self, path, params=None, method="GET", json=None, timeout=15):
        self.calls.append((method, path))
        if path == "/v1/vc/create":
            self.live[json["id"]] = {"id": json["id"], "container": f"jarvis-vc-{json['id'][:8]}", "state": "running",
                                     "profile": json["profile"], "disk_mb": str(json["disk_mb"]), "session": json.get("session", ""), "owner": json["owner"]}
            return {"ok": True}
        if path == "/v1/vc":
            return list(self.live.values())
        if path.endswith("/lifecycle/remove"):
            self.live.pop(path.split("/")[3], None)
            return {"ok": True}
        if path.endswith("/lifecycle/stop"):
            self.live[path.split("/")[3]]["state"] = "exited"
            return {"ok": True}
        if path.endswith("/lifecycle/start"):
            self.live[path.split("/")[3]]["state"] = "running"
            return {"ok": True}
        if path.endswith("/disk"):
            return {"bytes": self.disk}
        if path.endswith("/egress"):
            return [{"ts": 1.0, "m": "POST", "host": "campus.ejemplo.edu", "path": "/x", "ok": False, "motivo": "dominio no permitido"}]
        raise AssertionError(path)


@pytest.fixture()
def ha(monkeypatch):
    f = FakeHA()
    monkeypatch.setattr(hostagent, "call", f.call)
    return f


def create(client, auth, **kw):
    r = client.post("/api/v1/virtual-computers", json={"name": "pc"} | kw, headers=auth)
    assert r.status_code == 200, r.text
    return r.json()


def test_crear_listar_y_auditar(client, auth, ha):
    v = create(client, auth, profile="desktop", persistence="persistent")
    assert v["status"] == "running" and v["profile"] == "desktop" and v["internet"] is False
    lst = client.get("/api/v1/virtual-computers").json()
    assert lst[0]["live"]["state"] == "running"
    assert any(a["action"] == "vc.create" for a in client.get("/api/v1/audit").json())
    assert client.get(f"/api/v1/virtual-computers/{v['id']}").json()["events"][0]["type"] == "created"


def test_maximo_a_la_vez(client, auth, ha):
    for _ in range(vcs.MAX_ACTIVE):
        create(client, auth, persistence="persistent")
    assert client.post("/api/v1/virtual-computers", json={"name": "x"}, headers=auth).status_code == 429


def test_efimero_parado_se_elimina(client, auth, ha):
    v = create(client, auth, persistence="ephemeral")
    assert client.post(f"/api/v1/virtual-computers/{v['id']}/stop", headers=auth).json()["status"] == "deleted"
    assert v["id"] not in ha.live
    assert client.get(f"/api/v1/virtual-computers/{v['id']}").status_code == 404


@pytest.mark.asyncio
async def test_caducidad_disco_y_registro(settings, ha):
    from app.vcs import CreateIn, create_vc
    t = await create_vc(CreateIn(name="t", persistence="ttl", ttl_hours=1), "prueba")
    p = await create_vc(CreateIn(name="p", persistence="persistent", disk_mb=128), "prueba")
    with session_scope() as db:
        db.get(VirtualComputer, t["id"]).expires_at = utcnow() - timedelta(minutes=1)
    ha.disk = 200 * 1024 * 1024
    ha.live["99999999-9999-9999-9999-999999999999"] = {"id": "99999999-9999-9999-9999-999999999999", "container": "jarvis-vc-99999999",
                                                      "state": "running", "profile": "terminal", "disk_mb": "999999", "session": "", "owner": "agent:analista"}
    await vcs.reconcile()
    with session_scope() as db:
        assert db.get(VirtualComputer, t["id"]).status == "deleted"  # caducado
        assert db.get(VirtualComputer, p["id"]).status == "stopped"  # pasó del límite de disco
        reg = db.get(VirtualComputer, "99999999-9999-9999-9999-999999999999")
        assert reg is not None and reg.owner_agent == "analista"


def test_validacion_api(client, auth, ha):
    for bad in ({"profile": "root"}, {"cpus": 4}, {"memory_mb": 99999}, {"persistence": "siempre"}, {"name": ""}):
        assert client.post("/api/v1/virtual-computers", json={"name": "x"} | bad, headers=auth).status_code == 422


def test_terminal_sin_sesion_o_de_otro_origen(client, auth, ha):
    v = create(client, auth)
    cookie = f"cc_session={client.cookies.get('cc_session')}"
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/api/v1/virtual-computers/{v['id']}/tty", headers={"Origin": "https://malo.example", "Cookie": cookie}) as ws:
            ws.receive_bytes()
    client.cookies.clear()
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/api/v1/virtual-computers/{v['id']}/tty", headers={"Origin": ORIGIN}) as ws:
            ws.receive_bytes()


def test_sin_sesion_401(client):
    assert client.get("/api/v1/virtual-computers").status_code == 401


# ---------- Canvas UOC ----------

def test_canvas_siempre_persistente_y_sin_internet(client, auth, ha):
    v = create(client, auth, profile="canvas", persistence="ephemeral", internet=True, owner_agent="tutor")
    assert v["persistence"] == "persistent" and v["internet"] is False and v["owner_agent"] == "tutor"


def test_un_canvas_por_agente(client, auth, ha):
    create(client, auth, profile="canvas", owner_agent="tutor")
    r = client.post("/api/v1/virtual-computers", json={"name": "otro", "profile": "canvas", "owner_agent": "tutor"}, headers=auth)
    assert r.status_code == 409


def test_registro_de_accesos(client, auth, ha):
    v = create(client, auth, profile="canvas", owner_agent="tutor")
    assert ("POST", f"/v1/vc/{v['id']}/egress") not in ha.calls
    assert client.get(f"/api/v1/virtual-computers/{v['id']}/egress").json()[0]["ok"] is False


@pytest.fixture(autouse=True)
def _campus(config_instancia):
    """El ordenador del campus necesita su plataforma configurada (antes, los dominios de la UOC estaban fijos)."""
    import json
    (config_instancia / "estudios.json").write_text(json.dumps({"plataforma": {"url": "https://campus.ejemplo.edu/", "tipo": "canvas"}}))


def test_campus_sin_configurar_no_se_crea(client, auth, ha, config_instancia):
    (config_instancia / "estudios.json").unlink()
    r = client.post("/api/v1/virtual-computers", json={"name": "c", "profile": "canvas", "owner_agent": "tutor"}, headers=auth)
    assert r.status_code == 409 and "campus" in r.json()["detail"]


def test_campus_lleva_sus_dominios():
    from app.modules import campus
    assert {"campus.ejemplo.edu", "ejemplo.edu", "instructure.com"} <= set(campus.dominios())  # su web, su SSO y el CDN de Canvas
    assert campus.url() == "https://campus.ejemplo.edu/"
