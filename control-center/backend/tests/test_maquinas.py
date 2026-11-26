"""Máquinas locales: el backend solo valida, audita y pasa al Host Agent (aquí simulado)."""
import base64

import pytest

from app import maquinas
from app.adapters import hostagent


@pytest.fixture()
def ha(monkeypatch):
    llamadas = []

    async def call(path, params=None, method="GET", json=None, timeout=15):
        llamadas.append((method, path, json))
        if path == "/v1/maquinas" and method == "GET":
            return {"virtualbox": {"instalado": True, "version": "7.2"}, "vms": [], "maquinas": []}
        if path.endswith("/captura"):
            return {"png_base64": base64.b64encode(b"\x89PNG").decode()}
        if path == "/v1/maquinas":
            return {"id": "veriluoc", "puerto": 2222, "hecho": ["clave"], "comandos": {"base": "…", "navegador": "…"}}
        return {"ok": True}

    monkeypatch.setattr(hostagent, "call", call)
    return llamadas


def test_estado_incluye_agentes_con_ordenador(client, auth, ha):
    r = client.get("/api/v1/maquinas", headers=auth)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["virtualbox"]["instalado"] and "agentes" in d
    assert "tutor" in [a["id"] for a in d["agentes"]]  # el tutor que trae el proyecto tiene «ordenador»


def test_sin_host_agent_no_rompe(client, auth, monkeypatch):
    async def caido(*a, **k):
        raise hostagent.HostAgentError(503, "Host Agent no disponible")
    monkeypatch.setattr(hostagent, "call", caido)
    d = client.get("/api/v1/maquinas", headers=auth).json()
    assert d["virtualbox"]["instalado"] is False and d["error"] == "Host Agent no disponible"


def test_asistente_pasa_al_host_agent_y_audita(client, auth, ha):
    r = client.post("/api/v1/maquinas", json={"vbox": "VerilUOC_Desktop_1025", "nombre": "VerilUOC"}, headers=auth)
    assert r.status_code == 200 and r.json()["id"] == "veriluoc"
    assert client.post("/api/v1/maquinas/veriluoc/probar", json={"usuario": "mooccf"}, headers=auth).json() == {"ok": True}
    assert client.patch("/api/v1/maquinas/veriluoc", json={"agentes": ["tutor"], "notas": "x"}, headers=auth).status_code == 200
    assert client.post("/api/v1/maquinas/veriluoc/accion", json={"que": "encender"}, headers=auth).status_code == 200
    assert client.get("/api/v1/maquinas/veriluoc/captura", headers=auth).content == b"\x89PNG"
    assert client.delete("/api/v1/maquinas/veriluoc", headers=auth).status_code == 200
    assert [(m, p) for m, p, _ in ha] == [("POST", "/v1/maquinas"), ("POST", "/v1/maquinas/veriluoc/probar"),
                                         ("PATCH", "/v1/maquinas/veriluoc"), ("POST", "/v1/maquinas/veriluoc/accion"),
                                         ("GET", "/v1/maquinas/veriluoc/captura"), ("DELETE", "/v1/maquinas/veriluoc")]
    from app import db as dbm
    from app.models import AuditLog
    from sqlalchemy import select
    with dbm.session_scope() as s:
        acciones = [a.action for a in s.scalars(select(AuditLog).where(AuditLog.action.like("maquinas.%")))]
    assert acciones == ["maquinas.preparar", "maquinas.probar", "maquinas.cambiar", "maquinas.encender", "maquinas.quitar"]


def test_valida_antes_de_llamar(client, auth, ha):
    assert client.patch("/api/v1/maquinas/veriluoc", json={"agentes": ["no-existe"]}, headers=auth).status_code == 422
    assert client.post("/api/v1/maquinas/veriluoc/accion", json={"que": "borrar"}, headers=auth).status_code == 422
    assert client.post("/api/v1/maquinas/..%2Fx/probar", json={}, headers=auth).status_code >= 400
    assert client.post("/api/v1/maquinas/Mal_ID/probar", json={}, headers=auth).status_code == 422
    assert ha == []


def test_hace_falta_sesion(client, ha):
    assert client.get("/api/v1/maquinas").status_code == 401
    assert client.post("/api/v1/maquinas", json={"vbox": "x"}).status_code in (401, 403)
    assert ha == []


def test_agentes_con_ordenador_excluye_los_que_no():
    from app import db as dbm
    with dbm.session_scope() as s:
        ids = {a["id"] for a in maquinas.agentes_con_ordenador(s)}
    assert "tutor" in ids
