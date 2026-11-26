"""Host Agent del Jarvis Control Center.

Proceso aparte, como el usuario normal (nunca root), que escucha SOLO en un socket Unix con permisos 600.
Expone una lista cerrada de capacidades: el backend web no tiene acceso al host ni al socket de Docker,
solo a estas operaciones. Cada llamada se audita en un JSONL.

Capacidades de lectura:
  GET /v1/metrics                     CPU, RAM, swap, temperatura, GPU, discos, red, uptime, procesos top
  GET /v1/services                    unidades jarvis-* de systemd (usuario) y docker.service
  GET /v1/containers                  contenedores Docker (docker ps; solo lectura)
  GET /v1/logs/unit/{unit}            journal de una unidad jarvis-* (máx. 500 líneas)
  GET /v1/logs/container/{name}       logs de un contenedor permitido (jarvis, jarvis-vc-*)
  GET /v1/jarvis/status               ¿existe la sesión tmux de Jarvis?

Capacidades de ejecución (M3):
  POST /v1/jarvis/prompt              escribe en la sesión de Jarvis «💻 [panel id=…] texto» (el prefijo lo pone
                                      el agente, no el que llama), con el cerrojo común de bin/jarvis-prompt.sh y la voz
  POST /v1/jarvis/interrupt           pulsa Escape en la sesión (interrumpe el turno en curso)
  POST /v1/sessions/run               un turno de una sesión independiente (claude -p en contenedor efímero; NDJSON en directo)
  POST /v1/sessions/{id}/stop         para el turno en curso de esa sesión
  /v1/vc/*                            ordenadores virtuales: crear, arrancar, parar, reiniciar, eliminar, estado,
                                      ejecutar, archivos, captura; WS /tty (terminal) y /vnc (escritorio)
  GET  /v1/proposals                  propuestas de skills y agentes de Jarvis (bin/aprobar --json)
  POST /v1/proposals/{n}/approve      instala con bin/aprobar --si --hash (solo lo que se vio en el panel)
  POST /v1/proposals/{n}/reject       rechaza con bin/aprobar --rechazar
  POST /v1/claude/usage               uso del límite de Claude (5 h y semanal) con `claude -p /usage`: 0 tokens
  POST /v1/models/{key}/usage         cuota de Antigravity (`antigravity -p /usage`) y Codex (la última de sus sesiones): 0 tokens
  GET  /v1/timers, PUT y POST .../run  horarios de los timers de la lista TIMERS: ver, cambiar días y horas, activar y lanzar
  POST /v1/timers/{name}/enabled      encender o apagar un timer (al activar o desactivar su módulo)
  POST /v1/models/{key}/ask           consulta de solo texto a Codex o Antigravity, encerrada con bwrap: sin datos personales
  POST /v1/voice/transcribe           voz a texto con el Whisper del contenedor; el audio se borra al terminar
  POST /v1/notify/telegram            aviso por Telegram y al panel con bin/telegram-send.sh (máx. 10 por hora; el token no sale de aquí)

Uso: python hostagent.py   (variables CC_HOSTAGENT_SOCKET, CC_HOSTAGENT_TOKEN, CC_DATA_DIR)
"""
import base64
import hmac
import json
import os
import hashlib
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import asyncio

import httpx
import psutil

import proveedores
import sesiones
import vms
import maquinas
import maquinas_admin
import google_auth
import fcntl

from fastapi import Body, Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse
from instancia import INST

ROOT = Path(__file__).resolve().parents[2]
TOKEN = os.environ.get("CC_HOSTAGENT_TOKEN", "")
DATA = Path(os.environ.get("CC_DATA_DIR", str(ROOT / "data/control-center")))
AUDIT = DATA / "hostagent-audit.jsonl"
ENV_FILE = Path(os.environ.get("POS_ENV_FILE", str(ROOT / ".env")))  # credenciales del .env (permisos 600)

UNIT_RE = re.compile(rf"^{re.escape(INST)}-[a-z0-9-]{{1,40}}\.(service|timer|path)$")
# Unidades de fuera de la instancia que el panel también vigila (lista vacía por defecto)
WATCHED_USER_UNITS = [u for u in os.environ.get("POS_WATCHED_UNITS", "").split(",") if u]
CONTAINER_RE = re.compile(rf"^({re.escape(INST)}|{re.escape(INST)}-vc-[a-z0-9-]{{1,40}})$")
SYSTEM_UNITS = ("docker.service", "tailscaled.service")
TIMEOUT = 10

app = FastAPI(title="Personal OS Host Agent", docs_url=None, redoc_url=None, openapi_url=None)


def _audit(request: Request, capability: str, outcome: str, **detail) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    rec = {"ts": datetime.now(timezone.utc).isoformat(), "capability": capability, "outcome": outcome,
           "path": request.url.path, "actor": request.headers.get("x-actor", "")[:80],
           "run": request.headers.get("x-run-id", "")[:64], **detail}
    with AUDIT.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def auth(request: Request) -> None:
    sent = request.headers.get("authorization", "").removeprefix("Bearer ")
    if not TOKEN or not hmac.compare_digest(sent, TOKEN):
        _audit(request, "auth", "denied")
        raise HTTPException(401, "token inválido")


def run(argv: list[str], timeout: int = TIMEOUT) -> str:
    """Ejecuta un comando fijo (sin shell). Lanza HTTPException si falla."""
    if shutil.which(argv[0]) is None:
        raise HTTPException(503, f"{argv[0]} no disponible")
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        raise HTTPException(504, f"{argv[0]}: tiempo agotado")
    if r.returncode not in (0, 3):  # 3 = systemctl con unidades inactivas
        raise HTTPException(502, (r.stderr or r.stdout).strip()[:500])
    return r.stdout


# ---------- caché corta: varios clientes (Dashboard, Monitor, muestreo) comparten la misma lectura ----------

_cache: dict[str, tuple[float, object]] = {}
_cache_lock = threading.Lock()


def cached(key: str, ttl: float, fn):
    with _cache_lock:  # además serializa: nunca dos nvidia-smi o docker ps a la vez
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < ttl:
            return hit[1]
        val = fn()
        _cache[key] = (time.monotonic(), val)
        return val


# ---------- métricas ----------

def gpu() -> list[dict]:
    if shutil.which("nvidia-smi") is None:
        return []
    out = run(["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
               "--format=csv,noheader,nounits"])
    res = []
    for line in out.strip().splitlines():
        name, util, used, total, temp = [x.strip() for x in line.split(",")]
        res.append({"name": name, "util_pct": float(util), "vram_used_mb": float(used),
                    "vram_total_mb": float(total), "temp_c": float(temp)})
    return res


def temperatures() -> dict:
    out = {}
    for chip, sensors in (psutil.sensors_temperatures() or {}).items():
        vals = [s.current for s in sensors if s.current]
        if vals:
            out[chip] = max(vals)
    return out


def metrics() -> dict:
    vm, sw = psutil.virtual_memory(), psutil.swap_memory()
    disks, seen = [], set()
    # Un dispositivo una sola vez (los subvolúmenes de btrfs comparten espacio): gana el punto de montaje más corto
    for p in sorted(psutil.disk_partitions(all=False), key=lambda p: len(p.mountpoint)):
        if p.device in seen or p.fstype in {"squashfs", "overlay"}:
            continue
        try:
            u = psutil.disk_usage(p.mountpoint)
        except (PermissionError, OSError):
            continue
        seen.add(p.device)
        disks.append({"mount": p.mountpoint, "fs": p.fstype, "total": u.total, "used": u.used, "free": u.free,
                      "pct": u.percent})
    net = psutil.net_io_counters()
    procs = []
    for pr in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info", "username"]):
        mi = pr.info.get("memory_info")
        procs.append({"pid": pr.info["pid"], "name": pr.info["name"], "rss": mi.rss if mi else 0,
                      "user": pr.info.get("username")})
    procs.sort(key=lambda x: x["rss"], reverse=True)
    try:
        g = gpu()
    except HTTPException:
        g = []
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "cpu": {"pct": psutil.cpu_percent(interval=0.3), "per_core": psutil.cpu_percent(percpu=True),
                "count": psutil.cpu_count(), "load": os.getloadavg()},
        "memory": {"total": vm.total, "used": vm.total - vm.available, "available": vm.available, "pct": vm.percent},
        "swap": {"total": sw.total, "used": sw.used, "pct": sw.percent},
        "temperatures": temperatures(),
        "gpu": g,
        "disks": disks,
        "net": {"bytes_sent": net.bytes_sent, "bytes_recv": net.bytes_recv},
        "uptime_s": int(time.time() - psutil.boot_time()),
        "top_processes": procs[:10],
    }


# ---------- servicios ----------

PROPS = "Id,Description,LoadState,ActiveState,SubState,UnitFileState,NRestarts,ExecMainStatus,Result," \
        "ActiveEnterTimestamp,NextElapseUSecRealtime,LastTriggerUSec"


def parse_show(out: str) -> list[dict]:
    units, cur = [], {}
    for line in out.splitlines():
        if not line.strip():
            if cur:
                units.append(cur)
                cur = {}
            continue
        k, _, v = line.partition("=")
        cur[k] = v
    if cur:
        units.append(cur)
    return units


def services() -> list[dict]:
    listing = run(["systemctl", "--user", "list-units", "--all", "--plain", "--no-legend", "--no-pager", f"{INST}-*"])
    files = run(["systemctl", "--user", "list-unit-files", "--plain", "--no-legend", "--no-pager", f"{INST}-*"])
    names = sorted({ln.split()[0] for ln in (listing + files).splitlines() if ln.strip()} )
    names = [n for n in names if UNIT_RE.match(n)] + WATCHED_USER_UNITS
    res = []
    if names:
        for u in parse_show(run(["systemctl", "--user", "show", f"--property={PROPS}", *names])):
            u["scope"] = "user"
            res.append(u)
    for u in parse_show(run(["systemctl", "show", f"--property={PROPS}", *SYSTEM_UNITS])):
        u["scope"] = "system"
        res.append(u)
    return res


CONTAINER_FIELDS = ("ID", "Names", "Image", "State", "Status", "RunningFor")


def containers() -> list[dict]:
    # Campos explícitos: "{{json .}}" calcula tamaños y tarda ~15 s
    fmt = "\t".join("{{.%s}}" % k for k in CONTAINER_FIELDS)
    out = run(["docker", "ps", "-a", "--format", fmt])
    return [dict(zip(CONTAINER_FIELDS, line.split("\t"))) for line in out.strip().splitlines()]


# ---------- rutas ----------

@app.get("/v1/health")
def health():
    return {"ok": True}


# ---------- cuotas de los modelos alternativos (Claude va por /v1/claude/usage) ----------

ANTIGRAVITY_GROUPS = {"antigravity-flash": "Gemini Models", "antigravity-opus": "Claude and GPT models"}
ANTIGRAVITY_TTL = 60
CODEX_WINDOWS = {300: "five_hour", 10080: "weekly", 43200: "monthly"}
CODEX_MAX_FILES = 20
# Lock propio: la consulta tarda hasta 90 s y `cached` no puede retenerlo (bloquearía /v1/metrics y el Monitor
# daría por caído al Host Agent).
_antigravity_lock = threading.Lock()
_antigravity_hit: tuple[float, str] | None = None


