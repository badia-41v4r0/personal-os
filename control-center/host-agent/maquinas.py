"""Máquinas locales: VMs de VirtualBox del usuario que un agente puede manejar (p. ej. la de VerilUOC para FC).

A diferencia de los ordenadores virtuales (contenedores que crea el panel), estas máquinas son del usuario: las instala
él, tienen internet y él mismo entra en ellas (VirtualBox → Mostrar) cuando hace falta, p. ej. para iniciar sesión.

- La lista sale de `<CC_DATA_DIR>/maquinas.json` (o `POS_MAQUINAS`) y cada máquina dice qué agentes pueden usarla.
- El Host Agent entra por SSH con su propia clave (`secrets/vm/…`, 600), a 127.0.0.1 por una redirección NAT de la VM.
  El agente nunca ve ni la clave, ni VBoxManage, ni el resto del PC: solo estas operaciones, sobre sus máquinas.
- Las capturas salen de VirtualBox (funcionan aunque el SSH falle); ratón y teclado, de `xdotool` dentro de la VM.
- Dentro de la VM el agente tiene libertad (decisión del usuario, 25/11/2026): comandos y archivos de su usuario.
"""
import base64
import json
import os
import re
import shlex
import subprocess
import tempfile
import time
from pathlib import Path

import vms

ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
VBOX_RE = re.compile(r"^[A-Za-z0-9._ -]{1,64}$")
USER_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
DISPLAY_RE = re.compile(r"^:[0-9]{1,2}$")
MAX_OUTPUT = 100_000
MAX_FILE = 50 * 1024 * 1024
OPS = {"list", "info", "start", "stop", "exec", "read_file", "write_file", "copy_in", "copy_out",
       "screenshot", "click", "type", "key", "scroll", "open_url", "page_text"}
CDP_PY = (Path(__file__).parent / "vm_cdp.py").read_bytes()
# Chromium de la VM con su puerto de depuración (solo dentro de la VM). Si el usuario lo abrió sin él, no se cierra solo.
CHROMIUM = r"""up() { curl -sf -m 2 http://127.0.0.1:9222/json/version >/dev/null; }
up && exit 0
B=$(command -v chromium || command -v chromium-browser || command -v google-chrome) || { echo "Esta máquina no tiene Chromium ni Chrome"; exit 5; }
{ pgrep -x chromium || pgrep -x chrome || pgrep -x chromium-browse; } >/dev/null && { echo "El navegador está abierto sin el puerto de depuración: ciérralo (vm_key alt+F4 en su ventana) y repite"; exit 3; }
(setsid nohup "$B" --remote-debugging-port=9222 --no-first-run --no-default-browser-check --start-maximized >/tmp/chromium.log 2>&1 &)
for i in $(seq 40); do sleep 0.5; up && exit 0; done
echo "Chromium no arrancó"; exit 4"""


def config_path(data: Path) -> Path:
    return Path(os.environ.get("POS_MAQUINAS", str(data / "maquinas.json")))


