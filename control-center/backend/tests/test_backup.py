import importlib.util
import sqlite3
import sys

from app.config import ROOT


def load(monkeypatch, data):
    monkeypatch.setenv("CC_DATA_DIR", str(data))
    monkeypatch.delenv("CC_DB_URL", raising=False)  # esta prueba cubre la copia de SQLite
    spec = importlib.util.spec_from_file_location("backup", ROOT / "control-center/deployment/backup.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_copia_integra_y_rotacion(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    with sqlite3.connect(data / "cc.db") as c:
        c.execute("CREATE TABLE alembic_version (version_num TEXT)")
        c.execute("INSERT INTO alembic_version VALUES ('0002')")
        c.execute("CREATE TABLE t (x)")
        c.execute("INSERT INTO t VALUES (42)")
    (data / "hostagent-audit.jsonl").write_text("{}\n")
    m = load(monkeypatch, data)
    dest = tmp_path / "copias"
    dest.mkdir()
    import time
    outs = []
    for _ in range(3):
        outs.append(m.backup(dest, keep=2))
        time.sleep(1.05)
    left = sorted(p.name for p in dest.iterdir())
    assert len(left) == 2 and outs[0].name not in left  # rota
    last = outs[-1]
    with sqlite3.connect(last / "cc.db") as c:
        assert c.execute("SELECT x FROM t").fetchone()[0] == 42
    assert (last / "hostagent-audit.jsonl").exists() and "0002" in (last / "LEEME.txt").read_text()
    assert oct((last / "cc.db").stat().st_mode)[-3:] == "600"


def test_copia_cifrada_se_restaura(tmp_path, monkeypatch):
    data = tmp_path / "d"
    data.mkdir()
    with sqlite3.connect(data / "cc.db") as c:
        c.execute("CREATE TABLE alembic_version (version_num TEXT)")
        c.execute("INSERT INTO alembic_version VALUES ('x')")
        c.execute("CREATE TABLE t (v TEXT)")
        c.execute("INSERT INTO t VALUES ('secreto-de-prueba')")
    m = load(monkeypatch, data)
    monkeypatch.setenv("CC_BACKUP_KEY", "clave-de-prueba")
    out = m.backup(tmp_path / "b", 3)
    assert not (out / "cc.db").exists()
    enc = out / "cc.db.enc"
    assert b"secreto-de-prueba" not in enc.read_bytes()
    plano = m.descifrar(enc, "clave-de-prueba")
    with sqlite3.connect(plano) as c:
        assert c.execute("SELECT v FROM t").fetchone()[0] == "secreto-de-prueba"


def test_clave_incorrecta_no_descifra(tmp_path, monkeypatch):
    import pytest
    data = tmp_path / "d"
    data.mkdir()
    m = load(monkeypatch, data)
    f = tmp_path / "x"
    f.write_bytes(b"datos")
    enc = m.cifrar(f, "buena")
    with pytest.raises(Exception):
        m.descifrar(enc, "mala")
