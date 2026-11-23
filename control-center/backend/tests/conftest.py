import json
import os
import tempfile

os.environ["CC_MONITOR"] = "0"  # el muestreo real no corre en las pruebas
# Ninguna prueba puede tocar la vault real, aunque se ejecuten en la carpeta de una instalación en uso: los
# recopiladores (collectors/lib.py) y el backend leen CC_VAULT, que aquí apunta a una carpeta temporal antes de importar nada.
os.environ["CC_VAULT"] = tempfile.mkdtemp(prefix="pos-pruebas-vault-")
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import config, db
from app.models import User
from app.security import hash_password

ORIGIN = "http://127.0.0.1:3770"
PW = "contraseña-de-prueba-larga"


@pytest.fixture(autouse=True)
def config_instancia(tmp_path: Path, monkeypatch):
    """Configuración de la instancia en una carpeta temporal y con todos los módulos activos: las pruebas de cada
    módulo no dependen de lo que tenga configurado quien las ejecuta. Las de módulos apagados lo cambian."""
    d = tmp_path / "config-instancia"
    d.mkdir()
    monkeypatch.setenv("POS_CONFIG_DIR", str(d))
    from app.core import modules
    (d / "modulos.json").write_text(json.dumps({"activos": list(modules.MODULES)}))
    return d


@pytest.fixture(autouse=True)
def config_instancia(tmp_path: Path, monkeypatch):
    """Configuración de la instancia en una carpeta temporal y con todos los módulos activos (las pruebas de cada
    módulo los usan); las pruebas de módulos apagados lo cambian ellas mismas."""
    d = tmp_path / "config"
    d.mkdir()
    monkeypatch.setenv("POS_CONFIG_DIR", str(d))
    from app.core import modules
    (d / "modulos.json").write_text(json.dumps({"activos": list(modules.MODULES)}))
    return d


@pytest.fixture(autouse=True)
def _sin_vault_real(tmp_path: Path, monkeypatch):
    """Además, las rutas de collectors/tareas.py van a la carpeta temporal de cada prueba (16/11: una prueba reescribió
    el Tareas.md real de una instalación en uso). Una prueba que necesite otra ruta la cambia con monkeypatch."""
    import sys
    if str(config.ROOT / "collectors") not in sys.path:
        sys.path.insert(0, str(config.ROOT / "collectors"))
    import tareas
    j = tmp_path / "vault" / "Jarvis"
    for k, sub in (("TAREAS", "Tareas.md"), ("PANEL", "Panel.md"), ("HECHOS", "Sistema/hechos.json"), ("PANEL_ESTADO", "Sistema/panel-estado.json")):
        monkeypatch.setattr(tareas, k, j / sub)
    from app import agenda
    monkeypatch.setattr(agenda, "_visto", None, raising=False)


@pytest.fixture()
def settings(tmp_path: Path):
    proj = tmp_path / "projects"
    proj.mkdir()
    (tmp_path / "agents").mkdir()
    s = config.Settings(data_dir=tmp_path / "data", vault=tmp_path / "vault", jarvis_projects=proj, agents_dir=tmp_path / "agents", sessions_dir=tmp_path / "sesiones", files_dir=tmp_path / "archivos",
                        hostagent_socket=tmp_path / "nohay.sock", hostagent_token="x" * 40,
                        allowed_origins=(ORIGIN,), cookie_secure=False)
    config.set_settings(s)
    db.reset_engine()
    if s.db_url:  # base compartida entre pruebas: se vacía antes de cada una
        # Las pruebas borran la base: jamás deben tocar otra que la temporal, aunque CC_DB_URL esté cargada en el entorno
        if s.db_url.rsplit("/", 1)[-1] != "prueba":
            pytest.exit("CC_DB_URL no apunta a una base de pruebas (debe llamarse «prueba»): no se ejecuta nada", returncode=2)
        with db.engine().begin() as c:
            c.execute(text("DROP SCHEMA public CASCADE"))
            c.execute(text("CREATE SCHEMA public"))
    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "migrations"))
    command.upgrade(cfg, "head")
    with db.session_scope() as s_:
        s_.add(User(username="ana", password_hash=hash_password(PW)))
    yield s
    db.reset_engine()


@pytest.fixture()
def client(settings):
    from app.main import app
    with TestClient(app, base_url="http://127.0.0.1:8770") as c:
        yield c


@pytest.fixture()
def auth(client):
    r = client.post("/api/v1/auth/login", json={"username": "ana", "password": PW}, headers={"Origin": ORIGIN})
    assert r.status_code == 200
    return {"Origin": ORIGIN, "X-CSRF-Token": r.json()["csrf_token"]}


def seed_tasks(path) -> None:
    """Las tareas viven en la base: siembra desde una nota (como la primera sincronización) y deja la marca de «la base manda»."""
    from app.modules import vault_sync
    with db.session_scope() as s:
        vault_sync.import_tasks(s, path)
    marca = config.get_settings().data_dir / vault_sync.MARCA_TAREAS
    marca.parent.mkdir(parents=True, exist_ok=True)
    marca.write_text("test")