def _usage_env() -> dict:
    """Entorno de las CLIs: nunca reciben el token del Host Agent ni uno de OAuth heredado."""
    return {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CODE_OAUTH_TOKEN", "CC_HOSTAGENT_TOKEN")}


def _cli(name: str, install: str) -> str | None:
    home = Path.home()
    return shutil.which(name) or shutil.which(name, path=f"{home}/.local/share/mise/installs/{install}:"
                                                         f"{home}/.local/share/mise/shims:{home}/.local/bin")


def _antigravity_usage() -> str:
    exe = _cli("antigravity", "antigravity-cli/latest")
    if not exe:
        return ""
    try:
        with tempfile.TemporaryDirectory(prefix="cc-usage-") as tmp:
            p = subprocess.run([exe, "-p", "/usage", "--output-format", "json", "--mode", "plan"], cwd=tmp, env=_usage_env(),
                               stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=90, check=False)
        return p.stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def antigravity_stdout() -> str:
    """Una sola consulta para Flash y Opus: salen de la misma respuesta."""
    global _antigravity_hit
    with _antigravity_lock:
        if _antigravity_hit and time.monotonic() - _antigravity_hit[0] < ANTIGRAVITY_TTL:
            return _antigravity_hit[1]
        out = _antigravity_usage()
        _antigravity_hit = (time.monotonic(), out)
        return out


def parse_antigravity_windows(stdout: str, key: str) -> list[dict]:
    try:
        d = json.loads(stdout)
        groups = d["command"]["data"]["groups"]
    except (ValueError, KeyError, TypeError):
        return []
    windows = []
    for g in groups:
        if g.get("name") != ANTIGRAVITY_GROUPS[key]:
            continue
        for b in g.get("buckets", []):
            rem = b.get("remaining_fraction")
            if isinstance(rem, (int, float)):
                raw = str(b.get("window") or b.get("id") or "")
                name = "weekly" if "weekly" in raw else "five_hour" if "5h" in raw or "five" in raw else raw
                windows.append({"name": name, "utilization": round(max(0.0, min(1.0, 1.0 - float(rem))), 4),
                                "resets_at": b.get("reset_time")})
    return windows


def codex_latest(sessions: Path) -> tuple[list[dict], float | None]:
    """Última cuota de Codex y cuándo se midió (la sesión puede ser de hace días)."""
    try:
        files = sorted(sessions.rglob("rollout-*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)
    except OSError:
        return [], None
    for f in files[:CODEX_MAX_FILES]:
        windows = codex_windows_in(f)
        if windows:
            return windows, f.stat().st_mtime
    return [], None


def codex_windows(sessions: Path) -> list[dict]:
    return codex_latest(sessions)[0]


def codex_windows_in(f: Path) -> list[dict]:
    """Última cuota real de Codex, la que él mismo anota en sus sesiones (`rate_limits`).

    Codex no tiene consulta no interactiva: `codex exec /status` abre una conversación. Por eso es el dato
    de su última sesión en este PC: lo gastado después en otro sitio no aparece hasta la siguiente.
    """
    try:
        lines = f.read_bytes()[-1_000_000:].decode("utf-8", "ignore").splitlines()
    except OSError:
        return []
    for line in reversed(lines):
        if '"rate_limits"' not in line:
            continue
        try:
            limits = (json.loads(line).get("payload") or {}).get("rate_limits") or {}
        except (ValueError, AttributeError):
            continue
        windows = []
        for slot in ("primary", "secondary"):
            w = limits.get(slot) or {}
            if isinstance(w.get("used_percent"), (int, float)):
                minutes = w.get("window_minutes")
                windows.append({"name": CODEX_WINDOWS.get(minutes, f"{minutes}_min"),
                                "utilization": max(0.0, min(1.0, w["used_percent"] / 100)), "resets_at": w.get("resets_at")})
        if windows:
            return windows
    return []


def _codex_usage() -> dict:
    if not _cli("codex", "codex/latest/bin"):
        return {"available": False, "windows": [], "error": "Codex CLI no instalado"}
    windows, measured = codex_latest(Path.home() / ".codex/sessions")
    return {"available": bool(windows), "windows": windows, "measured_at": measured,
            "error": "" if windows else "Codex aún no ha dejado una lectura de cuota"}


ASK_HIDE = ("Desktop", ".ssh", ".gnupg", ".aws", ".claude", ".docker", ".config/gh", ".config/rclone", ".config/chromium", ".config/google-chrome",
            ".config/google-chrome-beta", ".config/google-chrome-unstable", ".mozilla", ".local/share/keyrings", ".local/share/mise/state")
ASK_TIMEOUT = 170
_ask_lock = threading.Lock()


def jail_argv(home: Path, work: Path, state: Path) -> list[str]:
    """Encierra una CLI en el host: lo personal queda oculto y solo escribe en su estado y en una carpeta temporal."""
    argv = ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp", "--bind", str(work), "/tmp/w"]
    for rel in ASK_HIDE:
        if (home / rel).exists():
            argv += ["--tmpfs", str(home / rel)]
    return argv + ["--bind", str(state), str(state), "--unshare-pid", "--die-with-parent", "--chdir", "/tmp/w"]


def ask_cli(key: str, prompt: str, model: str) -> str:
    home = Path.home()
    with tempfile.TemporaryDirectory(prefix="cc-ask-") as tmp:
        work = Path(tmp)
        if key == "codex-terra":
            exe = _cli("codex", "codex/latest/bin")
            cmd = [exe, "exec", "--sandbox", "read-only", "--skip-git-repo-check", "--color", "never", "-m", model, "-o", "/tmp/w/r.txt", "--", prompt]
            state = home / ".codex"
        else:
            exe = _cli("antigravity", "antigravity-cli/latest")
            cmd = [exe, "-p", prompt, "--mode", "plan", "--output-format", "json", "--model", model]
            state = home / ".gemini"
        if not exe:
            raise HTTPException(503, "CLI no instalada")
        env = {k: v for k, v in _usage_env().items() if not k.startswith("CC_")}
        with _ask_lock:
            r = subprocess.run(jail_argv(home, work, state) + cmd, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=ASK_TIMEOUT)
        if r.returncode != 0:
            raise HTTPException(502, "El proveedor no respondió")
        if key == "codex-terra":
            f = work / "r.txt"
            return f.read_text(encoding="utf-8").strip() if f.exists() else ""
        return str(json.loads(r.stdout).get("response") or "").strip()


@app.post("/v1/models/{key}/ask", dependencies=[Depends(auth)])
def model_ask(key: str, request: Request, prompt: str = Body(..., embed=True), model: str = Body(..., embed=True)):
    if key != "codex-terra" and key not in ANTIGRAVITY_GROUPS:
        _audit(request, "models.ask", "denied", key=key)
        raise HTTPException(403, "proveedor no permitido")
    if len(prompt) > 20_000 or not re.fullmatch(r"[\w.\-]{3,60}", model):
        raise HTTPException(422, "Petición no válida")
    text = ask_cli(key, prompt, model)
    _audit(request, "models.ask", "ok" if text else "empty", key=key, chars=len(prompt))
    return {"text": text}


@app.post("/v1/models/{key}/usage", dependencies=[Depends(auth)])
def model_usage(key: str, request: Request):
    if key == "codex-terra":
        out = _codex_usage()
    elif key in ANTIGRAVITY_GROUPS:
        windows = parse_antigravity_windows(antigravity_stdout(), key)
        out = {"available": bool(windows), "windows": windows, "error": "" if windows else "Antigravity CLI no expuso ventanas de uso"}
    else:
        _audit(request, "models.usage", "denied", key=key)
        raise HTTPException(403, "proveedor no permitido")
    _audit(request, "models.usage", "ok" if out["available"] else "unavailable", key=key)
    return out


@app.get("/v1/metrics", dependencies=[Depends(auth)])
def get_metrics():
    return cached("metrics", 3, metrics)


@app.get("/v1/services", dependencies=[Depends(auth)])
def get_services():
    return cached("services", 10, services)


@app.get("/v1/containers", dependencies=[Depends(auth)])
def get_containers():
    return cached("containers", 5, containers)


@app.get("/v1/logs/unit/{unit}", dependencies=[Depends(auth)])
def unit_logs(unit: str, request: Request, lines: int = 200):
    if not UNIT_RE.match(unit):
        _audit(request, "logs.unit", "denied", unit=unit)
        raise HTTPException(403, "unidad no permitida")
    lines = max(1, min(lines, 500))
    out = run(["journalctl", "--user", "-u", unit, "-n", str(lines), "--no-pager", "-o", "short-iso"])
    _audit(request, "logs.unit", "ok", unit=unit)
    return {"unit": unit, "lines": out.splitlines()}


@app.get("/v1/logs/container/{name}", dependencies=[Depends(auth)])
def container_logs(name: str, request: Request, lines: int = 200):
    if not CONTAINER_RE.match(name):
        _audit(request, "logs.container", "denied", name=name)
        raise HTTPException(403, "contenedor no permitido")
    lines = max(1, min(lines, 500))
    r = subprocess.run(["docker", "logs", "--tail", str(lines), "--timestamps", name],
                       capture_output=True, text=True, timeout=TIMEOUT)
    _audit(request, "logs.container", "ok" if r.returncode == 0 else "error", name=name)
    if r.returncode != 0:
        raise HTTPException(404, "contenedor no encontrado")
    return {"name": name, "lines": (r.stdout + r.stderr).splitlines()}


# ---------- sesión de Jarvis (tmux en el contenedor) ----------

TMUX = ["docker", "exec", INST, "tmux"]
RUN_ID_RE = re.compile(r"^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$")
CTRL_RE = re.compile(r"[\x00-\x1f\x7f\u200b-\u200f\u202a-\u202e\u2066-\u2069]")
MAX_PROMPT = 4000


def prompt_lock_path() -> Path:
    return Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / f"{INST}-prompt.lock"


def clean_prompt(text: str) -> str:
    """Una sola línea, sin caracteres de control ni de dirección (no se pueden pulsar teclas ni ocultar texto)."""
    text = text.replace("\r\n", "\n").replace("\n", " ⏎ ")
    text = CTRL_RE.sub("", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def tmux_alive() -> bool:
    r = subprocess.run(TMUX + ["has-session", "-t", INST], capture_output=True, timeout=TIMEOUT)
    return r.returncode == 0


@app.get("/v1/jarvis/status", dependencies=[Depends(auth)])
def jarvis_status():
    return {"tmux": tmux_alive()}


@app.post("/v1/jarvis/prompt", dependencies=[Depends(auth)])
def jarvis_prompt(request: Request, run_id: str = Body(...), text: str = Body(...), telegram: bool = Body(False)):
    if not RUN_ID_RE.match(run_id):
        _audit(request, "jarvis.prompt", "denied", reason="run_id")
        raise HTTPException(422, "run_id inválido")
    body = clean_prompt(text)
    if not body or len(body) > MAX_PROMPT:
        _audit(request, "jarvis.prompt", "denied", reason="longitud", run_id=run_id)
        raise HTTPException(422, f"El mensaje debe tener entre 1 y {MAX_PROMPT} caracteres")
    if not tmux_alive():
        _audit(request, "jarvis.prompt", "error", reason="sin sesión", run_id=run_id)
        raise HTTPException(503, "La sesión del asistente no está en marcha")
    line = f"💻 [panel id={run_id}{' tg' if telegram else ''}] {body}"
    with prompt_lock_path().open("w") as fl:
        fcntl.flock(fl, fcntl.LOCK_EX)
        run(TMUX + ["send-keys", "-t", INST, "-l", line])
        time.sleep(0.5)
        run(TMUX + ["send-keys", "-t", INST, "C-m"])
    _audit(request, "jarvis.prompt", "ok", run_id=run_id, chars=len(body), telegram=telegram)
    return {"ok": True, "line": line}


@app.post("/v1/jarvis/interrupt", dependencies=[Depends(auth)])
def jarvis_interrupt(request: Request):
    if not tmux_alive():
        raise HTTPException(503, "La sesión del asistente no está en marcha")
    with prompt_lock_path().open("w") as fl:
        fcntl.flock(fl, fcntl.LOCK_EX)
        run(TMUX + ["send-keys", "-t", INST, "Escape"])
    _audit(request, "jarvis.interrupt", "ok")
    return {"ok": True}


# ---------- sesiones independientes ----------

MAX_SESSIONS = 2  # turnos simultáneos (RAM justa)
_running: set[str] = set()


@app.post("/v1/sessions/run", dependencies=[Depends(auth)])
async def session_run(request: Request, body: dict = Body(...)):
    try:
        req = sesiones.validate(body)
    except ValueError as e:
        _audit(request, "sessions.run", "denied", reason=str(e))
        raise HTTPException(422, str(e))
    sid = req["session_id"]
    if sid in _running:
        raise HTTPException(409, "Esa sesión ya está respondiendo")
    if len(_running) >= MAX_SESSIONS:
        raise HTTPException(429, "Hay demasiadas sesiones trabajando a la vez")
    dirs = sesiones.prepare_dirs(ROOT, sid)
    dirs["settings"].write_text(json.dumps(sesiones.managed_settings(req["level"], req["internet"], req["vault"],
                                                                    vc=bool(req["vc"]), subagents=req["subagents"],
                                                                    gym=req["gym"], pos=bool(req.get("pos_token")),
                                                                    vault_write=req["vault_write"],
                                                                    entregables=req["entregables"])))
    extra: asyncio.Queue = asyncio.Queue()  # avisos de la pasarela (p. ej. ordenador creado) para el backend
    gateway = await start_gateway(sid, req["vc"], dirs["gw"], extra) if req["vc"] else None
    pos_gateway = await start_pos_gateway(req["pos_token"], dirs["gw"]) if req.get("pos_token") else None
    prov = req["provider"]
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    egress = None
    if prov == "claude":
        env["CLAUDE_CODE_OAUTH_TOKEN"] = sesiones.read_token(ROOT)
        argv = sesiones.docker_argv(ROOT, req, dirs)
    else:
        try:
            secretos = proveedores_credenciales(prov)
        except ValueError as e:
            if gateway is not None:
                gateway.close()
            if pos_gateway is not None:
                pos_gateway.close()
            raise HTTPException(409, str(e))
        servers = sesiones.mcp_servers(bool(req["vc"]), req["gym"], bool(req.get("pos_token")))
        extra_env = proveedores.preparar_home(prov, dirs["home"], servers, req["level"], req["system_prompt"], secretos)
        env |= extra_env
        egress = start_egress(sid, prov, dirs["egress"])
        argv = sesiones.docker_argv(ROOT, req, dirs, tuple(extra_env))
    _audit(request, "sessions.run", "ok", session=sid, provider=prov, level=req["level"], internet=req["internet"],
           vault=req["vault"], model=req["model"], gym=req["gym"])
    _running.add(sid)
    traductor = None if prov == "claude" else proveedores.Traductor(prov)
    proc = await asyncio.create_subprocess_exec(*argv, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.PIPE, env=env, limit=8 * 1024 * 1024)
    proc.stdin.write(req["prompt"].encode())
    await proc.stdin.drain()
    proc.stdin.close()

    async def stream():
        deadline = time.monotonic() + req["minutes"] * 60
        try:
            while True:
                while not extra.empty():
                    yield json.dumps(extra.get_nowait()) + "\n"
                left = deadline - time.monotonic()
                if left <= 0:
                    subprocess.run(["docker", "kill", sesiones.container_name(sid)], capture_output=True, timeout=TIMEOUT)
                    yield json.dumps({"type": "_error", "error": "Tiempo máximo agotado"}) + "\n"
                    break
                try:
                    line = await asyncio.wait_for(proc.stdout.readline(), timeout=min(left, 30))
                except asyncio.TimeoutError:
                    yield json.dumps({"type": "_ping"}) + "\n"
                    continue
                if not line:
                    break
                if traductor is None:
                    yield line.decode("utf-8", errors="replace")
                else:
                    for ev in traductor.linea(line.decode("utf-8", errors="replace")):
                        yield json.dumps(ev, ensure_ascii=False) + "\n"
            code = await proc.wait()
            if traductor is not None:
                for ev in traductor.final():
                    yield json.dumps(ev, ensure_ascii=False) + "\n"
            while not extra.empty():
                yield json.dumps(extra.get_nowait()) + "\n"
            err = (await proc.stderr.read()).decode("utf-8", errors="replace")[-1000:]
            yield json.dumps({"type": "_exit", "code": code, "stderr": err if code else ""}) + "\n"
        finally:
            if proc.returncode is None:
                proc.kill()
            if gateway is not None:
                gateway.close()
                (dirs["gw"] / "vc.sock").unlink(missing_ok=True)
            if pos_gateway is not None:
                pos_gateway.close()
                (dirs["gw"] / "pos.sock").unlink(missing_ok=True)
            if egress:
                subprocess.run(["docker", "rm", "-f", egress], capture_output=True, timeout=TIMEOUT)
            if prov == "codex":  # la credencial no se queda en el home de la sesión
                guardar_codex_renovada(dirs["home"] / ".codex/auth.json")
            _running.discard(sid)

    return StreamingResponse(stream(), media_type="application/x-ndjson")


# ---------- proveedores de IA (proveedores.py) ----------
# Credenciales: las escribe solo el Host Agent (Ajustes → Motor de IA). El backend nunca las ve.
PROV_DIR = DATA / "proveedores"
EGRESS_SCRIPT = ROOT / "programador/egress.py"


def _prov_file(nombre: str) -> Path:
    return PROV_DIR / nombre


def proveedores_credenciales(prov: str) -> dict:
    if prov == "codex":
        f = _prov_file("codex-auth.json")
        if not f.exists():
            raise ValueError("Codex no está conectado: Ajustes → Motor de IA → Conectar Codex")
        return {"codex_auth": f.read_text()}
    if prov == "opencode":
        f = _prov_file("openrouter.key")
        if not f.exists():
            raise ValueError("Falta la clave de OpenRouter: Ajustes → Motor de IA")
        return {"openrouter_key": f.read_text().strip()}
    return {}


def guardar_codex_renovada(f: Path) -> None:
    """Codex renueva su token durante el turno y el anterior deja de valer: se guarda el nuevo y se borra la copia."""
    try:
        if f.exists():
            nuevo = f.read_text()
            json.loads(nuevo)
            guardado = _prov_file("codex-auth.json")
            if guardado.exists() and nuevo != guardado.read_text():
                tmp = guardado.with_suffix(".tmp")
                tmp.write_text(nuevo)
                tmp.chmod(0o600)
                tmp.replace(guardado)
    except (OSError, ValueError):
        pass
    finally:
        f.unlink(missing_ok=True)


def egress_name(sid: str) -> str:
    return f"{INST}-ses-{sid[:8]}-egress"


def start_egress(sid: str, prov: str, d: Path) -> str:
    """Proxy de salida de la sesión en su propio contenedor, con solo los dominios de la API de su proveedor."""
    name = egress_name(sid)
    subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=TIMEOUT)
    (d / "proxy.sock").unlink(missing_ok=True)
    r = subprocess.run(["docker", "run", "-d", "--rm", "--name", name, "--label", f"{INST}.egress={sid}", "--read-only", "--tmpfs", "/tmp",
                        "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--memory", "128m", "--cpus", "0.5",
                        "--pids-limit", "64", "--network", "bridge", "-e", "EGRESS_ALLOW=" + ",".join(proveedores.DOMINIOS[prov]),
                        "-v", f"{d}:/gw", "-v", f"{EGRESS_SCRIPT}:/opt/egress.py:ro", "--entrypoint", "python3",
                        sesiones.IMAGE, "/opt/egress.py", "/gw/proxy.sock"], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise HTTPException(500, "No se pudo arrancar el proxy de salida")
    for _ in range(50):  # el socket tarda un momento en aparecer
        if (d / "proxy.sock").exists():
            break
        time.sleep(0.1)
    return name


def _prov_estado(prov: str) -> dict:
    cap = proveedores.CAPACIDADES[prov]
    if prov == "claude":
        conectado = bool(_env_leer().get("CLAUDE_CODE_OAUTH_TOKEN"))
    elif prov == "codex":
        conectado = _prov_file("codex-auth.json").exists()
    elif prov == "opencode":
        conectado = _prov_file("openrouter.key").exists()
    else:  # antigravity: la sesión del usuario en el PC (solo modo consulta)
        conectado = shutil.which("antigravity") is not None or Path.home().joinpath(".local/share/mise/installs/antigravity-cli").exists()
    return {"id": prov, "conectado": conectado, **cap}


@app.get("/v1/proveedores", dependencies=[Depends(auth)])
def proveedores_lista():
    return [_prov_estado(p) for p in proveedores.PROVEEDORES]


@app.put("/v1/proveedores/openrouter/clave", dependencies=[Depends(auth)])
def proveedores_clave(request: Request, clave: str = Body(..., embed=True)):
    clave = clave.strip()
    if not re.fullmatch(r"sk-or-[A-Za-z0-9_-]{20,200}", clave):
        _audit(request, "proveedores.clave", "denied", proveedor="openrouter")
        raise HTTPException(422, "Eso no parece una clave de OpenRouter (empieza por sk-or-)")
    PROV_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    f = _prov_file("openrouter.key")
    f.write_text(clave)
    f.chmod(0o600)
    _audit(request, "proveedores.clave", "ok", proveedor="openrouter")  # nunca la clave
    return _prov_estado("opencode")


@app.delete("/v1/proveedores/{prov}", dependencies=[Depends(auth)])
def proveedores_desconectar(request: Request, prov: str):
    archivo = {"opencode": "openrouter.key", "codex": "codex-auth.json"}.get(prov)
    if not archivo:
        raise HTTPException(404, "Ese proveedor no guarda credenciales aquí")
    _prov_file(archivo).unlink(missing_ok=True)
    _audit(request, "proveedores.desconectar", "ok", proveedor=prov)
    return _prov_estado(prov)


@app.post("/v1/proveedores/codex/importar", dependencies=[Depends(auth)])
def proveedores_codex_importar(request: Request):
    """Copia la sesión de Codex del PC (`codex login` hecho por el usuario) a la del Personal OS."""
    origen = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "auth.json"
    if not origen.exists():
        raise HTTPException(404, "No hay sesión de Codex en este PC: ejecuta `codex login` y vuelve a intentarlo")
    try:
        json.loads(origen.read_text())
    except ValueError:
        raise HTTPException(422, "La sesión de Codex del PC no se puede leer")
    PROV_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    f = _prov_file("codex-auth.json")
    f.write_text(origen.read_text())
    f.chmod(0o600)
    _audit(request, "proveedores.codex.importar", "ok")
    return _prov_estado("codex")


# ---------- credenciales del .env que se ponen desde el panel (Ajustes) ----------
# Solo estas claves, con su formato. El valor nunca se devuelve ni se registra: el panel solo ve si está puesto.
ENV_PERMITIDAS = {
    "CLAUDE_CODE_OAUTH_TOKEN": re.compile(r"sk-ant-[A-Za-z0-9_-]{20,300}"),
    "TELEGRAM_BOT_TOKEN": re.compile(r"\d{5,15}:[A-Za-z0-9_-]{30,60}"),
    "TELEGRAM_CHAT_ID": re.compile(r"-?\d{1,20}"),
}
ENV_AYUDA = {
    "CLAUDE_CODE_OAUTH_TOKEN": "Eso no parece un token de Claude: sale de «claude setup-token» y empieza por sk-ant-",
    "TELEGRAM_BOT_TOKEN": "Eso no parece el token de un bot (número:letras, te lo da @BotFather)",
    "TELEGRAM_CHAT_ID": "El chat id es un número (puede empezar por -)",
}


def _env_leer() -> dict[str, str]:
    if not ENV_FILE.exists():
        return {}
    out = {}
    for line in ENV_FILE.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _env_poner(clave: str, valor: str) -> None:
    """Cambia o añade CLAVE=valor sin tocar el resto del .env. Escritura atómica y con permisos 600."""
    lineas = ENV_FILE.read_text().splitlines() if ENV_FILE.exists() else []
    nueva = f"{clave}={valor}"
    for i, line in enumerate(lineas):
        if line.split("=", 1)[0].strip() == clave:
            lineas[i] = nueva
            break
    else:
        lineas.append(nueva)
    tmp = ENV_FILE.with_name(ENV_FILE.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(lineas) + "\n")
    os.chmod(tmp, 0o600)
    tmp.replace(ENV_FILE)


# ---------- clave de Enable Banking (banco, solo lectura): solo el Host Agent escribe en secrets/ ----------

SECRETS = Path(os.environ.get("POS_SECRETS_DIR", str(ROOT / "secrets")))
APP_ID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


@app.put("/v1/banco/clave", dependencies=[Depends(auth)])
def banco_clave(request: Request, app_id: str = Body(...), pem: str = Body(...)):
    """Guarda la clave privada de la aplicación de Enable Banking en secrets/<app_id>.pem (600). Nunca la devuelve."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    app_id = app_id.strip().lower()
    if not APP_ID_RE.fullmatch(app_id) or len(pem) > 20_000:
        _audit(request, "banco.clave", "denied")
        raise HTTPException(422, "El Application ID o el archivo no son válidos")
    try:
        key = serialization.load_pem_private_key(pem.encode(), None)
    except (ValueError, TypeError):
        _audit(request, "banco.clave", "denied", app_id=app_id)
        raise HTTPException(422, "Ese archivo no es una clave privada (.pem) sin contraseña") from None
    if not isinstance(key, rsa.RSAPrivateKey):
        raise HTTPException(422, "Enable Banking usa claves RSA: ese archivo es de otro tipo")
    SECRETS.mkdir(parents=True, exist_ok=True, mode=0o700)
    destino = SECRETS / f"{app_id}.pem"
    tmp = destino.with_name(destino.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(pem.strip() + "\n")
    os.chmod(tmp, 0o600)
    tmp.replace(destino)
    _audit(request, "banco.clave", "ok", app_id=app_id)  # nunca la clave
    return {"app_id": app_id, "guardada": True}


# ---------- máquinas locales (VirtualBox del usuario), administradas desde el panel ----------

def _maq(request: Request, cap: str, fn, *a, **kw):
    """Ejecuta una operación de maquinas_admin con auditoría; errores de uso → 422, máquina desconocida → 404."""
    try:
        out = fn(*a, **kw)
    except KeyError as e:
        _audit(request, cap, "error")
        raise HTTPException(404, str(e).strip("'\"")) from None
    except (ValueError, subprocess.TimeoutExpired) as e:
        _audit(request, cap, "error", reason=str(e)[:200])
        raise HTTPException(422, str(e) if isinstance(e, ValueError) else "VirtualBox tardó demasiado") from None
    _audit(request, cap, "ok", **{k: v for k, v in kw.items() if k in ("mid", "vbox", "que")})
    return out


@app.get("/v1/maquinas", dependencies=[Depends(auth)])
def maquinas_estado():
    return maquinas_admin.estado(DATA, SECRETS)


@app.post("/v1/maquinas", dependencies=[Depends(auth)])
def maquinas_preparar(request: Request, vbox: str = Body(...), nombre: str = Body(""), instantanea: bool = Body(True)):
    return _maq(request, "maquinas.preparar", lambda **k: maquinas_admin.preparar(DATA, SECRETS, k["vbox"], nombre, instantanea), vbox=vbox)


@app.post("/v1/maquinas/{mid}/probar", dependencies=[Depends(auth)])
def maquinas_probar(request: Request, mid: str, usuario: str = Body("", embed=True)):
    return _maq(request, "maquinas.probar", lambda **k: maquinas_admin.probar(DATA, SECRETS, k["mid"], usuario), mid=mid)


@app.patch("/v1/maquinas/{mid}", dependencies=[Depends(auth)])
def maquinas_actualizar(request: Request, mid: str, nombre: str | None = Body(None), agentes: list[str] | None = Body(None),
                        notas: str | None = Body(None)):
    return _maq(request, "maquinas.actualizar", lambda **k: maquinas_admin.actualizar(DATA, k["mid"], nombre, agentes, notas), mid=mid)


@app.delete("/v1/maquinas/{mid}", dependencies=[Depends(auth)])
def maquinas_quitar(request: Request, mid: str):
    return _maq(request, "maquinas.quitar", lambda **k: maquinas_admin.quitar(DATA, SECRETS, k["mid"]), mid=mid)


@app.post("/v1/maquinas/{mid}/accion", dependencies=[Depends(auth)])
def maquinas_accion(request: Request, mid: str, que: str = Body(..., embed=True)):
    return _maq(request, "maquinas.accion", lambda **k: maquinas_admin.accion(DATA, k["mid"], k["que"]), mid=mid, que=que)


@app.get("/v1/maquinas/{mid}/captura", dependencies=[Depends(auth)])
def maquinas_captura(request: Request, mid: str):
    try:
        out = maquinas_admin.captura(DATA, mid)
    except (KeyError, ValueError):
        raise HTTPException(404, "Esa máquina no está conectada") from None
    if "error" in out:
        raise HTTPException(409, out["error"])
    return out


@app.get("/v1/credenciales", dependencies=[Depends(auth)])
def credenciales_estado():
    """Qué credenciales del .env están puestas (nunca su valor)."""
    env = _env_leer()
    return {k: bool(env.get(k)) for k in ENV_PERMITIDAS}


@app.put("/v1/credenciales/{clave}", dependencies=[Depends(auth)])
def credenciales_poner(request: Request, clave: str, valor: str = Body(..., embed=True)):
    if clave not in ENV_PERMITIDAS:
        _audit(request, "credenciales.poner", "denied", clave=clave[:40])
        raise HTTPException(404, "Esa credencial no se puede cambiar desde el panel")
    valor = valor.strip()
    if not ENV_PERMITIDAS[clave].fullmatch(valor):
        _audit(request, "credenciales.poner", "denied", clave=clave)
        raise HTTPException(422, ENV_AYUDA[clave])
    _env_poner(clave, valor)
    _audit(request, "credenciales.poner", "ok", clave=clave)  # nunca el valor
    return credenciales_estado()


@app.delete("/v1/credenciales/{clave}", dependencies=[Depends(auth)])
def credenciales_quitar(request: Request, clave: str):
    if clave not in ENV_PERMITIDAS:
        raise HTTPException(404, "Esa credencial no se puede cambiar desde el panel")
    if clave in _env_leer():
        _env_poner(clave, "")
    _audit(request, "credenciales.quitar", "ok", clave=clave)
    return credenciales_estado()


# ---------- pasarela agente ↔ su ordenador virtual ----------

async def start_gateway(sid: str, cfg: dict, gw_dir: Path, extra: asyncio.Queue):
    """Socket Unix por turno, montado solo en el contenedor de esa sesión. Solo puede tocar el ordenador de la
    sesión (uno como máximo), creado con límites fijos, sin internet y con caducidad (la aplica el backend)."""
    state = {"vc_id": cfg.get("vc_id")}
    owner = f"agent:{cfg.get('owner') or 'sesion'}"
    loop = asyncio.get_running_loop()
    fixed = cfg["profile"] in vms.FIXED_PROFILES  # ordenador asignado (p. ej. Canvas): no se crea ni se destruye
    if fixed and state["vc_id"]:
        lbl = vms.docker("inspect", "-f", f'{{{{index .Config.Labels "{INST}.vc.owner"}}}}|{{{{index .Config.Labels "{INST}.vc.profile"}}}}',
                         vms.name(state["vc_id"])).stdout.decode().strip()
        if lbl not in (f"{cfg.get('owner')}|{cfg['profile']}", f"{owner}|{cfg['profile']}"):
            state["vc_id"] = None  # no es de este agente: no se toca

    def audit(op, outcome="ok", **kw):
        with AUDIT.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(), "capability": f"gateway.{op}",
                                "outcome": outcome, "session": sid, "vc": state["vc_id"], **kw}) + "\n")

    def exists() -> bool:
        return bool(state["vc_id"]) and vms.docker("inspect", vms.name(state["vc_id"])).returncode == 0

    def running() -> bool:
        st = vms.docker("inspect", "-f", "{{.State.Status}}", vms.name(state["vc_id"])).stdout.decode().strip()
        return st == "running"

    def ensure_running() -> None:
        """El ordenador asignado puede estar parado: se arranca (primero su proxy)."""
        if fixed and not running():
            vms.docker("start", vms.egress_name(state["vc_id"]), timeout=40)
            vms.docker("start", vms.name(state["vc_id"]), timeout=40)
            time.sleep(3)
            audit("autostart")

    aplicaciones = cfg["profile"] == "aplicaciones"
    red = "solo los dominios de esta solicitud" if aplicaciones else "solo los dominios de su campus" if fixed else False

    def after_action() -> dict:
        time.sleep(0.7)
        r = vms.docker("exec", "-u", "vc", "-e", "DISPLAY=:1", vms.name(state["vc_id"]), "sh", "-c",
                       "scrot -o /tmp/.shot.png && cat /tmp/.shot.png", timeout=20)
        import base64 as _b64
        return {"png_base64": _b64.b64encode(r.stdout).decode()} if r.returncode == 0 else {"ok": True}

    def form(op: str, arg: dict | None = None) -> dict:
        try:
            cmd = vms.form_cmd(op, arg)
        except ValueError as e:
            return {"error": str(e)}
        try:
            r = vms.docker("exec", "-u", "vc", vms.name(state["vc_id"]), *cmd, timeout=90)
        except subprocess.TimeoutExpired:
            return {"error": "El navegador no respondió a tiempo"}
        if r.returncode != 0:
            return {"error": "El navegador no responde", "detalle": r.stderr.decode("utf-8", "replace")[-300:]}
        try:
            return json.loads(r.stdout.decode("utf-8", "replace"))
        except ValueError:
            return {"error": "Respuesta del navegador no válida"}

    def do(op: str, a: dict) -> dict:
        if aplicaciones and op not in vms.APLICACIONES_OPS:
            audit(op, "denied")
            return {"error": "En una solicitud solo puedes leer la página y rellenar campos con form_fill y form_attach. "
                             "No hay terminal, ni ratón, ni teclado, y el envío lo hace el usuario al aprobar."}
        if op.startswith("vm_"):  # máquinas locales del usuario (VirtualBox) asignadas a este agente
            mias = maquinas.de_agente(maquinas.cargar(DATA, SECRETS), cfg.get("owner"))
            return maquinas.op(mias, op[3:], a, ROOT, lambda o, outcome="ok", **kw: audit(o, outcome, **kw))
        if op == "info":
            if not exists():
                if aplicaciones:
                    return {"vc": None, "nota": "El ordenador de esta solicitud ya no existe: aborta con candidatura.abortar."}
                if fixed:
                    return {"vc": None, "nota": "Tu ordenador de Canvas no existe: pide al usuario que lo cree en el panel."}
                return {"vc": None, "nota": "No tienes ordenador. Usa vc_request si lo necesitas."}
            st = vms.docker("inspect", "-f", "{{.State.Status}}", vms.name(state["vc_id"])).stdout.decode().strip()
            out = {"vc_id": state["vc_id"], "estado": st, "perfil": cfg["profile"], "internet": red,
                   "home": vms.HOME, "trabajo": f"{vms.HOME}/trabajo"}
            return out
        if fixed:
            if not exists():
                return {"error": "Tu ordenador de Canvas no existe: pide al usuario que lo cree en el panel."}
            if op == "destroy":
                audit("destroy", "denied")
                return {"error": "Este ordenador es fijo (guarda la sesión del campus): no se puede destruir."}
            ensure_running()
        if op == "request":
            if exists():
                return {"vc_id": state["vc_id"], "nota": "Ya tienes un ordenador; reutilízalo."}
            import uuid as _uuid
            vid = str(_uuid.uuid4())
            req = vms.validate({"id": vid, "profile": cfg["profile"], "internet": False, "cpus": 1,
                                "memory_mb": 1024 if cfg["profile"] == "terminal" else 1536, "disk_mb": 2048,
                                "owner": owner, "session": sid})
            r = vms.docker(*vms.run_argv(req)[1:], timeout=60)
            if r.returncode != 0:
                audit("request", "error")
                return {"error": "No se pudo crear el ordenador (límite alcanzado o falta la imagen)."}
            state["vc_id"] = vid
            audit("request", motivo=str(a.get("motivo", ""))[:200])
            loop.call_soon_threadsafe(extra.put_nowait, {"type": "_vc", "vc_id": vid, "profile": cfg["profile"],
                                                         "motivo": str(a.get("motivo", ""))[:200]})
            return {"vc_id": vid, "perfil": cfg["profile"], "internet": False, "caduca": "2 h",
                    "instrucciones": "Usa vc_exec para comandos (bash, usuario vc, carpeta ~/trabajo), vc_read_file y "
                                     "vc_write_file para archivos, vc_screenshot si tiene pantalla y vc_destroy al terminar."}
        if not exists():
            return {"error": "No tienes ordenador: pide uno con vc_request."}
        n = vms.name(state["vc_id"])
        if op == "exec":
            cmd = str(a.get("command", ""))
            if not cmd.strip() or len(cmd) > 20_000:
                return {"error": "Comando vacío o demasiado largo"}
            t = max(1, min(int(a.get("timeout", 60)), 600))
            try:
                r = vms.docker("exec", "-u", "vc", "-w", f"{vms.HOME}/trabajo", "-e", "DISPLAY=:1", n, "bash", "-lc", cmd, timeout=t + 5)
                out = {"codigo": r.returncode, "salida": r.stdout.decode("utf-8", "replace")[-vms.MAX_OUTPUT:],
                       "errores": r.stderr.decode("utf-8", "replace")[-20_000:]}
            except subprocess.TimeoutExpired:
                out = {"codigo": 124, "salida": "", "errores": "Tiempo agotado"}
            audit("exec", chars=len(cmd), code=out["codigo"])
            return out
        if op in ("read_file", "write_file"):
            try:
                path = vms.safe_path(str(a.get("path", "")))
            except ValueError as e:
                return {"error": str(e)}
            if op == "read_file":
                r = vms.docker("exec", "-u", "vc", n, "head", "-c", "200000", path)
                audit("read_file", path=path)
                return {"path": path, "contenido": r.stdout.decode("utf-8", "replace")} if r.returncode == 0 else {"error": "No se pudo leer"}
            data = str(a.get("content", "")).encode()
            if len(data) > 5 * 1024 * 1024:
                return {"error": "Máximo 5 MB"}
            r = vms.docker("exec", "-i", "-u", "vc", n, "sh", "-c", 'mkdir -p "$(dirname "$1")" && cat > "$1"', "sh", path, input=data, timeout=60)
            audit("write_file", path=path, bytes=len(data))
            return {"ok": r.returncode == 0, "path": path}
        if op == "screenshot":
            r = vms.docker("exec", "-u", "vc", "-e", "DISPLAY=:1", n, "sh", "-c", "scrot -o /tmp/.shot.png && cat /tmp/.shot.png", timeout=20)
            import base64 as _b64
            audit("screenshot")
            return {"png_base64": _b64.b64encode(r.stdout).decode()} if r.returncode == 0 else {"error": "Sin pantalla (perfil terminal)"}
        if op in ("click", "type", "key", "scroll"):
            try:
                if op == "click":
                    cmd = vms.click_cmd(int(a.get("x", -1)), int(a.get("y", -1)), str(a.get("button", "left")), bool(a.get("double")))
                elif op == "type":
                    cmd = vms.type_cmd(str(a.get("text", "")))
                elif op == "key":
                    cmd = vms.key_cmd(str(a.get("keys", "")))
                else:
                    cmd = vms.scroll_cmd(int(a.get("x", 640)), int(a.get("y", 400)), str(a.get("direction", "down")), int(a.get("amount", 3)))
            except (TypeError, ValueError) as e:
                return {"error": str(e)}
            r = vms.docker("exec", "-u", "vc", "-e", "DISPLAY=:1", n, *cmd, timeout=60)
            audit(op, code=r.returncode)
            if r.returncode != 0:
                return {"error": "Sin pantalla (perfil terminal) o acción fallida"}
            return after_action()
        if op == "form_fields":
            r = form("fields")
            audit(op, campos=len(r.get("campos") or []))
            return r
        if op == "form_fill":
            valores = a.get("valores")
            if not isinstance(valores, dict) or not valores or len(valores) > 80 or \
                    not all(isinstance(k, str) and isinstance(v, (str, bool, int, float)) for k, v in valores.items()):
                return {"error": "valores debe ser un objeto {referencia: valor} (como mucho 80)"}
            r = form("fill", {"valores": valores})
            audit(op, campos=len(valores))
            return r
        if op == "form_attach":
            sha = str(a.get("documento", ""))
            if sha not in (cfg.get("docs") or []):
                audit(op, "denied", documento=sha[:16])
                return {"error": "Ese documento no es el de esta solicitud"}
            f = next((x for x in sorted((ROOT / "archivos/Carrera").glob("*")) if x.is_file() and not x.is_symlink()
                      and hashlib.sha256(x.read_bytes()).hexdigest() == sha), None)
            if f is None:
                return {"error": "No encuentro ese documento en archivos/Carrera"}
            destino = f"{vms.HOME}/descargas/{re.sub(r'[^A-Za-z0-9._ -]', '_', f.name)[:120]}"
            c = vms.docker("exec", "-i", "-u", "vc", vms.name(state["vc_id"]), "sh", "-c", 'cat > "$1"', "sh", destino,
                           input=f.read_bytes(), timeout=60)
            if c.returncode != 0:
                return {"error": "No se pudo copiar el documento"}
            r = form("attach", {"ref": str(a.get("ref", "")), "ruta": destino})
            audit(op, documento=sha[:16])
            return r
        if op in ("open_url", "page_text"):
            try:
                cmd = vms.browser_cmd("open" if op == "open_url" else "text", str(a.get("url", "")))
            except ValueError as e:
                return {"error": str(e)}
            try:
                r = vms.docker("exec", "-u", "vc", n, *cmd, timeout=90)
            except subprocess.TimeoutExpired:
                return {"error": "El navegador no respondió a tiempo"}
            audit(op, url=str(a.get("url", ""))[:200], code=r.returncode)
            if r.returncode != 0:
                return {"error": "No hay navegador en este ordenador o no responde",
                        "detalle": r.stderr.decode("utf-8", "replace")[-300:]}
            try:
                return json.loads(r.stdout.decode("utf-8", "replace"))
            except ValueError:
                return {"error": "Respuesta del navegador no válida"}
        if op == "destroy":
            vms.docker("rm", "-f", n, timeout=30)
            vms.docker("volume", "rm", "-f", vms.volume(state["vc_id"]), timeout=30)
            audit("destroy")
            loop.call_soon_threadsafe(extra.put_nowait, {"type": "_vc_destroyed", "vc_id": state["vc_id"]})
            state["vc_id"] = None
            return {"ok": True}
        return {"error": "Operación no permitida"}

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            line = await reader.readline()
            msg = json.loads(line or b"{}")
            res = await loop.run_in_executor(None, do, str(msg.get("op", "")), msg.get("args") or {})
        except Exception as e:  # noqa: BLE001
            res = {"error": f"{e.__class__.__name__}"}
        writer.write((json.dumps(res, ensure_ascii=False) + "\n").encode())
        await writer.drain()
        writer.close()

    path = gw_dir / "vc.sock"
    path.unlink(missing_ok=True)
    old = os.umask(0o177)
    try:
        server = await asyncio.start_unix_server(handle, path=str(path), limit=8 * 1024 * 1024)
    finally:
        os.umask(old)
    return server


async def start_pos_gateway(token: str, gw_dir: Path):
    """Socket del MCP pos, abierto solo durante el turno. La credencial la pone aquí: el agente nunca la ve."""
    url = os.environ.get("CC_BACKEND_URL", "http://127.0.0.1:8770") + "/api/v1/internal/pos"

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            line = await reader.readline()
            msg = json.loads(line or b"{}")
            headers = {"X-Run-Token": token}
            async with httpx.AsyncClient(timeout=120) as c:
                r = await (c.get(url + "/tools", headers=headers) if msg.get("kind") == "tools" else c.post(url + "/call", json=msg, headers=headers))
            out = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"error": "respuesta no válida"}
        except (ValueError, httpx.HTTPError) as e:
            out = {"error": f"Personal OS no disponible: {type(e).__name__}"}
        writer.write(json.dumps(out, ensure_ascii=False).encode() + b"\n")
        await writer.drain()
        writer.close()

    path = gw_dir / "pos.sock"
    path.unlink(missing_ok=True)
    old = os.umask(0o177)
    try:
        return await asyncio.start_unix_server(handle, path=str(path), limit=8 * 1024 * 1024)
    finally:
        os.umask(old)


@app.post("/v1/sessions/{sid}/stop", dependencies=[Depends(auth)])
def session_stop(sid: str, request: Request):
    if not sesiones.SESSION_RE.match(sid):
        raise HTTPException(422, "id inválido")
    r = subprocess.run(["docker", "kill", sesiones.container_name(sid)], capture_output=True, text=True, timeout=TIMEOUT)
    _audit(request, "sessions.stop", "ok" if r.returncode == 0 else "error", session=sid)
    return {"stopped": r.returncode == 0}


# ---------- ordenadores virtuales ----------

def _vc(vid: str) -> str:
    if not vms.VC_RE.match(vid):
        raise HTTPException(422, "id inválido")
    return vms.name(vid)


def _check(r: subprocess.CompletedProcess, what: str) -> None:
    if r.returncode != 0:
        raise HTTPException(502 if r.returncode != 1 else 404, f"{what}: {(r.stderr or b'').decode(errors='replace').strip()[:300]}")


@app.post("/v1/vc/create", dependencies=[Depends(auth)])
def vc_create(request: Request, body: dict = Body(...)):
    try:
        req = vms.validate(body)
    except ValueError as e:
        _audit(request, "vc.create", "denied", reason=str(e))
        raise HTTPException(422, str(e))
    if vms.docker("image", "inspect", vms.PROFILES[req["profile"]]).returncode != 0:
        raise HTTPException(503, "Falta la imagen: construye control-center/virtual-computers/images")
    if req["profile"] in vms.EGRESS_PROFILES:
        if vms.docker("image", "inspect", vms.EGRESS_IMAGE).returncode != 0:
            raise HTTPException(503, "Falta la imagen del proxy: construye control-center/virtual-computers/egress")
        e = vms.egress_create(req["id"], req["egress_allow"] or None)
        if e.returncode != 0:
            vms.egress_remove(req["id"])
            _audit(request, "vc.create", "error", vc=req["id"], profile=req["profile"], reason="proxy")
            _check(e, "No se pudo crear el proxy")
    r = vms.docker(*vms.run_argv(req)[1:], timeout=60)
    if r.returncode != 0 and req["profile"] in vms.EGRESS_PROFILES:
        vms.egress_remove(req["id"])
    _audit(request, "vc.create", "ok" if r.returncode == 0 else "error", vc=req["id"], profile=req["profile"],
           internet=req["internet"], owner=req["owner"])
    _check(r, "No se pudo crear")
    return {"ok": True, "container": vms.name(req["id"])}


@app.put("/v1/vc/{vid}/dominios", dependencies=[Depends(auth)])
def vc_dominios(request: Request, vid: str, dominios: list[str] = Body(..., embed=True)):
    """Dominios del proxy de un ordenador con salida filtrada (el campus cuando el usuario cambia de plataforma)."""
    if not vms.VC_RE.match(vid):
        raise HTTPException(422, "id inválido")
    allow = [str(d).lower().strip(".") for d in dominios]
    if not allow or len(allow) > vms.MAX_DOMINIOS or not all(vms.DOMINIO_RE.match(d) for d in allow):
        raise HTTPException(422, "Dominios no válidos (como mucho 40)")
    if vms.docker("inspect", vms.egress_name(vid)).returncode != 0:
        raise HTTPException(404, "Ese ordenador no tiene proxy de salida")
    r = vms.egress_allow(vid, allow)
    _audit(request, "vc.dominios", "ok" if r.returncode == 0 else "error", vc=vid, dominios=allow)
    _check(r, "No se pudieron cambiar los dominios")
    return {"ok": True, "dominios": sorted(set(allow))}


@app.post("/v1/vc/{vid}/lifecycle/{action}", dependencies=[Depends(auth)])
def vc_action(vid: str, action: str, request: Request):
    n = _vc(vid)
    if action not in ("start", "stop", "restart", "remove"):
        raise HTTPException(404, "Acción desconocida")
    egress = vms.egress_exists(vid)
    if action == "remove":
        r = vms.docker("rm", "-f", n, timeout=30)
        v = vms.docker("volume", "rm", "-f", vms.volume(vid), timeout=30)  # borrado seguro: el volumen también
        if egress:
            vms.egress_remove(vid)
        _audit(request, "vc.remove", "ok" if v.returncode == 0 else "error", vc=vid)
        return {"ok": True}
    if egress and action in ("start", "restart"):  # el proxy siempre antes que el ordenador
        vms.docker(action, *(["-t", "5"] if action != "start" else []), vms.egress_name(vid), timeout=40)
    r = vms.docker(action, *(["-t", "5"] if action != "start" else []), n, timeout=40)
    if egress and action == "stop":
        vms.docker("stop", "-t", "5", vms.egress_name(vid), timeout=40)
    _audit(request, f"vc.{action}", "ok" if r.returncode == 0 else "error", vc=vid)
    _check(r, action)
    return {"ok": True}


@app.get("/v1/vc/{vid}/egress", dependencies=[Depends(auth)])
def vc_egress_log(vid: str, lines: int = 200):
    _vc(vid)
    if not vms.egress_exists(vid):
        raise HTTPException(404, "Este ordenador no tiene proxy")
    return vms.egress_log(vid, lines)


@app.get("/v1/vc", dependencies=[Depends(auth)])
def vc_list():
    fmt = "\t".join(["{{.Label \"%s\"}}" % f"{INST}.vc", "{{.Names}}", "{{.State}}", "{{.Status}}"]
                    + ["{{.Label \"%s\"}}" % f"{INST}.vc.{k}" for k in ("profile", "disk_mb", "session", "owner")])
    r = vms.docker("ps", "-a", "--filter", f"label={INST}.vc", "--format", fmt)
    _check(r, "docker ps")
    keys = ("id", "container", "state", "status", "profile", "disk_mb", "session", "owner")
    rows = [dict(zip(keys, ln.split("\t"))) for ln in r.stdout.decode().splitlines() if ln.strip()]
    running = [x["container"] for x in rows if x["state"] == "running"]
    if running:
        st = vms.docker("stats", "--no-stream", "--format", "{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.PIDs}}", *running, timeout=20)
        stats = {}
        for ln in st.stdout.decode().splitlines():
            nm, cpu, mem, memp, pids = ln.split("\t")
            stats[nm] = {"cpu_pct": float(cpu.rstrip("%") or 0), "mem": mem, "mem_pct": float(memp.rstrip("%") or 0), "pids": int(pids or 0)}
        for x in rows:
            x["stats"] = stats.get(x["container"])
    return rows


@app.get("/v1/vc/{vid}/disk", dependencies=[Depends(auth)])
def vc_disk(vid: str):
    r = vms.docker("exec", _vc(vid), "du", "-sb", vms.HOME, timeout=30)
    _check(r, "du")
    return {"bytes": int(r.stdout.decode().split()[0])}


@app.post("/v1/vc/{vid}/exec", dependencies=[Depends(auth)])
def vc_exec(vid: str, request: Request, command: str = Body(..., embed=True), timeout: int = Body(60, embed=True)):
    n = _vc(vid)
    if not command.strip() or len(command) > 20_000:
        raise HTTPException(422, "Comando vacío o demasiado largo")
    t = max(1, min(int(timeout), 600))
    try:
        r = vms.docker("exec", "-u", "vc", "-w", f"{vms.HOME}/trabajo", "-e", "DISPLAY=:1", n, "bash", "-lc", command, timeout=t + 5)
        code, out, err = r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        code, out, err = 124, b"", b"Tiempo agotado"
    _audit(request, "vc.exec", "ok", vc=vid, command=command[:2000], code=code)
    return {"code": code, "stdout": out.decode("utf-8", "replace")[-vms.MAX_OUTPUT:],
            "stderr": err.decode("utf-8", "replace")[-vms.MAX_OUTPUT // 4:]}


@app.get("/v1/vc/{vid}/files", dependencies=[Depends(auth)])
def vc_files(vid: str, path: str = vms.HOME + "/trabajo"):
    n = _vc(vid)
    try:
        p = vms.safe_path(path)
    except ValueError as e:
        raise HTTPException(403, str(e))
    r = vms.docker("exec", "-u", "vc", n, "find", p, "-mindepth", "1", "-maxdepth", "1", "-printf", "%y\t%s\t%T@\t%f\n")
    _check(r, "No se pudo listar")
    return {"path": p, "items": vms.listing(r.stdout.decode("utf-8", "replace"))}


@app.get("/v1/vc/{vid}/file", dependencies=[Depends(auth)])
def vc_file(vid: str, path: str, request: Request):
    n = _vc(vid)
    try:
        p = vms.safe_path(path)
    except ValueError as e:
        raise HTTPException(403, str(e))
    st = vms.docker("exec", "-u", "vc", n, "stat", "-L", "-c", "%F\t%s", p)
    _check(st, "No existe")
    kind, size = st.stdout.decode().strip().split("\t")
    if kind != "regular file" or int(size) > vms.MAX_FILE:
        raise HTTPException(413, "Solo archivos normales de hasta 50 MB")
    r = vms.docker("exec", "-u", "vc", n, "cat", p, timeout=60)
    _check(r, "No se pudo leer")
    _audit(request, "vc.download", "ok", vc=vid, path=p, bytes=len(r.stdout))
    import base64
    return {"path": p, "size": len(r.stdout), "base64": base64.b64encode(r.stdout).decode()}


@app.post("/v1/vc/{vid}/file", dependencies=[Depends(auth)])
def vc_write(vid: str, request: Request, path: str = Body(..., embed=True), content: str = Body(..., embed=True)):
    n = _vc(vid)
    try:
        p = vms.safe_path(path)
    except ValueError as e:
        raise HTTPException(403, str(e))
    data = content.encode()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(413, "Máximo 5 MB")
    r = vms.docker("exec", "-i", "-u", "vc", n, "sh", "-c", 'mkdir -p "$(dirname "$1")" && cat > "$1"', "sh", p, input=data, timeout=60)
    _audit(request, "vc.write", "ok" if r.returncode == 0 else "error", vc=vid, path=p, bytes=len(data))
    _check(r, "No se pudo escribir")
    return {"ok": True, "path": p}


@app.post("/v1/vc/{vid}/form/{op}", dependencies=[Depends(auth)])
def vc_form(vid: str, op: str, request: Request, body: dict = Body(default={})):
    """Solo el backend: leer el formulario y, tras la aprobación del usuario, pulsar el botón de enviar si el
    formulario sigue exactamente como se aprobó (si no, no se pulsa nada)."""
    n = _vc(vid)
    if op not in ("fields", "submit"):
        raise HTTPException(404, "Operación desconocida")
    if op == "submit" and (not isinstance(body.get("esperado"), dict) or not str(body.get("boton", "")).startswith("b")):
        raise HTTPException(422, "Falta lo aprobado (campos y botón)")
    lbl = vms.docker("inspect", "-f", f'{{{{index .Config.Labels "{INST}.vc.profile"}}}}', n).stdout.decode().strip()
    if lbl != "aplicaciones":
        raise HTTPException(409, "Solo para ordenadores de solicitudes")
    try:
        r = vms.docker("exec", "-u", "vc", n, *vms.form_cmd(op, body if op == "submit" else None), timeout=120)
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "El navegador no respondió a tiempo")
    try:
        out = json.loads(r.stdout.decode("utf-8", "replace"))
    except ValueError:
        raise HTTPException(502, "Respuesta del navegador no válida")
    _audit(request, f"vc.form.{op}", "ok" if out.get("enviado", True) else "denied", vc=vid)
    return out


@app.get("/v1/vc/{vid}/screenshot", dependencies=[Depends(auth)])
def vc_screenshot(vid: str):
    n = _vc(vid)
    r = vms.docker("exec", "-u", "vc", "-e", "DISPLAY=:1", n, "sh", "-c", "scrot -o /tmp/.shot.png && cat /tmp/.shot.png", timeout=20)
    if r.returncode != 0:
        raise HTTPException(409, "Este ordenador no tiene pantalla (perfil terminal) o no está en marcha")
    import base64
    return {"png_base64": base64.b64encode(r.stdout).decode()}


def _ws_auth(ws: WebSocket) -> bool:
    sent = ws.headers.get("authorization", "").removeprefix("Bearer ")
    return bool(TOKEN) and hmac.compare_digest(sent, TOKEN)


@app.websocket("/v1/vc/{vid}/tty")
async def vc_tty(ws: WebSocket, vid: str):
    """Terminal interactiva: pty local + `docker exec -it` como usuario vc. Texto ↔ bytes; JSON {resize}."""
    import pty, struct, termios
    if not _ws_auth(ws) or not vms.VC_RE.match(vid):
        await ws.close(code=4401)
        return
    await ws.accept()
    master, slave = pty.openpty()

    def _child():
        os.setsid()
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)

    proc = subprocess.Popen(["docker", "exec", "-it", "-u", "vc", "-w", f"{vms.HOME}/trabajo", "-e", "TERM=xterm-256color",
                             "-e", "DISPLAY=:1", vms.name(vid), "bash", "-l"],
                            stdin=slave, stdout=slave, stderr=slave, preexec_fn=_child, close_fds=True)
    os.close(slave)
    loop = asyncio.get_running_loop()
    out: asyncio.Queue = asyncio.Queue()
    loop.add_reader(master, lambda: out.put_nowait(_read(master)))
    _audit_ws(vid, "vc.tty")

    async def pump_out():
        while True:
            data = await out.get()
            if not data:
                await ws.close()
                return
            await ws.send_bytes(data)

    task = asyncio.create_task(pump_out())
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("text") is not None:
                t = msg["text"]
                if t.startswith("{"):
                    try:
                        c = json.loads(t)
                        if c.get("type") == "resize":
                            fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", int(c["rows"]), int(c["cols"]), 0, 0))
                            continue
                    except (ValueError, KeyError):
                        pass
                os.write(master, t.encode())
            elif msg.get("bytes"):
                os.write(master, msg["bytes"])
    except (WebSocketDisconnect, OSError):
        pass
    finally:
        task.cancel()
        loop.remove_reader(master)
        proc.terminate()
        os.close(master)


def _read(fd: int) -> bytes:
    try:
        return os.read(fd, 65536)
    except OSError:
        return b""


def _audit_ws(vid: str, cap: str) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    with AUDIT.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(), "capability": cap, "outcome": "ok", "vc": vid}) + "\n")


@app.websocket("/v1/vc/{vid}/vnc")
async def vc_vnc(ws: WebSocket, vid: str):
    """Escritorio: bytes RFB entre el WebSocket y el VNC local del contenedor (docker exec socat), sin puertos."""
    if not _ws_auth(ws) or not vms.VC_RE.match(vid):
        await ws.close(code=4401)
        return
    await ws.accept()
    proc = await asyncio.create_subprocess_exec("docker", "exec", "-i", vms.name(vid), "socat", "STDIO", "TCP:127.0.0.1:5900",
                                                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.DEVNULL)
    _audit_ws(vid, "vc.vnc")

    async def pump_out():
        while True:
            data = await proc.stdout.read(65536)
            if not data:
                await ws.close()
                return
            await ws.send_bytes(data)

    task = asyncio.create_task(pump_out())
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            data = msg.get("bytes") or (msg.get("text") or "").encode()
            proc.stdin.write(data)
            await proc.stdin.drain()
    except (WebSocketDisconnect, ConnectionResetError, BrokenPipeError):
        pass
    finally:
        task.cancel()
        if proc.returncode is None:
            proc.kill()


# ---------- propuestas de Jarvis (bin/aprobar) ----------

PROP_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
HASH_RE = re.compile(r"^[a-f0-9]{64}$")
APROBAR = ROOT / "bin/aprobar"


@app.get("/v1/proposals", dependencies=[Depends(auth)])
def proposals():
    r = subprocess.run([str(APROBAR), "--json"], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise HTTPException(502, (r.stderr or "bin/aprobar falló").strip()[-300:])
    return json.loads(r.stdout or "[]")


@app.post("/v1/proposals/{name}/approve", dependencies=[Depends(auth)])
def proposal_approve(name: str, request: Request, hash: str = Body(..., embed=True)):  # noqa: A002
    if not PROP_RE.match(name) or not HASH_RE.match(hash):
        raise HTTPException(422, "nombre o huella inválidos")
    r = subprocess.run([str(APROBAR), "--si", name, "--hash", hash], capture_output=True, text=True, timeout=60)
    out = (r.stdout + r.stderr).strip()
    _audit(request, "proposals.approve", "ok" if r.returncode == 0 else "error", name=name, hash=hash[:12])
    if r.returncode != 0:
        raise HTTPException(409, out.splitlines()[-1] if out else "No se instaló")
    return {"ok": True, "output": out[-2000:]}


@app.post("/v1/proposals/{name}/reject", dependencies=[Depends(auth)])
def proposal_reject(name: str, request: Request, motivo: str = Body("", embed=True)):
    if not PROP_RE.match(name):
        raise HTTPException(422, "nombre inválido")
    motivo = re.sub(r"[\x00-\x1f]", " ", motivo)[:500]
    r = subprocess.run([str(APROBAR), "--rechazar", name, motivo], capture_output=True, text=True, timeout=30)
    _audit(request, "proposals.reject", "ok" if r.returncode == 0 else "error", name=name)
    if r.returncode != 0:
        raise HTTPException(409, (r.stdout + r.stderr).strip()[-300:])
    return {"ok": True}


# ---------- uso del límite de Claude ----------
# `claude -p /usage` lo resuelve Claude Code localmente: 0 tokens, 0 turnos (comprobado). Usa el login de Claude Code
# del PC (misma cuenta y suscripción que Jarvis): el token de `claude setup-token` de Jarvis solo sirve para el
# modelo y no puede leer el uso. Se ejecuta en una carpeta temporal y sin guardar sesión.

USAGE_MIN_INTERVAL = 60
_usage: dict = {"ts": 0.0, "data": None}
_usage_lock = asyncio.Lock()
USAGE_LINE = re.compile(r"^Current (session|week)[^:]*:\s*(\d+(?:\.\d+)?)%\s*used(?:\s*·\s*resets\s+(.+?)\s*\(([^)]+)\))?", re.M)


def parse_reset(text: str, tz: str, now: datetime | None = None) -> float | None:
    """«Oct 31, 11:40pm» / «Nov 4, 7am» en la zona indicada → epoch (año: la próxima vez que llegue esa fecha)."""
    from zoneinfo import ZoneInfo
    try:
        zone = ZoneInfo(tz)
    except Exception:  # noqa: BLE001
        return None
    m = re.match(r"^([A-Za-z]{3})\w*\s+(\d{1,2}),?\s+(\d{1,2})(?::(\d{2}))?\s*([ap]m)$", text.strip(), re.I)
    if not m:
        return None
    months = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
    mon = months.index(m[1].lower()) + 1
    hour = int(m[3]) % 12 + (12 if m[5].lower() == "pm" else 0)
    now = now or datetime.now(zone)
    for year in (now.year, now.year + 1):
        dt = datetime(year, mon, int(m[2]), hour, int(m[4] or 0), tzinfo=zone)
        if dt.timestamp() >= now.timestamp() - 86400:
            return dt.timestamp()
    return None


def parse_usage_text(text: str) -> dict | None:
    out = {}
    for kind, pct, reset, tz in USAGE_LINE.findall(text):
        key = "five_hour" if kind == "session" else "seven_day"
        out[key] = {"utilization": float(pct) / 100, "resets_at": parse_reset(reset, tz) if reset else None}
    return out or None


@app.post("/v1/claude/usage", dependencies=[Depends(auth)])
async def claude_usage(request: Request):
    async with _usage_lock:
        if _usage["data"] and time.monotonic() - _usage["ts"] < USAGE_MIN_INTERVAL:
            return _usage["data"] | {"cached": True}
        with tempfile.TemporaryDirectory(prefix="cc-usage-") as tmp:
            proc = await asyncio.create_subprocess_exec(
                "claude", "-p", "/usage", "--output-format", "json", "--no-session-persistence",
                "--strict-mcp-config", "--setting-sources", "", cwd=tmp, env=_usage_env(),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, stdin=asyncio.subprocess.DEVNULL)
            try:
                out, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
            except asyncio.TimeoutError:
                proc.kill()
                raise HTTPException(504, "Claude Code no respondió a tiempo")
        try:
            d = json.loads(out or b"{}")
        except ValueError:
            d = {}
        data = parse_usage_text(str(d.get("result", "")))
        tokens = sum(int((d.get("usage") or {}).get(k) or 0) for k in ("input_tokens", "output_tokens", "cache_creation_input_tokens"))
        _audit(request, "claude.usage", "ok" if data else "error", tokens=tokens)
        if not data:
            raise HTTPException(502, "Claude Code no devolvió el uso (¿sesión de Claude Code en el PC iniciada?)")
        _usage.update(ts=time.monotonic(), data=data)
        return data | {"cached": False, "tokens": tokens}


# ---------- voz a texto ----------

@app.post("/v1/voice/transcribe", dependencies=[Depends(auth)])
def voice_transcribe(request: Request, audio: str = Body(..., embed=True)):
    """Con el Whisper del contenedor. El audio se borra al terminar: no se guarda nada."""
    try:
        data = base64.b64decode(audio, validate=True)
    except ValueError:
        raise HTTPException(422, "Audio no válido")
    name = f"panel-{uuid.uuid4().hex}.audio"
    carpeta = ROOT / "data/voz/entrada"
    carpeta.mkdir(parents=True, exist_ok=True)
    f = carpeta / name
    f.write_bytes(data)
    try:
        r = subprocess.run(["docker", "exec", INST, "/opt/jarvis/bin/transcribir", f"/voz/entrada/{name}"],
                           capture_output=True, text=True, timeout=170)
    finally:
        f.unlink(missing_ok=True)
    _audit(request, "voice.transcribe", "ok" if r.returncode == 0 else "error", bytes=len(data))
    if r.returncode != 0:
        raise HTTPException(502, "No se pudo transcribir")
    return {"text": r.stdout.strip()}


# ---------- permisos de Google (google_auth.py) ----------

@app.get("/v1/google/status", dependencies=[Depends(auth)])
def google_status():
    return google_auth.status()


@app.post("/v1/google/{cuenta}/auth-url", dependencies=[Depends(auth)])
def google_auth_url(request: Request, cuenta: str):
    try:
        r = google_auth.auth_url(cuenta)
    except google_auth.GoogleError as e:
        _audit(request, "google.auth_url", "error", cuenta=cuenta, reason=e.msg)
        raise HTTPException(e.status, e.msg)
    _audit(request, "google.auth_url", "ok", cuenta=cuenta)
    return r


@app.post("/v1/google/{cuenta}/exchange", dependencies=[Depends(auth)])
def google_exchange(request: Request, cuenta: str, pegado: str = Body(..., embed=True)):
    try:
        r = google_auth.exchange(cuenta, pegado)
    except google_auth.GoogleError as e:
        _audit(request, "google.exchange", "error", cuenta=cuenta, reason=e.msg)
        raise HTTPException(e.status, e.msg)
    _audit(request, "google.exchange", "ok", cuenta=cuenta)
    return r


# ---------- avisos ----------

NOTIFY_MAX_PER_HOUR = 10
_notify_log: list[float] = []


@app.post("/v1/notify/telegram", dependencies=[Depends(auth)])
def notify_telegram(request: Request, text: str = Body(..., embed=True), level: str = Body("info", embed=True)):
    now = time.time()
    _notify_log[:] = [t for t in _notify_log if now - t < 3600]
    if len(_notify_log) >= NOTIFY_MAX_PER_HOUR:
        _audit(request, "notify.telegram", "denied", reason="límite por hora")
        raise HTTPException(429, "Demasiados avisos en la última hora")
    body = re.sub(r"[\x00-\x09\x0b-\x1f\x7f]", "", text).strip()[:3900]
    if not body:
        raise HTTPException(422, "Aviso vacío")
    nivel = level if level in ("critical", "action", "info", "silent") else "info"
    r = subprocess.run([str(ROOT / "bin/telegram-send.sh"), body], capture_output=True, text=True, timeout=30,
                       env={**os.environ, "JARVIS_NIVEL": nivel})
    _notify_log.append(now)
    _audit(request, "notify.telegram", "ok" if r.returncode == 0 else "error", chars=len(body))
    if r.returncode != 0:
        raise HTTPException(502, "Telegram no aceptó el aviso")
    return {"ok": True}


# ---------- timers: el apartado Automatizaciones ----------
# Los cambios van a un drop-in: la unidad del repo no se toca y borrarlo devuelve el horario original.
TIMERS = {
    "collect": ("Preparar el día", "Recoge agenda, correo, ofertas y tareas para el Panel y el resumen.", False),
    "briefing": ("Briefing de la mañana", "Cierra el día anterior si quedó abierto y te manda el resumen del día.", True),
    "noche": ("Recordatorio de la noche", "Si el día sigue abierto, te recuerda contarme cómo te ha ido.", False),
    "semanal": ("Revisión semanal", "Analiza la semana de gym y estudio y te manda el resumen.", True),
    "replan": ("Replanificar el estudio", "Recalcula el plan con los bloques que has marcado.", False),
    "google": ("Permiso de Google", "Mantiene vivo el acceso a Calendar y correo.", False),
    "cc-backup": ("Copia de seguridad", "Copia cifrada de la base de datos y los datos del panel.", False),
}
DIAS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
CALENDARIO = re.compile(r"^(?:([A-Za-z,.]+) )?\*-\*-\* (\d{2}(?:,\d{2})*):(\d{2})(?::\d{2})?$")
HORA = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def _unit(name: str) -> str:
    if name not in TIMERS:
        raise HTTPException(404, "Timer desconocido")
    return f"{INST}-{name}.timer"


def _calendars(unit: str) -> list[str]:
    """OnCalendar vigentes: una línea vacía anula las anteriores, como hace systemd."""
    out: list[str] = []
    for line in run(["systemctl", "--user", "cat", unit]).splitlines():
        if line.startswith("OnCalendar="):
            v = line.split("=", 1)[1].strip()
            out = [] if not v else [*out, v]
    return out


def horarios(calendars: list[str]) -> tuple[list[str], list[str]]:
    """De OnCalendar a días y horas. Lo que no encaje en esa forma no se puede editar aquí."""
    dias: set[str] = set()
    horas: set[str] = set()
    for c in calendars:
        m = CALENDARIO.match(c.strip())
        if not m:
            raise ValueError(c)
        if m[1]:
            for d in m[1].split(","):
                if ".." in d:
                    a, b = d.split("..")
                    dias.update(DIAS[DIAS.index(a):DIAS.index(b) + 1])
                else:
                    dias.add(d)
        horas.update(f"{h}:{m[3]}" for h in m[2].split(","))
    return [d for d in DIAS if d in dias], sorted(horas)


def calendars_for(dias: list[str], horas: list[str]) -> list[str]:
    if not horas or len(horas) > 6 or not all(HORA.match(h) for h in horas):
        raise ValueError("Hora no válida")
    if not set(dias) <= set(DIAS):
        raise ValueError("Día no válido")
    prefijo = f"{','.join(d for d in DIAS if d in dias)} " if dias and len(set(dias)) < 7 else ""
    return [f"{prefijo}*-*-* {h}:00" for h in sorted(set(horas))]


def _when(v: str | None) -> str:
    """De «Fri 2026-11-06 07:00:00 CET» a ISO; vacío si nunca."""
    partes = (v or "").split()
    return f"{partes[1]}T{partes[2]}" if len(partes) >= 3 else ""


def _timer(name: str) -> dict:
    unit = _unit(name)
    u = parse_show(run(["systemctl", "--user", "show", "--property=Id,ActiveState,UnitFileState,NextElapseUSecRealtime,LastTriggerUSec", unit]))[0]
    s = parse_show(run(["systemctl", "--user", "show", "--property=Id,Result,ActiveState,ExecMainStatus", f"{INST}-{name}.service"]))[0]
    titulo, detalle, modelo = TIMERS[name]
    cal = _calendars(unit)
    try:
        dias, horas = horarios(cal)
    except ValueError:
        dias, horas = [], []
    return {"id": name, "titulo": titulo, "detalle": detalle, "usa_modelo": modelo, "dias": dias, "horas": horas, "calendario": cal,
            "activo": u.get("UnitFileState") == "enabled" and u.get("ActiveState") == "active", "proximo": _when(u.get("NextElapseUSecRealtime")),
            "ultimo": _when(u.get("LastTriggerUSec")), "resultado": s.get("Result") or "", "ejecutando": s.get("ActiveState") == "activating"}


@app.get("/v1/timers", dependencies=[Depends(auth)])
def timers():
    return [_timer(n) for n in TIMERS]


@app.put("/v1/timers/{name}", dependencies=[Depends(auth)])
def timer_set(request: Request, name: str, dias: list[str] = Body(...), horas: list[str] = Body(...), activo: bool = Body(...)):
    unit = _unit(name)
    try:
        cal = calendars_for(dias, horas)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    d = Path.home() / ".config/systemd/user" / f"{unit}.d"
    d.mkdir(parents=True, exist_ok=True)
    (d / "panel.conf").write_text("[Timer]\nOnCalendar=\n" + "".join(f"OnCalendar={c}\n" for c in cal))
    run(["systemctl", "--user", "daemon-reload"])
    run(["systemctl", "--user", "enable" if activo else "disable", "--now", unit])
    if activo:
        run(["systemctl", "--user", "restart", unit])
    _audit(request, "timer.set", "ok", timer=name, calendario=cal, activo=activo)
    return _timer(name)


@app.post("/v1/timers/{name}/enabled", dependencies=[Depends(auth)])
def timer_enabled(request: Request, name: str, activo: bool = Body(..., embed=True)):
    """Encender o apagar un timer sin tocar su horario (lo usa el panel al activar o desactivar un módulo)."""
    unit = _unit(name)
    run(["systemctl", "--user", "enable" if activo else "disable", "--now", unit])
    _audit(request, "timer.enabled", "ok", timer=name, activo=activo)
    return {"ok": True}


@app.post("/v1/timers/{name}/run", dependencies=[Depends(auth)])
def timer_run(request: Request, name: str):
    _unit(name)
    run(["systemctl", "--user", "start", "--no-block", f"{INST}-{name}.service"])
    _audit(request, "timer.run", "ok", timer=name)
    return {"ok": True}


@app.exception_handler(Exception)
def _err(_, exc: Exception):
    return JSONResponse({"detail": "error interno del host agent"}, status_code=500)


# ---------- extensiones locales (host-agent/privado/, no se publica) ----------
# Si existe el paquete privado/, su registrar() añade rutas y temporizadores propios de esta instalación.
try:
    import privado as _privado
except ImportError:
    _privado = None
if _privado is not None:
    _privado.registrar(sys.modules[__name__])


def main() -> None:
    import uvicorn
    sock = Path(os.environ.get("CC_HOSTAGENT_SOCKET",
                               f"{os.environ.get('XDG_RUNTIME_DIR', '/tmp')}/{INST}-cc/hostagent.sock"))
    if os.geteuid() == 0:
        raise SystemExit("El host agent no debe ejecutarse como root")
    if not TOKEN or len(TOKEN) < 32:
        raise SystemExit("Falta CC_HOSTAGENT_TOKEN (mínimo 32 caracteres)")
    sock.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    sock.unlink(missing_ok=True)
    # uvicorn fuerza 666 en sockets que crea él: lo creamos nosotros con 600 y le pasamos el descriptor
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    old = os.umask(0o177)
    try:
        s.bind(str(sock))
    finally:
        os.umask(old)
    os.chmod(sock, 0o600)
    uvicorn.run(app, fd=s.fileno(), log_level="warning")


if __name__ == "__main__":
    main()
