import pytest
import sys
import types
from datetime import date, timedelta

from app import archivos
from app.models import Assessment, StudyBlock
from app.modules import education
from app.db import session_scope

HOY = date.today()


def test_sm2_sube_el_intervalo_y_reinicia_al_fallar():
    c = education.EduCard(subject="SD", front="a", back="b", due=HOY.isoformat(), ease=2.5, interval=0, reps=0, lapses=0)
    education.sm2(c, 4, HOY)
    assert (c.reps, c.interval) == (1, 1)
    education.sm2(c, 4, HOY)
    assert c.interval == 3
    education.sm2(c, 5, HOY)
    assert c.interval >= 7 and c.ease > 2.5
    education.sm2(c, 0, HOY)
    assert (c.reps, c.interval, c.lapses) == (0, 1, 1) and c.due == (HOY + timedelta(days=1)).isoformat()
    for _ in range(20):
        education.sm2(c, 0, HOY)
    assert c.ease == 1.3  # nunca baja del mínimo


def test_tarjetas_alta_repaso_y_sin_duplicados(client, auth):
    cuerpo = [{"asignatura": "SD", "frente": "¿Qué es un reloj de Lamport?", "dorso": "Orden lógico de eventos"}]
    r = client.post("/api/v1/education/cards", json=cuerpo, headers=auth).json()
    assert r["creadas"] == 1
    assert client.post("/api/v1/education/cards", json=cuerpo, headers=auth).json()["repetidas"] == 1
    due = client.get("/api/v1/education/cards/due").json()
    assert len(due) == 1
    cid = due[0]["id"]
    v = client.post(f"/api/v1/education/cards/{cid}/review", json={"nota": 4}, headers=auth).json()
    assert v["intervalo"] == 1 and v["vence"] == (HOY + timedelta(days=1)).isoformat()
    assert client.get("/api/v1/education/cards/due").json() == []  # ya no toca hoy
    st = client.get("/api/v1/education/cards/stats").json()
    assert st["total"] == 1 and st["hoy"] == 0 and st["racha_dias"] == 1
    assert st["retencion"] == [{"asig": "SD", "acierto": 100, "revisiones": 1}]
    assert client.delete(f"/api/v1/education/cards/{cid}", headers=auth).status_code == 200
    assert client.get("/api/v1/education/cards").json() == []


def test_tarjeta_de_asignatura_inventada_se_rechaza(client, auth):
    r = client.post("/api/v1/education/cards", json=[{"asignatura": "XYZ", "frente": "a", "dorso": "b"}], headers=auth)
    assert r.status_code == 422


def test_simulacro_prioriza_examen_y_falla_sin_tarjetas(client, auth):
    assert client.post("/api/v1/education/simulacro", json={"asignatura": "SC", "n": 5}, headers=auth).status_code == 404
    cards = [{"asignatura": "SC", "frente": f"p{i}", "dorso": "r", "tipo": "examen" if i < 3 else "concepto"} for i in range(8)]
    client.post("/api/v1/education/cards", json=cards, headers=auth)
    r = client.post("/api/v1/education/simulacro", json={"asignatura": "SC", "n": 3}, headers=auth).json()
    assert len(r["preguntas"]) == 3 and all(p["tipo"] == "examen" for p in r["preguntas"])


def test_cronometro_uno_a_la_vez(client, auth):
    a = client.post("/api/v1/education/timer/start", json={"label": "SD · Módulo 1"}, headers=auth).json()
    assert a["asignatura"] == "SD"
    b = client.post("/api/v1/education/timer/start", json={"label": "FP · PEC 2"}, headers=auth).json()
    assert b["id"] != a["id"]
    t = client.get("/api/v1/education/timer").json()
    assert t["activo"] and t["asignatura"] == "FP"
    assert client.post("/api/v1/education/timer/stop", headers=auth).status_code == 200
    assert client.post("/api/v1/education/timer/stop", headers=auth).status_code == 409
    assert client.get("/api/v1/education/timer").json() == {"activo": False}


def test_codigo_de_bloque_y_de_entrega():
    assert education.codigo_de("FP · PEC 1 (1/2)") == "FP"
    assert education.codigo_de("Sistemas distribuidos: PR1") == "SD"
    assert education.codigo_de("Repaso semanal con Jarvis (1 h)") == ""


def test_panorama_con_datos_reales(client, auth, monkeypatch):
    monkeypatch.setattr(education, "_hechos", lambda: ({}, {}))
    with session_scope() as db:
        db.add(Assessment(external_id="a1", due=(HOY + timedelta(days=2)).isoformat(), due_time="23:59", title="Sistemas distribuidos: PR1"))
        db.add(Assessment(external_id="a2", due=(HOY - timedelta(days=1)).isoformat(), due_time="23:59", title="Fundamentos de programación: PR 1"))
        db.add(StudyBlock(day=HOY.isoformat(), slot=0, text="SD · Módulo 1 (1/2)"))
    o = client.get("/api/v1/education/overview").json()
    por = {a["codigo"]: a for a in o["asignaturas"]}
    assert por["SD"]["siguiente"]["dias"] == 2 and por["SD"]["semaforo"] == "ambar" and por["SD"]["bloques_pasados"] == 1
    assert por["FP"]["atrasadas"] == 1 and por["FP"]["semaforo"] == "rojo"
    assert por["SC"]["siguiente"] is None
    assert o["progreso"]["capacidad"] > 0 and len(o["carga"]) == 10


