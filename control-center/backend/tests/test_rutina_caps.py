"""La rutina (briefing, cierre, semanal) cambia tareas, candidaturas y entrenos por acciones, no editando las notas."""
import asyncio

from app import db as dbm
from app.core import actions, gateway, orchestrator as orq, runs
from app.models import ChatSession


def test_las_capacidades_de_la_rutina_existen_y_son_de_nivel_1():
    r = orq.RUTINA
    assert set(r.capabilities) <= set(actions.REGISTRY) and set(r.tools) <= set(gateway.TOOLS)
    assert {"task.create", "task.done", "task.reschedule", "career.application.update", "gym.register"} <= set(r.capabilities)
    # solo lo que no afecta a terceros ni gasta: nada de correo, calendario, Fantasy, repos ni encargos
    assert all(actions.REGISTRY[c].level == 1 for c in r.capabilities)
    prohibidas = {"mail.draft", "calendar.create", "calendar.move", "calendar.delete", "fantasy.action", "encargo.create", "repo.create", "ayudante.create", "day.close"}
    assert not prohibidas & set(r.capabilities)


def test_el_turno_de_la_rutina_lleva_su_credencial_con_esas_capacidades(client):
    runs.order_routine("cierre", "haz el cierre")
    assert asyncio.run(runs.ingest_orders()) == 1
    with dbm.session_scope() as s:
        c = s.get(ChatSession, runs.session_id("rutina", runs._day()))
        assert c.permissions["vault_write"] is True
        assert set(c.permissions["pos"]["capabilities"]) == set(orq.RUTINA_CAPS)
        assert c.permissions["pos"]["agent"] == "rutina"
