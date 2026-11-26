"""Vista previa de una personalización: un segundo panel con el código del Constructor y una copia de los datos.

- **Una sola a la vez** por instalación: data/constructor/personalizacion.json dice cuál está abierta (y de qué
  conversación es). Mientras exista, no se puede abrir otra.
- **Código:** clon de la instalación en data/constructor/copia, rama `personalizaciones`. El panel real no se toca hasta
  que el usuario pulsa «Aplicar cambios» (supervisor.py aplicar).
- **Datos:** copia de la base, la vault y la configuración en data/constructor/datos. Lo que se haga en la vista previa
  se tira al cerrarla. Nunca se copian secretos (secrets.env, credenciales de los motores, claves de avisos, banco).
- **Sin efectos hacia fuera:** CC_VISTA_PREVIA=1 apaga los bucles de fondo (avisos, banco, sesión principal), no hay Host
  Agent (sin agentes, ordenadores, Telegram ni Docker) y los temporizadores siguen llamando al panel real.
- **Encerrada con bubblewrap:** solo ve su copia del código (lectura) y sus datos (escritura); la carpeta de la
  instalación y lo personal del home quedan ocultos.
- Se sirve en /vista-previa/ a través del panel real (proxy en app/vista_previa.py, con la sesión del usuario), y se
  duerme sola si nadie la usa en una hora (se despierta al volver a abrirla).

Uso (python del backend; lo lanza el Host Agent como unidades transitorias):
  vista_previa.py abrir <conversación> [--version vX.Y.Z]   prepara la copia y arranca (unidad <inst>-cc-vp-preparar)
  vista_previa.py servir                                   el servidor, encerrado (unidad <inst>-cc-vista-previa)
  vista_previa.py cerrar [--motivo descartada]             para todo y borra la copia y sus datos
"""
import argparse
import os
import secrets
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comun as C  # noqa: E402
from comun import Fallo  # noqa: E402

BASE_PATH = "/vista-previa"
WEB_OUT = "out-vista-previa"
USO = C.CONSTRUCTOR / "uso"              # el proxy lo toca en cada petición: si no cambia en DORMIR s, se duerme
DORMIR = 3600
HISTORIAL = C.CONSTRUCTOR / "historial.jsonl"
# Lo personal del home que nunca ve un proceso encerrado (igual que las consultas del Host Agent)
OCULTOS = (".ssh", ".gnupg", ".aws", ".claude", ".codex", ".docker", ".config/gh", ".config/rclone", ".config/chromium",
           ".config/google-chrome", ".config/google-chrome-beta", ".config/google-chrome-unstable", ".mozilla",
           ".local/share/keyrings", ".local/share/mise/state", ".config/opencode", ".local/share/opencode", ".gemini",
           ".netrc", ".git-credentials", ".pgpass", ".kube", ".password-store")
# De data/control-center no se copia: la base (va aparte), secretos, credenciales, colas y copias
NO_COPIAR = {"backups", "cc.db", "cc.db-wal", "cc.db-shm", "pg.env", "proveedores", "vapid.pem", "hostagent-audit.jsonl",
             "avisos", "ordenes", "runtime", "solicitudes", "gym-imports"}
NO_COPIAR_CONFIG = {"banco.json"}


def unidad(nombre: str) -> str:
    return f"{C.instancia()}-cc-{nombre}"


def abierta() -> dict | None:
    return C.leer_json(C.ABIERTA)


def _guardar(**cambios) -> dict:
    p = abierta() or {}
    p.update(cambios)
    C.escribir_json(C.ABIERTA, p)
    return p


def _paso(texto: str) -> None:
    _guardar(paso=texto)
    print(f"· {texto}", flush=True)


def _puerto_libre(desde: int) -> int:
    for p in range(desde, desde + 200):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    raise Fallo("No hay ningún puerto libre para la vista previa")


def _pg_url_vp(url: str) -> str:
    return url.rsplit("/", 1)[0] + "/personal_os_vp"