def cargar(data: Path, secrets: Path) -> list[dict]:
    """Máquinas válidas del archivo de configuración. Las mal escritas se ignoran (nunca rompen la sesión)."""
    try:
        raw = json.loads(config_path(data).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for m in raw.get("maquinas") or []:
        try:
            clave = (secrets / str(m["clave"])).resolve()
            ok = (ID_RE.match(m["id"]) and VBOX_RE.match(m["vbox"]) and USER_RE.match(m["usuario"])
                  and 1024 <= int(m["puerto"]) <= 65535 and clave.is_relative_to(secrets.resolve())
                  and DISPLAY_RE.match(m.get("display", ":0")))
        except (KeyError, TypeError, ValueError):
            ok = False
        if ok:
            out.append({"id": m["id"], "nombre": str(m.get("nombre") or m["id"])[:80], "vbox": m["vbox"],
                        "usuario": m["usuario"], "puerto": int(m["puerto"]), "clave": str(clave),
                        "known_hosts": str(clave.parent / "known_hosts"), "display": m.get("display", ":0"),
                        "agentes": [str(a) for a in m.get("agentes") or []], "notas": str(m.get("notas") or "")[:2000]})
    return out


def de_agente(maquinas: list[dict], agente: str | None) -> list[dict]:
    return [m for m in maquinas if agente and agente in m["agentes"]]


# ---------- VirtualBox y SSH ----------

def vbox(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["VBoxManage", *args], capture_output=True, timeout=timeout)


def estado(m: dict) -> str:
    r = vbox("showvminfo", m["vbox"], "--machinereadable", timeout=20)
    st = re.search(rb'^VMState="([^"]+)"', r.stdout, re.M)
    return st.group(1).decode() if st else "desconocido"


def ssh_argv(m: dict, remote: str) -> list[str]:
    # -F /dev/null: sin la configuración del sistema. En el servicio (PrivateTmp ⇒ espacio de usuarios propio) los archivos
    # de root se ven como de «nobody» y ssh rechaza /etc/ssh/ssh_config.d/* («Bad owner or permissions»).
    return ["ssh", "-F", "/dev/null", "-i", m["clave"], "-p", str(m["puerto"]), "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
            "-o", f"UserKnownHostsFile={m['known_hosts']}", "-o", "StrictHostKeyChecking=accept-new",
            "-o", "ConnectTimeout=8", "-o", "LogLevel=ERROR", f"{m['usuario']}@127.0.0.1", remote]


def ssh(m: dict, cmd: str, timeout: int = 60, data: bytes | None = None) -> subprocess.CompletedProcess:
    """Ejecuta `cmd` con bash de login en la VM, con la pantalla del usuario (DISPLAY)."""
    remote = f"export DISPLAY={m['display']}; cd ~ && bash -lc {shlex.quote(cmd)}"
    return subprocess.run(ssh_argv(m, remote), capture_output=True, timeout=timeout, input=data)


def ssh_listo(m: dict) -> bool:
    try:
        return ssh(m, "true", timeout=15).returncode == 0
    except subprocess.TimeoutExpired:
        return False


def captura(m: dict) -> dict:
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "c.png"
        r = vbox("controlvm", m["vbox"], "screenshotpng", str(f), timeout=30)
        if r.returncode != 0 or not f.exists():
            return {"error": "No se pudo capturar la pantalla (¿está encendida?)"}
        return {"png_base64": base64.b64encode(f.read_bytes()).decode()}


# ---------- rutas del lado del PC (copias) ----------

def ruta_pc(p: str, root: Path, escribir: bool) -> Path:
    """Solo /entregables/… (archivos/Uni) y, para leer, /vault/…: las mismas carpetas que ve el agente."""
    p = (p or "").strip()
    bases = {"/entregables": root / "archivos/Uni"}
    if not escribir:
        bases["/vault"] = root / "Jarvis-Vault"
    for pre, base in bases.items():
        if p == pre or p.startswith(pre + "/"):
            dest = (base / p[len(pre):].lstrip("/")).resolve()
            if ".." not in p.split("/") and dest.is_relative_to(base.resolve()):
                return dest
    raise ValueError("Ruta no permitida: usa /entregables/… " + ("" if escribir else "o /vault/…"))


# ---------- operaciones ----------

def op(maquinas: list[dict], name: str, a: dict, root: Path, audit) -> dict:
    """Una operación del agente sobre una de SUS máquinas (`maquinas` ya está filtrada por agente)."""
    if name not in OPS:
        return {"error": "Operación no permitida"}
    if name == "list":
        return {"maquinas": [{"id": m["id"], "nombre": m["nombre"], "estado": estado(m), "notas": m["notas"]} for m in maquinas]}
    if not maquinas:
        return {"error": "No tienes ninguna máquina local asignada"}
    mid = str(a.get("maquina") or maquinas[0]["id"])
    m = next((x for x in maquinas if x["id"] == mid), None)
    if m is None:
        return {"error": f"La máquina «{mid}» no es tuya"}
    try:
        return _op(m, name, a, root, audit)
    except subprocess.TimeoutExpired:
        return {"error": "Tiempo agotado"}


def _op(m: dict, name: str, a: dict, root: Path, audit) -> dict:
    st = estado(m)
    if name == "info":
        return {"maquina": m["id"], "nombre": m["nombre"], "estado": st,
                "ssh": st == "running" and ssh_listo(m), "notas": m["notas"]}
    if name == "start":
        if st == "paused":  # p. ej. si el usuario la pausó desde la ventana de VirtualBox: se reanuda, no se arranca
            r = vbox("controlvm", m["vbox"], "resume", timeout=30)
            if r.returncode != 0:
                audit("vm.start", "error", maquina=m["id"])
                return {"error": "Está en pausa y no se pudo reanudar", "detalle": r.stderr.decode("utf-8", "replace")[-300:]}
        elif st != "running":
            r = vbox("startvm", m["vbox"], "--type", "headless", timeout=90)
            if r.returncode != 0:
                audit("vm.start", "error", maquina=m["id"])
                return {"error": "No arrancó (¿la tiene abierta el usuario en otra ventana?)",
                        "detalle": r.stderr.decode("utf-8", "replace")[-300:]}
        for _ in range(36):  # hasta ~3 min a que responda el SSH
            if ssh_listo(m):
                audit("vm.start", maquina=m["id"])
                return {"ok": True, "estado": "running"}
            time.sleep(5)
        return {"error": "Arrancada, pero el SSH no responde aún; prueba vm_info en un rato"}
    if name == "stop":
        if st != "running":
            return {"ok": True, "estado": st}
        vbox("controlvm", m["vbox"], "acpipowerbutton", timeout=20)
        audit("vm.stop", maquina=m["id"])
        return {"ok": True, "nota": "Apagando (como pulsar el botón de apagado)"}
    if st != "running":
        return {"error": f"La máquina está «{st}»: usa vm_start (arranca o reanuda)"}
    if name == "screenshot":
        audit("vm.screenshot", maquina=m["id"])
        return captura(m)
    if name == "exec":
        cmd = str(a.get("command", ""))
        if not cmd.strip() or len(cmd) > 20_000:
            return {"error": "Comando vacío o demasiado largo"}
        t = max(1, min(int(a.get("timeout", 60)), 600))
        try:
            r = ssh(m, cmd, timeout=t + 10)
            out = {"codigo": r.returncode, "salida": r.stdout.decode("utf-8", "replace")[-MAX_OUTPUT:],
                   "errores": r.stderr.decode("utf-8", "replace")[-20_000:]}
        except subprocess.TimeoutExpired:
            out = {"codigo": 124, "salida": "", "errores": "Tiempo agotado (para procesos largos o con ventana, usa nohup … &)"}
        audit("vm.exec", maquina=m["id"], chars=len(cmd), code=out["codigo"])
        return out
    if name == "read_file":
        path = str(a.get("path", ""))
        r = ssh(m, f"head -c 200000 -- {shlex.quote(path)}", timeout=30)
        audit("vm.read_file", maquina=m["id"], path=path[:200])
        if r.returncode != 0:
            return {"error": "No se pudo leer", "detalle": r.stderr.decode("utf-8", "replace")[-300:]}
        return {"path": path, "contenido": r.stdout.decode("utf-8", "replace")}
    if name == "write_file":
        path, data = str(a.get("path", "")), str(a.get("content", "")).encode()
        if not path.strip() or len(data) > 5 * 1024 * 1024:
            return {"error": "Ruta vacía o contenido de más de 5 MB"}
        q = shlex.quote(path)
        r = ssh(m, f'mkdir -p -- "$(dirname -- {q})" && cat > {q}', timeout=60, data=data)
        audit("vm.write_file", maquina=m["id"], path=path[:200], bytes=len(data))
        return {"ok": r.returncode == 0, "path": path} if r.returncode == 0 else {"error": r.stderr.decode("utf-8", "replace")[-300:]}
    if name == "copy_in":
        try:
            src = ruta_pc(str(a.get("origen", "")), root, escribir=False)
        except ValueError as e:
            return {"error": str(e)}
        if not src.is_file() or src.stat().st_size > MAX_FILE:
            return {"error": "No existe ese archivo o pasa de 50 MB"}
        dest = str(a.get("destino") or f"Documents/{src.name}")
        q = shlex.quote(dest)
        r = ssh(m, f'mkdir -p -- "$(dirname -- {q})" && cat > {q}', timeout=120, data=src.read_bytes())
        audit("vm.copy_in", maquina=m["id"], origen=str(a.get("origen", ""))[:200], destino=dest[:200])
        return {"ok": True, "destino": dest} if r.returncode == 0 else {"error": r.stderr.decode("utf-8", "replace")[-300:]}
    if name == "copy_out":
        try:
            dest = ruta_pc(str(a.get("destino", "")), root, escribir=True)
        except ValueError as e:
            return {"error": str(e)}
        src = str(a.get("origen", ""))
        r = ssh(m, f"head -c {MAX_FILE + 1} -- {shlex.quote(src)}", timeout=120)
        if r.returncode != 0 or len(r.stdout) > MAX_FILE:
            return {"error": "No se pudo leer en la máquina o pasa de 50 MB", "detalle": r.stderr.decode("utf-8", "replace")[-300:]}
        if dest.exists() and dest.is_dir():
            dest = dest / Path(src).name
        if dest.exists() and not a.get("sobrescribir"):
            return {"error": f"Ya existe {dest.name}: elige otro nombre (p. ej. -v2) o pasa sobrescribir"}
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(r.stdout)
        audit("vm.copy_out", maquina=m["id"], origen=src[:200], bytes=len(r.stdout))
        return {"ok": True, "destino": "/entregables/" + str(dest.relative_to((root / "archivos/Uni").resolve())), "bytes": len(r.stdout)}
    if name in ("open_url", "page_text"):
        url = str(a.get("url", ""))
        if name == "open_url" and (not re.match(r"^https?://", url) or len(url) > 2000):
            return {"error": "URL no válida (http o https)"}
        r = ssh(m, CHROMIUM, timeout=40)
        if r.returncode != 0:
            return {"error": r.stdout.decode("utf-8", "replace").strip()[-300:] or "Chromium no responde"}
        cmd = "python3 - open " + shlex.quote(url) if name == "open_url" else "python3 - text"
        r = ssh(m, cmd, timeout=60, data=CDP_PY)
        audit(f"vm.{name}", maquina=m["id"], url=url[:200])
        try:
            return json.loads(r.stdout.decode("utf-8", "replace").strip().splitlines()[-1])
        except (ValueError, IndexError):
            return {"error": "Respuesta del navegador no válida", "detalle": r.stderr.decode("utf-8", "replace")[-300:]}
    # ratón y teclado
    try:
        if name == "click":
            cmd = vms.click_cmd(int(a.get("x", -1)), int(a.get("y", -1)), str(a.get("button", "left")), bool(a.get("double")))
        elif name == "type":
            cmd = vms.type_cmd(str(a.get("text", "")))
        elif name == "key":
            cmd = vms.key_cmd(str(a.get("keys", "")))
        else:
            cmd = vms.scroll_cmd(int(a.get("x", 640)), int(a.get("y", 400)), str(a.get("direction", "down")), int(a.get("amount", 3)))
    except (TypeError, ValueError) as e:
        return {"error": str(e)}
    r = ssh(m, shlex.join(cmd), timeout=60)
    audit(f"vm.{name}", maquina=m["id"], code=r.returncode)
    if r.returncode != 0:
        return {"error": "Acción fallida", "detalle": r.stderr.decode("utf-8", "replace")[-300:]}
    time.sleep(0.7)
    return captura(m)
