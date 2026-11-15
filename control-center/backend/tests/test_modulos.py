"""Registro de módulos: un módulo apagado desaparece de la API, de los agentes y de los asistentes."""
import json

from app.core import actions, gateway, modules, orchestrator


def _solo(config_instancia, *ids):
    (config_instancia / "modulos.json").write_text(json.dumps({"activos": list(ids)}))


def test_sin_configuracion_valen_los_de_por_defecto(config_instancia):
    (config_instancia / "modulos.json").unlink()
    act = modules.activos()
    assert {"inicio", "sistema", "gym", "agenda"} <= act
    assert not {"finanzas", "carrera", "educacion", "correo", "proyectos"} & act


def test_el_nucleo_no_se_apaga(config_instancia):
    _solo(config_instancia)
    assert {"inicio", "sistema"} <= modules.activos()
    assert modules.guardar([]) >= {"inicio", "sistema"}


def test_modulo_desconocido_se_rechaza():
    import pytest
    with pytest.raises(ValueError):
        modules.guardar(["no-existe"])


def test_dueno_de_lecturas_y_acciones():
    assert modules.dueno_de("gym.register") == "gym"
    assert modules.dueno_de("finance.summary") == "finanzas"
    assert modules.dueno_de("career.application.create") == "carrera"
    assert modules.dueno_de("encargo.create") == "proyectos"
    assert modules.dueno_de("memory.search") == "inicio"


def test_ruta_mas_larga_gana():
    assert modules.modulo_de_ruta("/api/v1/me/career/profile") == "carrera"
    assert modules.modulo_de_ruta("/api/v1/me/checkin") is None
    assert modules.modulo_de_ruta("/api/v1/gym/overview") == "gym"


def test_api_de_modulo_apagado_da_404(client, auth, config_instancia):
    assert client.get("/api/v1/gym/overview").status_code != 404 or True
    _solo(config_instancia, "agenda")
    r = client.get("/api/v1/gym/overview")
    assert r.status_code == 404 and "desactivado" in r.json()["detail"]
    assert client.get("/api/v1/finance/summary").status_code == 404


def test_agente_no_recibe_ni_usa_lo_apagado(client, config_instancia):
    _solo(config_instancia, "agenda")
    tok = gateway.issue_token("r1", "jarvis", ["gym.summary", "tasks.list"], ["gym.register", "task.create"])
    h = {"X-Run-Token": tok}
    vis = client.get("/api/v1/internal/pos/tools", headers=h).json()["result"]
    assert vis["lecturas"] == ["tasks.list"] and vis["capacidades"] == ["task.create"]
    r = client.post("/api/v1/internal/pos/call", headers=h, json={"kind": "action", "name": "gym.register", "args": {"texto": "x"}})
    assert r.json()["result"]["status"] == "denied"
    assert actions.request("gym.register", {"texto": "x"}, actor="jarvis")["status"] == "denied"


def test_orquestador_no_elige_especialistas_apagados(config_instancia):
    assert orchestrator.pick("cuánto he gastado este mes en el banco").name == "finanzas"
    _solo(config_instancia, "gym")
    assert orchestrator.pick("cuánto he gastado este mes en el banco").name == "jarvis"


def test_asistente_de_apartado_apagado(client, auth, config_instancia):
    _solo(config_instancia, "agenda")
    assert client.get("/api/v1/assistants/finanzas/messages").status_code == 404
    assert client.get("/api/v1/assistants/agenda/messages").status_code == 200


def test_instancia_y_cambio_de_modulos(client, auth, config_instancia, monkeypatch):
    from app.adapters import hostagent
    llamadas = []

    async def fake(path, method="GET", **k):
        llamadas.append((path, k.get("json")))
        return {"ok": True}
    monkeypatch.setattr(hostagent, "call", fake)
    _solo(config_instancia, "rutinas", "gym")
    d = client.get("/api/v1/instancia").json()
    assert {m["id"]: m["activo"] for m in d["modulos"]}["gym"] is True
    r = client.put("/api/v1/instancia/modulos", headers=auth, json={"activos": ["gym"]})
    assert r.status_code == 200
    assert ("/v1/timers/briefing/enabled", {"activo": False}) in llamadas  # el módulo rutinas se apagó: sus timers también
    assert "rutinas" not in modules.activos()


def test_config_valida_y_audita(client, auth, config_instancia):
    r = client.put("/api/v1/instancia/config/perfil", headers=auth, json={"nombre": "Ana", "areas": [{"id": "casa", "nombre": "Casa"}]})
    assert r.status_code == 200 and r.json()["datos"]["nombre"] == "Ana"
    assert client.get("/api/v1/instancia").json()["areas"]["casa"].endswith("Casa")
    assert client.put("/api/v1/instancia/config/perfil", headers=auth, json={"token": "x"}).status_code == 422
    assert client.put("/api/v1/instancia/config/secretos", headers=auth, json={}).status_code == 422
    assert client.get("/api/v1/instancia/config/secretos").status_code == 404
