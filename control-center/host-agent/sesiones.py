"""Sesiones independientes: cada turno es `claude -p` en un contenedor efímero y endurecido.

Lo que NO tiene una sesión, por diseño:
- Bash ni ningún intérprete: el contenedor necesita red para hablar con Claude y lleva el token en el entorno;
  con una terminal, un contenido malicioso podría intentar leerlo y sacarlo (mismo criterio que el ayudante).
  Ejecutar comandos llegará con los ordenadores virtuales (M5), sin red ni token.
- La vault, salvo que se conceda (entera o solo las rutas de su apartado, siempre en solo lectura), ni nada de Jarvis
  (su home, sus secretos). La excepción son las rutinas programadas: escriben en Jarvis/, nunca en Sistema/.
- Credenciales: solo CLAUDE_CODE_OAUTH_TOKEN, que se lee del .env en cada turno y se pasa por entorno
  (no aparece en la línea de comandos).

Niveles: read (Read, Glob, Grep) · propose (+ Edit, Write, TodoWrite en /trabajo). Internet: + WebSearch, WebFetch.
"""
import json
import os
import re
from pathlib import Path
from instancia import INST
import proveedores

SESSION_RE = re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")
CLAUDE_SID_RE = SESSION_RE
MODELS = {"sonnet", "opus"}
LEVELS = {"read", "propose", "execute"}  # execute solo con ordenador virtual: los comandos corren allí
IMAGE = f"{INST}:local"
MAX_PROMPT = 20_000
MAX_SYSTEM = 20_000
VAULT_PATH_RE = re.compile(r"^[\w][\w. -]*(/[\w][\w. -]*)*$")

TOOLS = {
    "read": ["Read", "Glob", "Grep"],
    "propose": ["Read", "Glob", "Grep", "Edit", "Write", "TodoWrite"],
    "execute": ["Read", "Glob", "Grep", "Edit", "Write", "TodoWrite"],  # + herramientas mcp__vc
}
VC_PROFILES = {"terminal", "browser", "desktop", "canvas", "aplicaciones"}
MCP_SCRIPT = "control-center/virtual-computers/mcp/vc_mcp.py"
POS_SCRIPT = "control-center/pos/pos_mcp.py"
MCP_CONFIG = '{"mcpServers":{"vc":{"command":"python3","args":["/opt/vc/vc_mcp.py"]}}}'
# Coach del gym: servidor MCP de consulta (sin ejecutar código) + el motor del gym, todo en solo lectura
ENTREGABLES = "archivos/Uni"
GYM_MCP = "control-center/gym/gym_mcp.py"
GYM_LIB = ["collectors/gym_stats.py", "collectors/gym_coach.py", "collectors/gym_musculos.json", "collectors/lib.py"]
GYM_SERVER = {"command": "python3", "args": ["/opt/gym/gym_mcp.py"]}


def mcp_servers(vc: bool, gym: bool, pos: bool = False) -> dict:
    servers = {}
    if pos:
        servers["pos"] = {"command": "python3", "args": ["/opt/pos/pos_mcp.py"]}
    if vc:
        servers["vc"] = {"command": "python3", "args": ["/opt/vc/vc_mcp.py"]}
    if gym:
        servers["gym"] = GYM_SERVER
    return servers


def mcp_config(vc: bool, gym: bool, pos: bool = False) -> str:
    return json.dumps({"mcpServers": mcp_servers(vc, gym, pos)}, separators=(",", ":"))
WEB = ["WebSearch", "WebFetch"]


def tools_for(level: str, internet: bool, subagents: bool = False) -> list[str]:
    # Los subagentes (herramienta Agent) heredan las herramientas y los permisos de su sesión: nunca más
    return TOOLS[level] + (WEB if internet else []) + (["Agent"] if subagents else [])


COPIAS = ("Diario/**", "Tareas.md")


