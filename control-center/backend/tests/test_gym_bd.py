"""Entrenos: la base manda. El `## Registro` de Gym.md es una copia; Rutina y Perfil siguen siendo editables."""
import pytest

from app import db as dbm
from app.models import Workout
from app.modules import mirror, vault_sync

GYM = ("# 🏋️ Gym\n\n## Perfil\n- objetivo: hipertrofia\n\n## Registro\n\n"
       "### 2026-11-02 · Leg day\n- Sentadilla Hack: 80×8, 70×10\n\n### 2026-11-03 · Push\n- Press banca: 60×8\n")


@pytest.fixture()
def gym(client, settings):
    f = settings.vault / "Jarvis/Areas/Gym.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(GYM)
    with dbm.session_scope() as s:
        assert vault_sync.sync_workouts(s)["sembrada"] is True
    assert (settings.data_dir / vault_sync.MARCA_GYM).exists()
    return f


def n_workouts():
    with dbm.session_scope() as s:
        return s.query(Workout).filter(Workout.removed_at.is_(None)).count()


def test_la_siembra_conserva_todo_y_pone_el_aviso(gym):
    t = gym.read_text()
    assert mirror.AVISO_GYM in t and "## Perfil\n- objetivo: hipertrofia" in t and "Sentadilla Hack: 80×8" in t
    assert n_workouts() == 2
    with dbm.session_scope() as s:
        assert vault_sync.sync_workouts(s) == {"descartados": 0}
    assert gym.read_text() == t


def test_registrar_desde_el_panel_va_a_la_base_y_a_la_copia(gym, auth, client):
    r = client.post("/api/v1/gym/register", json={"texto": "Remo en T: 50x10, 50x9", "fecha": "2026-11-04", "sesion": "Pull"}, headers=auth)
    assert r.status_code == 200, r.text
    assert "### 2026-11-04 · Pull" in gym.read_text() and n_workouts() == 3
    assert client.post("/api/v1/gym/register", json={"texto": "Remo: 50x10", "fecha": "2026-11-04", "sesion": "Pull"}, headers=auth).status_code == 409


def test_editar_el_registro_a_mano_se_descarta_pero_el_perfil_no(gym, settings):
    t = gym.read_text().replace("- objetivo: hipertrofia", "- objetivo: fuerza").replace("60×8", "100×8")
    gym.write_text(t)
    with dbm.session_scope() as s:
        assert vault_sync.sync_workouts(s)["descartados"] == 1
    nuevo = gym.read_text()
    assert "60×8" in nuevo and "100×8" not in nuevo
    assert "- objetivo: fuerza" in nuevo  # lo de antes de `## Registro` sigue siendo de la nota
    assert any("100×8" in f.read_text() for f in (settings.data_dir / "descartes/gym").iterdir())


def test_las_secciones_detras_del_registro_se_conservan(gym):
    gym.write_text(gym.read_text() + "\n## Notas\n- algo\n")
    with dbm.session_scope() as s:
        vault_sync.sync_workouts(s)
    assert gym.read_text().rstrip().endswith("## Notas\n- algo")
    with dbm.session_scope() as s:
        assert vault_sync.sync_workouts(s) == {"descartados": 0}


def test_base_sin_entrenos_no_borra_la_nota(gym):
    with dbm.session_scope() as s:
        s.query(Workout).delete()
    with dbm.session_scope() as s:
        r = vault_sync.sync_workouts(s)
    assert r["descartados"] == 0 and n_workouts() == 2 and "Sentadilla Hack" in gym.read_text()


def test_sin_nota_ni_entrenos_no_se_crea_nada(client, settings):
    with dbm.session_scope() as s:
        vault_sync.sync_workouts(s)
    assert not (settings.vault / "Jarvis/Areas/Gym.md").exists()
