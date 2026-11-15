from pathlib import Path

import pytest

from app.config import ROOT

ENTRENADOR = (ROOT / "agent/.claude/agents/entrenador.md").read_text()


def spec(**kw):
    return {"name": "analista", "target": "panel", "description": "Analiza documentos y resume lo importante",
            "instructions": "Lee lo que te pasen y resume en 5 puntos.", "level": "read", "model": "sonnet"} | kw


@pytest.fixture()
def repo_agent(settings):
    (settings.agents_dir / "entrenador.md").write_text(ENTRENADOR)
    return settings.agents_dir


def test_importa_los_del_repo(client, auth, repo_agent):
    a = {x["id"]: x for x in client.get("/api/v1/agents").json()}["entrenador"]
    assert a["origin"] == "repo" and a["status"] == "active" and a["target"] == "jarvis"
    assert a["tools"] == ["Read", "Grep", "Glob"] and a["model"] == "sonnet" and a["level"] == "read"
    d = client.get("/api/v1/agents/entrenador").json()
    assert d["rendered"] == ENTRENADOR  # la versión 1 es el archivo tal cual


@pytest.mark.parametrize("bad,msg", [
    ({"name": "Mal Nombre"}, "Nombre"), ({"level": "execute"}, "ordenador virtual"),
    ({"target": "jarvis", "internet": True}, "internet"), ({"instructions": "haz esto !`rm -rf /` ya"}, "inyección"),
    ({"name": "jarvis"}, "reservado"),
])
def test_validacion(client, auth, bad, msg):
    r = client.post("/api/v1/agents/validate", json={"spec": spec(**bad)}, headers=auth).json()
    assert not r["ok"] and any(msg in e for e in r["errors"])
    assert client.post("/api/v1/agents", json={"spec": spec(**bad)}, headers=auth).status_code == 422


def test_vista_previa_formato_claude(client, auth):
    r = client.post("/api/v1/agents/validate", json={"spec": spec(target="jarvis", level="propose", objective="Ayudar")}, headers=auth).json()
    assert r["ok"] and r["rendered"].startswith("---\nname: analista\ndescription: \"Analiza")
    assert "tools: Read, Grep, Glob, Edit, Write\nmodel: sonnet\n---\n## Objetivo\nAyudar" in r["rendered"]


def test_nace_como_borrador_y_activar_jarvis_pide_confirmacion(client, auth, settings):
    a = client.post("/api/v1/agents", json={"spec": spec(target="jarvis")}, headers=auth).json()
    assert a["status"] == "draft" and a["origin"] == "panel"
    f = settings.agents_dir / "analista.md"
    r = client.post("/api/v1/agents/analista/activate", json={}, headers=auth).json()
    assert r["needs_confirm"] and not f.exists()
    r = client.post("/api/v1/agents/analista/activate", json={"confirm": True}, headers=auth).json()
    assert r["status"] == "active" and f.read_text().startswith("---\nname: analista")
    # Editar un subagente activo reescribe el archivo
    r = client.patch("/api/v1/agents/analista", json={"spec": spec(target="jarvis", instructions="Nuevas instrucciones largas"), "base_version": 1}, headers=auth).json()
    assert r["version"] == 2 and r["written"] and "Nuevas instrucciones" in f.read_text()


def test_conflicto_de_version_y_restaurar(client, auth):
    client.post("/api/v1/agents", json={"spec": spec()}, headers=auth)
    assert client.patch("/api/v1/agents/analista", json={"spec": spec(level="propose"), "base_version": 1}, headers=auth).json()["escalates"]
    assert client.patch("/api/v1/agents/analista", json={"spec": spec(), "base_version": 1}, headers=auth).status_code == 409
    v = client.get("/api/v1/agents/analista/versions").json()
    assert [x["version"] for x in v] == [2, 1]
    r = client.post("/api/v1/agents/analista/restore", json={"version": 1, "base_version": 2}, headers=auth).json()
    assert r["version"] == 3 and r["level"] == "read"
    audit = client.get("/api/v1/audit").json()
    assert any(x["action"] == "agent.update" for x in audit)