def managed_settings(level: str, internet: bool, vault: bool, vc: bool = False, subagents: bool = False,
                     gym: bool = False, pos: bool = False, vault_write: bool = False, entregables: bool = False) -> dict:
    allow = ["Read(//trabajo/**)", "Glob", "Grep"]
    if entregables:  # solo archivos/Uni: ahí deja el tutor lo que el usuario verá en el explorador del panel
        allow += ["Read(//entregables/**)", "Edit(//entregables/**)", "Write(//entregables/**)"]
    if pos:
        allow.append("mcp__pos")  # el Personal OS decide qué abre cada ejecución, por su credencial
    if gym:
        allow.append("mcp__gym")  # consultas del gym y propuestas (que el panel valida y el usuario aprueba)
    if subagents:
        allow += ["Agent", "Task"]
    if vc:
        allow.append("mcp__vc")  # solo las herramientas de SU ordenador virtual
    if level in ("propose", "execute"):
        allow += ["Edit(//trabajo/**)", "Write(//trabajo/**)", "TodoWrite"]
    if vault:
        allow.append("Read(//vault/**)")
    if vault_write:
        allow += ["Edit(//vault/Jarvis/**)", "Write(//vault/Jarvis/**)"]
    if internet:
        allow += WEB
    protegido = "//vault/Jarvis/Sistema/**" if vault_write else "//vault/**"
    deny = ["Bash", "Read(//home/node/**)", "Read(//proc/**)", "Read(//etc/**)", "Read(//run/**)",
            f"Edit({protegido})", f"Write({protegido})", "Read(//gym/**)", "Edit(//gym/**)", "Write(//gym/**)",
            "Read(//opt/**)"]
    if vault_write:  # copias que rehace el panel desde la base: se cambian por acciones, no a mano
        deny += [f"{t}(//vault/Jarvis/{c})" for c in COPIAS for t in ("Edit", "Write")]
    if not internet:
        deny += WEB
    return {"permissions": {"defaultMode": "dontAsk", "allow": allow, "deny": deny},
            "disableSkillShellExecution": True}


def validate(body: dict) -> dict:
    sid = str(body.get("session_id", ""))
    if not SESSION_RE.match(sid):
        raise ValueError("session_id inválido")
    level = body.get("level", "read")
    if level not in LEVELS:
        raise ValueError("Nivel no permitido")
    vc = body.get("vc") or {}
    vc_on = bool(vc.get("enabled"))
    if level == "execute" and not vc_on:
        raise ValueError("Execute solo con ordenador virtual")
    if vc_on and vc.get("profile", "terminal") not in VC_PROFILES:
        raise ValueError("Perfil de ordenador no válido")
    vc_id = vc.get("vc_id")
    if vc_id is not None and not SESSION_RE.match(str(vc_id)):
        raise ValueError("vc_id inválido")
    proveedor = str(body.get("provider") or "claude")
    if proveedor not in proveedores.PROVEEDORES or not proveedores.CAPACIDADES[proveedor]["contenedor"]:
        raise ValueError("Proveedor no disponible para sesiones")
    model = proveedores.valida_modelo(proveedor, str(body.get("model", "sonnet")))
    cap = proveedores.CAPACIDADES[proveedor]
    prompt = str(body.get("prompt", ""))
    if not prompt.strip() or len(prompt) > MAX_PROMPT:
        raise ValueError("Mensaje vacío o demasiado largo")
    system = str(body.get("system_prompt") or "")
    if len(system) > MAX_SYSTEM:
        raise ValueError("Instrucciones demasiado largas")
    resume = proveedores.valida_resume(proveedor, body.get("resume"))
    if body.get("subagents") and not cap["subagentes"]:
        raise ValueError(f"{proveedor} no admite subagentes")
    if body.get("internet") and not cap["web"]:
        raise ValueError(f"{proveedor} no tiene búsqueda web en el Personal OS")
    if body.get("gym") and not body.get("vault"):
        raise ValueError("El Coach del gym necesita la vault (solo lectura)")
    pos_token = str(body.get("pos_token") or "")
    if pos_token and not re.fullmatch(r"[\w-]{32,64}", pos_token):
        raise ValueError("Credencial no válida")
    minutes = int(body.get("minutes", 30))
    paths = [str(x) for x in (body.get("vault_paths") or [])]
    if len(paths) > 12 or not all(VAULT_PATH_RE.match(x) and ".." not in x for x in paths):
        raise ValueError("Rutas de la vault no válidas")
    entregables = bool(body.get("entregables"))
    if entregables and level == "read":
        raise ValueError("La carpeta de entregables necesita escritura")
    write = bool(body.get("vault_write"))
    if write and (paths or not body.get("vault") or level == "read" or vc_on):
        raise ValueError("Solo una rutina con la vault entera escribe en ella")
    return {"session_id": sid, "provider": proveedor, "level": level, "model": model, "prompt": prompt, "system_prompt": system,
            "resume": resume, "internet": bool(body.get("internet")), "vault": bool(body.get("vault")),
            "vault_paths": paths, "vault_write": write, "entregables": entregables,
            "minutes": max(1, min(minutes, 90)), "subagents": bool(body.get("subagents")),
            "gym": bool(body.get("gym")), "pos_token": pos_token,
            "vc": {"enabled": vc_on, "profile": vc.get("profile", "terminal"), "vc_id": vc_id,
                   "owner": re.sub(r"[^a-z0-9-]", "", str(vc.get("owner", "")).lower())[:48],
                   # Documentos que puede adjuntar (huellas SHA-256): solo los de esa solicitud
                   "docs": [d for d in (vc.get("docs") or [])[:5] if re.fullmatch(r"[0-9a-f]{64}", str(d))]} if vc_on else None}