def test_plan_semana_con_entregas_y_estado(client, auth, monkeypatch):
    monkeypatch.setattr(education, "_hechos", lambda: ({}, {}))
    with session_scope() as db:
        db.add(Assessment(external_id="a1", due=HOY.isoformat(), due_time="23:59", title="Sistemas distribuidos: PR1"))
        db.add(StudyBlock(day=HOY.isoformat(), slot=1, text="SD · Módulo 1 (1/2)"))
    p = client.get("/api/v1/education/plan?dias=3").json()
    assert len(p["dias"]) == 3
    d0 = p["dias"][0]
    assert d0["bloques"][0]["asig"] == "SD" and d0["entregas"][0]["estado"] == "sin_empezar"
    assert client.get("/api/v1/education/plan?dias=90").status_code == 422


def test_canvas_linea_base_y_cambios(client, auth, monkeypatch):
    estado = {"ev": [{"id": "1", "calendario": "Canvas Campus", "titulo": "PEC 1", "dia": "2026-12-01", "inicio": None},
                     {"id": "x", "calendario": "Personal", "titulo": "Dentista", "dia": "2026-12-02", "inicio": "10:00"}]}
    mod = types.SimpleNamespace(agenda=lambda dias: estado["ev"])
    monkeypatch.setitem(sys.modules, "gcal", mod)
    r = client.post("/api/v1/education/canvas/check", headers=auth).json()
    assert r["eventos"] == 1 and r["linea_base"] is True and r["cambios"] == 0
    estado["ev"][0]["dia"] = "2026-11-28"
    estado["ev"].append({"id": "2", "calendario": "Canvas Campus", "titulo": "PEC 2", "dia": "2026-12-10", "inicio": None})
    r = client.post("/api/v1/education/canvas/check", headers=auth).json()
    assert r["cambios"] == 2
    tipos = {(c["tipo"], c["titulo"]) for c in client.get("/api/v1/education/canvas").json()}
    assert tipos == {("movido", "PEC 1"), ("nuevo", "PEC 2")}
    assert client.get("/api/v1/education/overview").json()["canvas_nuevos"] == 2
    client.post("/api/v1/education/canvas/seen", headers=auth)
    assert client.get("/api/v1/education/overview").json()["canvas_nuevos"] == 0
    # Si desaparece de Canvas, se avisa una sola vez
    estado["ev"] = [e for e in estado["ev"] if e["id"] != "2"]
    assert client.post("/api/v1/education/canvas/check", headers=auth).json()["cambios"] == 1
    assert client.post("/api/v1/education/canvas/check", headers=auth).json()["cambios"] == 0


def test_archivos_carpetas_por_asignatura_y_limites(client, auth, settings):
    r = client.get("/api/v1/education/archivos").json()
    assert {i["nombre"] for i in r["items"]} == set(education.asignaturas())
    assert client.post("/api/v1/education/archivos?path=SD&name=borrador.md", content=b"# hola", headers=auth).status_code == 200
    assert client.post("/api/v1/education/archivos?path=SD&name=borrador.md", content=b"# otra", headers=auth).json()["ruta"] == "SD/borrador (2).md"
    ls = client.get("/api/v1/education/archivos?path=SD").json()["items"]
    assert [i["nombre"] for i in ls] == ["borrador (2).md", "borrador.md"]
    assert client.get("/api/v1/education/archivos/texto?path=SD/borrador.md").json()["texto"] == "# hola"
    raw = client.get("/api/v1/education/archivos/raw?path=SD/borrador.md")
    assert "attachment" in raw.headers["content-disposition"]  # el markdown nunca se sirve activo
    assert client.get("/api/v1/education/archivos/recientes").json()[0]["nombre"].startswith("borrador")
    # Fuera de Uni/ no se llega
    assert client.get("/api/v1/education/archivos?path=../Entrada").status_code == 403
    assert client.get("/api/v1/education/archivos/raw?path=..%2F..%2Fetc%2Fpasswd").status_code == 403
    assert client.get("/api/v1/education/archivos?path=.oculta").status_code == 403
    # Un enlace simbólico no se sigue
    (archivos.root() / "secreto.txt").write_text("no")
    (education.uni_root() / "SD" / "enlace.txt").symlink_to(archivos.root() / "secreto.txt")
    assert client.get("/api/v1/education/archivos/raw?path=SD/enlace.txt").status_code == 403
    assert "enlace.txt" not in [i["nombre"] for i in client.get("/api/v1/education/archivos?path=SD").json()["items"]]


