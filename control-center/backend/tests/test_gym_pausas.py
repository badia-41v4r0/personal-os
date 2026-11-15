"""Periodos sin entrenar (enfermedad, lesión, vacaciones): no cuentan como perdidos y la vuelta es prudente."""
from datetime import date, timedelta

import pytest

from app import db as dbm
from app.core import actions
from app.models import GymPause
from app.modules import home, insights
from tests.test_gym_coach import gc, gym

L = date(2026, 10, 5)  # lunes
ENFERMO = {"desde": "2026-10-19", "hasta": "2026-10-23", "motivo": "enfermedad"}


def _push(tmp_path, extra: list[tuple[date, str]] | None = None):
    bloques = [(L + timedelta(days=1), "Push", ["Press de Banca (Barra): 100×8, 90×10"]),
               (L + timedelta(days=8), "Push", ["Press de Banca (Barra): 100×9, 90×10"])]
    bloques += [(d, "Push", [f"Press de Banca (Barra): {s}"]) for d, s in (extra or [])]
    return gym(tmp_path, bloques)


def _banca(prop: dict) -> dict:
    return next(e for e in prop["ejercicios"] if "banca" in e["nombre"].lower())["objetivo"]


# ---------- motor ----------

def test_dias_de_pausa_y_pausas_cortas():
    assert gc.dias_laborables_en_pausa([ENFERMO], date(2026, 10, 19), date(2026, 10, 25)) == 5
    assert gc.pausa_en([ENFERMO], date(2026, 10, 21)) and not gc.pausa_en([ENFERMO], date(2026, 10, 24))
    assert gc.pausa_en([{"desde": "2026-10-19", "hasta": None, "motivo": "lesion"}], date(2027, 1, 1))  # en curso
    assert gc.pausa_reciente([ENFERMO], date(2026, 10, 27)) == ENFERMO
    assert gc.pausa_reciente([ENFERMO], date(2026, 11, 30)) is None  # pasada la ventana: progresión normal
    corta = {"desde": "2026-10-19", "hasta": "2026-10-20", "motivo": "otro"}
    assert gc.pausa_reciente([corta], date(2026, 10, 27)) is None  # 2 días: un descanso normal


def test_primera_sesion_tras_la_pausa_al_90_y_sin_fallo(tmp_path):
    s = _push(tmp_path)
    prop = gc.proponer_sesion(s, date(2026, 10, 26), fecha=date(2026, 10, 27), nombre="Push", pausas=[ENFERMO])
    o = _banca(prop)
    assert o["accion"] == "vuelta" and o["top"] == {"peso": 90.0, "reps": 9, "rir": 2}
    assert "pausa" in o["motivo"] and "enfermedad" in o["motivo"]
    assert prop["pausa"]["en_curso"] is False and "vuelta prudente" in prop["justificacion"]
    # sin pausa, lo de siempre: mismo peso y +1 rep
    assert _banca(gc.proponer_sesion(s, date(2026, 10, 26), fecha=date(2026, 10, 27), nombre="Push"))["top"]["peso"] == 100


def test_segunda_sesion_recupera_la_carga_de_antes(tmp_path):
    s = _push(tmp_path, [(date(2026, 10, 27), "90×9, 80×10")])
    o = _banca(gc.proponer_sesion(s, date(2026, 11, 2), fecha=date(2026, 11, 3), nombre="Push", pausas=[ENFERMO]))
    assert o["accion"] == "retomar" and o["top"]["peso"] == 100 and o["top"]["reps"] == 9


def test_si_la_vuelta_costo_no_se_fuerza(tmp_path):
    s = _push(tmp_path, [(date(2026, 10, 27), "60×5")])
    o = _banca(gc.proponer_sesion(s, date(2026, 11, 2), fecha=date(2026, 11, 3), nombre="Push", pausas=[ENFERMO]))
    assert o["accion"] != "retomar" and "costó" in o["motivo"]


def test_tras_dos_sesiones_progresion_normal(tmp_path):
    s = _push(tmp_path, [(date(2026, 10, 27), "90×9"), (date(2026, 11, 3), "100×9")])
    o = _banca(gc.proponer_sesion(s, date(2026, 11, 9), fecha=date(2026, 11, 10), nombre="Push", pausas=[ENFERMO]))
    assert o["accion"] not in ("vuelta", "retomar")


def test_durante_la_pausa_se_avisa(tmp_path):
    s = _push(tmp_path)
    en_curso = {"desde": "2026-10-19", "hasta": None, "motivo": "lesion"}
    prop = gc.proponer_sesion(s, date(2026, 10, 20), fecha=date(2026, 10, 20), nombre="Push", pausas=[en_curso])
    assert prop["pausa"]["en_curso"] is True and prop["justificacion"].startswith("Estás en pausa")


