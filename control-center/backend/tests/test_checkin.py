import asyncio
import json
from datetime import date, timedelta

import pytest

from app import db as dbm
from app.models import CheckIn, Notification
from app.modules import checkin, insights, reminders

HOY = date(2026, 11, 6)


def test_franja_sugerida_segun_la_hora():
    vacio = {"manana": False, "noche": False}
    assert checkin.suggested(vacio, 8) == "manana"
    assert checkin.suggested(vacio, 16) == "manana"  # entre medias: la que falte
    assert checkin.suggested({"manana": True, "noche": False}, 16) == "noche"
    assert checkin.suggested(vacio, 21) == "noche"
    assert checkin.suggested({"manana": True, "noche": True}, 21) is None
    assert checkin.suggested({"manana": True, "noche": False}, 9) is None  # de mañana y ya hecho: nada que pedir


def test_guardar_y_leer_sin_duplicar(client, auth):
    r = client.put("/api/v1/me/checkin", json={"slot": "manana", "mood": 4, "energy": 3, "sleep_h": 7.5, "intention": "Terminar la PEC"}, headers=auth)
    assert r.status_code == 200 and r.json()["manana"]["sleep_h"] == 7.5 and r.json()["noche"] is None
    # volver a guardar corrige: no crea otro
    client.put("/api/v1/me/checkin", json={"slot": "manana", "mood": 5, "sleep_h": 8}, headers=auth)
    g = client.get("/api/v1/me/checkin").json()
    assert g["manana"]["mood"] == 5 and g["manana"]["sleep_h"] == 8 and g["manana"]["intention"] == ""
    with dbm.session_scope() as s:
        assert s.query(CheckIn).count() == 1


@pytest.mark.parametrize("body", [
    {"slot": "tarde", "mood": 3},
    {"slot": "noche", "mood": 6},
    {"slot": "noche", "mood": 0},
    {"slot": "manana", "sleep_h": 25},
    {"slot": "manana", "sleep_h": -1},
    {"slot": "manana"},  # vacío
    {"slot": "manana", "note": "   "},
    {"slot": "noche", "note": "x" * 1001},
    {"slot": "noche", "mood": 3, "dia": "2999-01-01"},  # futuro
    {"slot": "noche", "mood": 3, "dia": "ayer"},
])
def test_validacion(client, auth, body):
    assert client.put("/api/v1/me/checkin", json=body, headers=auth).status_code == 422


def test_exige_sesion_csrf_y_origin(client, auth):
    body = {"slot": "noche", "mood": 3}
    assert client.put("/api/v1/me/checkin", json=body, headers={"Origin": auth["Origin"]}).status_code in (401, 403)
    assert client.put("/api/v1/me/checkin", json=body, headers=auth | {"Origin": "https://evil.example"}).status_code in (401, 403)
    client.post("/api/v1/auth/logout", headers=auth)
    assert client.get("/api/v1/me/checkin").status_code == 401
    assert client.put("/api/v1/me/checkin", json=body, headers=auth).status_code == 401


def test_incluye_los_habitos_de_hoy(client, auth):
    hid = client.post("/api/v1/me/habits", json={"nombre": "Leer"}, headers=auth).json()["id"]
    assert client.get("/api/v1/me/checkin").json()["habitos"][0]["hoy"] is False
    client.post(f"/api/v1/me/habits/{hid}/toggle", json={}, headers=auth)
    h = client.get("/api/v1/me/checkin").json()["habitos"][0]
    assert h["hoy"] is True and h["racha"] == 1


def test_resumen_sin_datos_no_inventa(client):
    with dbm.session_scope() as s:
        assert checkin.summary(s, HOY) is None


def test_resumen_con_datos(client):
    with dbm.session_scope() as s:
        s.add_all([CheckIn(day=HOY.isoformat(), slot="manana", mood=4, energy=2, sleep_h=7),
                   CheckIn(day=(HOY - timedelta(days=1)).isoformat(), slot="manana", mood=2, energy=4, sleep_h=5),
                   CheckIn(day=(HOY - timedelta(days=30)).isoformat(), slot="manana", mood=1, energy=1, sleep_h=1)])  # fuera de la semana
    with dbm.session_scope() as s:
        r = checkin.summary(s, HOY)
    assert r["checkins"] == 2 and r["animo"] == 3.0 and r["energia"] == 3.0 and r["sueno"] == 6.0


