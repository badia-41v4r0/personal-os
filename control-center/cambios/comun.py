"""Lo común al supervisor de cambios, la vista previa y el Constructor: rutas, entorno, git y archivos de estado.

Todo se ejecuta como el usuario, fuera del panel (unidades transitorias de systemd que lanza el Host Agent), así que un
reinicio del panel no los corta. El panel solo lee los archivos de estado que dejan aquí.
"""
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(os.environ.get("POS_ROOT") or Path(__file__).resolve().parents[2])
DATA = ROOT / "data"
CAMBIOS = DATA / "cambios"            # estado de la operación en curso, historial y copias de seguridad
ESTADO = CAMBIOS / "estado.json"
HISTORIAL = CAMBIOS / "historial.jsonl"
COPIAS = CAMBIOS / "copias"
CONSTRUCTOR = DATA / "constructor"    # la personalización abierta: copia del código, datos de la vista previa, turnos
ABIERTA = CONSTRUCTOR / "personalizacion.json"
COPIA = CONSTRUCTOR / "copia"         # clon del código donde trabaja el Constructor (rama RAMA)
DATOS_VP = CONSTRUCTOR / "datos"      # copia de los datos para la vista previa
RAMA = "personalizaciones"
WEB = ROOT / "control-center/apps/web"
BACKEND = ROOT / "control-center/backend"
PREFIJO_PERSONALIZACION = "Personalización: "
PREFIJO_DESHACER = "Deshacer personalización: "
PREFIJO_ACTUALIZACION = "Actualización a "
VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
GIT_ID = {"GIT_AUTHOR_NAME": "Personal OS", "GIT_AUTHOR_EMAIL": "personal-os@localhost",
          "GIT_COMMITTER_NAME": "Personal OS", "GIT_COMMITTER_EMAIL": "personal-os@localhost"}


def ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def leer_env(f: Path) -> dict[str, str]:
    """KEY=valor de un archivo .env, sin ejecutarlo."""
    out: dict[str, str] = {}
    try:
        for linea in f.read_text(encoding="utf-8").splitlines():
            if "=" in linea and not linea.lstrip().startswith("#"):
                k, v = linea.split("=", 1)
                out[k.strip()] = v.strip()
    except OSError:
        pass
    return out


def config_instancia() -> dict[str, str]:
    return leer_env(ROOT / ".env")


def instancia() -> str:
    return os.environ.get("POS_INSTANCE") or config_instancia().get("POS_INSTANCE") or "pos"


def puerto() -> int:
    return int(config_instancia().get("POS_PORT") or os.environ.get("POS_PORT") or 8770)


def entorno(secretos: bool = True) -> dict[str, str]:
    """Entorno para las órdenes de mantenimiento: el PATH con el que se instaló (uv, node) y la configuración del panel."""
    env = dict(os.environ)
    cfg = config_instancia()
    if cfg.get("POS_PATH"):
        env["PATH"] = cfg["POS_PATH"] + ":" + env.get("PATH", "/usr/bin:/bin")
    home = Path.home()
    env["PATH"] = env.get("PATH", "/usr/bin:/bin") + f":{home}/.local/bin:{home}/.local/share/mise/shims:/usr/local/bin:/usr/bin:/bin"
    env["POS_INSTANCE"] = instancia()
    if cfg.get("POS_TZ"):
        env["POS_TZ"] = cfg["POS_TZ"]
    if secretos:
        env |= leer_env(DATA / "control-center/secrets.env")
    return env


def ejecutar(argv: list[str], cwd: Path = ROOT, env: dict | None = None, timeout: int = 1800, log=None) -> str:
    """Ejecuta una orden; si falla, lanza Fallo con el final de su salida."""
    r = subprocess.run(argv, cwd=cwd, env=env or entorno(), capture_output=True, text=True, timeout=timeout,
                       stdin=subprocess.DEVNULL)
    salida = (r.stdout or "") + (r.stderr or "")
    if log is not None:
        log(f"$ {' '.join(argv)}\n{salida[-4000:]}")
    if r.returncode != 0:
        raise Fallo(f"Falló «{' '.join(argv[:3])}»: {salida.strip()[-600:]}")
    return r.stdout


def git(*args: str, cwd: Path = ROOT, check: bool = True) -> str:
    env = {**os.environ, **GIT_ID, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}
    r = subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL)
    if check and r.returncode != 0:
        raise Fallo(f"git {args[0]}: {(r.stderr or r.stdout).strip()[-500:]}")
    return r.stdout.strip()


def git_ok(*args: str, cwd: Path = ROOT) -> bool:
    env = {**os.environ, **GIT_ID, "GIT_TERMINAL_PROMPT": "0"}
    return subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, timeout=300, stdin=subprocess.DEVNULL).returncode == 0


def leer_json(f: Path, defecto=None):
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return defecto


def escribir_json(f: Path, datos) -> None:
    """Escritura atómica (el panel puede estar leyéndolo)."""
    f.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = f.with_name(f".{f.name}.tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(f)


def version_actual(cwd: Path = ROOT) -> str:
    try:
        return (cwd / "VERSION").read_text().strip()
    except OSError:
        return "0.0.0"


def version_tupla(v: str) -> tuple[int, int, int] | None:
    m = VERSION_RE.match(v.strip())
    return tuple(int(x) for x in m.groups()) if m else None  # type: ignore[return-value]


def notas_de_version(changelog: str, version: str) -> str:
    """La entrada `## [X.Y.Z]` del CHANGELOG (sin el título)."""
    v = version.lstrip("v")
    fuera, dentro = [], False
    for linea in changelog.splitlines():
        if linea.startswith("## ["):
            if dentro:
                break
            dentro = linea.startswith(f"## [{v}]")
            continue
        if dentro:
            fuera.append(linea)
    return "\n".join(fuera).strip()


class Fallo(Exception):
    """Un paso no ha ido bien. `codigo` lo distingue para el panel (p. ej. «conflicto»)."""

    def __init__(self, mensaje: str, codigo: str = "error"):
        super().__init__(mensaje)
        self.codigo = codigo
