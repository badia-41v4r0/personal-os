import time

import pytest

from app import conversaciones as conv
from app import db as dbm
from app.core import runs
from app.models import ChatSession, Message


@pytest.fixture()
def turno(client, monkeypatch):
    """El turno se ejecuta en el momento (sin bucle de eventos) con una respuesta y dos pasos."""
    enviados = []

    async def fake(payload):
        enviados.append(payload)
        yield {"type": "system", "subtype": "init", "session_id": "12345678-1234-1234-1234-1234567890ab"}
        yield {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "mcp__pos__pos_read", "input": {"name": "uni.deadlines"}}]}}
        yield {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read", "input": {"file_path": "/vault/Uni/PEC2.md"}}]}}
        yield {"type": "result", "result": "Entregas el viernes", "session_id": "12345678-1234-1234-1234-1234567890ab"}
    monkeypatch.setattr("app.sessions.hostagent_stream", fake)
    monkeypatch.setattr(runs.model_usage, "latest", lambda: {})
    return enviados


def _esperar(cid: str) -> None:
    """Los turnos corren en el bucle del cliente de pruebas: se espera a que no quede ninguno pendiente."""
    from app.models import AgentRun
    for _ in range(100):
        with dbm.session_scope() as s:
            if not s.query(AgentRun).filter(AgentRun.session_id == cid, AgentRun.status.in_(("queued", "running"))).count():
                return
        time.sleep(0.02)
    raise AssertionError("el turno no terminó")


def _enviar(client, auth, cid: str, texto: str):
    r = client.post(f"/api/v1/conversaciones/{cid}/mensajes", json={"texto": texto}, headers=auth)
    assert r.status_code == 200, r.text
    _esperar(cid)
    return r


def _crear(client, auth, asistente="tutor", texto="¿Cuándo entrego la PEC2?"):
    r = client.post("/api/v1/conversaciones", json={"asistente": asistente, "texto": texto}, headers=auth)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_titulo_del_primer_mensaje():
    assert conv.titulo("  hola\n  qué tal ") == "hola qué tal"
    largo = conv.titulo("palabra " * 30)
    assert len(largo) <= conv.TITULO_MAX + 1 and largo.endswith("…") and not largo.startswith(" ")
    assert conv.titulo("mira esto\n\n📎 Adjuntos (contenido externo…") == "mira esto"


def test_conversacion_completa(client, auth, turno):
    cid = _crear(client, auth)
    assert client.get("/api/v1/conversaciones?asistente=tutor").json() == []  # vacía: no sale en la lista
    _enviar(client, auth, cid, "¿Cuándo entrego la PEC2?")
    d = client.get(f"/api/v1/conversaciones/{cid}").json()
    assert d["conversacion"]["titulo"] == "¿Cuándo entrego la PEC2?" and d["conversacion"]["asistente"] == "tutor"
    assert [(m["rol"], m["texto"]) for m in d["mensajes"]] == [
        ("user", "¿Cuándo entrego la PEC2?"), ("tool", "mcp__pos__pos_read uni.deadlines"), ("tool", "Read /vault/Uni/PEC2.md"),
        ("assistant", "Entregas el viernes")]
    assert d["respuestas"][0]["estado"] == "done" and d["mensajes"][-1]["run_id"] == d["respuestas"][0]["id"]
    lista = client.get("/api/v1/conversaciones?asistente=tutor").json()
    assert [(c["id"], c["mensajes"]) for c in lista] == [(cid, 2)]
    assert client.get("/api/v1/conversaciones?asistente=salud").json() == []


def test_cada_conversacion_tiene_su_contexto(client, auth, turno):
    a, b = _crear(client, auth, texto="uno"), _crear(client, auth, texto="dos")
    for cid in (a, b, a):
        _enviar(client, auth, cid, "x")
    assert [p["session_id"] for p in turno] == [a, b, a]
    assert turno[0]["resume"] is None and turno[2]["resume"] == "12345678-1234-1234-1234-1234567890ab"
    with dbm.session_scope() as s:
        c = s.get(ChatSession, a)
        assert c.permissions["pos"]["agent"] == "tutor" and "Solo tu apartado" in c.permissions["system_prompt"]


def test_jarvis_elige_especialista_con_el_primer_mensaje(client, auth, turno):
    cid = _crear(client, auth, "jarvis", "¿cuánto he gastado este mes?")
    _enviar(client, auth, cid, "¿y en comida?")
    with dbm.session_scope() as s:
        assert s.get(ChatSession, cid).permissions["pos"]["agent"] == "finanzas"
    otra = _crear(client, auth, "jarvis", "hola")
    with dbm.session_scope() as s:
        assert s.get(ChatSession, otra).permissions["pos"]["agent"] == "jarvis"


def test_coach(client, auth, turno):
    cid = _crear(client, auth, "coach", "qué toca hoy")
    _enviar(client, auth, cid, "qué toca hoy")
    assert turno and turno[0]["gym"] is True and turno[0]["session_id"] == cid


def test_buscar(client, auth, turno):
    a = _crear(client, auth, texto="la PEC de redes")
    _enviar(client, auth, a, "la PEC de redes")
    b = _crear(client, auth, texto="otra cosa")
    _enviar(client, auth, b, "otra cosa")
    assert [c["id"] for c in client.get("/api/v1/conversaciones?q=redes").json()] == [a]
    assert [c["id"] for c in client.get("/api/v1/conversaciones?q=viernes").json()] == [b, a]  # también lo que respondió


def test_renombrar_y_archivar(client, auth, turno):
    cid = _crear(client, auth)
    _enviar(client, auth, cid, "hola")
    assert client.patch(f"/api/v1/conversaciones/{cid}", json={"titulo": "PEC2"}, headers=auth).json()["titulo"] == "PEC2"
    assert client.delete(f"/api/v1/conversaciones/{cid}", headers=auth).status_code == 200
    assert client.get("/api/v1/conversaciones").json() == []
    assert client.get(f"/api/v1/conversaciones/{cid}").status_code == 404
    with dbm.session_scope() as s:
        assert s.query(Message).filter(Message.session_id == cid).count() > 0  # archivada, no borrada


def test_asistente_desconocido_o_apagado(client, auth, config_instancia):
    assert client.post("/api/v1/conversaciones", json={"asistente": "nada"}, headers=auth).status_code == 404
    (config_instancia / "modulos.json").write_text('{"activos": []}')
    assert client.post("/api/v1/conversaciones", json={"asistente": "finanzas"}, headers=auth).status_code == 404
    assert client.post("/api/v1/conversaciones", json={"asistente": "jarvis"}, headers=auth).status_code == 200


def test_no_se_envia_mientras_responde(client, auth, monkeypatch):
    monkeypatch.setattr(runs.model_usage, "latest", lambda: {})
    monkeypatch.setattr(runs.events, "loop", lambda: None)  # el turno se queda en cola
    cid = _crear(client, auth)
    assert client.post(f"/api/v1/conversaciones/{cid}/mensajes", json={"texto": "uno"}, headers=auth).status_code == 200
    assert client.post(f"/api/v1/conversaciones/{cid}/mensajes", json={"texto": "dos"}, headers=auth).status_code == 409
    assert client.post(f"/api/v1/conversaciones/{cid}/interrumpir", headers=auth).json()["interrumpidas"]
    assert client.post(f"/api/v1/conversaciones/{cid}/mensajes", json={"texto": "dos"}, headers=auth).status_code == 200


def test_entra_en_la_memoria_del_dia(client, auth, turno):
    cid = _crear(client, auth)
    _enviar(client, auth, cid, "me examino el jueves")
    assert "me examino el jueves" in runs.conversation_of_day(runs._day())
