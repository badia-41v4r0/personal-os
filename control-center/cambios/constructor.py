"""Un turno del Constructor: la CLI de IA trabajando en la copia del código, en el PC del usuario y encerrada.

Lo lanza el Host Agent como unidad transitoria (`<instancia>-cc-constructor`), no como hijo suyo: si el panel o el
Host Agent se reinician a mitad, el turno sigue. La salida (NDJSON con el formato de `claude -p --output-format
stream-json`; los demás motores se traducen con host-agent/proveedores.py) va a data/constructor/turnos/<run>.ndjson,
que el panel lee según crece y retoma donde lo dejó si se reinicia.

Encierro (bubblewrap): el sistema en solo lectura; escribe solo en la copia del código, en los datos de la vista previa
y en su propio home (data/constructor/home: ahí guarda la CLI sus conversaciones para poder seguirlas). La instalación
real (base, vault, secretos, .env) y lo personal del home (~/.ssh, ~/.claude, navegadores…) no existen dentro. Tiene
red: la necesita su CLI para hablar con el modelo.

Uso: constructor.py turno <run_id>     (lee data/constructor/turnos/<run_id>.json, que escribe el Host Agent)
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comun as C  # noqa: E402
import vista_previa as VP  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "host-agent"))  # proveedores.py
TURNOS = C.CONSTRUCTOR / "turnos"
HOME = C.CONSTRUCTOR / "home"
INSTRUCCIONES = C.ROOT / "control-center/cambios/instrucciones.md"
MINUTOS = 45
PROV_DIR = C.DATA / "control-center/proveedores"


def binario(nombre: str) -> str | None:
    """Ruta real de una CLI (mise instala envoltorios que dentro de la jaula no sabrían resolver)."""
    try:
        r = subprocess.run(["mise", "which", nombre], capture_output=True, text=True, timeout=20)
        if r.returncode == 0 and r.stdout.strip():
            return os.path.realpath(r.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    home = Path.home()
    w = shutil.which(nombre, path=C.entorno(secretos=False)["PATH"] + f":{home}/.opencode/bin")
    return os.path.realpath(w) if w else None


def path_jaula() -> str:
    dirs: list[str] = []
    for b in ("node", "npm", "uv", "git", "python3"):
        r = binario(b)
        if r and os.path.dirname(r) not in dirs:
            dirs.append(os.path.dirname(r))
    return ":".join(dirs + ["/usr/local/bin", "/usr/bin", "/bin"])


def preparar_cli(req: dict, sistema: str) -> tuple[list[str], dict]:
    """Orden y entorno de la CLI del motor elegido."""
    prov, modelo, resume = req["proveedor"], req.get("modelo") or "", req.get("resume")
    env = {"HOME": str(HOME), "PATH": path_jaula(), "LANG": "C.UTF-8", "TZ": C.entorno().get("POS_TZ", "Europe/Madrid"),
           "DISABLE_AUTOUPDATER": "1", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "GIT_TERMINAL_PROMPT": "0",
           "npm_config_update_notifier": "false", "NEXT_TELEMETRY_DISABLED": "1",
           # Para que lo que ejecute (alembic, pruebas, la compilación) use la copia de los datos, nunca los reales
           **{k: v for k, v in VP.entorno_vp(VP.abierta() or {"token": ""}).items()
              if k.startswith(("POS_CONFIG", "CC_DATA", "CC_VAULT", "CC_FILES", "CC_SESSIONS", "CC_DB_URL", "CC_JARVIS"))},
           "CC_VISTA_PREVIA": "1", "POS_INSTANCE": C.instancia()}
    if prov == "claude":
        # POS_CONSTRUCTOR_CLI (solo para pruebas, en .env): otra orden con la misma salida que `claude -p`
        falsa = C.config_instancia().get("POS_CONSTRUCTOR_CLI", "")
        exe = falsa or binario("claude")
        token = C.config_instancia().get("CLAUDE_CODE_OAUTH_TOKEN", "")
        if not exe:
            raise C.Fallo("Claude Code no está instalado en este PC")
        if not token and not falsa:
            raise C.Fallo("Claude Code no está conectado: Ajustes → Motor de IA")
        env["CLAUDE_CODE_OAUTH_TOKEN"] = token
        argv = [exe, "-p", "--output-format", "stream-json", "--verbose", "--include-partial-messages",
                "--model", modelo if modelo in ("sonnet", "opus") else "sonnet",
                "--dangerously-skip-permissions", "--append-system-prompt", sistema]
        if resume:
            argv += ["--resume", resume]
        return argv, env
    import proveedores  # noqa: PLC0415
    if prov == "codex":
        exe = binario("codex")
        auth = PROV_DIR / "codex-auth.json"
        if not exe or not auth.exists():
            raise C.Fallo("Codex no está instalado o conectado: Ajustes → Motor de IA")
        d = HOME / ".codex"
        d.mkdir(parents=True, exist_ok=True, mode=0o700)
        cfg = proveedores.codex_config({}, sistema).replace('sandbox_mode = "workspace-write"', 'sandbox_mode = "danger-full-access"')
        (d / "config.toml").write_text(cfg, encoding="utf-8")
        shutil.copy2(auth, d / "auth.json")
        (d / "auth.json").chmod(0o600)
        env["CODEX_HOME"] = str(d)
        argv = proveedores.argv("codex", modelo, resume)
        return [exe, *argv[1:]], env
    if prov == "opencode":
        exe = binario("opencode")
        clave = PROV_DIR / "openrouter.key"
        if not exe or not clave.exists():
            raise C.Fallo("OpenCode no está instalado o falta la clave de OpenRouter: Ajustes → Motor de IA")
        d = HOME / ".config/opencode"
        d.mkdir(parents=True, exist_ok=True, mode=0o700)
        (HOME / "instrucciones.md").write_text(sistema, encoding="utf-8")
        cfg = proveedores.opencode_config({}, "execute", str(HOME / "instrucciones.md"))
        cfg["permission"] = {"bash": "allow", "edit": "allow", "webfetch": "allow"}
        (d / "opencode.json").write_text(json.dumps(cfg, indent=1), encoding="utf-8")
        env["OPENROUTER_API_KEY"] = clave.read_text().strip()
        argv = proveedores.argv("opencode", modelo, resume)
        return [exe, *argv[1:]], env
    raise C.Fallo(f"El Constructor no puede usar {prov}: elige Claude Code, Codex u OpenCode en Ajustes → Motor de IA")


def sistema(req: dict) -> str:
    base = INSTRUCCIONES.read_text(encoding="utf-8") if INSTRUCCIONES.exists() else ""
    p = VP.abierta() or {}
    extra = [f"\n\n## Esta personalización\n- Copia del código: {C.COPIA} (rama {C.RAMA}).",
             f"- Vista previa: {VP.BASE_PATH}/ (puerto interno {p.get('puerto')}).",
             f"- Versión instalada: {p.get('base_version', C.version_actual())}."]
    if p.get("conflicto"):
        extra.append(f"- **Hay una actualización a {p.get('version_objetivo')} a medio juntar** con conflictos en: "
                     + ", ".join(p["conflicto"][:30]) + ". Resuélvelos primero (conserva las personalizaciones del usuario "
                     "y lo nuevo de la versión), haz `git commit` y recompila la vista previa.")
    return base + "\n".join(extra)


def turno(run_id: str) -> int:
    req = json.loads((TURNOS / f"{run_id}.json").read_text(encoding="utf-8"))
    salida = TURNOS / f"{run_id}.ndjson"
    marca = TURNOS / f"{run_id}.en-curso"
    marca.write_text(str(os.getpid()))
    HOME.mkdir(parents=True, exist_ok=True, mode=0o700)
    out = salida.open("a", encoding="utf-8")

    def escribe(ev: dict) -> None:
        out.write(json.dumps(ev, ensure_ascii=False) + "\n")
        out.flush()

    proc = None
    codigo, err = 1, ""
    try:
        if not (C.COPIA / ".git").exists():
            raise C.Fallo("La copia del código aún no está preparada")
        argv, env = preparar_cli(req, sistema(req))
        escritura = [C.COPIA, C.DATOS_VP, HOME]
        for cache in (Path.home() / ".cache/uv", Path.home() / ".npm"):
            if cache.is_dir():
                escritura.append(cache)
        jail = VP.jaula(argv, escritura=escritura, lectura=[], chdir=C.COPIA)
        proc = subprocess.Popen(jail, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, encoding="utf-8", errors="replace", bufsize=1)
        signal.signal(signal.SIGTERM, lambda *_: proc.terminate())
        proc.stdin.write(req["prompt"])
        proc.stdin.close()
        traductor = None
        if req["proveedor"] != "claude":
            import proveedores  # noqa: PLC0415
            traductor = proveedores.Traductor(req["proveedor"])
        fin = time.monotonic() + MINUTOS * 60
        for linea in proc.stdout:
            if time.monotonic() > fin:
                proc.terminate()
                escribe({"type": "_error", "error": f"Tiempo máximo agotado ({MINUTOS} min)"})
                break
            if not linea.strip():
                continue
            if traductor is None:
                out.write(linea if linea.endswith("\n") else linea + "\n")
                out.flush()
            else:
                for ev in traductor.linea(linea):
                    escribe(ev)
        codigo = proc.wait()
        if traductor is not None:
            for ev in traductor.final():
                escribe(ev)
        err = proc.stderr.read()[-1500:] if codigo else ""
    except C.Fallo as e:
        escribe({"type": "_error", "error": str(e)})
    except Exception as e:  # noqa: BLE001
        escribe({"type": "_error", "error": f"{e.__class__.__name__}: {e}"[:500]})
    finally:
        if proc and proc.poll() is None:
            proc.kill()
        if req.get("proveedor") == "codex":  # Codex renueva su token: se guarda el nuevo y no se queda copia
            nuevo = HOME / ".codex/auth.json"
            try:
                if nuevo.exists():
                    json.loads(nuevo.read_text())
                    tmp = PROV_DIR / "codex-auth.json.tmp"
                    tmp.write_text(nuevo.read_text())
                    tmp.chmod(0o600)
                    tmp.replace(PROV_DIR / "codex-auth.json")
            except (OSError, ValueError):
                pass
            finally:
                nuevo.unlink(missing_ok=True)
        escribe({"type": "_exit", "code": codigo, "stderr": err})
        out.close()
        marca.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "turno":
        sys.exit(__doc__)
    sys.exit(turno(sys.argv[2]))
