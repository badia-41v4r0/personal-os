"""Tareas: la base manda. Crear y marcar desde el panel o Jarvis rehace Tareas.md como copia."""
import pytest

from app import agenda  # noqa: F401  (pone collectors/ en el path)
import tareas
from app import db as dbm
from app.models import Task
from tests.conftest import seed_tasks

NOTA = "# ✅ Tareas\n\n## Pendientes\n- [ ] Una #uni\n\n## Hechas\n"


@pytest.fixture()
def nota(settings, monkeypatch):
    f = settings.vault / "Jarvis/Tareas.md"
    f.parent.mkdir(parents=True)
    f.write_text(NOTA)
    monkeypatch.setattr(tareas, "TAREAS", f)
    monkeypatch.setattr(tareas, "PANEL", settings.vault / "Jarvis/Panel.md")
    monkeypatch.setattr(tareas, "PANEL_ESTADO", settings.vault / "Jarvis/Sistema/panel-estado.json")
    seed_tasks(f)
    return f


def test_crear_desde_el_panel(client, auth, nota):
    r = client.post("/api/v1/tasks", json={"texto": "Llamar al banco", "fecha": "2026-11-10", "area": "trabajo"}, headers=auth)
    assert r.status_code == 200 and r.json()["ok"] is True
    assert "- [ ] Llamar al banco 📅 2026-11-10 #trabajo" in nota.read_text()
    with dbm.session_scope() as s:
        t = s.query(Task).filter(Task.text == "Llamar al banco").one()
        assert (t.due, t.area, t.done) == ("2026-11-10", "trabajo", False) and t.external_id.startswith("db:")
    pend = client.get("/api/v1/tasks").json()["pendientes"]
    assert any(x["texto"] == "Llamar al banco" for x in pend)


def test_crear_dos_veces_lo_mismo_no_duplica(client, auth, nota):
    b = {"texto": "Pagar", "fecha": "2026-11-12"}
    client.post("/api/v1/tasks", json=b, headers=auth)
    assert client.post("/api/v1/tasks", json=b, headers=auth).json()["repetida"] is True
    with dbm.session_scope() as s:
        assert s.query(Task).filter(Task.text == "Pagar").count() == 1


@pytest.mark.parametrize("body", [{"texto": ""}, {"texto": "x" * 301}, {"texto": "a", "fecha": "mañana"}, {"texto": "   "}])
def test_crear_valida(client, auth, nota, body):
    assert client.post("/api/v1/tasks", json=body, headers=auth).status_code == 422


def test_area_desconocida_cae_en_personal(client, auth, nota):
    client.post("/api/v1/tasks", json={"texto": "Rara", "area": "inventada"}, headers=auth)
    assert "- [ ] Rara #personal" in nota.read_text()


def test_crear_exige_sesion_csrf_y_origin(client, auth, nota):
    b = {"texto": "Nada"}
    assert client.post("/api/v1/tasks", json=b, headers={"Origin": auth["Origin"]}).status_code in (401, 403)
    assert client.post("/api/v1/tasks", json=b, headers=auth | {"Origin": "https://evil.example"}).status_code in (401, 403)
    client.post("/api/v1/auth/logout", headers=auth)
    assert client.post("/api/v1/tasks", json=b, headers=auth).status_code == 401
    with dbm.session_scope() as s:
        assert s.query(Task).filter(Task.text == "Nada").count() == 0


def test_la_nota_se_regenera_si_se_edita_a_mano_y_se_abre_tareas(client, auth, nota):
    nota.write_text(NOTA.replace("Una", "Cambiada a mano"))
    client.get("/api/v1/tasks")  # abrir Tareas concilia: el texto editado a mano se descarta
    assert "Cambiada a mano" not in nota.read_text() and "- [ ] Una #uni" in nota.read_text()


def test_marcar_casilla_en_la_nota_si_se_acepta(client, auth, nota):
    nota.write_text(NOTA.replace("- [ ] Una #uni", "- [x] Una #uni ✅ 2026-11-06"))
    hechas = client.get("/api/v1/tasks").json()["hechas"]
    assert [h["texto"] for h in hechas] == ["Una"] and hechas[0]["hecho_el"] == "2026-11-06"
