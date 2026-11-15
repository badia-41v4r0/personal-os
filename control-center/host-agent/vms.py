"""Ordenadores virtuales: contenedores Docker endurecidos (NO máquinas virtuales: comparten kernel con el host).

Aislamiento de cada uno:
- Usuario `vc` (uid 1001) sin sudo; raíz de solo lectura; /tmp en tmpfs; su home en un volumen propio.
- `--cap-drop ALL`, `no-new-privileges`, seccomp por defecto de Docker, límites de CPU, RAM y procesos.
- Sin red (`--network none`) salvo que se pida internet (`bridge`). Nunca el socket de Docker, ni $HOME, ni secretos.
- Ningún puerto publicado: el panel entra por `docker exec` (terminal) y `docker exec socat` al VNC local.
El disco del volumen no se puede limitar con el driver local: se mide y el backend para el ordenador si se pasa.
"""
import json
import re
import subprocess
import time
from instancia import INST

VC_RE = re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")
PROFILES = {"terminal": f"{INST}-vc:terminal", "browser": f"{INST}-vc:desktop", "desktop": f"{INST}-vc:desktop",
            "canvas": f"{INST}-vc:canvas", "aplicaciones": f"{INST}-vc:aplicaciones"}
# Campus (perfil «canvas»): sin red propia; su única salida es un proxy en otro contenedor (`egress`), que el agente
# no puede tocar y que solo deja abrir los dominios del campus del usuario. Lo que el agente puede hacer en Canvas lo marcan sus instrucciones.
EGRESS_IMAGE = f"{INST}-vc:egress"
FIXED_PROFILES = {"canvas", "aplicaciones"}  # ordenadores que el agente usa pero no puede crear ni destruir
EGRESS_PROFILES = {"canvas", "aplicaciones"}  # sin red propia: solo su proxy
# Aplicaciones (candidaturas): el proxy solo deja los dominios de esa solicitud, y el agente no tiene ni terminal, ni
# ratón, ni teclado: solo operaciones de formulario cerradas. El botón de enviar lo pulsa el Host Agent, y solo cuando
# el backend lo pide tras la aprobación del usuario (y si el formulario sigue como lo aprobó).
APLICACIONES_OPS = {"info", "screenshot", "open_url", "page_text", "scroll", "form_fields", "form_fill", "form_attach"}
DOMINIO_RE = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
MAX_DOMINIOS = 40
HOME = "/home/vc"
MAX_OUTPUT = 100_000
MAX_FILE = 50 * 1024 * 1024
TIMEOUT = 15


def name(vid: str) -> str:
    return f"{INST}-vc-{vid[:8]}"


def volume(vid: str) -> str:
    return f"{INST}-vc-{vid}"


def validate(body: dict) -> dict:
    vid = str(body.get("id", ""))
    if not VC_RE.match(vid):
        raise ValueError("id inválido")
    profile = body.get("profile", "terminal")
    if profile not in PROFILES:
        raise ValueError("Perfil no válido (terminal, browser, desktop, canvas, aplicaciones)")
    allow = [str(d).lower().strip(".") for d in (body.get("egress_allow") or [])]
    if profile in EGRESS_PROFILES:
        if not allow or len(allow) > MAX_DOMINIOS or not all(DOMINIO_RE.match(d) for d in allow):
            raise ValueError("Este ordenador necesita su lista de dominios (válidos, como mucho 40)")
    else:
        allow = []
    cpus = float(body.get("cpus", 1))
    mem = int(body.get("memory_mb", 1536 if profile != "terminal" else 1024))
    disk = int(body.get("disk_mb", 2048))
    if not 0.25 <= cpus <= 2:
        raise ValueError("CPU entre 0,25 y 2")
    if not 256 <= mem <= 4096:
        raise ValueError("Memoria entre 256 MB y 4 GB")
    if not 128 <= disk <= 10240:
        raise ValueError("Disco entre 128 MB y 10 GB")
    internet = bool(body.get("internet")) and profile not in EGRESS_PROFILES  # esos salen solo por su proxy
    start = str(body.get("start_url") or "")
    if start and not re.fullmatch(r"https://[A-Za-z0-9.-]{1,253}(/[\w./%?=&#~+-]{0,400})?", start):
        raise ValueError("Dirección de inicio no válida (https)")
    return {"id": vid, "profile": profile, "internet": internet, "cpus": cpus, "memory_mb": mem, "egress_allow": allow, "start_url": start,
            "disk_mb": disk, "owner": re.sub(r"[^a-z0-9:_-]", "", str(body.get("owner", "")).lower())[:64],
            "session": str(body.get("session", "")) if VC_RE.match(str(body.get("session", ""))) else ""}