def _pg(*args: str, entrada=None, timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", "exec", "-i", f"{C.instancia()}-db", *args], stdin=entrada, capture_output=True, timeout=timeout)


def copiar_datos() -> dict:
    """Copia de los datos para la vista previa. Devuelve el entorno que la apunta a ella."""
    env_real = C.entorno()
    d = C.DATOS_VP
    shutil.rmtree(d, ignore_errors=True)
    (d / "control-center").mkdir(parents=True, mode=0o700)
    for sub in ("archivos", "sesiones", "transcripciones", "config"):
        (d / sub).mkdir(mode=0o700)
    origen = Path(env_real.get("CC_DATA_DIR") or C.DATA / "control-center")
    for x in origen.iterdir() if origen.is_dir() else []:
        if x.name in NO_COPIAR or x.name.startswith("secrets"):
            continue
        (shutil.copytree if x.is_dir() else shutil.copy2)(x, d / "control-center" / x.name)
    cfg = Path(env_real.get("POS_CONFIG_DIR") or C.DATA / "config")
    for x in cfg.glob("*.json") if cfg.is_dir() else []:
        if x.name not in NO_COPIAR_CONFIG:
            shutil.copy2(x, d / "config" / x.name)
    vault = Path(env_real.get("CC_VAULT") or C.ROOT / "Jarvis-Vault")
    if vault.is_dir():
        subprocess.run(["cp", "-a", "--reflink=auto", str(vault), str(d / "vault")], check=True, timeout=1800)
    else:
        (d / "vault").mkdir()
    url = env_real.get("CC_DB_URL", "")
    extra = {}
    if url.startswith("postgresql"):
        _pg("dropdb", "-U", "jarvis", "--if-exists", "personal_os_vp")
        r = _pg("createdb", "-U", "jarvis", "personal_os_vp")
        if r.returncode != 0:
            raise Fallo("No he podido crear la base de la vista previa: " + r.stderr.decode(errors="replace")[-300:])
        r = subprocess.run(["docker", "exec", f"{C.instancia()}-db", "sh", "-c",
                            "pg_dump -U jarvis -Fc personal_os | pg_restore -U jarvis -d personal_os_vp --no-owner"],
                           capture_output=True, timeout=1800)
        if r.returncode not in (0, 1):  # pg_restore devuelve 1 con avisos sin importancia
            raise Fallo("No he podido copiar la base: " + r.stderr.decode(errors="replace")[-300:])
        extra["CC_DB_URL"] = _pg_url_vp(url)
    else:
        src = origen / "cc.db"
        with sqlite3.connect(f"file:{src}?mode=ro", uri=True) as s, sqlite3.connect(d / "control-center/cc.db") as dst:
            s.backup(dst)
    for f in d.rglob("*"):
        try:
            f.chmod(0o700 if f.is_dir() else 0o600)
        except OSError:
            pass
    return extra


def entorno_vp(p: dict) -> dict:
    """Entorno del servidor de la vista previa: limpio (sin los secretos del panel real) y apuntando a la copia."""
    real = C.entorno()
    d = C.DATOS_VP
    env = {
        "PATH": real.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home()), "LANG": real.get("LANG", "C.UTF-8"),
        "POS_INSTANCE": C.instancia(), "POS_TZ": real.get("POS_TZ", "Europe/Madrid"),
        "POS_CONFIG_DIR": str(d / "config"), "CC_DATA_DIR": str(d / "control-center"), "CC_VAULT": str(d / "vault"),
        "CC_FILES_DIR": str(d / "archivos"), "CC_SESSIONS_DIR": str(d / "sesiones"),
        "CC_JARVIS_PROJECTS": str(d / "transcripciones"), "CC_HOSTAGENT_SOCKET": str(d / "sin-host-agent.sock"),
        "CC_HOSTAGENT_TOKEN": "", "CC_MONITOR": "0", "CC_VISTA_PREVIA": "1", "CC_VISTA_PREVIA_TOKEN": p["token"],
        "CC_ALLOWED_ORIGINS": real.get("CC_ALLOWED_ORIGINS", ""), "CC_COOKIE_SECURE": real.get("CC_COOKIE_SECURE", "1"),
        "CC_WEB_DIR": str(C.COPIA / "control-center/apps/web" / WEB_OUT), "PYTHONDONTWRITEBYTECODE": "1",
    }
    if p.get("db_url"):
        env["CC_DB_URL"] = p["db_url"]
    return env


def compilar_web_vp(cwd: Path = C.COPIA) -> None:
    web = cwd / "control-center/apps/web"
    C.ejecutar(["npm", "run", "build"], cwd=web, timeout=1800,
               env={**C.entorno(secretos=False), "NEXT_PUBLIC_BASE_PATH": BASE_PATH, "CC_WEB_OUT": WEB_OUT})