def prepare_dirs(root: Path, sid: str) -> dict[str, Path]:
    base = root / "data/sesiones" / sid
    home, trabajo = base / "home", base / "trabajo"
    for d in (base, home, trabajo):
        d.mkdir(parents=True, exist_ok=True)
        d.chmod(0o700)
    cfg = home / ".claude.json"
    if not cfg.exists():
        cfg.write_text(json.dumps({"hasCompletedOnboarding": True,
                                   "projects": {"/trabajo": {"hasTrustDialogAccepted": True}}}))
    gw = base / "gw"
    gw.mkdir(exist_ok=True)
    gw.chmod(0o700)
    egress = base / "egress"  # socket del proxy de salida (solo proveedores sin red propia)
    egress.mkdir(exist_ok=True)
    egress.chmod(0o700)
    return {"base": base, "home": home, "trabajo": trabajo, "settings": base / "managed-settings.json", "gw": gw, "egress": egress}


def container_name(sid: str) -> str:
    return f"{INST}-ses-{sid[:8]}"


SESION_RUN = "bin/sesion-run"
PUENTE = "programador/puente.js"


def docker_argv(root: Path, req: dict, dirs: dict[str, Path], env_extra: tuple[str, ...] = ()) -> list[str]:
    """`env_extra`: nombres de variables que el proceso ya trae (sus valores nunca van en la línea de comandos)."""
    claude = req.get("provider", "claude") == "claude"
    argv = [
        "docker", "run", "--rm", "-i", "--name", container_name(req["session_id"]),
        "--label", f"{INST}.session={req['session_id']}",
        "--read-only", "--tmpfs", "/tmp:size=256m", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--memory", "1g", "--cpus", "1", "--pids-limit", "256",
        # Claude sale a internet como siempre; el resto, sin red: solo su proxy con los dominios de su API
        "--network", "bridge" if claude else "none",
        *(["-e", "CLAUDE_CODE_OAUTH_TOKEN"] if claude else [x for n in env_extra for x in ("-e", n)]),
        "-e", "HOME=/home/node", "-e", "DISABLE_AUTOUPDATER=1", "-e", f"TZ={os.environ.get('POS_TZ', 'Europe/Madrid')}",
        "-v", f"{dirs['home']}:/home/node", "-v", f"{dirs['trabajo']}:/trabajo",
        "-v", f"{dirs['settings']}:/etc/claude-code/managed-settings.json:ro",
        "-w", "/trabajo", "--entrypoint", "claude" if claude else "/opt/sesion/run",
    ]
    if not claude:
        argv += ["-v", f"{dirs['egress']}:/run/egress:ro", "-v", f"{root / SESION_RUN}:/opt/sesion/run:ro",
                 "-v", f"{root / PUENTE}:/opt/sesion/puente.js:ro"]
    if req["vault"]:
        if req.get("vault_paths"):  # solo lo de su apartado: lo demás ni existe dentro del contenedor
            for x in req["vault_paths"]:
                if (root / "Jarvis-Vault" / x).exists():
                    argv += ["-v", f"{root / 'Jarvis-Vault' / x}:/vault/{x}:ro"]
        else:
            argv += ["-v", f"{root / 'Jarvis-Vault'}:/vault:ro"]
        if req.get("vault_write"):
            argv += ["-v", f"{root / 'Jarvis-Vault/Jarvis'}:/vault/Jarvis:rw", "-v", f"{root / 'Jarvis-Vault/Jarvis/Sistema'}:/vault/Jarvis/Sistema:ro"]
    if req.get("entregables"):
        ent = root / ENTREGABLES  # solo esta carpeta, nunca la común entera (ahí está la bandeja de entrada)
        ent.mkdir(parents=True, exist_ok=True, mode=0o700)
        argv += ["-v", f"{ent}:/entregables:rw"]
    if req["vc"]:
        argv += ["-v", f"{dirs['gw']}:/run/vc", "-v", f"{root / MCP_SCRIPT}:/opt/vc/vc_mcp.py:ro"]
    if req.get("pos_token"):
        argv += ["-v", f"{dirs['gw']}:/run/pos", "-v", f"{root / POS_SCRIPT}:/opt/pos/pos_mcp.py:ro"]
    if req.get("gym"):
        if not req["vault"]:
            raise ValueError("El Coach del gym necesita la vault (solo lectura)")
        gym = dirs["base"] / "gym"
        (gym / "salida").mkdir(parents=True, exist_ok=True)
        argv += ["-v", f"{gym}:/gym", "-v", f"{root / GYM_MCP}:/opt/gym/gym_mcp.py:ro"]
        for f in GYM_LIB:
            argv += ["-v", f"{root / f}:/opt/gym/{Path(f).name}:ro"]
    if not claude:
        return argv + [IMAGE, *proveedores.argv(req["provider"], req["model"], req["resume"])]
    argv += [IMAGE, "-p", "--output-format", "stream-json", "--verbose", "--include-partial-messages",
             "--model", req["model"], "--permission-mode", "dontAsk", "--strict-mcp-config",
             "--tools", ",".join(tools_for(req["level"], req["internet"], req["subagents"]))]
    if req["vault"]:
        argv += ["--add-dir", "/vault"]
    if req.get("entregables"):
        argv += ["--add-dir", "/entregables"]
    if req["vc"] or req.get("gym") or req.get("pos_token"):
        argv += ["--mcp-config", mcp_config(bool(req["vc"]), bool(req.get("gym")), bool(req.get("pos_token")))]
    if req["resume"]:
        argv += ["--resume", req["resume"]]
    if req["system_prompt"]:
        argv += ["--append-system-prompt", req["system_prompt"]]
    return argv


def read_token(root: Path) -> str:
    for line in (root / ".env").read_text().splitlines():
        if line.startswith("CLAUDE_CODE_OAUTH_TOKEN="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("Falta CLAUDE_CODE_OAUTH_TOKEN en .env")