def run_argv(req: dict) -> list[str]:
    argv = [
        "docker", "run", "-d", "--name", name(req["id"]), "--hostname", "vc",
        "--label", f"{INST}.vc={req['id']}", "--label", f"{INST}.vc.profile={req['profile']}",
        "--label", f"{INST}.vc.owner={req['owner']}", "--label", f"{INST}.vc.disk_mb={req['disk_mb']}",
        "--read-only", "--tmpfs", "/tmp:size=512m,mode=1777",
        "--mount", f"type=volume,src={volume(req['id'])},dst={HOME}",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--pids-limit", "512",
        "--memory", f"{req['memory_mb']}m", "--memory-swap", f"{req['memory_mb']}m", "--cpus", str(req["cpus"]),
        "--network", "bridge" if req["internet"] else "none",
        "--shm-size", "256m", "-e", f"VC_PROFILE={req['profile']}",
    ]
    if req["session"]:
        argv += ["--label", f"{INST}.vc.session={req['session']}"]
    if req.get("start_url"):  # página con la que se abre el navegador del campus
        argv += ["-e", f"VC_START_URL={req['start_url']}"]
    if req["profile"] in EGRESS_PROFILES:
        argv += ["--mount", f"type=volume,src={gw_volume(req['id'])},dst=/run/egress,readonly"]
    return argv + [PROFILES[req["profile"]]]


# ---------- proxy de salida (perfil canvas) ----------

def egress_name(vid: str) -> str:
    return f"{name(vid)}-egress"


def gw_volume(vid: str) -> str:
    return f"{INST}-vc-{vid}-gw"  # socket del proxy y su CA (el ordenador lo monta en solo lectura)


def egress_volume(vid: str) -> str:
    return f"{INST}-vc-{vid}-egress"  # CA de mitmproxy y registro de peticiones


def egress_argv(vid: str) -> list[str]:
    return ["docker", "run", "-d", "--name", egress_name(vid), "--hostname", "egress",
            "--label", f"{INST}.vc.egress={vid}", "--read-only",
            "--tmpfs", "/tmp:size=64m",
            "--mount", f"type=volume,src={gw_volume(vid)},dst=/gw",
            "--mount", f"type=volume,src={egress_volume(vid)},dst=/data",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--pids-limit", "256",
            "--memory", "384m", "--memory-swap", "384m", "--cpus", "0.5", "--network", "bridge", EGRESS_IMAGE]


def egress_create(vid: str, allow: list[str] | None = None) -> subprocess.CompletedProcess:
    """Crea los volúmenes del proxy (propiedad de su usuario, uid 1002) y lo arranca. Con `allow`, esos son los
    únicos dominios (allow.json en su volumen, que el ordenador no monta); sin él, no sale nada."""
    for v in (gw_volume(vid), egress_volume(vid)):
        docker("volume", "create", v)
    r = docker("run", "--rm", "--network", "none", "--user", "0", "--cap-drop", "ALL", "--cap-add", "CHOWN",
               "-v", f"{gw_volume(vid)}:/gw", "-v", f"{egress_volume(vid)}:/d", "--entrypoint", "chown",
               EGRESS_IMAGE, "1002:1002", "/gw", "/d", timeout=60)
    if r.returncode != 0:
        return r
    if allow:
        r = docker("run", "--rm", "-i", "--network", "none", "--user", "1002", "--cap-drop", "ALL",
                   "-v", f"{egress_volume(vid)}:/d", "--entrypoint", "sh", EGRESS_IMAGE, "-c", "cat > /d/allow.json",
                   input=json.dumps(sorted(set(allow))).encode(), timeout=60)
        if r.returncode != 0:
            return r
    r = docker(*egress_argv(vid)[1:], timeout=60)
    if r.returncode == 0:
        for _ in range(100):  # espera al socket y a la CA antes de arrancar el ordenador
            if docker("exec", egress_name(vid), "test", "-S", "/gw/proxy.sock").returncode == 0:
                break
            time.sleep(0.2)
    return r


