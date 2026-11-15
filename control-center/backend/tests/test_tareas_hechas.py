"""Marcar tareas desde el panel: Tareas.md y la casilla del Panel, sin que la regeneración lo deshaga."""
import json

import pytest

from app import agenda  # noqa: F401  (pone collectors/ en el path)
import tareas

TAREAS = """# Tareas
- [ ] Llamar al banco 📅 2026-11-01 #personal
- [ ] Preguntar en el foro de CI #uni
- [x] Vieja ✅ 2026-10-30
"""
PANEL = """---
fecha: 2026-11-01
---
> [!jarvis-tareas] Tareas
> - [ ] Llamar al banco ⚠️ atrasada
> - [ ] Preguntar en el foro de CI (🎓 Uni)
"""


@pytest.fixture()
def vault(tmp_path, monkeypatch):
    t, pn, est = tmp_path / "Tareas.md", tmp_path / "Panel.md", tmp_path / "panel-estado.json"
    t.write_text(TAREAS)
    pn.write_text(PANEL)
    est.write_text(json.dumps({"Llamar al banco ⚠️ atrasada": "tarea|Llamar al banco",
                               "Preguntar en el foro de CI (🎓 Uni)": "tarea|Preguntar en el foro de CI"}))
    monkeypatch.setattr(tareas, "TAREAS", t)
    monkeypatch.setattr(tareas, "PANEL", pn)
    monkeypatch.setattr(tareas, "PANEL_ESTADO", est)
    from tests.conftest import seed_tasks
    seed_tasks(t)  # las tareas viven en la base; la nota es su copia
    return t, pn


def test_marcar_y_desmarcar(client, auth, vault):
    t, pn = vault
    r = client.post("/api/v1/tasks/done", json={"texto": "Llamar al banco"}, headers=auth)
    assert r.status_code == 200 and r.json()["tareas"] == 1 and r.json()["panel"] == 1
    assert "- [x] Llamar al banco 📅 2026-11-01 #personal ✅ " in t.read_text()
    assert "> - [x] Llamar al banco ⚠️ atrasada" in pn.read_text()
    assert "- [ ] Preguntar en el foro de CI" in t.read_text() and "> - [ ] Preguntar" in pn.read_text()
    # la ruta de tareas la ve hecha
    hechas = client.get("/api/v1/tasks", headers=auth).json()["hechas"]
    assert hechas[0]["texto"] == "Llamar al banco"

    r = client.post("/api/v1/tasks/done", json={"texto": "Llamar al banco", "hecho": False}, headers=auth)
    assert r.status_code == 200
    texto = t.read_text()
    assert "- [ ] Llamar al banco 📅 2026-11-01 #personal\n" in texto and "✅ 2026-11-0" not in texto.split("## Hechas")[0]
    assert pn.read_text() == PANEL  # el Panel queda como estaba


def test_tarea_que_no_existe_o_ya_cambio(client, auth, vault):
    assert client.post("/api/v1/tasks/done", json={"texto": "No existe"}, headers=auth).status_code == 409
    assert client.post("/api/v1/tasks/done", json={"texto": "Vieja"}, headers=auth).status_code == 409  # ya hecha
    assert client.post("/api/v1/tasks/done", json={"texto": ""}, headers=auth).status_code == 422


def test_sin_casilla_en_el_panel(client, auth, vault):
    t, pn = vault
    pn.write_text("---\nfecha: 2026-11-01\n---\nnada\n")
    r = client.post("/api/v1/tasks/done", json={"texto": "Preguntar en el foro de CI"}, headers=auth).json()
    assert r["tareas"] == 1 and r["panel"] == 0


def test_la_regeneracion_no_lo_deshace(vault, monkeypatch):
    """Lo que hace build.sincronizar con el Panel tras marcar desde la web: deja la tarea hecha."""
    t, pn = vault
    tareas.cambiar("Llamar al banco", True)
    import build
    est = tareas.PANEL_ESTADO
    monkeypatch.setattr(build, "PANEL", pn)
    monkeypatch.setattr(build, "ESTADO", est)
    monkeypatch.setattr(build, "HECHOS", est.with_name("hechos.json"))
    from datetime import date
    build.sincronizar(date(2026, 11, 1))
    assert "- [x] Llamar al banco" in t.read_text()