def test_calendario_informe_y_reprogramar_no_cuentan_la_pausa(tmp_path):
    s = _push(tmp_path)
    cal = gc.calendario(s, date(2026, 10, 19), date(2026, 10, 25), date(2026, 10, 26), pausas=[ENFERMO])
    estados = {c["fecha"]: c["estado"] for c in cal}
    assert estados["2026-10-20"] == "pausa" and estados["2026-10-24"] == "descanso"
    assert not [r for r in gc.reprogramar(s, date(2026, 10, 23), pausas=[ENFERMO]) if r.get("desde", "") >= "2026-10-19"]
    inf = gc.informe(s, "semanal", date(2026, 10, 19), date(2026, 10, 25), pausas=[ENFERMO])
    assert inf["sesiones_previstas"] == 0 and inf["dias_en_pausa"] == 5 and inf["pausas"][0]["motivo"] == "enfermedad"
    sin = gc.informe(s, "semanal", date(2026, 10, 19), date(2026, 10, 25))
    assert sin["sesiones_previstas"] == 5  # sin pausa serían 5 perdidas


# ---------- portada e insights ----------

def test_portada_e_insight_de_semana_de_pausa(tmp_path):
    s = _push(tmp_path)
    viernes = date(2026, 10, 23)
    g = home.gym_resumen(s, viernes, 5, [ENFERMO])
    assert g["planificadas"] == 0 and g["pausa"]["dias"] == 5 and g["pausa"]["en_curso"] is True
    i = insights.gym_insight(g, viernes)
    assert i["titulo"] == "En pausa del gym" and "Enfermedad" in i["texto"]
    # semana siguiente ya fuera de la pausa: vuelve la cuenta normal
    assert home.gym_resumen(s, date(2026, 10, 27), 5, [ENFERMO])["pausa"] is None


def test_pausa_de_un_dia_solo_resta_ese_dia(tmp_path):
    s = _push(tmp_path)
    g = home.gym_resumen(s, date(2026, 10, 23), 5, [{"desde": "2026-10-21", "hasta": "2026-10-21", "motivo": "otro"}])
    assert g["planificadas"] == 4


# ---------- API y acción de los agentes ----------

def test_api_de_pausas(client, auth):
    r = client.post("/api/v1/gym/pauses", json={"desde": "2026-11-09", "hasta": "2026-11-13", "motivo": "enfermedad", "nota": "Gripe"}, headers=auth)
    assert r.status_code == 200 and r.json()["hasta"] == "2026-11-13"
    pid = r.json()["id"]
    # solapada, al revés o con motivo raro: no
    assert client.post("/api/v1/gym/pauses", json={"desde": "2026-11-12", "hasta": "2026-11-15"}, headers=auth).status_code == 409
    assert client.post("/api/v1/gym/pauses", json={"desde": "2026-11-20", "hasta": "2026-11-18"}, headers=auth).status_code == 422
    assert client.post("/api/v1/gym/pauses", json={"desde": "2026-11-20", "motivo": "fiesta"}, headers=auth).status_code == 422
    assert [p["id"] for p in client.get("/api/v1/gym/pauses").json()] == [pid]
    assert client.get("/api/v1/gym/recovery").json()["pausas"][0]["nota"] == "Gripe"
    assert client.post(f"/api/v1/gym/pauses/{pid}/end", headers=auth).status_code == 409  # ya tiene fin
    assert client.delete(f"/api/v1/gym/pauses/{pid}", headers=auth).json() == {"ok": True}
    assert client.get("/api/v1/gym/pauses").json() == []


def test_terminar_una_pausa_en_curso(client, auth):
    pid = client.post("/api/v1/gym/pauses", json={"desde": "2026-01-01", "motivo": "lesion"}, headers=auth).json()["id"]
    r = client.post(f"/api/v1/gym/pauses/{pid}/end", headers=auth).json()
    assert r["hasta"] is not None and r["hasta"] >= "2026-01-01"


def test_las_rutas_exigen_sesion_csrf_y_origin(client, auth):
    b = {"desde": "2026-11-09"}
    assert client.post("/api/v1/gym/pauses", json=b, headers={"Origin": auth["Origin"]}).status_code in (401, 403)
    assert client.post("/api/v1/gym/pauses", json=b, headers=auth | {"Origin": "https://evil.example"}).status_code in (401, 403)
    client.post("/api/v1/auth/logout", headers=auth)
    assert client.get("/api/v1/gym/pauses").status_code == 401


def test_accion_de_los_agentes_y_deshacer(client):
    r = actions.request("gym.pause.log", {"desde": "2026-11-09", "hasta": "2026-11-13", "motivo": "enfermedad"}, actor="jarvis", reason="prueba")
    assert r["status"] == "done"
    with dbm.session_scope() as s:
        assert s.query(GymPause).count() == 1
    actions.undo(r["id"], "ana")
    with dbm.session_scope() as s:
        assert s.query(GymPause).count() == 0


@pytest.mark.parametrize("cap", ["gym.pause.log"])
def test_la_tienen_jarvis_el_coach_y_la_rutina(cap):
    from app.core import orchestrator as orq
    assert cap in orq.JARVIS_CAPS and cap in orq.GYM_CAPS and cap in orq.RUTINA_CAPS
    assert actions.REGISTRY[cap].level == 1
