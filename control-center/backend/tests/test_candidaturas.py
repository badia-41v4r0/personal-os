"""Candidaturas con agente: nada se envía sin aprobación, y lo que se envía es exactamente lo aprobado."""
import asyncio
import base64
from datetime import date, timedelta

import pytest

from app import db as dbm
from app import sessions
from app.core import actions
from app.models import Action, ApplicationRun, JobApplication
from app.modules import applications as ap

PNG = base64.b64encode(b"\x89PNG fake").decode()
CAMPOS = [{"ref": "f1", "tipo": "text", "nombre": "name", "etiqueta": "Nombre", "valor": "Ana Prueba", "obligatorio": True},
          {"ref": "f2", "tipo": "email", "nombre": "email", "etiqueta": "Email", "valor": "a@b.c", "obligatorio": True},
          {"ref": "f3", "tipo": "file", "nombre": "cv", "etiqueta": "CV", "valor": ["cv.txt"], "obligatorio": True}]


class Fake:
    def __init__(self):
        self.calls, self.campos, self.bloqueos, self.enviar = [], [dict(c) for c in CAMPOS], [], True

    async def call(self, path, params=None, method="GET", json=None, timeout=15):
        self.calls.append((path, json))
        return {"ok": True}

    def call_sync(self, path, method="GET", json=None, timeout=15):
        self.calls.append((path, json))
        if path.endswith("/form/fields"):
            return {"url": "https://boards.greenhouse.io/acme/jobs/1", "titulo": "Apply", "campos": self.campos,
                    "botones": [{"ref": "b1", "texto": "Submit application", "tipo": "submit"}], "bloqueos": self.bloqueos}
        if path.endswith("/screenshot"):
            return {"png_base64": PNG}
        if path.endswith("/form/submit"):
            iguales = all(next((c["valor"] for c in self.campos if c["ref"] == k), object()) == v for k, v in json["esperado"].items())
            if not (self.enviar and iguales):
                return {"enviado": False, "motivo": "El formulario no es el que se aprobó"}
            return {"enviado": True, "url": "https://boards.greenhouse.io/acme/jobs/1/confirmation", "titulo": "Thanks", "texto": "Thank you"}
        return {"ok": True}


@pytest.fixture()
def ha(monkeypatch):
    f = Fake()
    monkeypatch.setattr(ap.hostagent, "call", f.call)
    monkeypatch.setattr(ap.hostagent, "call_sync", f.call_sync)
    return f


@pytest.fixture()
def agente(monkeypatch):
    """El turno del agente: rellena y llama a candidatura.preparada (o lo que diga la prueba)."""
    hace = {"accion": "preparada"}

    async def turno(sid, run_id, text):
        rid = text.split("`")[1]
        if hace["accion"] == "preparada":
            r = actions.request("candidatura.preparada", {"solicitud": rid, "campos": ["f1", "f2", "f3"], "boton": "b1", "notas": "todo"},
                                actor="solicitud")
        elif hace["accion"] == "abortar":
            r = actions.request("candidatura.abortar", {"solicitud": rid, "motivo": "captcha"}, actor="solicitud")
        else:
            return
        assert r["status"] == "done", r
    monkeypatch.setattr(sessions, "_run", turno)
    return hace


@pytest.fixture()
def cand(client, auth):
    r = client.post("/api/v1/me/career/applications", json={"empresa": "Acme", "puesto": "FDE", "estado": "interés"}, headers=auth)
    assert r.status_code < 300, r.text
    d = client.post("/api/v1/me/career/documents?nombre=cv.txt", content=b"Experiencia: IA", headers=auth | {"Content-Type": "application/octet-stream"})
    assert d.status_code == 200, d.text
    with dbm.session_scope() as s:
        aid = s.query(JobApplication).one().id
    return {"aid": aid, "doc": d.json()}


