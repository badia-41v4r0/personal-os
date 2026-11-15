from datetime import date, timedelta

import gym_texto
from app.modules import home, personal


def test_objetivo_sin_hitos_no_inventa_progreso(client, auth):
    g = client.post("/api/v1/me/goals", json={"titulo": "Trabajo estable", "area": "carrera"}, headers=auth).json()
    assert g["progreso"] is None
    client.post(f"/api/v1/me/goals/{g['id']}/milestones", json={"titulo": "CV"}, headers=auth)
    g = client.post(f"/api/v1/me/goals/{g['id']}/milestones", json={"titulo": "Entrevista"}, headers=auth).json()
    r = client.post(f"/api/v1/me/milestones/{g['hitos'][0]['id']}/toggle", headers=auth).json()
    assert r["progreso"] == 50


def test_portada_con_objetivos_y_finanzas(client, auth, monkeypatch):
    monkeypatch.setattr(home.agenda_mod, "calendario", lambda d: {"eventos": [], "error": None})
    monkeypatch.setattr(home.agenda_mod, "_cached", lambda k, fn, ttl=0: fn())
    assert client.get("/api/v1/home").json()["objetivos"] is None
    client.post("/api/v1/me/goals", json={"titulo": "X"}, headers=auth)
    client.post("/api/v1/finance/accounts", json={"name": "asset:banco", "kind": "asset"}, headers=auth)
    d = client.get("/api/v1/home").json()
    assert d["objetivos"][0]["titulo"] == "X" and d["finanzas"]["ahorro"] == "0.00" and d["estado_general"] is None


def test_racha():
    hoy = date(2026, 11, 4)
    d = lambda n: (hoy - timedelta(days=n)).isoformat()  # noqa: E731
    assert personal.streak({d(0), d(1), d(2)}, hoy) == 3
    assert personal.streak({d(1), d(2)}, hoy) == 2  # hoy aún no marcado no la rompe
    assert personal.streak({d(0), d(2)}, hoy) == 1
    assert personal.streak(set(), hoy) == 0


def test_habito_marcar_y_desmarcar(client, auth):
    hid = client.post("/api/v1/me/habits", json={"nombre": "Leer"}, headers=auth).json()["id"]
    assert client.post(f"/api/v1/me/habits/{hid}/toggle", json={}, headers=auth).json()["hecho"] is True
    assert client.get("/api/v1/me/habits").json()[0]["racha"] == 1
    assert client.post(f"/api/v1/me/habits/{hid}/toggle", json={}, headers=auth).json()["hecho"] is False


def test_salud_conserva_la_serie(client, auth):
    for d, v in (("2026-11-01", 80.0), ("2026-11-02", 80.5)):
        client.post("/api/v1/me/health", json={"metrica": "peso", "valor": v, "dia": d}, headers=auth)
    assert [x["valor"] for x in client.get("/api/v1/me/health").json()["series"]["peso"]] == [80.0, 80.5]


def test_candidatura_pone_seguimiento_al_aplicar(client, auth):
    a = client.post("/api/v1/me/career/applications", json={"empresa": "ACME", "puesto": "SE"}, headers=auth).json()
    assert a["estado"] == "interés" and a["follow_up"] is None
    r = client.patch(f"/api/v1/me/career/applications/{a['id']}", json={"estado": "aplicado"}, headers=auth).json()
    assert r["follow_up"] == (date.today() + timedelta(days=7)).isoformat()
    assert client.patch(f"/api/v1/me/career/applications/{a['id']}", json={"estado": "raro"}, headers=auth).status_code == 422


def test_notas_uni():
    t = "# N\n## Resumen\n| Asignatura | Fórmula | Nota actual |\n|---|---|---|\n| FC | 50% | 7,5 |\n\n## Otra\n"
    assert personal.notas_resumen(t) == [{"Asignatura": "FC", "Fórmula": "50%", "Nota actual": "7,5"}]
    assert personal.notas_resumen("sin tabla") == []


def test_estilo_de_vida(client, auth):
    i = client.post("/api/v1/me/lifestyle", json={"tipo": "viaje", "titulo": "Roma", "dia": "2027-03-01"}, headers=auth).json()["id"]
    assert client.get("/api/v1/me/lifestyle").json()[0]["titulo"] == "Roma"
    assert client.post("/api/v1/me/lifestyle", json={"tipo": "otro", "titulo": "X"}, headers=auth).status_code == 422
    client.delete(f"/api/v1/me/lifestyle/{i}", headers=auth)
    assert client.get("/api/v1/me/lifestyle").json() == []


HEVY = """Push day
Tuesday, Nov 3, 2026 at 6:00am

Bench Press (Barbell)
Set 1 [Warm-up]: 40 kg x 10
Set 1: 80 kg x 8
Set 2: 77,5 kg x 8

Pull Up
Set 1: 10 reps

@ana
https://hevy.com/workout/abc
"""


def test_texto_de_hevy():
    e, avisos = gym_texto.parsear(HEVY)
    assert e == [("Bench Press (Barbell)", ["80×8", "77.5×8"]), ("Pull Up", ["PC×10"])]
    assert avisos == []


def test_texto_formato_gym_md():
    e, _ = gym_texto.parsear("Sentadilla: 80×8, 80x8, 85×6\n- Curl: 12×10")
    assert e == [("Sentadilla", ["80×8", "80×8", "85×6"]), ("Curl", ["12×10"])]


def test_bloque_lo_entiende_el_motor(tmp_path):
    import gym_stats
    f = tmp_path / "Gym.md"
    f.write_text("# Gym\n## Registro\n\n" + gym_texto.bloque("2026-11-03", "Push", [("Press banca", ["80×8", "80×8"])]) + "\n")
    s = gym_stats.cargar(f)
    assert s[0].fecha == "2026-11-03" and s[0].series == 2 and s[0].volumen == 1280


def test_registrar_por_el_panel(client, auth, settings):
    d = settings.vault / "Jarvis/Areas"
    d.mkdir(parents=True)
    (d / "Gym.md").write_text("# Gym\n## Registro\n")
    body = {"texto": "Press banca: 80×8, 80×8", "fecha": "2026-11-03"}
    p = client.post("/api/v1/gym/register/preview", json=body, headers=auth).json()
    assert p["sesion"] == "Push" and p["ejercicios"][0]["series"] == ["80×8", "80×8"]
    assert client.post("/api/v1/gym/register", json=body, headers=auth).status_code == 200
    assert "### 2026-11-03 · Push" in (d / "Gym.md").read_text()
    assert client.post("/api/v1/gym/register", json=body, headers=auth).status_code == 409  # sin duplicados


def test_registrar_texto_sin_series(client, auth, settings):
    d = settings.vault / "Jarvis/Areas"
    d.mkdir(parents=True)
    (d / "Gym.md").write_text("# Gym\n")
    assert client.post("/api/v1/gym/register", json={"texto": "hola que tal", "fecha": "2026-11-03"}, headers=auth).status_code == 422