def test_html_se_descarga_y_no_se_ve_en_linea(client, auth):
    client.post("/api/v1/education/archivos?path=FP&name=x.html", content=b"<script>alert(1)</script>", headers=auth)
    raw = client.get("/api/v1/education/archivos/raw?path=FP/x.html")
    assert "attachment" in raw.headers["content-disposition"] and raw.headers["content-type"].startswith("application/octet-stream")


def test_cruces_sin_datos_no_inventan(client, auth):
    c = client.get("/api/v1/education/cruces").json()
    assert c["energia"]["suficiente"] is False
    assert c["coste"]["pagado"] is None and c["ofertas"]["analizadas"] == 0


def test_avisos_de_canvas_y_repaso_se_generan_una_vez(client, auth, monkeypatch):
    from app.modules import reminders
    monkeypatch.setitem(sys.modules, "gcal", types.SimpleNamespace(agenda=lambda d: [{"id": "1", "calendario": "Canvas", "titulo": "PEC 1", "dia": "2026-12-01", "inicio": None}]))
    with session_scope() as db:
        education.check_canvas(db)
    monkeypatch.setitem(sys.modules, "gcal", types.SimpleNamespace(agenda=lambda d: [{"id": "1", "calendario": "Canvas", "titulo": "PEC 1", "dia": "2026-11-25", "inicio": None}]))
    with session_scope() as db:
        education.check_canvas(db)
        cards = [{"asignatura": "SD", "frente": f"p{i}", "dorso": "r"} for i in range(12)]
        education.add_cards(db, cards, "tutor")
        items = reminders.pending(db, HOY)
    claves = {i["key"].split(":")[1] for i in items}
    assert {"canvas", "cards"} <= claves
    movido = next(i for i in items if i["key"].startswith("rec:canvas"))
    assert "2026-12-01" in movido["body"] and "2026-11-25" in movido["body"]


def test_tutor_da_de_alta_tarjetas_por_capacidad(client, auth):
    from app.modules import agent_caps
    with session_scope() as db:
        r = agent_caps.uni_card_add({"tarjetas": [{"asignatura": "SC", "frente": "¿Nyquist?", "dorso": "2·fmax"}]}, db)
        assert len(r["ids"]) == 1
        agent_caps.uni_card_add_undo(r, db)
    assert client.get("/api/v1/education/cards").json() == []
    with session_scope() as db:
        try:
            agent_caps.uni_card_add({"tarjetas": []}, db)
        except ValueError as e:
            assert "entre 1 y 30" in str(e)
        else:
            raise AssertionError("debía rechazar una lista vacía")


def test_atrasadas_cuentan_lo_marcado_y_no_modifican_la_base(client, auth, monkeypatch):
    ayer = (HOY - timedelta(days=1)).isoformat()
    antigua = (HOY - timedelta(days=40)).isoformat()
    with session_scope() as db:
        db.add(Assessment(external_id="a1", due=ayer, due_time="23:59", title="Fundamentos de programación: PR 1"))
        db.add(Assessment(external_id="a2", due=ayer, due_time="23:59", title="Fundamentos de programación: PR 2"))
        db.add(Assessment(external_id="a3", due=antigua, due_time="23:59", title="Fundamentos de programación: PR 0"))
    marcadas = {f"entrega|{ayer}|Fundamentos de programación: PR 1": "2026-11-05"}
    monkeypatch.setattr(education, "_hechos", lambda: (marcadas, {}))
    fp = next(a for a in client.get("/api/v1/education/overview").json()["asignaturas"] if a["codigo"] == "FP")
    assert fp["atrasadas"] == 1  # PR 1 marcada y PR 0 demasiado antigua: solo PR 2
    with session_scope() as db:
        assert db.query(Assessment).filter(Assessment.done.is_(True)).count() == 0  # un GET no escribe


ESTUDIOS = {"asignaturas": [{"codigo": "FP", "nombre": "Fundamentos de programación", "paquetes": []}, {"codigo": "FC", "nombre": "Fundamentos de computadores", "paquetes": []}, {"codigo": "SC", "nombre": "Sistemas de comunicación I", "paquetes": []}, {"codigo": "SD", "nombre": "Sistemas distribuidos", "paquetes": []}, {"codigo": "ARD", "nombre": "Automatización de redes", "paquetes": []}, {"codigo": "CI", "nombre": "Competencias interpersonales TIC", "paquetes": []}], "disponibilidad": {"lunes": ["10:30–12:30", "12:30–14:30", "16:00–18:00"], "martes": ["10:30–12:30", "12:30–14:30", "16:00–18:00"], "miercoles": ["10:30–12:30", "12:30–14:30", "16:00–18:00"], "jueves": ["10:30–12:30", "12:30–14:30", "16:00–18:00"], "viernes": ["10:30–12:30", "12:30–14:30", "16:00–18:00"], "sabado": [], "domingo": []}, "fin": "2027-01-22"}


@pytest.fixture(autouse=True)
def _estudios(config_instancia):
    """Las asignaturas de prueba (antes estaban escritas en el planificador)."""
    import json as _j
    (config_instancia / "estudios.json").write_text(_j.dumps(ESTUDIOS, ensure_ascii=False))
