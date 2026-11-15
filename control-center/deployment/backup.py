"""Copia de seguridad del Control Center (lo que no está en ningún otro sitio).

Con CC_DB_URL: pg_dump del contenedor pos-db, comprobado con pg_restore --list. Sin ella: copia en caliente de
data/control-center/cc.db con la API de backup de SQLite. Las dos son consistentes aunque el panel esté escribiendo.
Guarda también la auditoría del Host Agent y las claves de los avisos. Rota a 14 copias.
La vault, el repo y el estado de Jarvis no se copian aquí (Syncthing, git y backlog del disco externo).

Uso: control-center/backend/.venv/bin/python control-center/deployment/backup.py [--dest DIR] [--keep N]
"""
import argparse
import hashlib
import secrets
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ROOT = Path(__file__).resolve().parents[2]
import os

DATA = Path(os.environ.get("CC_DATA_DIR", str(ROOT / "data/control-center")))


PG_CONTAINER = "pos-db"
PG_ARGS = ["-U", "jarvis", "-d", "personal_os"]


def _sqlite(out: Path) -> str:
    src = DATA / "cc.db"
    if not src.exists():
        shutil.rmtree(out)
        sys.exit("No existe data/control-center/cc.db")
    with sqlite3.connect(src) as s, sqlite3.connect(out / "cc.db") as d:
        s.backup(d)
    with sqlite3.connect(out / "cc.db") as d:
        ok = d.execute("PRAGMA integrity_check").fetchone()[0]
        rev = d.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    if ok != "ok":
        shutil.rmtree(out)
        sys.exit(f"La copia no pasa integrity_check: {ok}")
    return rev


def _postgres(out: Path) -> str:
    dump = out / "personal_os.dump"
    with dump.open("wb") as f:
        r = subprocess.run(["docker", "exec", PG_CONTAINER, "pg_dump", *PG_ARGS, "-Fc"], stdout=f, stderr=subprocess.PIPE)
    check = None
    if r.returncode == 0:
        with dump.open("rb") as f:
            check = subprocess.run(["docker", "exec", "-i", PG_CONTAINER, "pg_restore", "--list"], stdin=f, capture_output=True)
    if r.returncode != 0 or check is None or check.returncode != 0 or b"TABLE DATA" not in check.stdout:
        shutil.rmtree(out)
        sys.exit("La copia de PostgreSQL no se puede leer: " + r.stderr.decode(errors="replace")[:300])
    q = subprocess.run(["docker", "exec", PG_CONTAINER, "psql", *PG_ARGS, "-Atc", "SELECT version_num FROM alembic_version"],
                       capture_output=True, text=True)
    return q.stdout.strip() or "?"


def _aes(key: str) -> AESGCM:
    return AESGCM(hashlib.sha256(key.encode()).digest())


def cifrar(f: Path, key: str) -> Path:
    nonce = secrets.token_bytes(12)
    out = f.with_name(f.name + ".enc")
    out.write_bytes(nonce + _aes(key).encrypt(nonce, f.read_bytes(), f.name.encode()))
    f.unlink()
    return out


def descifrar(f: Path, key: str) -> Path:
    data = f.read_bytes()
    name = f.name.removesuffix(".enc")
    out = f.with_name(name)
    out.write_bytes(_aes(key).decrypt(data[:12], data[12:], name.encode()))
    out.chmod(0o600)
    return out


def backup(dest: Path, keep: int) -> Path:
    out = dest / datetime.now().strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, mode=0o700)
    rev = _postgres(out) if os.environ.get("CC_DB_URL", "").startswith("postgresql") else _sqlite(out)
    for extra in ("hostagent-audit.jsonl", "vapid.pem"):
        if (DATA / extra).exists():
            shutil.copy2(DATA / extra, out / extra)
    key = os.environ.get("CC_BACKUP_KEY", "")
    if key:  # con finanzas dentro, una copia en claro no debe salir de aquí
        for f in [p for p in out.iterdir() if p.name in ("cc.db", "personal_os.dump", "vapid.pem", "hostagent-audit.jsonl")]:
            cifrar(f, key)
    (out / "LEEME.txt").write_text(f"Copia del Control Center\nfecha: {out.name}\nmigración: {rev}\nintegridad: ok\n"
                                  f"Restaurar: control-center/deployment/restaurar.sh {out}\n")
    for f in out.iterdir():
        f.chmod(0o600)
    copias = sorted(p for p in dest.iterdir() if p.is_dir() and p.name[:8].isdigit())
    for old in copias[:-keep]:
        shutil.rmtree(old)
    print(f"Copia hecha en {out} (migración {rev}, {len(copias[-keep:])} copias guardadas)")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", type=Path, default=DATA / "backups")
    ap.add_argument("--keep", type=int, default=14)
    ap.add_argument("--descifrar", type=Path, help="descifra los .enc de una copia y termina")
    a = ap.parse_args()
    if a.descifrar:
        for enc in a.descifrar.glob("*.enc"):
            print(descifrar(enc, os.environ["CC_BACKUP_KEY"]))
        sys.exit(0)
    a.dest.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup(a.dest, max(1, a.keep))
