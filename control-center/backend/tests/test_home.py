from datetime import date

from app.modules import home
from gym_stats import Ejercicio, Sesion, Serie  # noqa: F401


class S:
    def __init__(self, fecha, volumen, series):
        self.fecha, self.volumen, self.series = fecha, volumen, series


def test_saludo_por_hora():
    assert [home.saludo(h) for h in (7, 15, 22, 3)] == ["Buenos días", "Buenas tardes", "Buenas noches", "Buenas noches"]


def test_gym_compara_con_el_mismo_tramo_de_la_semana_pasada():
    miercoles = date(2026, 11, 4)
    ses = [S("2026-11-02", 1000, 10), S("2026-11-03", 1000, 10),  # esta semana
           S("2026-10-26", 800, 8), S("2026-10-27", 800, 8), S("2026-10-30", 9999, 99)]  # viernes pasado: no cuenta
    g = home.gym_resumen(ses, miercoles, 5)
    assert g["sesiones"] == 2 and g["planificadas"] == 5
    assert g["volumen_pct"] == 25.0 and g["series_pct"] == 25.0
    assert g["por_dia"][0]["volumen"] == 1000 and g["por_dia"][4]["volumen"] == 0


def test_sin_semana_previa_no_inventa_porcentaje():
    assert home.gym_resumen([S("2026-11-02", 1000, 10)], date(2026, 11, 4), 5)["volumen_pct"] is None


def test_carrera_lee_pipeline_y_filtra_ofertas(client, settings):
    d = settings.vault / "Jarvis"
    (d / "Areas").mkdir(parents=True)
    (d / "Sistema").mkdir()
    (d / "Areas/Trabajo.md").write_text("# T\n\n## Pipeline de candidaturas\n| Empresa | Puesto | Estado | Fecha |\n|---|---|---|---|\n| ACME | SE | aplicado | x |\n\n## Bloqueos\n- no\n")
    (d / "Sistema/ofertas-vistas.json").write_text('{"1":{"visto":"2026-11-03","puntos":"4"},"2":{"visto":"2026-11-03","puntos":"-9"},"3":{"visto":"2026-01-01","puntos":"5"}}')
    c = home.carrera_resumen(date(2026, 11, 4))
    assert c == {"pipeline": {"aplicado": 1}, "candidaturas": 1, "ofertas_nuevas": 1}


def test_carrera_sin_archivos_no_falla(client):
    assert home.carrera_resumen(date(2026, 11, 4))["candidaturas"] == 0


def test_estudios_cuenta_solo_esta_semana_y_pendientes():
    uni = {"entregas": [{"fecha": "2026-11-06", "texto": "A"}, {"fecha": "2026-11-05", "texto": "B", "hecho": True},
                        {"fecha": "2026-11-20", "texto": "C"}]}
    e = home.estudios_resumen(uni, date(2026, 11, 4))
    assert e["entregas_semana"] == 1 and e["proxima"]["texto"] == "A"


def test_agenda_ordena_y_excluye_canvas():
    ev = [{"dia": "2026-11-04", "inicio": "18:00", "titulo": "Tarde"}, {"dia": "2026-11-04", "inicio": "09:00", "titulo": "Mañana"},
          {"dia": "2026-11-05", "inicio": "09:00", "titulo": "Otro día"}, {"dia": "2026-11-04", "inicio": "10:00", "titulo": "PEC", "calendario": "Canvas"}]
    a = home.agenda_hoy(ev, {"bloques": ["FC"]}, date(2026, 11, 4))
    assert [i["titulo"] for i in a] == ["Mañana", "Tarde", "FC"]


def test_foco_maximo_tres_y_prioriza_lo_vencido():
    tareas = [{"texto": "vencida", "fecha": "2026-11-01"}, {"texto": "futura", "fecha": "2026-12-01"}, {"texto": "sin", "fecha": None}]
    assert home.foco({"bloques": ["a", "b", "c"]}, tareas, date(2026, 11, 4)) == ["vencida", "a", "b"]


def test_api_home_no_rellena_lo_que_no_existe(client, auth, monkeypatch):
    monkeypatch.setattr(home.agenda_mod, "calendario", lambda d: {"eventos": [], "error": None})
    monkeypatch.setattr(home.agenda_mod, "_cached", lambda k, fn, ttl=0: fn())
    r = client.get("/api/v1/home")
    assert r.status_code == 200
    d = r.json()
    assert d["objetivos"] is None and d["finanzas"] is None and d["estado_general"] is None
    assert all(i["fuente"] for i in d["insights"])  # lo que salga, siempre citado


def test_integraciones_no_lee_secretos(client, auth, settings, monkeypatch):
    from dataclasses import replace

    from app import config
    (settings.data_dir / "s" / "secrets").mkdir(parents=True)
    (settings.data_dir / "s" / "secrets" / "zoho.json").write_text("NO-DEBE-SALIR")
    config.set_settings(replace(settings, root=settings.data_dir / "s"))
    r = client.get("/api/v1/home/integraciones")
    assert "NO-DEBE-SALIR" not in r.text
    estados = {i["nombre"]: i["estado"] for i in r.json()}
    assert estados["Zoho Mail"] == "conectada" and estados["Google Calendar"] == "sin_conectar" and estados["Hevy"] == "manual"
