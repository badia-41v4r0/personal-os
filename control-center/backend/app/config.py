"""Configuración del Control Center. Todo por variables de entorno, con valores por defecto seguros.

Rutas por defecto relativas a la raíz del proyecto Jarvis (la carpeta que contiene control-center/).
"""
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
# Zona horaria del usuario (días, avisos, rutinas)
TZ_NAME = os.environ.get("POS_TZ", "Europe/Madrid")
# Nombre de la instancia: separa varias instalaciones en el mismo PC (contenedores, socket, unidades). Igual que en el Host Agent.
INSTANCE = os.environ.get("POS_INSTANCE", "jarvis")
if not re.fullmatch(r"[a-z][a-z0-9-]{1,15}", INSTANCE):
    raise SystemExit(f"POS_INSTANCE no válido: {INSTANCE!r}")


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    root: Path = ROOT
    instance: str = INSTANCE
    # Estado propio del panel (fuera de git: data/ está en .gitignore)
    data_dir: Path = field(default_factory=lambda: Path(_env("CC_DATA_DIR", str(ROOT / "data/control-center"))))
    # Vacío = SQLite en data_dir/cc.db. Ejemplo: postgresql+psycopg://jarvis:clave@127.0.0.1:55433/personal_os
    db_url: str = field(default_factory=lambda: _env("CC_DB_URL", ""))
    # Modelo de Ollama para embeddings (1024 dimensiones). Vacío = búsqueda solo por texto
    embed_model: str = field(default_factory=lambda: _env("CC_EMBED_MODEL", ""))
    # Consolidación de memoria cada noche. Gasta modelo: apagada salvo que se active
    consolidate: bool = field(default_factory=lambda: _env("CC_MEMORY_CONSOLIDATE", "0") == "1")
    # Token de lectura de TMDB (Ocio: carátulas e información de pelis y series). Vacío = solo a mano
    tmdb_token: str = field(default_factory=lambda: _env("CC_TMDB_TOKEN", ""))
    vault: Path = field(default_factory=lambda: Path(_env("CC_VAULT", str(ROOT / "Jarvis-Vault"))))
    # Transcripciones de la sesión principal de Jarvis (solo lectura)
    jarvis_projects: Path = field(
        default_factory=lambda: Path(_env("CC_JARVIS_PROJECTS", str(ROOT / "data/home/.claude/projects/-workspace"))))
    # Subagentes de Jarvis (los lee el contenedor en solo lectura; solo el panel y bin/aprobar los escriben)
    agents_dir: Path = field(default_factory=lambda: Path(_env("CC_AGENTS_DIR", str(ROOT / "agent/.claude/agents"))))
    # Carpetas de las sesiones independientes (las crea el Host Agent: data/sesiones/<id>/trabajo)
    sessions_dir: Path = field(default_factory=lambda: Path(_env("CC_SESSIONS_DIR", str(ROOT / "data/sesiones"))))
    # Carpeta común de archivos (adjuntos del panel; Jarvis la ordena y la ve en /archivos)
    files_dir: Path = field(default_factory=lambda: Path(_env("CC_FILES_DIR", str(ROOT / "archivos"))))
    hostagent_socket: Path = field(default_factory=lambda: Path(_env(
        "CC_HOSTAGENT_SOCKET", f"{os.environ.get('XDG_RUNTIME_DIR', '/tmp')}/{INSTANCE}-cc/hostagent.sock")))
    hostagent_token: str = field(default_factory=lambda: _env("CC_HOSTAGENT_TOKEN", ""))
    # Orígenes admitidos (CSRF de peticiones con efecto y WebSocket). Separados por comas.
    # `https://host:*` admite ese host en cualquier puerto.
    allowed_origins: tuple[str, ...] = field(default_factory=lambda: tuple(
        o.strip().rstrip("/") for o in _env("CC_ALLOWED_ORIGINS", "http://127.0.0.1:3770,http://localhost:3770").split(",")
        if o.strip()))
    # En producción (detrás de Tailscale Serve con HTTPS) la cookie es Secure. Solo se desactiva en desarrollo local.
    cookie_secure: bool = field(default_factory=lambda: _env("CC_COOKIE_SECURE", "1") == "1")
    session_hours: int = field(default_factory=lambda: int(_env("CC_SESSION_HOURS", "168")))
    login_max_fails: int = 5
    login_lock_minutes: int = 15

    @property
    def db_path(self) -> Path:
        return self.data_dir / "cc.db"


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def set_settings(s: Settings) -> None:
    """Solo para pruebas."""
    global _settings
    _settings = s