def test_no_se_cambia_nombre_ni_destino(client, auth):
    client.post("/api/v1/agents", json={"spec": spec()}, headers=auth)
    assert client.patch("/api/v1/agents/analista", json={"spec": spec(name="otro"), "base_version": 1}, headers=auth).status_code == 422
    assert client.patch("/api/v1/agents/analista", json={"spec": spec(target="jarvis"), "base_version": 1}, headers=auth).status_code == 422


def test_desactivar_y_borrar(client, auth, settings):
    client.post("/api/v1/agents", json={"spec": spec(target="jarvis")}, headers=auth)
    client.post("/api/v1/agents/analista/activate", json={"confirm": True}, headers=auth)
    assert client.delete("/api/v1/agents/analista", headers=auth).status_code == 409
    assert client.post("/api/v1/agents/analista/deactivate", json={}, headers=auth).json()["needs_confirm"]
    assert client.post("/api/v1/agents/analista/deactivate", json={"confirm": True}, headers=auth).json()["status"] == "inactive"
    assert not (settings.agents_dir / "analista.md").exists()
    assert client.delete("/api/v1/agents/analista", headers=auth).status_code == 200
    assert client.get("/api/v1/agents/analista").status_code == 404


def test_los_del_repo_no_se_borran(client, auth, repo_agent):
    client.get("/api/v1/agents")
    client.post("/api/v1/agents/entrenador/deactivate", json={"confirm": True}, headers=auth)
    assert client.delete("/api/v1/agents/entrenador", headers=auth).status_code == 409
    assert not (repo_agent / "entrenador.md").exists()  # desactivado = sin archivo, definición guardada
    client.post("/api/v1/agents/entrenador/activate", json={"confirm": True}, headers=auth)
    assert (repo_agent / "entrenador.md").exists()


def test_cambio_externo_se_guarda_como_version(client, auth, repo_agent):
    client.get("/api/v1/agents")
    (repo_agent / "entrenador.md").write_text(ENTRENADOR.replace("exigente", "amable"))
    d = client.get("/api/v1/agents/entrenador").json()
    assert d["version"] == 2 and "amable" in d["rendered"]
    assert client.get("/api/v1/agents/entrenador/versions").json()[0]["author"] == "externo"


def test_duplicar_exportar_e_iniciar_sesion(client, auth):
    client.post("/api/v1/agents", json={"spec": spec(level="propose", internet=True)}, headers=auth)
    assert client.post("/api/v1/agents/analista/sessions", json={}, headers=auth).status_code == 409  # borrador
    client.post("/api/v1/agents/analista/activate", json={}, headers=auth)
    s = client.post("/api/v1/agents/analista/sessions", json={}, headers=auth).json()
    assert s["agent_id"] == "analista" and s["permissions"]["level"] == "propose" and s["permissions"]["internet"]
    assert "resume en 5 puntos" in s["permissions"]["system_prompt"]
    assert client.get("/api/v1/agents/analista/sessions").json()[0]["id"] == s["id"]
    d = client.post("/api/v1/agents/analista/duplicate", json={"name": "analista-2"}, headers=auth).json()
    assert d["status"] == "draft" and d["version"] == 1
    r = client.get("/api/v1/agents/analista/export")
    assert r.headers["content-disposition"].endswith('analista.md"') and r.text.startswith("---")


def test_subagentes_y_ordenador(client, auth):
    r = client.post("/api/v1/agents/validate", json={"spec": spec(target="jarvis", virtual_computer=True)}, headers=auth).json()
    assert not r["ok"] and any("ordenadores virtuales" in e for e in r["errors"])
    r = client.post("/api/v1/agents/validate", json={"spec": spec(target="jarvis", subagents=True)}, headers=auth).json()
    assert not r["ok"]
    r = client.post("/api/v1/agents/validate", json={"spec": spec(level="execute", virtual_computer=True, subagents=True, vault=True)}, headers=auth).json()
    assert r["ok"] and "Agent" in r["tools"]
    client.post("/api/v1/agents", json={"spec": spec(level="execute", virtual_computer=True, subagents=True, vault=True)}, headers=auth)
    client.post("/api/v1/agents/analista/activate", json={}, headers=auth)
    s = client.post("/api/v1/agents/analista/sessions", json={}, headers=auth).json()
    assert s["permissions"]["subagents"] and s["permissions"]["vc"]["enabled"] and s["permissions"]["vault"] and s["permissions"]["level"] == "execute"
