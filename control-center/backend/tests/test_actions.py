import pytest
from sqlalchemy import update

from app import db as dbm
from app import events
from app.core import actions as ac
from app.models import Action, AuditLog, Notification


@pytest.fixture()
def caps(client):
    hechos = []
    antes = dict(ac.REGISTRY)
    ac.REGISTRY.clear()

    def h(p, db):
        if p.get("falla"):
            raise RuntimeError("boom")
        hechos.append(p)
        return {"hecho": p.get("n", 0)}

    def inv(result, db):
        hechos.append({"deshecho": result["hecho"]})
    ac.register(ac.Capability("t.auto", 1, h, "Auto", inverse=inv))
    ac.register(ac.Capability("t.regla", 2, h, "Regla", rule=lambda p, lim: p.get("n", 0) <= lim.get("max", 10)))
    ac.register(ac.Capability("t.aprobar", 3, h, "Aprobar", summary=lambda p: f"Hacer {p.get('n')}"))
    yield hechos
    ac.REGISTRY.clear()
    ac.REGISTRY.update(antes)


def pedir(cap, payload=None, **k):
    return ac.request(cap, payload or {}, actor=k.pop("actor", "finanzas"), **k)


def test_desconocida_se_deniega_y_se_audita(caps):
    assert pedir("dinero.transferir")["status"] == "denied"
    with dbm.session_scope() as s:
        assert s.query(AuditLog).filter(AuditLog.action == "action.denied").count() == 1


def test_nivel_1_se_ejecuta(caps):
    assert pedir("t.auto", {"n": 1})["status"] == "done" and caps == [{"n": 1}]


def test_nivel_2_dentro_y_fuera_de_regla(caps):
    assert pedir("t.regla", {"n": 5})["status"] == "done"
    assert pedir("t.regla", {"n": 50})["status"] == "pending"
    assert len(caps) == 1


def test_contenido_externo_sube_el_nivel_2_a_aprobacion(caps):
    assert pedir("t.regla", {"n": 5}, tainted=True)["status"] == "pending" and caps == []


def test_nivel_3_espera_y_avisa(caps):
    r = pedir("t.aprobar", {"n": 1})
    assert r["status"] == "pending" and caps == []
    with dbm.session_scope() as s:
        n = s.query(Notification).one()
        assert n.level == "action" and n.url == "/bandeja/" and n.body == "Hacer 1"


def test_aprobar_ejecuta(caps):
    r = pedir("t.aprobar", {"n": 1})
    assert ac.decide(r["id"], True, r["hash"], "ana")["status"] == "done" and caps == [{"n": 1}]


def test_aprobacion_ligada_al_contenido(caps):
    r = pedir("t.aprobar", {"n": 1})
    with pytest.raises(Exception) as e:
        ac.decide(r["id"], True, "0" * 64, "ana")
    assert e.value.status_code == 409 and caps == []


def test_contenido_alterado_tras_pedir_no_se_ejecuta(caps):
    r = pedir("t.aprobar", {"n": 1})
    with dbm.session_scope() as s:
        s.execute(update(Action).where(Action.id == r["id"]).values(payload={"n": 999}))
    with pytest.raises(Exception):
        ac.decide(r["id"], True, r["hash"], "ana")
    assert caps == []


def test_rechazar(caps):
    r = pedir("t.aprobar")
    assert ac.decide(r["id"], False, r["hash"], "ana")["status"] == "rejected" and caps == []


def test_no_se_decide_dos_veces(caps):
    r = pedir("t.aprobar", {"n": 1})
    ac.decide(r["id"], True, r["hash"], "ana")
    with pytest.raises(Exception) as e:
        ac.decide(r["id"], True, r["hash"], "ana")
    assert e.value.status_code == 409 and len(caps) == 1


def test_caduca(caps):
    r = pedir("t.aprobar")
    with dbm.session_scope() as s:
        s.get(Action, r["id"]).expires_at = dbm.utcnow() - ac.timedelta(minutes=1)
    with pytest.raises(Exception) as e:
        ac.decide(r["id"], True, r["hash"], "ana")
    assert e.value.status_code == 409 and caps == []
    with dbm.session_scope() as s:
        assert s.get(Action, r["id"]).status == "expired"


def test_vencidas_se_cierran_solas(caps):
    r = pedir("t.aprobar")
    with dbm.session_scope() as s:
        s.get(Action, r["id"]).expires_at = dbm.utcnow() - ac.timedelta(minutes=1)
    assert ac.expire_pending() == 1


