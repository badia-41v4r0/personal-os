from datetime import timedelta

import pytest

from app import db as dbm
from app.core import actions, gateway, memory
from app.models import Action, Fact, LifeEvent


def test_cambiar_un_hecho_conserva_el_historial(client, auth):
    for fase in ("volumen", "definición"):
        assert client.post("/api/v1/core/facts", json={"subject": "gym", "predicate": "fase", "value": {"v": fase}}, headers=auth).status_code == 200
    actual = client.get("/api/v1/core/facts?subject=gym").json()
    assert [f["value"]["v"] for f in actual] == ["definición"]
    hist = client.get("/api/v1/core/facts/history?subject=gym&predicate=fase").json()
    assert len(hist) == 2 and hist[1]["valid_to"]
    with dbm.session_scope() as s:
        assert s.query(LifeEvent).filter(LifeEvent.type == "fact.changed").count() == 1


def test_repetir_el_mismo_valor_no_ensucia(client, auth):
    for _ in range(3):
        client.post("/api/v1/core/facts", json={"subject": "a", "predicate": "b", "value": {"v": 1}}, headers=auth)
    assert len(client.get("/api/v1/core/facts/history?subject=a&predicate=b").json()) == 1


def test_que_se_creia_en_una_fecha(client):
    with dbm.session_scope() as s:
        memory.set_fact(s, "gym", "fase", {"v": "volumen"}, "confirmed")
    corte = dbm.utcnow() + timedelta(milliseconds=1)
    with dbm.session_scope() as s:
        memory.set_fact(s, "gym", "fase", {"v": "definición"}, "confirmed", valid_from=corte + timedelta(seconds=1))
    with dbm.session_scope() as s:
        assert memory.facts_as_of(s, corte, "gym")[0]["value"] == {"v": "volumen"}


def test_agente_propone_pero_no_confirma(client, auth):
    r = actions.request("memory.fact.propose", {"subject": "yo", "predicate": "ciudad", "value": {"v": "BCN"}, "confidence": 0.7}, actor="jarvis")
    assert r["status"] == "done"
    f = client.get("/api/v1/core/facts?subject=yo").json()[0]
    assert f["verification"] == "inferred" and f["confidence"] == 0.7
    with dbm.session_scope() as s:
        assert memory.context_pack(s)["hechos"] == []  # lo inferido no entra como cierto en el contexto
    client.post(f"/api/v1/core/facts/{f['id']}/verify", headers=auth)
    with dbm.session_scope() as s:
        assert len(memory.context_pack(s)["hechos"]) == 1


def test_rechazar_lo_cierra_sin_borrarlo(client, auth):
    with dbm.session_scope() as s:
        fid = memory.set_fact(s, "x", "y", {"v": 1}, "inferred").id
    client.post(f"/api/v1/core/facts/{fid}/reject", headers=auth)
    assert client.get("/api/v1/core/facts?subject=x").json() == []
    with dbm.session_scope() as s:
        assert s.get(Fact, fid) is not None


def test_decisiones(client, auth):
    r = client.post("/api/v1/core/decisions", json={"decided_on": "2026-11-04", "title": "Empezar volumen", "domain": "fitness", "choice": "Superávit"}, headers=auth)
    assert r.status_code == 200
    assert client.get("/api/v1/core/decisions?status=active").json()[0]["titulo"] == "Empezar volumen"
    assert client.get("/api/v1/core/events?domain=fitness").json()[0]["type"] == "decision"


def test_trocear_markdown():
    t = "---\nfecha: x\n---\n# Título\n🧭 nav\nHola\n## Sección\n" + "a" * 2500
    c = memory.chunk_markdown(t)
    assert c[0] == ("Título", "Hola") and c[1][0] == "Sección" and len(c) == 4 and all(len(x[1]) <= memory.CHUNK_CHARS for x in c)


