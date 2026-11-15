"""Lo personal sale de la configuración de la instancia, no del código."""
import json

from app import agents
from app.db import session_scope
from app.models import AgentDefinition


def test_render_rellena_nombre_y_campus(config_instancia):
    import ajustes
    assert ajustes.render("Hola {{nombre}}") == "Hola el usuario"
    (config_instancia / "perfil.json").write_text(json.dumps({"nombre": "Ana"}))
    (config_instancia / "estudios.json").write_text(json.dumps({"plataforma": {"nombre": "Moodle", "url": "https://campus.example"}}))
    assert ajustes.render("{{nombre}} en {{campus_nombre}} ({{campus_url}})") == "Ana en Moodle (https://campus.example)"


def test_ninguna_instruccion_lleva_nombres_propios():
    from app.config import ROOT
    for f in [*(ROOT / "control-center/agents").glob("*.md"), ROOT / "control-center/gym/coach.md"]:
        t = f.read_text(encoding="utf-8")
        assert "\u00c1lvaro" not in t and "UOC" not in t, f.name  # escrito así para que una sustitución masiva no lo cambie


def test_tutor_se_siembra_una_vez_y_no_se_pisa(settings):
    with session_scope() as db:
        agents.seed_panel(db)
    with session_scope() as db:
        a = db.get(AgentDefinition, "tutor")
        assert a and a.status == "active" and a.origin == "panel"
        spec = agents._current(db, a).spec
        assert spec["level"] == "execute" and spec["virtual_computer"] and spec["subagents"] and "{{nombre}}" in spec["objective"]
        a.status = "inactive"
    with session_scope() as db:
        agents.seed_panel(db)
        assert db.get(AgentDefinition, "tutor").status == "inactive"  # lo existente no se toca


def test_prompt_del_tutor_va_rellenado(settings, config_instancia):
    (config_instancia / "perfil.json").write_text(json.dumps({"nombre": "Ana"}))
    with session_scope() as db:
        agents.seed_panel(db)
        spec = agents.Spec(**agents._current(db, db.get(AgentDefinition, "tutor")).spec)
    p = agents.system_prompt(spec)
    assert "Ana" in p and "{{" not in p


def test_planificador_lee_la_configuracion(config_instancia):
    import planificador
    (config_instancia / "estudios.json").write_text(json.dumps({
        "asignaturas": [{"codigo": "MAT", "nombre": "Matemáticas", "paquetes": [{"tarea": "Tema 1", "inicio": "2030-01-07", "limite": "2030-01-11", "bloques": 2}]}],
        "disponibilidad": {"lunes": ["9:00–11:00"], "sabado": ["10:00–12:00", "12:00–14:00"]}, "descansos": ["2030-01-14"]}))
    planificador.recargar()
    from datetime import date
    assert planificador.ASIG == {"MAT": "Matemáticas"}
    assert planificador.bloques_dia(date(2030, 1, 7)) == 1 and planificador.bloques_dia(date(2030, 1, 8)) == 0
    assert planificador.bloques_dia(date(2030, 1, 12)) == 2 and planificador.bloques_dia(date(2030, 1, 14)) == 0
    assert planificador.FIN == date(2030, 1, 11)