def test_idempotencia(caps):
    a = pedir("t.auto", {"n": 1}, idempotency_key="k1")
    b = pedir("t.auto", {"n": 1}, idempotency_key="k1")
    assert a["id"] == b["id"] and len(caps) == 1


def test_fallo_se_registra_sin_reintentar(caps):
    r = pedir("t.auto", {"falla": True})
    assert r["status"] == "failed" and "boom" in r["error"]


def test_deshacer(caps):
    r = pedir("t.auto", {"n": 3})
    assert ac.undo(r["id"], "ana")["status"] == "undone" and caps[-1] == {"deshecho": 3}


def test_no_reversible(caps):
    r = pedir("t.regla", {"n": 1})
    with pytest.raises(Exception) as e:
        ac.undo(r["id"], "ana")
    assert e.value.status_code == 409


def test_interruptor_general(client, auth, caps):
    assert client.post("/api/v1/autonomy/pause", json={"pausado": True}, headers=auth).status_code == 200
    assert pedir("t.auto")["status"] == "denied" and caps == []
    assert ac.request("t.auto", {"n": 1}, actor="ana", actor_type="user")["status"] == "done"  # Ana sí
    client.post("/api/v1/autonomy/pause", json={"pausado": False}, headers=auth)
    assert pedir("t.auto", {"n": 2})["status"] == "done"


@pytest.mark.parametrize("agente,cap,afecta", [("finanzas", "*", True), ("*", "t.auto", True), ("otro", "*", False)])
def test_revocacion(client, auth, caps, agente, cap, afecta):
    rid = client.post("/api/v1/autonomy/revocations", json={"agente": agente, "capacidad": cap}, headers=auth).json()["id"]
    assert (pedir("t.auto")["status"] == "denied") is afecta
    client.delete(f"/api/v1/autonomy/revocations/{rid}", headers=auth)
    assert pedir("t.auto")["status"] == "done"


def test_el_usuario_ajusta_el_nivel(client, auth, caps):
    assert client.put("/api/v1/actions/capabilities/t.auto", json={"nivel": 3}, headers=auth).status_code == 200
    assert pedir("t.auto")["status"] == "pending"
    client.put("/api/v1/actions/capabilities/t.auto", json={"activa": False}, headers=auth)
    assert pedir("t.auto")["status"] == "denied"


def test_limites_de_la_regla_vienen_de_la_politica(client, auth, caps):
    client.put("/api/v1/actions/capabilities/t.regla", json={"limites": {"max": 100}}, headers=auth)
    assert pedir("t.regla", {"n": 50})["status"] == "done"


def test_api_decidir(client, auth, caps):
    r = pedir("t.aprobar", {"n": 1})
    assert client.get("/api/v1/actions?estado=pending").json()[0]["id"] == r["id"]
    d = client.post(f"/api/v1/actions/{r['id']}/decide", json={"aprobar": True, "hash": r["hash"]}, headers=auth)
    assert d.json()["status"] == "done"


def test_cadena_de_auditoria_detecta_manipulacion(client, auth, caps):
    pedir("t.auto")
    pedir("t.auto")
    assert client.get("/api/v1/audit/verify").json()["ok"] is True
    with dbm.session_scope() as s:
        fila = s.query(AuditLog).filter(AuditLog.hash != "").order_by(AuditLog.id).first()
        fila.target = "alterado"
    v = client.get("/api/v1/audit/verify").json()
    assert v["ok"] is False and v["broken_at"]


def test_borrar_una_fila_rompe_la_cadena(client, auth, caps):
    pedir("t.auto")
    pedir("t.auto")
    with dbm.session_scope() as s:
        filas = s.query(AuditLog).filter(AuditLog.hash != "").order_by(AuditLog.id).all()
        s.delete(filas[1])
    with dbm.session_scope() as s:
        assert events.verify_chain(s)["ok"] is False


def test_identidad_llega_al_host_agent(client, auth, monkeypatch):
    from app.adapters import hostagent
    vistos = []

    async def fake(path, **k):
        vistos.append(hostagent.ACTOR.get())
        return {"text": "hola"}
    monkeypatch.setattr(hostagent, "call", fake)
    r = client.post("/api/v1/voice/transcribe", content=b"audio", headers=auth | {"Content-Type": "application/octet-stream"})
    assert r.json() == {"text": "hola"} and vistos == ["ana"]
