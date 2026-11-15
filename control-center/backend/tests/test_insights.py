from datetime import date

from app import db as dbm
from app.modules import insights

JUEVES = date(2026, 11, 5)
G = {"sesiones": 4, "planificadas": 5}
E = {"proxima": None}
C = {"ofertas_nuevas": 0, "candidaturas": 0}


def build(gym=G, est=E, car=C, tareas=(), goals=()):
    with dbm.session_scope() as s:
        return insights.build(s, JUEVES, gym, est, car, list(tareas), list(goals))


def test_reconoce_lo_que_va_bien(client):
    assert build()[0]["tipo"] == "bien"
    assert "descansar" in build({"sesiones": 5, "planificadas": 5})[0]["texto"]


def test_gym_por_detras(client):
    r = build({"sesiones": 1, "planificadas": 5})
    assert r[0]["tipo"] == "aviso" and "1 de 4" in r[0]["texto"]


def test_sin_novedad_no_inventa(client):
    assert build({"sesiones": 3, "planificadas": 5}) == []


def test_entrega_cercana_y_lejana(client):
    assert "mañana" in build(est={"proxima": {"fecha": "2026-11-06", "texto": "PEC 2"}})[0]["texto"]
    assert len(build(est={"proxima": {"fecha": "2026-12-06", "texto": "PEC 2"}})) == 1


def test_todo_cita_su_fuente_y_hay_tope(client):
    r = build({"sesiones": 1, "planificadas": 5}, {"proxima": {"fecha": "2026-11-05", "texto": "PEC"}}, {"ofertas_nuevas": 3, "candidaturas": 0},
              [{"texto": "t", "atrasada": True}], [{"titulo": "g", "progreso": None}])
    assert len(r) == 3 and all(i["fuente"] and i["url"].startswith("/") for i in r)


def test_la_buena_noticia_no_se_pierde(client):
    r = build(G, {"proxima": {"fecha": "2026-11-05", "texto": "PEC"}}, {"ofertas_nuevas": 3, "candidaturas": 0}, [{"texto": "t", "atrasada": True}], [{"titulo": "g", "progreso": None}])
    assert any(i["tipo"] == "bien" for i in r)
