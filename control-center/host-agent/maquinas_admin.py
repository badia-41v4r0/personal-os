"""Administración de las máquinas locales (VirtualBox) desde el panel: listar, conectar, probar, asignar y quitar.

Lo usa solo el panel (usuario administrador), nunca un agente. La configuración vive en `maquinas.json`, que solo
escribe el Host Agent (600); las claves, en `secrets/vm/` (600). Qué hace cada paso:
- `preparar`: instantánea de seguridad (opcional), clave propia de la máquina, redirección NAT `127.0.0.1:<puerto>` → 22
  y una entrada «pendiente» (sin usuario): los agentes aún no la ven.
- Dentro de la VM, el usuario pega unos comandos (SSH solo con esa clave, xdotool). El panel nunca pide ni guarda su sudo.
- `probar`: entra por SSH con el usuario que diga; si funciona, la entrada queda completa y se puede asignar a agentes.
"""
import json
import os
import re
import shlex
import socket
import subprocess
from pathlib import Path

import maquinas as mq

NAT_RULE = "pos-ssh"
SNAPSHOT = "antes-personal-os"
PUERTO_BASE = 2222
LIST_RE = re.compile(r'^"(.+)" \{([0-9a-f-]{36})\}$')
FWD_RE = re.compile(r'^Forwarding\(\d+\)="([^"]*)"$')


# ---------- VirtualBox ----------

def virtualbox() -> dict:
    try:
        r = mq.vbox("--version", timeout=15)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {"instalado": False, "version": None}
    return {"instalado": r.returncode == 0, "version": r.stdout.decode().strip() or None}


def listar_vms() -> list[dict]:
    r = mq.vbox("list", "vms", timeout=20)
    out = []
    for line in r.stdout.decode("utf-8", "replace").splitlines():
        m = LIST_RE.match(line.strip())
        if m:
            out.append({"vbox": m.group(1), "uuid": m.group(2)})
    return out


def info(vbox: str) -> dict:
    r = mq.vbox("showvminfo", vbox, "--machinereadable", timeout=20)
    if r.returncode != 0:
        raise ValueError("No existe esa máquina en VirtualBox")
    d, fwd = {}, []
    for line in r.stdout.decode("utf-8", "replace").splitlines():
        f = FWD_RE.match(line)
        if f:
            fwd.append(f.group(1))
            continue
        k, _, v = line.partition("=")
        d[k.strip('"')] = v.strip('"')
    d["_forwarding"] = fwd
    return d


def regla_ssh(i: dict) -> int | None:
    """Puerto de nuestra redirección (pos-ssh,tcp,127.0.0.1,<puerto>,,22), si existe."""
    for f in i.get("_forwarding", []):
        p = f.split(",")
        if len(p) == 6 and p[0] == NAT_RULE and p[3].isdigit():
            return int(p[3])
    return None


def puerto_libre(usados: set[int]) -> int:
    for p in range(PUERTO_BASE, PUERTO_BASE + 200):
        if p in usados:
            continue
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
            except OSError:
                continue
        return p
    raise ValueError("No hay ningún puerto libre entre 2222 y 2421")


# ---------- configuración (maquinas.json) ----------

def leer(data: Path) -> dict:
    try:
        raw = json.loads(mq.config_path(data).read_text(encoding="utf-8"))
        return raw if isinstance(raw.get("maquinas"), list) else {"maquinas": []}
    except (OSError, ValueError):
        return {"maquinas": []}


def escribir(data: Path, raw: dict) -> None:
    p = mq.config_path(data)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False, indent=2)
    os.chmod(tmp, 0o600)
    tmp.replace(p)


def _entrada(raw: dict, mid: str) -> dict:
    m = next((x for x in raw["maquinas"] if x.get("id") == mid), None)
    if m is None:
        raise KeyError("Esa máquina no está conectada")
    return m


def slug(nombre: str) -> str:
    import unicodedata
    plano = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode()  # «Máquina» → «Maquina»
    s = re.sub(r"[^a-z0-9]+", "-", plano.lower()).strip("-")
    s = re.sub(r"^[^a-z]+", "", s)[:28].strip("-")
    return s if len(s) >= 2 else "vm"


