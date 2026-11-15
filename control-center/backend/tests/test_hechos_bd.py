"""Lo marcado (hechos.json): manda la base. Se aceptan marcas y desmarcas de la copia (build.py, Obsidian), no perderla."""
import json

import pytest

from app import db as dbm
from app.modules import mirror, vault_sync

INICIAL = {f"estudio|2026-11-0{i}|SC · Bloque {i}": f"2026-11-0{i}" for i in range(1, 7)}


@pytest.fixture()
def h(client, settings):
    f = settings.vault / "Jarvis/Sistema/hechos.json"
    f.parent.mkdir(parents=True)
    f.write_text(json.dumps(INICIAL))
    with dbm.session_scope() as s:
        vault_sync.sync_hechos(s)
    assert (settings.data_dir / vault_sync.MARCA_UNI).exists()  # solo tras confirmar
    return f


def base():
    with dbm.session_scope() as s:
        return mirror.hechos_dict(s)


def test_siembra(h):
    assert base() == INICIAL


def test_se_aceptan_marcas_y_desmarcas_de_la_copia(h):
    d = dict(INICIAL)
    d.pop("estudio|2026-11-01|SC · Bloque 1")
    d["gym|2026-11-07"] = "2026-11-07"
    h.write_text(json.dumps(d))
    with dbm.session_scope() as s:
        r = vault_sync.sync_hechos(s)
    assert (r["nuevas"], r["quitadas"]) == (1, 1) and base() == d


def test_perder_la_mitad_no_desmarca_y_rehace(h, settings):
    h.write_text(json.dumps({"estudio|2026-11-01|SC · Bloque 1": "2026-11-01", "gym|2026-11-07": "2026-11-07"}))
    with dbm.session_scope() as s:
        assert vault_sync.sync_hechos(s)["rehecha"] is True
    esperado = INICIAL | {"gym|2026-11-07": "2026-11-07"}  # lo nuevo sí entra
    assert base() == esperado and json.loads(h.read_text()) == esperado


def test_borrado_se_rehace(h):
    h.unlink()
    with dbm.session_scope() as s:
        vault_sync.sync_hechos(s)
    assert json.loads(h.read_text()) == INICIAL


def test_marcar_escribe_primero_en_la_base(h):
    with dbm.session_scope() as s:
        vault_sync.set_hecho(s, "entrega|2026-11-09|SC I: PEC1", True, "2026-11-07")
    assert json.loads(h.read_text())["entrega|2026-11-09|SC I: PEC1"] == "2026-11-07"
    with dbm.session_scope() as s:
        vault_sync.set_hecho(s, "entrega|2026-11-09|SC I: PEC1", False)
    assert "entrega|2026-11-09|SC I: PEC1" not in json.loads(h.read_text()) and base() == INICIAL


def test_repetir_no_cambia_nada(h):
    with dbm.session_scope() as s:
        assert vault_sync.sync_hechos(s) == {"origen": 6, "nuevas": 0, "quitadas": 0}