def jaula(cmd: list[str], escritura: list[Path], lectura: list[Path], chdir: Path) -> list[str]:
    """bubblewrap: el sistema en solo lectura, lo personal y la instalación ocultos, y solo lo indicado a la vista."""
    home = Path.home()
    argv = ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp"]
    for rel in OCULTOS:
        if (home / rel).exists():
            argv += ["--tmpfs" if (home / rel).is_dir() else "--ro-bind", *((str(home / rel),) if (home / rel).is_dir() else ("/dev/null", str(home / rel)))]
    argv += ["--tmpfs", str(C.ROOT)]  # la instalación real (datos, vault, secretos, .env) no existe dentro
    for p in lectura:
        argv += ["--ro-bind", str(p), str(p)]
    for p in escritura:
        argv += ["--bind", str(p), str(p)]
    return argv + ["--unshare-pid", "--die-with-parent", "--new-session", "--chdir", str(chdir), "--", *cmd]


def _salud(puerto: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{puerto}/api/v1/health", timeout=5) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def systemd_run(nombre: str, argv: list[str], extra: tuple[str, ...] = ()) -> None:
    subprocess.run(["systemctl", "--user", "reset-failed", f"{nombre}.service"], capture_output=True, timeout=30)
    r = subprocess.run(["systemd-run", "--user", "--quiet", "--collect", f"--unit={nombre}", *extra,
                        f"--working-directory={C.ROOT}", "--", *argv], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise Fallo(f"No he podido arrancar {nombre}: {r.stderr.strip()[-300:]}")


def arrancar() -> None:
    """Arranca (o despierta) el servidor de la vista previa."""
    p = abierta()
    if not p or p.get("estado") not in ("lista", "dormida", "preparando"):
        raise Fallo("No hay ninguna vista previa preparada")
    if subprocess.run(["systemctl", "--user", "is-active", "--quiet", unidad("vista-previa")]).returncode == 0:
        return
    if p.get("conflicto"):  # actualización a medio juntar: solo se arranca cuando el Constructor la ha resuelto
        if C.git("diff", "--name-only", "--diff-filter=U", cwd=C.COPIA) or (C.COPIA / ".git/MERGE_HEAD").exists():
            raise Fallo("La actualización aún tiene conflictos sin resolver")
        p = _guardar(conflicto=None)
    if not (C.COPIA / "control-center/apps/web" / WEB_OUT / "index.html").exists():
        _guardar(estado="preparando", paso="Compilando la vista previa")
        compilar_web_vp()
        C.ejecutar([str(C.COPIA / "control-center/backend/.venv/bin/alembic"), "upgrade", "head"],
                   cwd=C.COPIA / "control-center/backend", env=entorno_vp(p), timeout=600)
    USO.touch()
    systemd_run(unidad("vista-previa"), [sys.executable, str(Path(__file__).resolve()), "servir"],
                ("-p", "MemoryMax=900M", "-p", "CPUQuota=100%"))
    for _ in range(90):
        if _salud(p["puerto"]):
            _guardar(estado="lista", paso="Lista")
            return
        time.sleep(1)
    raise Fallo("La vista previa no arranca (mira el registro de la unidad " + unidad("vista-previa") + ")")


def abrir(conversacion: str, version: str | None = None) -> None:
    p = abierta()
    if p and p.get("conversacion") != conversacion:
        raise Fallo("Ya hay una personalización abierta: aplícala o descártala antes de empezar otra", "ocupada")
    C.CONSTRUCTOR.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not p or not p.get("token"):  # sin reserva, o con la que acaba de escribir el Host Agent
        p = _guardar(conversacion=conversacion, estado="preparando", paso="Empezando", creada=(p or {}).get("creada") or C.ahora(),
                     base_commit=C.git("rev-parse", "HEAD"), base_version=C.version_actual(),
                     puerto=_puerto_libre(C.puerto() + 10), token=secrets.token_urlsafe(32), version_objetivo=version)
    else:
        _guardar(estado="preparando", error="")
    try:
        if not (C.COPIA / ".git").exists():
            _paso("Copiando el código")
            shutil.rmtree(C.COPIA, ignore_errors=True)
            C.git("clone", "--quiet", "--local", "--no-checkout", str(C.ROOT), str(C.COPIA))
            C.git("checkout", "--quiet", "-b", C.RAMA, p["base_commit"], cwd=C.COPIA)
            for k, v in (("user.name", "Constructor"), ("user.email", "constructor@personal-os.local")):
                C.git("config", k, v, cwd=C.COPIA)
            if version:  # actualización que chocaba: la fusión se deja a medias para que el Constructor la resuelva
                C.git("fetch", "--quiet", str(C.ROOT), f"refs/tags/{version}:refs/tags/{version}", cwd=C.COPIA)
                if not C.git_ok("merge", "--no-ff", "-m", f"{C.PREFIJO_ACTUALIZACION}{version}", version, cwd=C.COPIA):
                    _guardar(conflicto=C.git("diff", "--name-only", "--diff-filter=U", cwd=C.COPIA).splitlines())
            privado = C.ROOT / "control-center/apps/web/src/privado"
            if privado.is_dir() and not (C.COPIA / "control-center/apps/web/src/privado").exists():
                shutil.copytree(privado, C.COPIA / "control-center/apps/web/src/privado")
        _paso("Copiando tus datos (la vista previa nunca toca los reales)")
        _guardar(**{("db_url" if k == "CC_DB_URL" else k): v for k, v in copiar_datos().items()})
        _paso("Instalando dependencias")
        C.ejecutar(["uv", "sync", "--frozen"], cwd=C.COPIA / "control-center/backend", timeout=900)
        web = C.COPIA / "control-center/apps/web"
        if not (web / "node_modules").is_dir():
            C.ejecutar(["npm", "ci", "--no-fund", "--no-audit", "--prefer-offline"], cwd=web, timeout=1800)
        _paso("Compilando la vista previa")
        if not _guardar().get("conflicto"):
            compilar_web_vp()
            env = entorno_vp(abierta())
            C.ejecutar([str(C.COPIA / "control-center/backend/.venv/bin/alembic"), "upgrade", "head"],
                       cwd=C.COPIA / "control-center/backend", env=env, timeout=600)
            _paso("Arrancando la vista previa")
            arrancar()
        else:
            _guardar(estado="lista", paso="Esperando a que el Constructor junte la versión nueva")
    except Exception as e:  # noqa: BLE001
        _guardar(estado="error", paso="No se ha podido preparar", error=str(e)[:800])
        raise


def servir() -> int:
    """El servidor de la vista previa, encerrado. Se duerme si nadie lo usa en DORMIR segundos."""
    p = abierta()
    if not p:
        return 1
    backend = C.COPIA / "control-center/backend"
    cmd = [str(backend / ".venv/bin/uvicorn"), "app.main:app", "--host", "127.0.0.1", "--port", str(p["puerto"]),
           "--reload", "--reload-dir", str(backend / "app"), "--reload-dir", str(C.COPIA / "collectors"), "--no-access-log"]
    argv = jaula(cmd, escritura=[C.DATOS_VP], lectura=[C.COPIA], chdir=backend)
    proc = subprocess.Popen(argv, env=entorno_vp(p))

    def parar(*_):
        proc.terminate()

    signal.signal(signal.SIGTERM, parar)
    while proc.poll() is None:
        time.sleep(30)
        try:
            quieta = time.time() - USO.stat().st_mtime
        except OSError:
            quieta = 0
        turno = any(C.CONSTRUCTOR.glob("turnos/*.en-curso"))
        if quieta > DORMIR and not turno:
            _guardar(estado="dormida", paso="Dormida (se despierta al abrirla)")
            proc.terminate()
            try:
                proc.wait(20)
            except subprocess.TimeoutExpired:
                proc.kill()
            return 0
    return proc.returncode or 0


def _parar(nombre: str) -> None:
    subprocess.run(["systemctl", "--user", "stop", f"{nombre}.service"], capture_output=True, timeout=60)


def cerrar(motivo: str = "descartada") -> None:
    """Para la vista previa, el Constructor y la preparación, y borra la copia y sus datos."""
    p = abierta() or {}
    for n in ("vista-previa", "vp-preparar", "constructor"):
        _parar(unidad(n))
    if p.get("db_url"):
        _pg("dropdb", "-U", "jarvis", "--if-exists", "personal_os_vp")
    for d in (C.COPIA, C.DATOS_VP, C.CONSTRUCTOR / "turnos"):
        shutil.rmtree(d, ignore_errors=True)
    USO.unlink(missing_ok=True)
    if p:
        import json  # noqa: PLC0415
        HISTORIAL.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with HISTORIAL.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"conversacion": p.get("conversacion"), "creada": p.get("creada"), "cerrada": C.ahora(),
                                "motivo": motivo}, ensure_ascii=False) + "\n")
    C.ABIERTA.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="orden", required=True)
    a = sub.add_parser("abrir")
    a.add_argument("conversacion")
    a.add_argument("--version")
    sub.add_parser("servir")
    sub.add_parser("arrancar")
    c = sub.add_parser("cerrar")
    c.add_argument("--motivo", default="descartada")
    args = ap.parse_args(argv)
    try:
        if args.orden == "abrir":
            abrir(args.conversacion, args.version)
        elif args.orden == "servir":
            return servir()
        elif args.orden == "arrancar":
            arrancar()
        else:
            cerrar(args.motivo)
    except Fallo as e:
        print(f"✗ {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
