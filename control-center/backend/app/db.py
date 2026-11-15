"""Base de datos con SQLAlchemy: PostgreSQL si hay CC_DB_URL, si no SQLite (WAL). El esquema lo crean las migraciones."""
from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import create_engine, event
from sqlalchemy.pool import NullPool
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


_engine: Engine | None = None
_Session: sessionmaker | None = None


def make_engine(url: str) -> Engine:
    if not url.startswith("sqlite"):
        # Pool con tope: una petición larga no debe dejar a las demás sin conexión
        return create_engine(url, pool_size=8, max_overflow=8, pool_pre_ping=True, pool_recycle=1800, pool_timeout=15)
    # Sin pool: en SQLite abrir una conexión es casi gratis, y así una petición larga (que espera al Host Agent o a
    # Google) nunca deja a las demás sin conexión. La concurrencia la gestionan WAL y busy_timeout.
    eng = create_engine(url, connect_args={"check_same_thread": False, "timeout": 15}, poolclass=NullPool)

    @event.listens_for(eng, "connect")
    def _pragmas(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA busy_timeout=15000")
        cur.close()

    return eng


def engine() -> Engine:
    global _engine, _Session
    if _engine is None:
        s = get_settings()
        s.data_dir.mkdir(parents=True, exist_ok=True)
        s.data_dir.chmod(0o700)
        _engine = make_engine(s.db_url or f"sqlite:///{s.db_path}")
        _Session = sessionmaker(_engine, expire_on_commit=False)
    return _engine


def reset_engine() -> None:
    """Solo para pruebas."""
    global _engine, _Session
    if _engine is not None:
        _engine.dispose()
    _engine, _Session = None, None


@contextmanager
def session_scope():
    engine()
    s: Session = _Session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def get_db():
    """Dependencia de FastAPI."""
    with session_scope() as s:
        yield s
