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


def test_tareas_repetidas_no_dan_aviso_sin_fin(client, auth, nota, settings):
    """Dos tareas con el mismo texto (una hecha sin fecha y otra pendiente con fecha, creada después): la nota las
    escribe en otro orden que la base y no debe confundirlas en cada sincronización (26/11: aviso en bucle)."""
    from app.modules import vault_sync
    client.post("/api/v1/tasks", json={"texto": "Repetida"}, headers=auth)
    with dbm.session_scope() as s:
        t = s.query(Task).filter(Task.text == "Repetida").one()
        t.done, t.done_on = True, "2026-11-20"
    with dbm.session_scope() as s:
        s.add(Task(external_id="db:repetida-2", text="Repetida", area="personal", due="2026-11-28"))
    with dbm.session_scope() as s:
        from app.modules import mirror
        mirror.export_tasks(s)
    antes = nota.read_text()
    avisos = settings.data_dir / "avisos"
    n = len(list(avisos.glob("*"))) if avisos.exists() else 0
    for _ in range(3):
        with dbm.session_scope() as s:
            assert vault_sync.sync_tasks(s)["descartados"] == 0
    assert nota.read_text() == antes
    assert (len(list(avisos.glob("*"))) if avisos.exists() else 0) == n
    # y marcar en la nota la pendiente marca esa, no la otra
    nota.write_text(antes.replace("- [ ] Repetida 📅 2026-11-28 #personal", "- [x] Repetida 📅 2026-11-28 #personal ✅ 2026-11-26"))
    with dbm.session_scope() as s:
        r = vault_sync.sync_tasks(s)
        assert r["descartados"] == 0 and r["marcas"] == 1
        assert s.query(Task).filter(Task.external_id == "db:repetida-2").one().done is True


def _id(client, texto):
    return next(x["id"] for x in client.get("/api/v1/tasks").json()["pendientes"] if x["texto"] == texto)


@pytest.fixture()
def avisos(monkeypatch):
    from app.modules import mirror
    dados = []
    monkeypatch.setattr(mirror, "warn", dados.append)
    return dados


def test_editar_desde_el_panel(client, auth, nota, avisos):
    tid = _id(client, "Una")
    r = client.patch(f"/api/v1/tasks/{tid}", json={"texto": "Una cambiada", "fecha": "2026-12-01", "area": "trabajo"}, headers=auth)
    assert r.status_code == 200 and r.json()["antes"] == {"texto": "Una", "fecha": None, "area": "uni"}
    texto = nota.read_text()
    assert "- [ ] Una cambiada 📅 2026-12-01 #trabajo" in texto and "Una #uni" not in texto
    pend = client.get("/api/v1/tasks").json()["pendientes"]  # la copia rehecha no se toma por un cambio a mano
    assert avisos == [] and [x["id"] for x in pend if x["texto"] == "Una cambiada"] == [tid]
    client.patch(f"/api/v1/tasks/{tid}", json={"texto": "Una cambiada", "fecha": None, "area": "trabajo"}, headers=auth)
    assert "- [ ] Una cambiada #trabajo" in nota.read_text()  # sin fecha


def test_editar_una_de_dos_iguales_cambia_esa(client, auth, nota):
    client.post("/api/v1/tasks", json={"texto": "Una", "fecha": "2026-12-09", "area": "uni"}, headers=auth)
    pend = [x for x in client.get("/api/v1/tasks").json()["pendientes"] if x["texto"] == "Una"]
    sin_fecha = next(x["id"] for x in pend if x["fecha"] is None)
    client.patch(f"/api/v1/tasks/{sin_fecha}", json={"texto": "La otra", "fecha": None, "area": "uni"}, headers=auth)
    texto = nota.read_text()
    assert "- [ ] Una 📅 2026-12-09 #uni" in texto and "- [ ] La otra #uni" in texto


@pytest.mark.parametrize("body", [{"texto": "", "area": "uni"}, {"texto": "   ", "area": "uni"}, {"texto": "a", "fecha": "mañana", "area": "uni"},
                                  {"texto": "a", "area": "inventada"}, {"texto": "a"}, {"texto": "x" * 301, "area": "uni"}])
def test_editar_valida(client, auth, nota, body):
    tid = _id(client, "Una")
    assert client.patch(f"/api/v1/tasks/{tid}", json=body, headers=auth).status_code == 422
    assert "- [ ] Una #uni" in nota.read_text()


def test_editar_o_borrar_una_que_no_existe(client, auth, nota):
    assert client.patch("/api/v1/tasks/999999", json={"texto": "x", "area": "uni"}, headers=auth).status_code == 409
    assert client.delete("/api/v1/tasks/999999", headers=auth).status_code == 409


def test_borrar_desde_el_panel(client, auth, nota, avisos):
    tid = _id(client, "Una")
    assert client.delete(f"/api/v1/tasks/{tid}", headers=auth).status_code == 200
    assert "Una" not in nota.read_text()
    assert not any(x["texto"] == "Una" for x in client.get("/api/v1/tasks").json()["pendientes"])
    assert avisos == []
    with dbm.session_scope() as s:
        assert s.get(Task, tid).removed_at is not None  # queda en la base, marcada
    assert client.delete(f"/api/v1/tasks/{tid}", headers=auth).status_code == 409  # dos veces no


def test_editar_y_borrar_exigen_sesion_y_csrf(client, auth, nota):
    tid = _id(client, "Una")
    sin_csrf = {"Origin": auth["Origin"]}
    assert client.patch(f"/api/v1/tasks/{tid}", json={"texto": "x", "area": "uni"}, headers=sin_csrf).status_code in (401, 403)
    assert client.delete(f"/api/v1/tasks/{tid}", headers=sin_csrf).status_code in (401, 403)
    assert "- [ ] Una #uni" in nota.read_text()


def test_jarvis_edita_y_borra_y_se_deshace(nota):
    from app.modules import agent_caps
    with dbm.session_scope() as s:
        r = agent_caps.task_edit({"texto": "Una", "nuevo_texto": "Otra", "fecha": "2026-12-03"}, s)
        assert "- [ ] Otra 📅 2026-12-03 #uni" in nota.read_text()
        agent_caps.task_edit_undo(r, s)
        assert "- [ ] Una #uni" in nota.read_text()
        b = agent_caps.task_delete({"texto": "Una"}, s)
        assert "Una" not in nota.read_text()
        agent_caps.task_delete_undo(b, s)
        assert "- [ ] Una #uni" in nota.read_text()


def test_jarvis_y_agenda_pueden_editar_y_borrar_y_las_rutinas_no():
    from app.core import orchestrator
    for caps in (orchestrator.JARVIS_CAPS, orchestrator.SECTIONS["agenda"].capabilities):
        assert {"task.edit", "task.delete"} <= set(caps)
    assert "task.delete" not in orchestrator.RUTINA_CAPS