def _completa(m: dict, secrets: Path) -> dict:
    """La misma entrada con rutas absolutas, como la usa `maquinas.py` (si está completa)."""
    clave = (secrets / str(m.get("clave", ""))).resolve()
    return {"id": m["id"], "vbox": m["vbox"], "usuario": m.get("usuario") or "", "puerto": int(m["puerto"]),
            "clave": str(clave), "known_hosts": str(clave.parent / "known_hosts"), "display": m.get("display") or ":0"}


# ---------- estado para el panel ----------

def estado(data: Path, secrets: Path) -> dict:
    vb = virtualbox()
    if not vb["instalado"]:
        return {"virtualbox": vb, "vms": [], "maquinas": []}
    raw = leer(data)
    conectadas = {m.get("vbox"): m for m in raw["maquinas"]}
    vms = []
    for v in listar_vms():
        try:
            st = info(v["vbox"]).get("VMState", "desconocido")
        except ValueError:
            st = "desconocido"
        vms.append({**v, "estado": st, "conectada": (conectadas.get(v["vbox"]) or {}).get("id")})
    estados = {v["vbox"]: v["estado"] for v in vms}
    maqs = []
    for m in raw["maquinas"]:
        maqs.append({"id": m.get("id"), "nombre": m.get("nombre") or m.get("id"), "vbox": m.get("vbox"),
                     "usuario": m.get("usuario") or "", "puerto": m.get("puerto"), "agentes": m.get("agentes") or [],
                     "notas": m.get("notas") or "", "pendiente": not m.get("usuario"),
                     "estado": estados.get(m.get("vbox"), "no existe"), "comprobado": m.get("comprobado")})
    return {"virtualbox": vb, "vms": vms, "maquinas": maqs}


# ---------- conectar una VM ----------

def comandos(pub: str) -> dict:
    """Lo que el usuario pega en una terminal DENTRO de la VM (Debian/Ubuntu). Su sudo lo escribe él allí."""
    base = "\n".join([
        "sudo apt-get update && sudo apt-get install -y openssh-server xdotool",
        "mkdir -p -m 700 ~/.ssh && grep -qxF " + shlex.quote(pub) + " ~/.ssh/authorized_keys 2>/dev/null || echo "
        + shlex.quote(pub) + " >> ~/.ssh/authorized_keys; chmod 600 ~/.ssh/authorized_keys",
        "printf 'PasswordAuthentication no\\nKbdInteractiveAuthentication no\\nPermitRootLogin no\\n' | sudo tee /etc/ssh/sshd_config.d/personal-os.conf >/dev/null",
        "command -v ufw >/dev/null && sudo ufw allow 22/tcp >/dev/null; sudo systemctl enable --now ssh && sudo systemctl restart ssh",
        'echo "Listo. Tu usuario en esta máquina es: $USER"',
    ])
    navegador = "\n".join([
        "mkdir -p ~/.local/share/applications",
        "for f in /usr/share/applications/chromium*.desktop /usr/share/applications/google-chrome*.desktop; do",
        "  [ -f \"$f\" ] && sed 's#^Exec=\\([^ ]*\\)#Exec=\\1 --remote-debugging-port=9222#' \"$f\" > ~/.local/share/applications/\"$(basename \"$f\")\"",
        "done; echo Hecho",
    ])
    return {"base": base, "navegador": navegador}