def crear(client, auth, cand, url="https://boards.greenhouse.io/acme/jobs/1"):
    return client.post(f"/api/v1/me/career/applications/{cand['aid']}/runs", json={"url": url, "documento": cand["doc"]["id"]}, headers=auth)


def preparar(client, auth, cand):
    r = crear(client, auth, cand)
    assert r.status_code == 200, r.text
    rid = r.json()["id"]
    asyncio.run(ap.preparar(rid))
    return rid


def test_perfil_siempre_conserva_lo_basico_de_nunca_rellenar(client, auth):
    r = client.put("/api/v1/me/career/profile", json={"nombre": "Ana", "nunca_rellenar": ["matrícula"]}, headers=auth)
    assert r.status_code == 200 and set(ap.NUNCA) <= set(r.json()["nunca_rellenar"]) and "matrícula" in r.json()["nunca_rellenar"]
    assert client.get("/api/v1/me/career/profile").json()["nombre"] == "Ana"


def test_documento_sin_duplicar(client, auth, cand):
    d = client.post("/api/v1/me/career/documents?nombre=otro.txt", content=b"Experiencia: IA", headers=auth | {"Content-Type": "application/octet-stream"})
    assert d.json()["repetido"] is True and len(client.get("/api/v1/me/career/documents").json()) == 1
    assert client.post("/api/v1/me/career/documents?nombre=virus.exe", content=b"x", headers=auth).status_code == 422


@pytest.mark.parametrize("url", ["http://acme.com/jobs", "https://user@acme.com/jobs", "ftp://acme.com/jobs/12345"])
def test_solo_https(client, auth, cand, url):
    assert crear(client, auth, cand, url).status_code == 422


def test_flujo_completo_solo_se_envia_tras_aprobar(client, auth, cand, ha, agente):
    rid = preparar(client, auth, cand)
    run = client.get(f"/api/v1/me/career/runs/{rid}").json()
    assert run["estado"] == "listo_para_revisar" and run["dominios"][0] == "greenhouse.io"
    assert not any(p.endswith("/form/submit") for p, _ in ha.calls)  # nada enviado aún
    a = run["accion"]
    with dbm.session_scope() as s:
        act = s.get(Action, a["id"])
        assert act.level == 3 and act.status == "pending" and act.payload["esperado"]["f1"] == "Ana Prueba"
        assert act.payload["documento"]["sha256"] == cand["doc"]["sha256"] and act.payload["boton"] == "b1"
    # aprobar
    r = client.post(f"/api/v1/actions/{a['id']}/decide", json={"aprobar": True, "hash": a["hash"]}, headers=auth)
    assert r.status_code == 200, r.text
    run = client.get(f"/api/v1/me/career/runs/{rid}").json()
    assert run["estado"] == "enviada" and run["resultado"]["titulo"] == "Thanks"
    with dbm.session_scope() as s:
        app = s.get(JobApplication, cand["aid"])
        assert app.status == "aplicado" and app.follow_up == (date.today() + timedelta(days=7)).isoformat()
    assert client.get(f"/api/v1/me/career/runs/{rid}/screenshot/0").status_code == 200


def test_si_el_formulario_cambia_no_se_envia(client, auth, cand, ha, agente):
    rid = preparar(client, auth, cand)
    a = client.get(f"/api/v1/me/career/runs/{rid}").json()["accion"]
    ha.campos[1]["valor"] = "otro@correo.com"  # alguien (la página) lo cambió tras la revisión
    client.post(f"/api/v1/actions/{a['id']}/decide", json={"aprobar": True, "hash": a["hash"]}, headers=auth)
    run = client.get(f"/api/v1/me/career/runs/{rid}").json()
    assert run["estado"] == "fallida" and "No se ha enviado" in run["error"]
    with dbm.session_scope() as s:
        assert s.get(JobApplication, cand["aid"]).status == "interés" and s.get(Action, a["id"]).status == "failed"