def egress_allow(vid: str, allow: list[str]) -> subprocess.CompletedProcess:
    """Cambia los dominios de un proxy ya creado. El filtro relee allow.json en cada petición: no hace falta reiniciar."""
    return docker("run", "--rm", "-i", "--network", "none", "--user", "1002", "--cap-drop", "ALL",
                  "-v", f"{egress_volume(vid)}:/d", "--entrypoint", "sh", EGRESS_IMAGE, "-c", "cat > /d/allow.tmp && mv /d/allow.tmp /d/allow.json",
                  input=json.dumps(sorted(set(allow))).encode(), timeout=60)


def egress_remove(vid: str) -> None:
    docker("rm", "-f", egress_name(vid), timeout=30)
    for v in (gw_volume(vid), egress_volume(vid)):
        docker("volume", "rm", "-f", v, timeout=30)


def egress_exists(vid: str) -> bool:
    return docker("inspect", egress_name(vid)).returncode == 0


def egress_log(vid: str, lines: int = 200) -> list[dict]:
    r = docker("exec", egress_name(vid), "tail", "-n", str(max(1, min(lines, 2000))), "/data/egress.jsonl")
    out = []
    for line in r.stdout.decode("utf-8", "replace").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


# ---------- control del escritorio y del navegador (perfiles con pantalla) ----------

KEY_RE = re.compile(r"^[A-Za-z0-9_+\-]{1,40}$")  # p. ej. Return, ctrl+l, Page_Down, alt+Left


def click_cmd(x: int, y: int, button: str = "left", double: bool = False) -> list[str]:
    b = {"left": "1", "middle": "2", "right": "3"}.get(button)
    if b is None or not (0 <= x <= 4000 and 0 <= y <= 4000):
        raise ValueError("Botón o coordenadas no válidos")
    return ["xdotool", "mousemove", str(int(x)), str(int(y)), "click", *(["--repeat", "2"] if double else []), b]


def type_cmd(text: str) -> list[str]:
    if not text or len(text) > 5000:
        raise ValueError("Texto vacío o demasiado largo (máx. 5000)")
    return ["xdotool", "type", "--delay", "8", "--", text]


def key_cmd(keys: str) -> list[str]:
    ks = keys.split()
    if not ks or len(ks) > 10 or not all(KEY_RE.match(k) for k in ks):
        raise ValueError("Teclas no válidas (p. ej. «Return», «ctrl+l», «Page_Down»)")
    return ["xdotool", "key", "--delay", "50", *ks]


def scroll_cmd(x: int, y: int, direction: str, amount: int = 3) -> list[str]:
    b = {"up": "4", "down": "5", "left": "6", "right": "7"}.get(direction)
    if b is None or not (0 <= x <= 4000 and 0 <= y <= 4000):
        raise ValueError("Dirección o coordenadas no válidas")
    return ["xdotool", "mousemove", str(int(x)), str(int(y)), "click", "--repeat", str(max(1, min(int(amount), 20))), b]


