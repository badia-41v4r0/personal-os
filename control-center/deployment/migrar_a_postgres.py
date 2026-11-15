"""Copia cc.db (SQLite) a PostgreSQL y verifica que nada cambia. No toca el archivo de origen.

Requisitos: esquema vacío o con tablas sin filas; el backend parado para que no entren datos durante la copia.
Uso: CC_DB_URL=postgresql+psycopg://… control-center/backend/.venv/bin/python control-center/deployment/migrar_a_postgres.py [--origen cc.db]

Todo va en una transacción: si cualquier tabla no cuadra, Postgres queda como estaba. Para volver atrás basta con
quitar CC_DB_URL: cc.db sigue intacta.
"""
import argparse
import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "control-center/backend"))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import create_engine, insert, select, text  # noqa: E402
from sqlalchemy.types import JSON, Boolean, DateTime  # noqa: E402

from app import models  # noqa: E402,F401  (registra las tablas)
from app.db import Base  # noqa: E402

LOTE = 500


def convertir(valor, tipo):
    """SQLite guarda booleanos como 0/1 y JSON y fechas como texto."""
    if valor is None:
        return None
    if isinstance(tipo, Boolean):
        return bool(valor)
    if isinstance(tipo, JSON):
        return json.loads(valor) if isinstance(valor, str) else valor
    if isinstance(tipo, DateTime) and isinstance(valor, str):
        from datetime import datetime
        return datetime.fromisoformat(valor)
    return valor


def huella(filas: list[dict]) -> str:
    h = hashlib.sha256()
    for f in sorted(json.dumps(x, sort_keys=True, default=str) for x in filas):
        h.update(f.encode())
    return h.hexdigest()


def migrar(origen: Path, url: str) -> dict[str, int]:
    src = sqlite3.connect(f"file:{origen}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    rev = src.execute("SELECT version_num FROM alembic_version").fetchone()[0]

    cfg = Config(str(ROOT / "control-center/backend/alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "control-center/backend/migrations"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(cfg, rev)

    dest = create_engine(url)
    resumen: dict[str, int] = {}
    with dest.begin() as c:
        for t in Base.metadata.sorted_tables:  # primero los padres, por las claves ajenas
            filas = []
            for r in src.execute(f'SELECT * FROM "{t.name}"'):  # noqa: S608  (nombres del propio esquema)
                filas.append({col.name: convertir(r[col.name], col.type) for col in t.columns})
            if c.scalar(select(text("count(*)")).select_from(t)):
                raise SystemExit(f"{t.name} ya tiene datos en Postgres: no se ha copiado nada")
            for i in range(0, len(filas), LOTE):
                c.execute(insert(t), filas[i:i + LOTE])
            copia = [dict(f._mapping) for f in c.execute(select(t))]
            if len(copia) != len(filas) or huella(copia) != huella(filas):
                raise SystemExit(f"{t.name} no cuadra tras copiar: se deshace todo")
            resumen[t.name] = len(filas)
            for col in t.primary_key.columns:  # las claves autoincrementales siguen desde la última
                if col.autoincrement in (True, "auto") and col.type.python_type is int:
                    c.execute(text(f"""SELECT setval(pg_get_serial_sequence('"{t.name}"', '{col.name}'),
                                       COALESCE((SELECT max("{col.name}") FROM "{t.name}"), 1),
                                       (SELECT max("{col.name}") IS NOT NULL FROM "{t.name}"))"""))
    src.close()
    return resumen


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--origen", default=str(ROOT / "data/control-center/cc.db"))
    args = ap.parse_args()
    url = os.environ.get("CC_DB_URL", "")
    if not url.startswith("postgresql"):
        sys.exit("Falta CC_DB_URL con una base PostgreSQL")
    r = migrar(Path(args.origen), url)
    print(f"Copiadas {sum(r.values())} filas de {len(r)} tablas. Todas cuadran.")
    for k, v in sorted(r.items()):
        if v:
            print(f"  {k}: {v}")