def preparar(data: Path, secrets: Path, vbox: str, nombre: str = "", instantanea: bool = True) -> dict:
    if not mq.VBOX_RE.match(vbox or "") or vbox not in {v["vbox"] for v in listar_vms()}:
        raise ValueError("No existe esa máquina en VirtualBox (o su nombre tiene caracteres raros)")
    i = info(vbox)
    if i.get("nic1") != "nat":
        raise ValueError("La tarjeta de red 1 de la máquina tiene que estar en «NAT» (VirtualBox → Configuración → Red)")
    st = i.get("VMState", "")
    if st == "saved":
        raise ValueError("La máquina está guardada: arráncala (o descarta su estado guardado) y repite")
    raw = leer(data)
    m = next((x for x in raw["maquinas"] if x.get("vbox") == vbox), None)
    hecho = []
    if instantanea:
        snaps = mq.vbox("snapshot", vbox, "list", "--machinereadable", timeout=30).stdout.decode("utf-8", "replace")
        if f'="{SNAPSHOT}"' not in snaps:
            r = mq.vbox("snapshot", vbox, "take", SNAPSHOT, "--description", "Antes de conectarla a Personal OS", timeout=300)
            if r.returncode != 0:
                raise ValueError("No se pudo hacer la instantánea: " + r.stderr.decode("utf-8", "replace")[-200:])
            hecho.append("instantánea")
    if m is None:
        ids = {x.get("id") for x in raw["maquinas"]}
        mid, n = slug(nombre or vbox), 2
        while mid in ids:
            mid, n = f"{slug(nombre or vbox)[:26]}-{n}", n + 1
        m = {"id": mid, "nombre": (nombre or vbox)[:80], "vbox": vbox, "usuario": "", "puerto": 0,
             "clave": f"vm/{mid}_ed25519", "display": ":0", "agentes": [], "notas": ""}
        raw["maquinas"].append(m)
    # clave propia de esta máquina
    clave = (secrets / m["clave"]).resolve()
    if not clave.is_relative_to(secrets.resolve()):
        raise ValueError("Ruta de clave no válida")
    clave.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not clave.exists():
        r = subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", f"personal-os-{m['id']}", "-f", str(clave)],
                           capture_output=True, timeout=30)
        if r.returncode != 0:
            raise ValueError("No se pudo crear la clave SSH")
        hecho.append("clave")
    os.chmod(clave, 0o600)
    # redirección NAT (solo 127.0.0.1)
    puerto = regla_ssh(i)
    if puerto is None:
        usados = {int(x.get("puerto") or 0) for x in raw["maquinas"]}
        for v in listar_vms():
            p = regla_ssh(info(v["vbox"]))
            if p:
                usados.add(p)
        puerto = puerto_libre(usados)
        regla = f"{NAT_RULE},tcp,127.0.0.1,{puerto},,22"
        args = ("controlvm", vbox, "natpf1", regla) if st in ("running", "paused") else ("modifyvm", vbox, "--natpf1", regla)
        r = mq.vbox(*args, timeout=30)
        if r.returncode != 0:
            raise ValueError("No se pudo crear la redirección de puerto: " + r.stderr.decode("utf-8", "replace")[-200:])
        hecho.append("redirección")
    m["puerto"] = puerto
    escribir(data, raw)
    pub = Path(str(clave) + ".pub").read_text().strip()
    return {"id": m["id"], "puerto": puerto, "hecho": hecho, "comandos": comandos(pub)}


