"""Candidaturas: la base manda y la tabla del pipeline de Trabajo.md es una copia."""
import pytest

from app import db as dbm
from app.models import JobApplication
from app.modules import mirror, vault_sync as vs

NOTA = """# Trabajo

## Pipeline de candidaturas
| Empresa | Puesto | Estado | Fecha | Próximo paso | Follow-up |
|---|---|---|---|---|---|
| ACME | SE | aplicado | 2026-11-01 | Esperar | 2026-11-08 |

## Bloqueos
- ninguno
"""


@pytest.fixture()
def nota(settings):
    f = settings.vault / "Jarvis/Areas/Trabajo.md"
    f.parent.mkdir(parents=True)
    f.write_text(NOTA)
    return f


def _sync():
    with dbm.session_scope() as s:
        return vs.sync_jobs(s)


def _avisos(settings):
    d = settings.data_dir / "avisos"
    return list(d.glob("*.json")) if d.exists() else []


def test_la_primera_vez_siembra_la_base_desde_la_nota(client, nota, settings):
    assert _sync()["candidaturas_nuevas"] == 1
    with dbm.session_scope() as s:
        assert s.query(JobApplication).one().company == "ACME"
    assert (settings.data_dir / vs.MARCA_EMPLEO).exists()
    assert _sync()["candidaturas_nuevas"] == 0  # idempotente


def test_lo_cambiado_a_mano_se_descarta_y_se_avisa(client, nota, settings):
    _sync()
    with dbm.session_scope() as s:
        mirror.export_jobs(s)  # como tras cualquier escritura del panel: la copia queda al día
    editada = nota.read_text().replace("| Esperar |", "| Lo cambié a mano |").replace(
        "\n## Bloqueos", "| NUEVA | FDE | interés | 2026-11-02 |  |  |\n\n## Bloqueos", 1)
    nota.write_text(editada)
    _sync()
    final = nota.read_text()
    assert "Lo cambié a mano" not in final and "NUEVA" not in final and "ACME" in final and "## Bloqueos" in final
    with dbm.session_scope() as s:
        assert s.query(JobApplication).count() == 1  # la fila nueva a mano no entró
    assert len(_avisos(settings)) == 1 and "copia de la base de datos" in _avisos(settings)[0].read_text()
    _sync()  # ya está al día: no vuelve a avisar
    assert len(_avisos(settings)) == 1


def test_un_cambio_del_panel_se_refleja_en_la_nota_sin_avisos(client, auth, nota, settings):
    _sync()
    with dbm.session_scope() as s:
        aid = s.query(JobApplication).one().id
    r = client.patch(f"/api/v1/me/career/applications/{aid}", json={"estado": "entrevista", "proximo_paso": "Preparar caso"}, headers=auth)
    assert r.status_code == 200
    assert "entrevista" in nota.read_text() and "Preparar caso" in nota.read_text()
    _sync()
    assert _avisos(settings) == []