# Lectura del navegador por CDP (solo dentro del contenedor). Recibe la operación por argv, nunca código del agente.
BROWSER_PY = r"""
import json, sys
from playwright.sync_api import sync_playwright
op, arg = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "")
with sync_playwright() as p:
    b = p.chromium.connect_over_cdp("http://127.0.0.1:9222", timeout=15000)
    ctx = b.contexts[0]
    pages = [x for x in ctx.pages if not x.url.startswith("devtools://")]
    pg = pages[-1] if pages else ctx.new_page()
    if op == "open":
        try:
            pg.goto(arg, timeout=45000, wait_until="domcontentloaded")
        except Exception as e:
            print(json.dumps({"url": pg.url, "titulo": pg.title(), "aviso": str(e)[:200]})); sys.exit(0)
        pg.bring_to_front()
        print(json.dumps({"url": pg.url, "titulo": pg.title()}))
    elif op == "text":
        txt = pg.inner_text("body", timeout=15000)
        links = pg.eval_on_selector_all("a[href]", "els => els.slice(0, 300).map(e => [(e.innerText||'').trim().slice(0,80), e.href])")
        print(json.dumps({"url": pg.url, "titulo": pg.title(), "texto": txt[:60000],
                          "enlaces": [l for l in links if l[1].startswith("http")][:300]}, ensure_ascii=False))
"""


def browser_cmd(op: str, arg: str = "") -> list[str]:
    if op not in ("open", "text"):
        raise ValueError("Operación no válida")
    if op == "open" and not re.match(r"^https?://[^\s]{1,2000}$", arg):
        raise ValueError("URL no válida (http/https)")
    return ["python3", "-c", BROWSER_PY, op, arg]


