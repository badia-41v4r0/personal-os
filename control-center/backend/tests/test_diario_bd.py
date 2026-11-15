"""Diario: la base manda. La rutina lo escribe con `journal.write` y Diario/*.md son copias que se rehacen."""
import pytest

from app import db as dbm
from app.core import actions, orchestrator as orq
from app.models import JournalDay
from app.modules import mirror, vault_sync

DIA = "---\nfecha: 2026-11-06\ncierre: manual\n---\n# 📓 Viernes 6 de noviembre\n\n## ✅ Hecho\n- Gym: Upper\n"


@pytest.fixture()
def diario(client, settings):
    d = settings.vault / "Jarvis/Diario"
    d.mkdir(parents=True)
    (d / "2026-11-06.md").write_text(DIA)
    (d / "Semana 2026-11-02.md").write_text("## 🏋️ Gym\nbien\n")
    with dbm.session_scope() as s:
        r = vault_sync.sync_journal(s)
    assert r["sembrada"] is True and r["origen"] == 2
    return d


def pedir(p):
    return actions.request("journal.write", p, actor="rutina", reason="prueba")


def test_la_siembra_pone_el_aviso_sin_cambiar_el_contenido(diario):
    texto = (diario / "2026-11-06.md").read_text()
    assert texto.startswith("---\nfecha: 2026-11-06") and mirror.AVISO_DIARIO in texto
    assert texto.index("---\n", 4) < texto.index(mirror.AVISO_DIARIO)  # tras el frontmatter
    with dbm.session_scope() as s:
        row = s.get(JournalDay, "Jarvis/Diario/2026-11-06.md")
        assert mirror.AVISO_DIARIO not in row.content and "Gym: Upper" in row.content
        assert s.get(JournalDay, "Jarvis/Diario/Semana 2026-11-02.md").kind == "semana"


def test_repetir_la_sincronizacion_no_cambia_nada(diario):
    antes = (diario / "2026-11-06.md").read_text()
    with dbm.session_scope() as s:
        r = vault_sync.sync_journal(s)
    assert r == {"origen": 2, "descartados": 0, "rehechas": 0}
    assert (diario / "2026-11-06.md").read_text() == antes


def test_crear_anadir_y_deshacer(diario):
    r = pedir({"fecha": "2026-11-07", "contenido": "---\nfecha: 2026-11-07\n---\n# 📓 Sábado\n", "modo": "crear"})
    assert r["status"] == "done"
    f = diario / "2026-11-07.md"
    assert "# 📓 Sábado" in f.read_text() and mirror.AVISO_DIARIO in f.read_text()
    assert pedir({"fecha": "2026-11-07", "contenido": "otra"})["status"] != "done"  # crear sobre uno que ya existe falla
    r2 = pedir({"fecha": "2026-11-07", "contenido": "## Actualización\nfue al gym", "modo": "anadir"})
    assert r2["status"] == "done"
    t = f.read_text()
    assert t.index("# 📓 Sábado") < t.index("## Actualización")
    actions.undo(r2["id"], "ana")
    assert "Actualización" not in f.read_text() and "# 📓 Sábado" in f.read_text()
    actions.undo(r["id"], "ana")
    assert not f.exists()
    with dbm.session_scope() as s:
        assert s.get(JournalDay, "Jarvis/Diario/2026-11-07.md") is None


def test_semana_reemplaza(diario):
    assert pedir({"fecha": "2026-11-02", "tipo": "semana", "modo": "reemplazar", "contenido": "## 🏋️ Gym\nnuevo\n"})["status"] == "done"
    t = (diario / "Semana 2026-11-02.md").read_text()
    assert "nuevo" in t and "bien" not in t


@pytest.mark.parametrize("p", [{"fecha": "mañana", "contenido": "x"}, {"fecha": "2026-13-01", "contenido": "x"},
                               {"fecha": "2026-11-08", "contenido": "  "}, {"fecha": "2026-11-08", "contenido": "x", "tipo": "mes"},
                               {"fecha": "2026-11-08", "contenido": "x", "modo": "borrar"}, {"fecha": "../../x", "contenido": "x"}])
def test_valida(diario, p):
    assert pedir(p)["status"] != "done"
    assert sorted(x.name for x in diario.iterdir()) == ["2026-11-06.md", "Semana 2026-11-02.md"]


def test_edicion_a_mano_se_descarta_y_se_guarda(diario, settings):
    f = diario / "2026-11-06.md"
    f.write_text(f.read_text() + "\nlo escribí en Obsidian\n")
    (diario / "2026-11-09.md").write_text("inventado")
    with dbm.session_scope() as s:
        r = vault_sync.sync_journal(s)
    assert r["descartados"] == 2
    assert "Obsidian" not in f.read_text() and not (diario / "2026-11-09.md").exists()
    guardados = list((settings.data_dir / "descartes/diario").iterdir())
    assert len(guardados) == 2 and any("Obsidian" in g.read_text() for g in guardados)
    avisos = list((settings.data_dir / "avisos").iterdir())
    assert any("diario" in a.read_text() for a in avisos)


def test_una_nota_borrada_se_rehace(diario):
    (diario / "2026-11-06.md").unlink()
    with dbm.session_scope() as s:
        vault_sync.sync_journal(s)
    assert "Gym: Upper" in (diario / "2026-11-06.md").read_text()


def test_conflictos_y_notas_sin_fecha_no_se_tocan(diario):
    c = diario / "2026-11-06.sync-conflict-20261107-1.md"
    c.write_text("conflicto")
    libre = diario / "Ideas.md"
    libre.write_text("mía")
    with dbm.session_scope() as s:
        vault_sync.sync_journal(s)
    assert c.read_text() == "conflicto" and libre.read_text() == "mía"


def test_la_rutina_puede_escribir_el_diario():
    assert "journal.write" in orq.RUTINA_CAPS and actions.REGISTRY["journal.write"].level == 1
