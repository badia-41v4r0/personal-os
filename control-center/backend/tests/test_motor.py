"""Motor de IA elegido en Ajustes: cada turno va al proveedor elegido, con su modelo, su límite y sin mezclar conversaciones."""
import json

from app.core import proveedores as motor

from .test_sessions import CLAUDE_SID, fake_stream, new, wait


def _ia(config_instancia, **kw):
    (config_instancia / "ia.json").write_text(json.dumps(kw))


def test_por_defecto_claude(client, auth, monkeypatch):
    from app import sessions
    calls = []
    monkeypatch.setattr(sessions, "hostagent_stream", fake_stream(calls))
    s = new(client, auth)
    client.post(f"/api/v1/sessions/{s['id']}/messages", json={"text": "hola"}, headers=auth)
    wait(client, s["id"], 1)
    assert calls[0]["provider"] == "claude" and calls[0]["model"] == "sonnet" and calls[0]["internet"] is True


def test_opencode_usa_su_modelo_y_quita_lo_que_no_sabe(client, auth, monkeypatch, config_instancia):
    from app import sessions
    _ia(config_instancia, proveedor="opencode", modelos={"opencode": {"standard": "openrouter/a/b", "deep": "openrouter/a/c"}})
    calls = []
    monkeypatch.setattr(sessions, "hostagent_stream", fake_stream(calls))
    s = new(client, auth, model="opus")
    client.post(f"/api/v1/sessions/{s['id']}/messages", json={"text": "hola"}, headers=auth)
    runs = wait(client, s["id"], 1)
    assert calls[0]["provider"] == "opencode" and calls[0]["model"] == "openrouter/a/c" and calls[0]["internet"] is False
    assert runs[0]["usage"]["provider"] == "opencode"
    msgs = client.get(f"/api/v1/sessions/{s['id']}/messages").json()
    assert "búsqueda web" in msgs[-1]["content"]  # se le dice al usuario lo que este motor no puede hacer


def test_no_reanuda_una_conversacion_de_otro_motor(client, auth, monkeypatch, config_instancia):
    from app import sessions
    calls = []
    monkeypatch.setattr(sessions, "hostagent_stream", fake_stream(calls))
    s = new(client, auth)
    client.post(f"/api/v1/sessions/{s['id']}/messages", json={"text": "uno"}, headers=auth)
    wait(client, s["id"], 1)
    _ia(config_instancia, proveedor="codex")
    client.post(f"/api/v1/sessions/{s['id']}/messages", json={"text": "dos"}, headers=auth)
    wait(client, s["id"], 2)
    assert calls[1]["provider"] == "codex" and calls[1]["resume"] is None and calls[1]["model"] == ""


def test_limite_de_gasto_de_openrouter(client, auth, monkeypatch, config_instancia):
    from app import sessions
    from app.db import session_scope
    from app.models import AgentRun, ChatSession
    from app.db import utcnow
    _ia(config_instancia, proveedor="opencode", modelos={"opencode": {"standard": "openrouter/a/b"}}, limite_mensual_usd=1)
    with session_scope() as db:
        db.add(ChatSession(id="viejo", kind="independent", name="x", workdir="x", model="sonnet", permissions={}))
        db.flush()
        db.add(AgentRun(id="r-viejo", session_id="viejo", status="done", started_at=utcnow(), usage={"provider": "opencode", "cost_usd": 1.5}))
    calls = []
    monkeypatch.setattr(sessions, "hostagent_stream", fake_stream(calls))
    s = new(client, auth)
    client.post(f"/api/v1/sessions/{s['id']}/messages", json={"text": "hola"}, headers=auth)
    runs = wait(client, s["id"], 1)
    assert calls == [] and runs[0]["status"] == "error" and "límite" in runs[0]["error"]


def test_opencode_sin_modelo_no_arranca(client, auth, monkeypatch, config_instancia):
    from app import sessions
    _ia(config_instancia, proveedor="opencode")
    calls = []
    monkeypatch.setattr(sessions, "hostagent_stream", fake_stream(calls))
    s = new(client, auth)
    client.post(f"/api/v1/sessions/{s['id']}/messages", json={"text": "hola"}, headers=auth)
    runs = wait(client, s["id"], 1)
    assert calls == [] and "modelo" in runs[0]["error"]


def test_antigravity_no_lleva_herramientas_al_contenedor(config_instancia):
    _ia(config_instancia, proveedor="antigravity")
    t = motor.turno(None, "sonnet", {})
    assert t.proveedor == "claude"  # las sesiones con herramientas siguen en Claude; Inicio responde en modo consulta


def test_motor_estado_y_clave(client, auth, monkeypatch):
    from app.adapters import hostagent
    vistas = []

    async def fake(path, method="GET", json=None, **k):
        vistas.append((path, method, json))
        if path == "/v1/proveedores":
            return [{"id": "claude", "conectado": True}, {"id": "opencode", "conectado": False}]
        return {"id": "opencode", "conectado": True}
    monkeypatch.setattr(hostagent, "call", fake)
    d = client.get("/api/v1/instancia/motor").json()
    assert d["elegido"] == "claude" and {p["id"]: p["conectado"] for p in d["proveedores"]}["claude"] is True
    r = client.put("/api/v1/instancia/motor/openrouter/clave", headers=auth, json={"clave": "sk-or-v1-abcdefghijklmnopqrstuvwxyz"})
    assert r.status_code == 200 and vistas[-1][0] == "/v1/proveedores/openrouter/clave"
    from app.db import session_scope
    from app.models import AuditLog
    from sqlalchemy import select
    with session_scope() as db:
        assert not any("sk-or" in json.dumps(a.detail or {}) for a in db.scalars(select(AuditLog)))
    assert client.put("/api/v1/instancia/config/ia", headers=auth, json={"proveedor": "gpt-casero"}).status_code == 422
