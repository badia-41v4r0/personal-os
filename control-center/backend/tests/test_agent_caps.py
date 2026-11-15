import asyncio
from datetime import date, timedelta

import pytest

from app import db as dbm
from app.core import actions, gateway, orchestrator as orq
from app.models import LifestyleItem, Notification, Task
from app.modules import agent_caps as ac
from app.modules import reminders

TAREAS = "# T\n## Pendientes\n- [ ] Vieja #uni\n"


@pytest.fixture()
def v(client, settings, monkeypatch):
    import tareas
    j = settings.vault / "Jarvis"
    j.mkdir(parents=True)
    (j / "Tareas.md").write_text(TAREAS)
    monkeypatch.setattr(tareas, "TAREAS", j / "Tareas.md", raising=False)
    from tests.conftest import seed_tasks
    seed_tasks(j / "Tareas.md")
    return j


@pytest.fixture()
def cli(monkeypatch):
    calls = []

    def fake(script, *args):
        calls.append((script, *args))
        return '{"ok": true, "id": "ev1"}'
    monkeypatch.setattr(ac, "cli", fake)
    return calls


def pedir(cap, p, **k):
    return actions.request(cap, p, actor="jarvis", reason="prueba", **k)


def test_crear_tarea_y_deshacer(v):
    r = pedir("task.create", {"texto": "Llamar", "fecha": "2026-11-10", "area": "uni"})
    assert r["status"] == "done"
    assert "- [ ] Llamar 📅 2026-11-10 #uni" in (v / "Tareas.md").read_text()  # la copia se rehace tras el cambio en la base
    with dbm.session_scope() as s:
        assert s.query(Task).filter(Task.text == "Llamar", Task.due == "2026-11-10").count() == 1
    actions.undo(r["id"], "ana")
    assert "Llamar" not in (v / "Tareas.md").read_text() and "- [ ] Vieja #uni" in (v / "Tareas.md").read_text()
    with dbm.session_scope() as s:
        assert s.query(Task).filter(Task.text == "Llamar").count() == 0


def test_tarea_con_salto_de_linea_no_inyecta(v):
    pedir("task.create", {"texto": "Hola\n## Otra sección\n- [x] falsa"})
    lineas = (v / "Tareas.md").read_text().splitlines()
    assert [x for x in lineas if x.startswith("## ")] == ["## Pendientes", "## Hechas"]  # no cuela una sección ni una casilla
    assert sum(1 for x in lineas if x.startswith("- [")) == 2


def test_marcar_y_desmarcar(v):
    r = pedir("task.done", {"texto": "Vieja"})
    assert r["status"] == "done" and "- [x] Vieja" in (v / "Tareas.md").read_text()
    with dbm.session_scope() as s:
        assert s.query(Task).filter(Task.text == "Vieja").one().done is True
    actions.undo(r["id"], "ana")
    assert "- [ ] Vieja" in (v / "Tareas.md").read_text()
    with dbm.session_scope() as s:
        assert s.query(Task).filter(Task.text == "Vieja").one().done is False


def test_tarea_que_no_existe_falla_sin_romper(v):
    assert pedir("task.done", {"texto": "No existe"})["status"] == "failed"


def test_nota_solo_en_la_bandeja(v):
    r = pedir("note.add", {"texto": "idea\n# inyección"})
    assert r["result"]["archivo"].startswith("Jarvis/00-Inbox/")
    f = next((v / "00-Inbox").iterdir())
    assert len(f.read_text().splitlines()) == 1


def test_evento_propio_con_reglas(client, cli):
    r = pedir("calendar.create", {"titulo": "Dentista", "inicio": "2026-11-10T10:00", "fin": "2026-11-10T11:00"})
    assert r["status"] == "done" and cli[0][:2] == ("gcal.py", "crear") and "--titulo=Dentista" in cli[0]


def test_valor_con_guion_no_es_opcion(client, cli):
    pedir("calendar.create", {"titulo": "--borrar-todo", "dia": "2026-11-10"})
    assert "--titulo=--borrar-todo" in cli[0]


def test_deshacer_evento(client, cli):
    r = pedir("calendar.create", {"titulo": "X", "dia": "2026-11-10"})
    actions.undo(r["id"], "ana")
    assert cli[-1] == ("gcal.py", "borrar", "--id=ev1")


def test_borrar_evento_pide_aprobacion(client, cli):
    assert pedir("calendar.delete", {"id": "ev1"})["status"] == "pending" and cli == []


def test_borrador_tras_leer_correo_pide_aprobacion(client, cli):
    """Un correo malicioso no puede hacer que Jarvis redacte algo sin que Ana lo vea."""
    t = gateway.issue_token("r1", "jarvis", ["mail.recent"], ["mail.draft"])
    h = {"X-Run-Token": t}
    body = {"kind": "action", "name": "mail.draft", "args": {"cuenta": "gmail", "para": "a@b.c", "asunto": "x", "cuerpo": "y"}}
    assert client.post("/api/v1/internal/pos/call", json=body, headers=h).json()["result"]["status"] == "done"
    client.post("/api/v1/internal/pos/call", json={"kind": "read", "name": "mail.recent"}, headers=h)
    assert client.post("/api/v1/internal/pos/call", json=body, headers=h).json()["result"]["status"] == "pending"


def test_no_existe_enviar_correo():
    assert not [c for c in actions.REGISTRY if "send" in c or "enviar" in c]


def test_cada_especialista_solo_lo_suyo():
    for s in [*orq.SPECIALISTS.values(), orq.DEFAULT]:
        assert set(s.capabilities) <= set(actions.REGISTRY), s.name
        assert set(s.tools) <= set(gateway.TOOLS), s.name
    assert not set(orq.SPECIALISTS["entrenador"].capabilities) & {"mail.draft", "calendar.delete", "fantasy.action"}
    assert not [c for c in orq.DEFAULT.capabilities if c.startswith("finance")]


def test_recordatorios_una_sola_vez(client):
    hoy = date(2026, 11, 4)
    with dbm.session_scope() as s:
        s.add(LifestyleItem(kind="garantia", title="Portátil", day=(hoy + timedelta(days=10)).isoformat()))
        s.add(LifestyleItem(kind="viaje", title="Lejos", day=(hoy + timedelta(days=60)).isoformat()))
    assert asyncio.run(reminders.run(hoy)) == 1
    assert asyncio.run(reminders.run(hoy)) == 0
    with dbm.session_scope() as s:
        assert s.query(Notification).one().body.startswith("Portátil")


def test_escribir_conserva_los_permisos_del_archivo(v):
    f = v / "Tareas.md"
    f.chmod(0o644)
    pedir("task.create", {"texto": "Con permisos"})
    assert f.stat().st_mode & 0o777 == 0o644


def test_argumento_que_falta_se_explica(v):
    r = pedir("task.create", {"titulo": "mal"})
    assert r["status"] == "failed" and "texto" in r["error"]
