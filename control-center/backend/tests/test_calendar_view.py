from datetime import date, datetime, timedelta

import pytest

from app import agenda
from app.db import session_scope
from app.models import Assessment, EduCalendarBlock, GymPlannedSession, JobApplication, LifestyleItem, StudyBlock, Task

HOY = date.today()
D = HOY.isoformat()
H = (HOY + timedelta(days=6)).isoformat()
RANGO = f"?desde={D}&hasta={H}"


def ev(id_, cal, titulo="X", dia=D):
    return {"id": id_, "calendario": cal, "titulo": titulo, "lugar": "", "dia": dia, "hasta": dia, "inicio": "10:00", "fin": "11:00", "de_jarvis": False}


@pytest.fixture()
def google(monkeypatch):
    import gcal
    agenda._cache.clear()
    datos = {"eventos": []}
    monkeypatch.setattr(gcal, "agenda", lambda dias, hoy=None: datos["eventos"])
    return datos


def test_google_sin_family_y_sin_canvas_por_defecto(client, auth, google):
    import json, os
    from pathlib import Path
    (Path(os.environ["POS_CONFIG_DIR"]) / "agenda.json").write_text(json.dumps({"calendarios_ocultos": ["family"]}))
    google["eventos"] = [ev("a", "Personal", "Dentista"), ev("b", "Family", "Cena"), ev("c", "Canvas Campus", "Entrega FP")]
    r = client.get(f"/api/v1/calendar{RANGO}&capas=google").json()
    assert [i["titulo"] for i in r["items"]] == ["Dentista"]
    r = client.get(f"/api/v1/calendar{RANGO}&capas=google&canvas=true").json()
    assert sorted(i["titulo"] for i in r["items"]) == ["Dentista", "Entrega FP"]  # Family nunca


def test_google_oculta_bloques_ya_volcados(client, auth, google):
    google["eventos"] = [ev("ya", "Personal", "📚 FP"), ev("otro", "Personal", "Comida")]
    with session_scope() as db:
        db.add(EduCalendarBlock(day=D, slot=0, event_id="ya"))
    r = client.get(f"/api/v1/calendar{RANGO}&capas=google").json()
    assert [i["titulo"] for i in r["items"]] == ["Comida"]


def test_google_caido_no_tumba_el_resto(client, auth, monkeypatch):
    import gcal
    agenda._cache.clear()

    def boom(dias, hoy=None):
        raise RuntimeError("sin red")

    monkeypatch.setattr(gcal, "agenda", boom)
    with session_scope() as db:
        db.add(Task(external_id="t1", text="Pagar", area="personal", due=D))
    r = client.get(f"/api/v1/calendar{RANGO}").json()
    assert "Google Calendar no disponible" in r["errores"]["google"]
    assert [i["titulo"] for i in r["items"] if i["capa"] == "tareas"] == ["Pagar"]


def test_capas_locales(client, auth, google):
    with session_scope() as db:
        db.add_all([
            Task(external_id="t1", text="Tarea hecha", area="uni", due=D, done=True),
            Task(external_id="t2", text="Tarea borrada", area="uni", due=D, removed_at=datetime.now()),
            Assessment(external_id="a1", due=D, due_time="23:59", title="PEC 1 FP"),
            StudyBlock(day=D, slot=0, text="FP · Módulo 1"),
            JobApplication(company="Acme", role="FDE", status="aplicado", follow_up=D),
            JobApplication(company="Muerta", role="X", status="descartado", follow_up=D),
            GymPlannedSession(id="g1", date=D, name="Push", status="aceptada"),
            GymPlannedSession(id="g2", date=D, name="Pull", status="descartada"),
            LifestyleItem(kind="garantia", title="Garantía TV", day=D),
            LifestyleItem(kind="viaje", title="Fuera de rango", day=(HOY + timedelta(days=30)).isoformat()),
        ])
    items = client.get(f"/api/v1/calendar{RANGO}").json()["items"]
    por_capa = {c: [i["titulo"] for i in items if i["capa"] == c] for c in ("tareas", "uni", "trabajo", "gym", "vida")}
    assert por_capa["tareas"] == ["Tarea hecha"]
    assert sorted(por_capa["uni"]) == ["📌 PEC 1 FP", "📚 FP · Módulo 1"]
    assert por_capa["trabajo"] == ["Seguimiento: Acme · FDE"]
    assert por_capa["gym"] == ["🏋️ Push"]
    assert por_capa["vida"] == ["Garantía TV"]
    assert next(i for i in items if i["capa"] == "tareas")["hecho"] is True
    assert next(i for i in items if i["titulo"].startswith("📌"))["clave"] == f"entrega|{D}|PEC 1 FP"


def test_filtra_capas_y_valida_rango(client, auth, google):
    with session_scope() as db:
        db.add(Task(external_id="t1", text="Pagar", area="personal", due=D))
    r = client.get(f"/api/v1/calendar{RANGO}&capas=gym").json()
    assert r["items"] == [] and r["capas"] == ["gym"]
    assert client.get("/api/v1/calendar?desde=hoy&hasta=mañana").status_code == 422
    assert client.get(f"/api/v1/calendar?desde={H}&hasta={D}").status_code == 422
    assert client.get(f"/api/v1/calendar?desde={D}&hasta={(HOY + timedelta(days=90)).isoformat()}").status_code == 422


def test_marcar_tarea_desde_el_calendario(client, auth, google, tmp_path, monkeypatch):
    """Flujo real: Tareas.md -> base -> calendario -> /tasks/done -> calendario."""
    import tareas
    f = tmp_path / "Tareas.md"
    f.write_text(f"# Tareas\n- [ ] Llamar al banco 📅 {D} #personal\n- [ ] Otra cosa 📅 {D} #uni\n")
    monkeypatch.setattr(tareas, "TAREAS", f)
    monkeypatch.setattr(tareas, "PANEL", tmp_path / "Panel.md")
    monkeypatch.setattr(tareas, "PANEL_ESTADO", tmp_path / "panel-estado.json")
    client.get("/api/v1/tasks")  # abrir Tareas importa Tareas.md a la base
    its = client.get(f"/api/v1/calendar{RANGO}&capas=tareas").json()["items"]
    assert sorted(i["titulo"] for i in its) == ["Llamar al banco", "Otra cosa"]
    r = client.post("/api/v1/tasks/done", json={"texto": its[0]["titulo"]}, headers=auth)
    assert r.status_code == 200, r.text
    hechas = {i["titulo"]: i["hecho"] for i in client.get(f"/api/v1/calendar{RANGO}&capas=tareas").json()["items"]}
    assert hechas == {"Llamar al banco": True, "Otra cosa": False}


def test_calendario_ve_cambios_de_tareas_md_sin_abrir_tareas(client, auth, google, tmp_path, monkeypatch):
    """Si Tareas.md cambió fuera del panel (Jarvis, Obsidian), el calendario no debe enseñar la tarea como pendiente."""
    import tareas
    f = tmp_path / "Tareas.md"
    f.write_text(f"# Tareas\n- [ ] Llamar al banco 📅 {D} #personal\n")
    monkeypatch.setattr(tareas, "TAREAS", f)
    client.get("/api/v1/tasks")
    f.write_text(f"# Tareas\n- [x] Llamar al banco 📅 {D} #personal ✅ {D}\n")
    its = client.get(f"/api/v1/calendar{RANGO}&capas=tareas").json()["items"]
    assert its[0]["hecho"] is True


def test_exige_sesion(client):
    assert client.get(f"/api/v1/calendar{RANGO}").status_code in (401, 403)