def test_rechazar_cierra_la_solicitud(client, auth, cand, ha, agente):
    rid = preparar(client, auth, cand)
    a = client.get(f"/api/v1/me/career/runs/{rid}").json()["accion"]
    client.post(f"/api/v1/actions/{a['id']}/decide", json={"aprobar": False, "hash": a["hash"]}, headers=auth)
    assert client.get(f"/api/v1/me/career/runs/{rid}").json()["estado"] == "rechazada"
    assert any(p.endswith("/lifecycle/remove") for p, _ in ha.calls) and not any(p.endswith("/form/submit") for p, _ in ha.calls)


def test_captcha_pasa_a_manual(client, auth, cand, ha, agente):
    ha.bloqueos = ["captcha"]
    rid = preparar(client, auth, cand)
    run = client.get(f"/api/v1/me/career/runs/{rid}").json()
    assert run["estado"] == "fallida" and "captcha" in run["error"] and run["accion"] is None


def test_un_campo_sensible_con_valor_no_se_ofrece(client, auth, cand, ha, agente):
    ha.campos.append({"ref": "f4", "tipo": "text", "nombre": "dni", "etiqueta": "DNI", "valor": "12345678Z"})
    rid = preparar(client, auth, cand)
    run = client.get(f"/api/v1/me/career/runs/{rid}").json()
    assert run["estado"] == "fallida" and "nunca rellenar" in run["error"]


def test_el_agente_aborta(client, auth, cand, ha, agente):
    agente["accion"] = "abortar"
    rid = preparar(client, auth, cand)
    assert client.get(f"/api/v1/me/career/runs/{rid}").json()["estado"] == "abortada"


def test_si_el_agente_no_termina_falla(client, auth, cand, ha, agente):
    agente["accion"] = "nada"
    rid = preparar(client, auth, cand)
    assert client.get(f"/api/v1/me/career/runs/{rid}").json()["estado"] == "fallida"


def test_una_solicitud_a_la_vez(client, auth, cand, ha):
    assert crear(client, auth, cand).status_code == 200
    assert crear(client, auth, cand).status_code == 409


def test_el_nivel_de_enviar_no_se_puede_bajar(client, auth):
    r = client.put("/api/v1/actions/capabilities/candidatura.aplicar", json={"nivel": 1}, headers=auth)
    assert r.status_code == 409
    assert actions.REGISTRY["candidatura.aplicar"].level == 3


def test_el_agente_no_puede_pedir_el_envio_por_su_cuenta(client):
    # aunque lo pidiera con su credencial, es nivel 3: queda pendiente de Ana y su solicitud no está lista
    r = actions.request("candidatura.aplicar", {"solicitud": "x", "boton": "b1", "esperado": {}}, actor="solicitud")
    assert r["status"] == "pending"


def test_preparada_solo_con_referencias_validas(client, auth, cand, ha):
    rid = crear(client, auth, cand).json()["id"]
    with dbm.session_scope() as s:
        s.get(ApplicationRun, rid).status = "preparando"
    r = actions.request("candidatura.preparada", {"solicitud": rid, "campos": ["f1"], "boton": "javascript:alert(1)"}, actor="solicitud")
    assert r["status"] == "failed"


def test_borrar_candidatura(client, auth, cand, ha):
    rid = crear(client, auth, cand).json()["id"]
    assert client.delete(f"/api/v1/me/career/applications/{cand['aid']}", headers=auth).status_code == 409  # solicitud en marcha
    client.post(f"/api/v1/me/career/runs/{rid}/abort", headers=auth)
    assert client.delete(f"/api/v1/me/career/applications/{cand['aid']}", headers=auth).status_code == 200
    with dbm.session_scope() as s:
        assert s.get(JobApplication, cand["aid"]) is None and s.get(ApplicationRun, rid) is None
    assert client.delete(f"/api/v1/me/career/applications/{cand['aid']}", headers=auth).status_code == 404
