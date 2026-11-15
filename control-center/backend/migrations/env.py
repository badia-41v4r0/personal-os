"""Migraciones: usan la misma base que la app (CC_DATA_DIR) salvo que se pase sqlalchemy.url."""
from alembic import context

from app import models  # noqa: F401  (registra las tablas)
from app.db import Base, engine, make_engine

cfg = context.config
url = cfg.get_main_option("sqlalchemy.url")
eng = make_engine(url) if url else engine()

with eng.connect() as conn:
    context.configure(connection=conn, target_metadata=Base.metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()
