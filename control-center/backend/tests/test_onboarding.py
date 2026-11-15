"""Onboarding con agente: propone configuración, el usuario la aprueba viendo el resultado, y se puede deshacer."""
import json

from app.core import actions, gateway, orchestrator


def _token(spec):
    return gateway.issue_token("r-ob", spec.name, list(spec.tools), list(spec.capabilities))


def _accion(client, tok, nombre, args):
    return client.post("/api/v1/internal/pos/call", headers={"X-Run-Token": tok},
                       json={"kind": "action", "name": nombre, "args": args}).json()["result"]


def test_asistente_solo_recibe_lo_de_su_modulo():
    ed = orchestrator.onboarding("educacion")
    assert "config.estudios.set" in ed.capabilities and "config.ia.set" not in ed.capabilities
    assert ed.panel_agent == "tutor" and ed.guia and "campus" in ed.guia
    gym = orchestrator.onboarding("gym")
    assert not [c for c in gym.capabilities if c.startswith("config.")] or gym.capabilities == ()
    assert orchestrator.onboarding("no-existe") is None


def test_propuesta_espera_aprobacion_y_se_deshace(client, auth, config_instancia):
    (config_instancia / "estudios.json").write_text(json.dumps({"descansos": ["2030-01-01"]}))
    tok = _token(orchestrator.onboarding("educacion"))
    r = _accion(client, tok, "config.estudios.set", {"datos": {"plataforma": {"url": "https://campus.ejemplo.edu/", "nombre": "Campus"}}})
    assert r["status"] == "pending"  # nunca se guarda sin el OK
    assert "campus.ejemplo.edu" in r["summary"] and "2030-01-01" in r["summary"]  # se ve lo que quedará (fusionado)
    assert "plataforma" not in json.loads((config_instancia / "estudios.json").read_text())
    hecho = actions.decide(r["id"], True, r["hash"], "ana")
    assert hecho["status"] == "done"
    guardado = json.loads((config_instancia / "estudios.json").read_text())
    assert guardado["plataforma"]["url"] == "https://campus.ejemplo.edu/" and guardado["descansos"] == ["2030-01-01"]
    actions.undo(r["id"], "ana")
    assert "plataforma" not in json.loads((config_instancia / "estudios.json").read_text())


def test_no_puede_tocar_otra_configuracion_ni_campos_raros(client, config_instancia):
    tok = _token(orchestrator.onboarding("carrera"))
    assert _accion(client, tok, "config.estudios.set", {"datos": {}})["status"] == "denied"
    assert _accion(client, tok, "config.ia.set", {"datos": {"proveedor": "codex"}})["status"] == "denied"
    r = _accion(client, tok, "config.ofertas.set", {"datos": {"token": "x"}})
    assert r["status"] == "pending"
    assert actions.decide(r["id"], True, r["hash"], "ana")["status"] == "failed"  # el esquema lo rechaza al ejecutar


def test_config_get_no_lee_lo_del_usuario(client):
    tok = _token(orchestrator.onboarding("inicio"))
    h = {"X-Run-Token": tok}
    ok = client.post("/api/v1/internal/pos/call", headers=h, json={"kind": "read", "name": "config.get", "args": {"nombre": "perfil"}}).json()
    assert "datos" in ok["result"]
    no = client.post("/api/v1/internal/pos/call", headers=h, json={"kind": "read", "name": "config.get", "args": {"nombre": "ia"}}).json()
    assert "error" in no


def test_apartado_hecho(client, auth, config_instancia):
    tok = _token(orchestrator.onboarding("gym"))
    assert _accion(client, tok, "onboarding.hecho", {"apartado": "gym"})["status"] == "done"
    assert client.get("/api/v1/instancia").json()["onboarding"]["apartados"]["gym"] == "hecho"


def test_chat_de_onboarding_existe_solo_para_modulos_activos(client, auth, config_instancia):
    assert client.get("/api/v1/assistants/onboarding-gym/messages").status_code == 200
    (config_instancia / "modulos.json").write_text(json.dumps({"activos": ["agenda"]}))
    assert client.get("/api/v1/assistants/onboarding-gym/messages").status_code == 404
