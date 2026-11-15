import sys
from datetime import date

from app.config import ROOT

sys.path.insert(0, str(ROOT / "collectors"))
import gym_stats as g  # noqa: E402

GYM = """# Gym
## Perfil
- **Objetivo:** hipertrofia
## Registro
- **Objetivo:** repetido (no es una sesión)

### 2026-10-20 · Push
_Hevy: PechoTriceps_
- Press de Banca Inclinado (Mancuerna): 20×12 (cal.), 26×6, 24×10, 22×10
- Jalón de Tríceps en Polea: 30×10, 25×12 (unilateral)
- Dominada: PC×6, PC×3

### 2026-10-27 · Push
- Press de Banca Inclinado (Mancuerna): 26×8 (fallo), 24×9 RPE 9
- Cinta: 25 min a 4 km/h, inclinación 18 % (Hevy decía 2 km)
- Curl predicador (máquina): 30×10
- Curl predicador (Máquina): 32×8
"""


def write(tmp_path):
    p = tmp_path / "Gym.md"
    p.write_text(GYM)
    return p


def test_parseo(tmp_path):
    s = g.cargar(write(tmp_path))
    assert [x.id for x in s] == ["2026-10-20-push", "2026-10-27-push"]
    banca = s[0].ejercicios[0]
    assert banca.series[0].calentamiento and len(banca.efectivas) == 3
    assert banca.volumen == 26 * 6 + 24 * 10 + 22 * 10  # el calentamiento no suma
    assert s[0].ejercicios[1].notas == "unilateral"
    dom = s[0].ejercicios[2]
    assert dom.series[0].peso is None and dom.volumen == 0  # peso corporal: sin kg
    s2 = s[1].ejercicios
    assert s2[0].series[0].fallo and s2[0].series[1].rpe == 9
    assert s2[1].tipo == "cardio" and s2[1].series == [] and "Hevy decía" in s2[1].notas
    # Mismo ejercicio con distinta mayúscula/acento = mismo id
    assert s2[2].id == s2[3].id


def test_e1rm_y_tendencia(tmp_path):
    s = g.cargar(write(tmp_path))
    eid = s[0].ejercicios[0].id
    h = g.historial_ejercicio(s, eid)
    assert h[0]["mejor_serie"]["e1rm"] == round(24 * (1 + 10 / 30), 1)  # 32.0 > 26×6 (31.2)
    t = g.tendencia(h)
    assert t["estado"] in ("mejora", "estable", "empeora") and t["e1rm_inicio"] == 32.0


def test_musculos_secundarios_a_medias(tmp_path):
    s = g.cargar(write(tmp_path))
    m = g.series_por_musculo([s[0]])
    assert m["pecho"] == 3  # principal: 3 series efectivas
    assert m["hombros"] == 1.5 and m["triceps"] == 1.5 + 2  # secundario ×0,5 + jalón de tríceps
    assert m["espalda"] == 2 and m["biceps"] == 1


def test_busqueda_aproximada(tmp_path):
    s = g.cargar(write(tmp_path))
    assert g.buscar_ejercicio(s, "press inclinado")["nombre"].startswith("Press de Banca Inclinado")
    assert g.buscar_ejercicio(s, "zzz") is None


def test_sin_archivo(tmp_path):
    assert g.cargar(tmp_path / "no.md") == []


def test_api_gym(client, auth, settings):
    d = settings.vault / "Jarvis/Areas"
    d.mkdir(parents=True)
    (d / "Gym.md").write_text(GYM)
    w = client.get("/api/v1/gym/workouts").json()
    assert [x["id"] for x in w] == ["2026-10-27-push", "2026-10-20-push"]
    assert client.get("/api/v1/gym/workouts?musculo=espalda").json()[0]["id"] == "2026-10-20-push"
    det = client.get("/api/v1/gym/workouts/2026-10-20-push").json()
    assert det["ejercicios"][0]["series"][0]["calentamiento"] is True
    ex = client.get("/api/v1/gym/exercises").json()
    e = client.get(f"/api/v1/gym/exercises/{ex[0]['id']}").json()
    assert e["historial"] and "tendencia" in e
    assert client.get("/api/v1/gym/exercises/nada").status_code == 404
    st = client.get("/api/v1/gym/statistics?dias=3650").json()
    assert len(st["semanas"]) == 8 and "duración de la sesión" in st["faltan"]


def test_api_gym_requiere_sesion(client):
    assert client.get("/api/v1/gym/workouts").status_code == 401


def test_importar_no_pisa_un_cambio_simultaneo(tmp_path, monkeypatch):
    import hevy_import
    gym = tmp_path / "Gym.md"
    gym.write_text("# Gym\n")
    llamadas = []

    def bloque(w):
        if not llamadas:
            gym.write_text("# Gym\n\nnota de Jarvis\n")  # alguien escribe mientras se prepara
        llamadas.append(1)
        return "### nuevo"
    monkeypatch.setattr(hevy_import, "bloque", bloque)
    assert hevy_import.aplicar([{}], gym) == 1
    txt = gym.read_text()
    assert "nota de Jarvis" in txt and "### nuevo" in txt