def test_home_trae_checkin_y_estado_general(client, auth):
    d = client.get("/api/v1/home").json()
    assert d["estado_general"] is None and d["checkin"]["manana"] is None and "habitos" in d["checkin"]
    client.put("/api/v1/me/checkin", json={"slot": "manana", "mood": 4, "sleep_h": 7}, headers=auth)
    d = client.get("/api/v1/home").json()
    assert d["checkin"]["manana"]["mood"] == 4 and d["estado_general"]["checkins"] == 1


def test_cerrar_el_dia_exige_el_checkin_de_la_noche(client, auth, settings):
    assert client.post("/api/v1/me/checkin/close", headers=auth).status_code == 409
    client.put("/api/v1/me/checkin", json={"slot": "noche", "mood": 4, "energy": 3, "note": "Entregué la PEC"}, headers=auth)
    assert client.post("/api/v1/me/checkin/close", headers=auth).json() == {"encargado": True}
    orden = json.loads(next((settings.data_dir / "ordenes").glob("*.json")).read_text())
    assert orden["rutina"] == "cierre" and "Entregué la PEC" in orden["text"] and "Ánimo: 4/5" in orden["text"]
    assert "cierre.md" in orden["text"]


def test_cerrar_exige_admin_y_csrf(client, auth):
    client.put("/api/v1/me/checkin", json={"slot": "noche", "mood": 3}, headers=auth)
    assert client.post("/api/v1/me/checkin/close", headers={"Origin": auth["Origin"]}).status_code in (401, 403)


def test_recordatorio_de_la_noche_una_sola_vez(client, monkeypatch):
    enviados = []

    async def enviar(level, title, body, url, source, **k):
        enviados.append((level, source))
        with dbm.session_scope() as s:
            s.add(Notification(level=level, title=title, body=body, url=url, source=source))
    monkeypatch.setattr(reminders.notifications, "enviar", enviar)
    assert asyncio.run(reminders.run_night(HOY)) == 1
    assert asyncio.run(reminders.run_night(HOY)) == 0
    assert enviados == [("action", "rec:checkin:noche:2026-11-06")]


def test_no_hay_recordatorio_si_ya_hizo_el_checkin(client, monkeypatch):
    with dbm.session_scope() as s:
        s.add(CheckIn(day=HOY.isoformat(), slot="noche", mood=3))

    async def enviar(*a, **k):
        raise AssertionError("no debía avisar")
    monkeypatch.setattr(reminders.notifications, "enviar", enviar)
    assert asyncio.run(reminders.run_night(HOY)) == 0


def test_insight_de_sueno_bajo_solo_con_tres_mañanas_seguidas(client):
    with dbm.session_scope() as s:
        for i, h in enumerate((5, 5.5, 4)):
            s.add(CheckIn(day=(HOY - timedelta(days=i)).isoformat(), slot="manana", sleep_h=h))
        r = insights.checkin_insights(s, HOY)
    assert any(i["titulo"] == "Duermes poco" and i["fuente"] == "Check-ins" for i in r)
    with dbm.session_scope() as s:
        s.query(CheckIn).filter(CheckIn.day == HOY.isoformat()).update({"sleep_h": 8})
    with dbm.session_scope() as s:
        assert not any(i["titulo"] == "Duermes poco" for i in insights.checkin_insights(s, HOY))


def test_insight_ayer_sin_checkin_solo_si_hay_historia(client):
    with dbm.session_scope() as s:
        assert insights.checkin_insights(s, HOY) == []  # nunca ha hecho ninguno: no se le riñe
        s.add(CheckIn(day=(HOY - timedelta(days=5)).isoformat(), slot="noche", mood=3))
    with dbm.session_scope() as s:
        assert [i["titulo"] for i in insights.checkin_insights(s, HOY)] == ["Ayer sin check-in"]