# Formularios (perfil aplicaciones). Recibe la operación y sus datos en JSON por argv, nunca código del agente.
# Cada control visible recibe una referencia `data-jref` (f1, f2…; b1… los botones): el agente rellena por referencia
# y solo campos; los botones solo los pulsa `submit`, que no está en la pasarela del agente.
FORM_PY = r'''
import json, sys
from playwright.sync_api import sync_playwright
op, arg = sys.argv[1], json.loads(sys.argv[2] if len(sys.argv) > 2 else "{}")
MARCAR = """
(() => {
  const vis = e => { const r = e.getBoundingClientRect(); const st = getComputedStyle(e);
    return (r.width > 0 || r.height > 0 || e.type === 'file') && st.visibility !== 'hidden' && st.display !== 'none'; };
  const lab = e => { if (e.labels && e.labels.length) return [...e.labels].map(l => l.innerText.trim()).join(' ');
    return e.getAttribute('aria-label') || e.getAttribute('placeholder') || e.getAttribute('name') || ''; };
  let f = 0, b = 0;
  for (const e of document.querySelectorAll('[data-jref]')) { const n = parseInt(e.dataset.jref.slice(1)) || 0;
    if (e.dataset.jref[0] === 'b') b = Math.max(b, n); else f = Math.max(f, n); }
  const campos = [], botones = [];
  for (const e of document.querySelectorAll('input, textarea, select, button')) {
    const t = (e.getAttribute('type') || e.tagName).toLowerCase();
    if (t === 'hidden' || !vis(e)) continue;
    const boton = e.tagName === 'BUTTON' || ['submit', 'button', 'reset', 'image'].includes(t);
    if (!e.dataset.jref) e.dataset.jref = boton ? 'b' + (++b) : 'f' + (++f);
    if (boton) { botones.push({ref: e.dataset.jref, texto: (e.innerText || e.value || '').trim().slice(0, 120), tipo: t}); continue; }
    const c = {ref: e.dataset.jref, tag: e.tagName.toLowerCase(), tipo: t, nombre: e.name || '', etiqueta: lab(e).slice(0, 200),
               obligatorio: e.required, valor: t === 'checkbox' || t === 'radio' ? e.checked : t === 'file' ? [...(e.files || [])].map(x => x.name) : e.value};
    if (e.tagName === 'SELECT') c.opciones = [...e.options].slice(0, 200).map(o => o.text.trim());
    campos.push(c);
  }
  const html = document.documentElement.innerHTML.toLowerCase();
  const bloqueos = [];
  if (document.querySelector('iframe[src*="recaptcha"], iframe[src*="hcaptcha"], iframe[src*="turnstile"], .g-recaptcha, .h-captcha, .cf-turnstile')) bloqueos.push('captcha');
  if (document.querySelector('input[type="password"]')) bloqueos.push('inicio de sesión');
  if (/sign in with|iniciar sesión con|continue with google|continuar con google|login with linkedin/.test(html)) bloqueos.push('SSO');
  return {url: location.href, titulo: document.title, campos, botones, bloqueos};
})()
"""
with sync_playwright() as p:
    br = p.chromium.connect_over_cdp("http://127.0.0.1:9222", timeout=15000)
    ctx = br.contexts[0]
    pages = [x for x in ctx.pages if not x.url.startswith("devtools://")]
    pg = pages[-1] if pages else ctx.new_page()
    estado = pg.evaluate(MARCAR)
    campos = {c["ref"]: c for c in estado["campos"]}
    botones = {b["ref"]: b for b in estado["botones"]}
    loc = lambda ref: pg.locator('[data-jref="%s"]' % ref).first
    if op == "fields":
        print(json.dumps(estado, ensure_ascii=False)); sys.exit(0)
    if op == "fill":
        hechos, errores = [], []
        for ref, valor in (arg.get("valores") or {}).items():
            c = campos.get(ref)
            if c is None or c["tipo"] == "file":
                errores.append(ref + ": no es un campo que se pueda rellenar"); continue
            try:
                if c["tipo"] in ("checkbox", "radio"):
                    loc(ref).set_checked(bool(valor), timeout=5000)
                elif c["tag"] == "select":
                    loc(ref).select_option(label=str(valor), timeout=5000)
                else:
                    loc(ref).fill(str(valor), timeout=5000)
                hechos.append(ref)
            except Exception as e:
                errores.append(ref + ": " + str(e)[:120])
        print(json.dumps({"rellenados": hechos, "errores": errores, **pg.evaluate(MARCAR)}, ensure_ascii=False)); sys.exit(0)
    if op == "attach":
        c = campos.get(arg.get("ref", ""))
        if c is None or c["tipo"] != "file":
            print(json.dumps({"error": "Esa referencia no es un campo de archivo"})); sys.exit(0)
        loc(c["ref"]).set_input_files(arg["ruta"], timeout=10000)
        print(json.dumps({"adjuntado": c["ref"], **pg.evaluate(MARCAR)}, ensure_ascii=False)); sys.exit(0)
    if op == "submit":
        esperado = arg.get("esperado") or {}
        distintos = [ref for ref, v in esperado.items() if ref not in campos or campos[ref]["valor"] != v]
        if distintos or arg.get("boton") not in botones:
            print(json.dumps({"enviado": False, "motivo": "El formulario no es el que se aprobó", "distintos": distintos[:20]}, ensure_ascii=False)); sys.exit(0)
        antes = pg.url
        loc(arg["boton"]).click(timeout=10000)
        try:
            pg.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        texto = pg.inner_text("body", timeout=10000)[:4000]
        print(json.dumps({"enviado": True, "url_antes": antes, "url": pg.url, "titulo": pg.title(), "texto": texto}, ensure_ascii=False)); sys.exit(0)
    print(json.dumps({"error": "Operación no válida"}))
'''
FORM_OPS = {"fields", "fill", "attach", "submit"}


def form_cmd(op: str, arg: dict | None = None) -> list[str]:
    if op not in FORM_OPS:
        raise ValueError("Operación no válida")
    data = json.dumps(arg or {}, ensure_ascii=False)
    if len(data) > 100_000:
        raise ValueError("Datos demasiado largos")
    return ["python3", "-c", FORM_PY, op, data]


def docker(*args: str, timeout: int = TIMEOUT, input: bytes | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, timeout=timeout, input=input)


def safe_path(p: str) -> str:
    """Solo rutas dentro de /home/vc, sin '..'."""
    p = (p or "").strip()
    if not p.startswith("/"):
        p = f"{HOME}/trabajo/{p}"
    parts = p.split("/")
    if ".." in parts or "\x00" in p or not (p == HOME or p.startswith(HOME + "/")):
        raise ValueError("Ruta fuera de /home/vc")
    return p


def listing(rows: str) -> list[dict]:
    out = []
    for line in rows.splitlines():
        try:
            kind, size, mtime, nm = line.split("\t", 3)
        except ValueError:
            continue
        out.append({"name": nm, "dir": kind == "d", "size": int(size), "mtime": float(mtime)})
    return sorted(out, key=lambda x: (not x["dir"], x["name"].lower()))