def test_excluye_lo_generado_y_conflictos(tmp_path):
    (tmp_path / "Jarvis").mkdir()
    for n in ("Jarvis/Panel.md", "Jarvis/Nota.md", "Jarvis/Panel.sync-conflict-1.md"):
        (tmp_path / n).write_text("x")
    assert [p.name for p in memory._indexable(tmp_path)] == ["Nota.md"]


def test_gateway_sin_credencial(client):
    assert client.post("/api/v1/internal/pos/call", json={"kind": "read", "name": "memory.facts"}).status_code == 401
    assert client.post("/api/v1/internal/pos/call", json={"kind": "read", "name": "memory.facts"}, headers={"X-Run-Token": "x"}).status_code == 401


def test_gateway_solo_abre_lo_de_la_ejecucion(client):
    t = gateway.issue_token("r1", "fitness", ["memory.facts"], ["memory.fact.propose"])
    h = {"X-Run-Token": t}
    assert client.post("/api/v1/internal/pos/call", json={"kind": "read", "name": "memory.facts"}, headers=h).status_code == 200
    assert client.post("/api/v1/internal/pos/call", json={"kind": "read", "name": "memory.search"}, headers=h).status_code == 403
    r = client.post("/api/v1/internal/pos/call", json={"kind": "action", "name": "otra.cosa"}, headers=h).json()
    assert r["result"]["status"] == "denied"


def test_gateway_identifica_al_agente_y_marca_contenido_externo(client):
    t = gateway.issue_token("r2", "finanzas", [], ["memory.fact.propose"], tainted=True)
    body = {"kind": "action", "name": "memory.fact.propose", "args": {"subject": "a", "predicate": "b", "value": {}}, "reason": "porque"}
    assert client.post("/api/v1/internal/pos/call", json=body, headers={"X-Run-Token": t}).json()["result"]["status"] == "done"
    with dbm.session_scope() as s:
        a = s.query(Action).one()
        assert a.actor == "finanzas" and a.tainted and a.run_id == "r2" and a.reason == "porque"


def test_credencial_caduca_y_se_revoca(client):
    t = gateway.issue_token("r3", "x", ["memory.facts"], [])
    gateway.revoke_run("r3")
    assert client.post("/api/v1/internal/pos/call", json={"kind": "read", "name": "memory.facts"}, headers={"X-Run-Token": t}).status_code == 401


@pytest.mark.skipif("not __import__('os').environ.get('CC_DB_URL')", reason="requiere PostgreSQL")
def test_busqueda_en_espanol_e_incremental(client, settings):
    d = settings.vault / "Jarvis"
    d.mkdir(parents=True)
    (d / "Fuerza.md").write_text("# Entrenamiento\nMis sentadillas progresan muy bien este mes.\n")
    (d / "Otra.md").write_text("# Cocina\nReceta de lentejas.\n")
    r = memory.reindex()
    assert r["indexed"] == 2
    assert memory.reindex()["skipped"] == 2  # sin cambios no se reindexa
    with dbm.session_scope() as s:
        h = memory.search(s, "sentadilla")  # singular: encuentra el plural por la raíz española
    assert h and h[0]["path"] == "Jarvis/Fuerza.md"


def test_gateway_lista_lo_que_abre(client):
    t = gateway.issue_token("r9", "x", ["memory.facts"], ["memory.fact.propose"])
    r = client.get("/api/v1/internal/pos/tools", headers={"X-Run-Token": t}).json()
    assert r["result"] == {"lecturas": ["memory.facts"], "capacidades": ["memory.fact.propose"]}
    assert client.get("/api/v1/internal/pos/tools").status_code == 401


def test_finanzas_ve_agregados_por_el_gateway(client, auth):
    client.post("/api/v1/finance/accounts", json={"name": "asset:banco", "kind": "asset"}, headers=auth)
    t = gateway.issue_token("r8", "finanzas", ["finance.summary"], [])
    r = client.post("/api/v1/internal/pos/call", json={"kind": "read", "name": "finance.summary", "args": {"mes": "2026-11"}}, headers={"X-Run-Token": t}).json()
    assert r["result"]["patrimonio"]["patrimonio"] == "0.00"
