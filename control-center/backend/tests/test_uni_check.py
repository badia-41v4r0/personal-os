import json
from datetime import date, timedelta

import pytest

import tareas
import uni

HOY = date.today()


def fmt(d: date) -> str:
    return f"{d:%d/%m/%Y} 23:59"


@pytest.fixture()
def v(tmp_path, monkeypatch, settings):
    sem = tmp_path / "Semanas"
    sem.mkdir()
    ini, fin = HOY - timedelta(days=HOY.weekday()), HOY - timedelta(days=HOY.weekday()) + timedelta(days=6)
    fila = f"| Día {HOY:%d/%m} | [[Uni/A\\|SC]] · Bloque uno (1/2) | — | — |"
    nota = sem / "Semana.md"
    nota.write_text(f"""---
inicio: {ini}
fin: {fin}
---
# Semana

## 📌 Entregas de esta semana

- [ ] **lunes {fmt(HOY + timedelta(days=3))}** · [[Uni/A|SC]]: PEC1
- [ ] **lunes {fmt(HOY - timedelta(days=1))}** · [[Uni/B|FP]]: PR1

## 🎯 Objetivos por asignatura

- [ ] [[Uni/A|SC]]: Terminar la PEC1
- [x] [[Uni/B|FP]]: Ya hecho

## 🗓️ Plan diario

| Día | a | b | c |
|---|---|---|---|
{fila}
""", encoding="utf-8")
    pn, est, hechos, t = tmp_path / "Panel.md", tmp_path / "estado.json", settings.vault / "Jarvis/Sistema/hechos.json", tmp_path / "Tareas.md"
    clave = f"estudio|{HOY}|SC · Bloque uno (1/2)"
    pn.write_text("> - [ ] **10:30** · SC · Bloque uno (1/2)\n", encoding="utf-8")
    est.write_text(json.dumps({"**10:30** · SC · Bloque uno (1/2)": clave}), encoding="utf-8")
    hechos.parent.mkdir(parents=True, exist_ok=True)
    hechos.write_text("{}", encoding="utf-8")
    t.write_text("## Pendientes\n- [ ] Mirar el aula #uni\n- [ ] Comprar pan #personal\n", encoding="utf-8")
    monkeypatch.setattr(uni, "SEMANAS", sem)
    for k, x in (("PANEL", pn), ("PANEL_ESTADO", est), ("HECHOS", hechos), ("TAREAS", t)):
        monkeypatch.setattr(tareas, k, x)
    return {"nota": nota, "panel": pn, "hechos": hechos, "clave": clave}


def edu(client):
    return client.get("/api/v1/me/education").json()


def check(client, auth, clave, hecho=True):
    return client.post("/api/v1/me/education/check", json={"clave": clave, "hecho": hecho}, headers=auth)


def test_lista_todo_lo_marcable(client, auth, v):
    d = edu(client)
    assert d["bloques_hoy"][0]["texto"].startswith("SC · Bloque uno") and d["bloques_hoy"][0]["hecho"] is False
    assert [e["atrasada"] for e in d["entregas"]] == [True, False]
    assert [o["hecho"] for o in d["objetivos_semana"]] == [False, True]
    assert [t["texto"] for t in d["tareas"]] == ["Mirar el aula"]


def test_bloque_cuenta_para_el_plan_y_el_panel(client, auth, v):
    assert check(client, auth, v["clave"]).status_code == 200
    assert v["clave"] in json.loads(v["hechos"].read_text())
    assert "> - [x] **10:30**" in v["panel"].read_text(encoding="utf-8")
    assert edu(client)["bloques_hoy"][0]["hecho"] is True
    assert check(client, auth, v["clave"], False).status_code == 200
    assert v["clave"] not in json.loads(v["hechos"].read_text()) and "> - [ ] **10:30**" in v["panel"].read_text(encoding="utf-8")


def test_lo_marcado_en_el_panel_de_obsidian_se_ve(client, auth, v):
    v["panel"].write_text("> - [x] **10:30** · SC · Bloque uno (1/2)\n", encoding="utf-8")
    assert edu(client)["bloques_hoy"][0]["hecho"] is True


def test_entrega_marca_la_nota_semanal_y_la_pasada_desaparece(client, auth, v):
    pasada = edu(client)["entregas"][0]
    assert check(client, auth, pasada["clave"]).status_code == 200
    t = v["nota"].read_text(encoding="utf-8")
    assert "- [x] **lunes" in t and t.count("- [x] **lunes") == 1 and "SC]]: PEC1" in t
    assert pasada["clave"] in json.loads(v["hechos"].read_text())
    assert [e["clave"] for e in edu(client)["entregas"]] != [] and pasada["clave"] not in [e["clave"] for e in edu(client)["entregas"]]


def test_objetivo_marca_solo_esa_linea(client, auth, v):
    o = edu(client)["objetivos_semana"][0]
    assert check(client, auth, o["clave"]).status_code == 200
    assert "- [x] [[Uni/A|SC]]: Terminar la PEC1" in v["nota"].read_text(encoding="utf-8")
    assert edu(client)["objetivos_semana"][0]["hecho"] is True


def test_bloques_y_entregas_de_cualquier_dia_se_marcan_desde_el_calendario(client, auth, v):
    """Un bloque de ayer y una entrega de hace un mes no están en la lista de hoy, pero sí en el plan."""
    from app.db import session_scope
    from app.models import Assessment, StudyBlock
    ayer, vieja = (HOY - timedelta(days=1)).isoformat(), (HOY - timedelta(days=30)).isoformat()
    with session_scope() as db:
        db.add_all([StudyBlock(day=ayer, slot=0, text="FP · Módulo 1"),
                    Assessment(external_id="vieja", due=vieja, due_time="23:59", title="PEC 0")])
    bloque, entrega = f"estudio|{ayer}|FP · Módulo 1", f"entrega|{vieja}|PEC 0"
    assert check(client, auth, entrega).status_code == 200  # (la fila falsa no está en ninguna nota: la resincronización la retira)
    assert entrega in json.loads(v["hechos"].read_text())
    assert check(client, auth, bloque).status_code == 200
    assert bloque in json.loads(v["hechos"].read_text())
    assert check(client, auth, bloque, False).status_code == 200  # y se puede deshacer
    assert bloque not in json.loads(v["hechos"].read_text())
    # lo que no está en el plan sigue sin escribir nada
    assert check(client, auth, f"estudio|{ayer}|otra cosa").status_code == 404
    assert check(client, auth, f"entrega|{vieja}|inventada").status_code == 404


def test_una_clave_inventada_no_escribe(client, auth, v):
    antes = v["nota"].read_text(encoding="utf-8")
    assert check(client, auth, "estudio|2020-01-01|otra cosa").status_code == 404
    assert v["nota"].read_text(encoding="utf-8") == antes and json.loads(v["hechos"].read_text()) == {}