def probar(data: Path, secrets: Path, mid: str, usuario: str = "") -> dict:
    raw = leer(data)
    m = _entrada(raw, mid)
    usuario = (usuario or m.get("usuario") or "").strip()
    if not mq.USER_RE.match(usuario):
        raise ValueError("Escribe el usuario de la máquina (el que te dijo el último comando)")
    st = info(m["vbox"]).get("VMState")
    if st != "running":
        return {"ok": False, "pasos": [{"paso": "Máquina encendida", "ok": False, "detalle": f"Está «{st}»: enciéndela"}]}
    c = _completa(m, secrets) | {"usuario": usuario}
    pasos = []
    try:
        r = mq.ssh(c, "echo ok", timeout=20)
        ok = r.returncode == 0 and b"ok" in r.stdout
        detalle = "" if ok else (r.stderr.decode("utf-8", "replace").strip()[-200:] or "No responde")
    except subprocess.TimeoutExpired:
        ok, detalle = False, "No responde (¿has pegado los comandos? ¿está encendida?)"
    pasos.append({"paso": "Entrar por SSH", "ok": ok, "detalle": detalle})
    if ok:
        r = mq.ssh(c, 'echo "GEO=$(command -v xdotool >/dev/null && xdotool getdisplaygeometry 2>/dev/null)"; '
                      'echo "NAV=$(command -v chromium || command -v chromium-browser || command -v google-chrome)"', timeout=30)
        kv = dict(l.split("=", 1) for l in r.stdout.decode("utf-8", "replace").splitlines() if "=" in l)
        geo, nav = kv.get("GEO", "").strip(), kv.get("NAV", "").strip()
        pasos.append({"paso": "Pantalla, ratón y teclado (xdotool)", "ok": bool(geo),
                      "detalle": f"Pantalla {geo.replace(' ', 'x')}" if geo else "Falta xdotool o no hay sesión gráfica abierta"})
        pasos.append({"paso": "Navegador (opcional)", "ok": bool(nav), "detalle": nav or "No hay Chromium ni Chrome: el agente no podrá leer webs en esta máquina"})
        m["usuario"] = usuario
        from datetime import datetime, timezone
        m["comprobado"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        escribir(data, raw)
    return {"ok": ok, "pasos": pasos}


def actualizar(data: Path, mid: str, nombre: str | None = None, agentes: list[str] | None = None,
               notas: str | None = None) -> dict:
    raw = leer(data)
    m = _entrada(raw, mid)
    if nombre is not None:
        if not nombre.strip():
            raise ValueError("El nombre no puede estar vacío")
        m["nombre"] = nombre.strip()[:80]
    if agentes is not None:
        if len(agentes) > 20 or not all(isinstance(a, str) and re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", a) for a in agentes):
            raise ValueError("Agentes no válidos")
        if agentes and not m.get("usuario"):
            raise ValueError("Antes de asignarla, prueba la conexión")
        m["agentes"] = sorted(set(agentes))
    if notas is not None:
        m["notas"] = notas[:2000]
    escribir(data, raw)
    return {"ok": True}


def quitar(data: Path, secrets: Path, mid: str) -> dict:
    """Deja de usarla: borra su entrada, su redirección y su clave. La VM y su instantánea no se tocan."""
    raw = leer(data)
    m = _entrada(raw, mid)
    try:
        i = info(m["vbox"])
        if regla_ssh(i) is not None:
            vivo = i.get("VMState") in ("running", "paused")
            mq.vbox(*(("controlvm", m["vbox"], "natpf1", "delete", NAT_RULE) if vivo
                      else ("modifyvm", m["vbox"], "--natpf1", "delete", NAT_RULE)), timeout=30)
    except ValueError:
        pass  # la VM ya no existe
    clave = (secrets / str(m.get("clave", ""))).resolve()
    if clave.is_relative_to(secrets.resolve()) and clave.name.endswith("_ed25519"):
        kh = clave.parent / "known_hosts"
        if kh.exists() and m.get("puerto"):
            subprocess.run(["ssh-keygen", "-R", f"[127.0.0.1]:{m['puerto']}", "-f", str(kh)], capture_output=True, timeout=15)
        for f in (clave, Path(str(clave) + ".pub")):
            f.unlink(missing_ok=True)
    raw["maquinas"] = [x for x in raw["maquinas"] if x.get("id") != mid]
    escribir(data, raw)
    return {"ok": True}


def accion(data: Path, mid: str, que: str) -> dict:
    m = _entrada(leer(data), mid)
    st = info(m["vbox"]).get("VMState")
    if que == "encender":
        if st == "paused":
            r = mq.vbox("controlvm", m["vbox"], "resume", timeout=30)
        elif st == "running":
            return {"ok": True, "estado": st}
        else:
            r = mq.vbox("startvm", m["vbox"], "--type", "headless", timeout=90)
    elif que == "apagar":
        if st != "running":
            return {"ok": True, "estado": st}
        r = mq.vbox("controlvm", m["vbox"], "acpipowerbutton", timeout=30)
    else:
        raise ValueError("Acción no válida")
    if r.returncode != 0:
        raise ValueError(r.stderr.decode("utf-8", "replace").strip()[-300:] or "VirtualBox no pudo hacerlo")
    return {"ok": True}


def captura(data: Path, mid: str) -> dict:
    m = _entrada(leer(data), mid)
    return mq.captura(m)
