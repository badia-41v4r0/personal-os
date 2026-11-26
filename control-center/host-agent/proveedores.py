"""Proveedores de IA: cómo lanzar un turno con cada CLI y cómo traducir su salida al formato del panel.

El backend entiende los eventos de `claude -p --output-format stream-json` (system/init, stream_event, assistant,
result). Cada adaptador lanza su CLI dentro del mismo contenedor efímero y traduce lo que escribe a esos eventos, así
el resto del sistema no sabe qué modelo hay detrás.

Seguridad igual para todos, sin fiarse de los permisos de cada CLI:
- contenedor efímero endurecido (raíz de solo lectura, cap_drop ALL, sin $HOME del host);
- los que no son Claude van **sin red** (`--network none`): su única salida es un proxy aparte que solo deja los
  dominios de su API (`DOMINIOS`). Aunque una CLI ejecutara un comando, no podría sacar la credencial a otro sitio;
- la credencial entra solo durante el turno (variable de entorno o archivo en el home de la sesión) y la escribe
  el Host Agent, nunca el backend;
- lo que escriben en el Personal OS pasa por el MCP `pos` y core/actions, como con Claude.

Lo que cada uno sabe hacer (CAPACIDADES) decide qué se le puede encargar. Antigravity solo entra en modo consulta
(texto, sin herramientas) hasta que su CLI se pueda ejecutar dentro del contenedor.
"""
import json
import re
import tomllib  # noqa: F401  (solo para validar en pruebas que el TOML que escribimos se lee)
from pathlib import Path

PROVEEDORES = ("claude", "codex", "opencode", "antigravity")
CAPACIDADES = {
    #            herramientas pos/gym/vc (MCP) · subagentes · reanudar · web propia · dentro del contenedor
    "claude":      {"mcp": True,  "subagentes": True,  "reanudar": True,  "web": True,  "contenedor": True},
    "codex":       {"mcp": True,  "subagentes": False, "reanudar": True,  "web": False, "contenedor": True},
    "opencode":    {"mcp": True,  "subagentes": False, "reanudar": True,  "web": False, "contenedor": True},
    "antigravity": {"mcp": False, "subagentes": False, "reanudar": False, "web": False, "contenedor": False},
}
# Únicos dominios a los que puede salir cada CLI (por el proxy). Claude usa la red del contenedor como siempre.
DOMINIOS = {
    "codex": ("chatgpt.com", "api.openai.com", "auth.openai.com", "ab.chatgpt.com"),
    "opencode": ("openrouter.ai", "opencode.ai", "api.opencode.ai", "models.dev"),
}
# OpenCode habla con varios servicios; el prefijo del modelo dice cuál y solo esa clave entra en el turno.
# opencode/… = OpenCode Zen (pago por uso) · opencode-go/… = suscripción OpenCode Go · openrouter/… = OpenRouter
CLAVES_OPENCODE = {  # servicio: (archivo en data/proveedores, variable que lee la CLI)
    "opencode": ("opencode.key", "OPENCODE_API_KEY"),
    "openrouter": ("openrouter.key", "OPENROUTER_API_KEY"),
}
SERVICIO_DE_PREFIJO = {"opencode": "opencode", "opencode-go": "opencode", "openrouter": "openrouter"}
MODELO_RE = re.compile(r"^[\w][\w./:#@+-]{0,120}$")
RESUME_RE = {
    "claude": re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$"),
    "codex": re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$"),
    "opencode": re.compile(r"^ses_[A-Za-z0-9]{10,60}$"),
}


def valida_modelo(proveedor: str, modelo: str) -> str:
    if proveedor == "claude":
        if modelo not in ("sonnet", "opus"):
            raise ValueError("Modelo no permitido")
        return modelo
    if proveedor == "codex" and not modelo:
        return ""  # el que Codex tenga por defecto
    if not MODELO_RE.match(modelo or ""):
        raise ValueError("Modelo no válido")
    return modelo


def servicio_opencode(modelo: str) -> str:
    """Qué clave necesita un modelo de OpenCode («opencode» u «openrouter»), por su prefijo."""
    pref = (modelo or "").split("/", 1)[0]
    if "/" not in (modelo or "") or pref not in SERVICIO_DE_PREFIJO:
        raise ValueError("Modelo de OpenCode no válido: usa opencode/…, opencode-go/… u openrouter/… (Ajustes → Motor de IA)")
    return SERVICIO_DE_PREFIJO[pref]


def valida_resume(proveedor: str, resume) -> str | None:
    if resume is None:
        return None
    r = RESUME_RE.get(proveedor)
    if r is None or not r.match(str(resume)):
        raise ValueError("resume inválido")
    return str(resume)


# ---------- configuración que cada CLI lee de su home ----------

def _mcp_servers(servers: dict) -> dict:
    return {n: {"command": s["command"], "args": s["args"]} for n, s in servers.items()}


def _toml_str(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)  # una cadena JSON es una cadena TOML básica válida


def codex_config(servers: dict, instrucciones: str | None) -> str:
    """~/.codex/config.toml de la sesión: sin sandbox propio (ya hay contenedor y no tiene red), nunca pregunta,
    y solo los servidores MCP de este turno."""
    lines = ['approval_policy = "never"', 'sandbox_mode = "workspace-write"', "[sandbox_workspace_write]", "network_access = false", ""]
    if instrucciones:  # developer_instructions: texto que Codex añade a sus instrucciones (comprobado con la 0.169)
        lines.insert(0, f"developer_instructions = {_toml_str(instrucciones)}")
    for n, s in _mcp_servers(servers).items():
        lines += [f"[mcp_servers.{n}]", f"command = {_toml_str(s['command'])}",
                  "args = [" + ", ".join(_toml_str(a) for a in s["args"]) + "]", ""]
    return "\n".join(lines)


def opencode_config(servers: dict, nivel: str, instrucciones_path: str | None) -> dict:
    """opencode.json de la sesión: sin terminal, edición solo si el nivel lo permite, y las claves por entorno
    (`{env:…}`), nunca escritas en el archivo. Solo la del servicio del modelo llega al turno; las demás quedan vacías."""
    permiso_editar = "allow" if nivel in ("propose", "execute") else "deny"
    cfg = {
        "$schema": "https://opencode.ai/config.json",
        "autoupdate": False, "share": "disabled",
        "permission": {"bash": "deny", "edit": permiso_editar, "webfetch": "deny"},
        "provider": {
            "opencode": {"options": {"apiKey": "{env:OPENCODE_API_KEY}"}},
            "opencode-go": {"options": {"apiKey": "{env:OPENCODE_API_KEY}"}},
            "openrouter": {"options": {"apiKey": "{env:OPENROUTER_API_KEY}"}},
        },
        "mcp": {n: {"type": "local", "command": [s["command"], *s["args"]], "enabled": True} for n, s in _mcp_servers(servers).items()},
    }
    if instrucciones_path:
        cfg["instructions"] = [instrucciones_path]
    return cfg


def preparar_home(proveedor: str, home: Path, servers: dict, nivel: str, sistema: str, credenciales: dict) -> dict:
    """Escribe en el home de la sesión lo que su CLI necesita. Devuelve variables de entorno extra (sin secretos
    salvo los que la CLI exige por entorno, que van por `env` del proceso, nunca por la línea de comandos)."""
    env: dict[str, str] = {}
    instr = None
    if sistema and proveedor == "opencode":
        (home / "instrucciones.md").write_text(sistema, encoding="utf-8")
        instr = "/home/node/instrucciones.md"
    if proveedor == "codex":
        d = home / ".codex"
        d.mkdir(exist_ok=True)
        (d / "config.toml").write_text(codex_config(servers, sistema or None), encoding="utf-8")
        auth = credenciales.get("codex_auth")
        if auth:
            (d / "auth.json").write_text(auth, encoding="utf-8")
            (d / "auth.json").chmod(0o600)
        env["CODEX_HOME"] = "/home/node/.codex"
    elif proveedor == "opencode":
        d = home / ".config/opencode"
        d.mkdir(parents=True, exist_ok=True)
        (d / "opencode.json").write_text(json.dumps(opencode_config(servers, nivel, instr), indent=1), encoding="utf-8")
        for servicio, (_, var) in CLAVES_OPENCODE.items():
            if credenciales.get(f"{servicio}_key"):
                env[var] = credenciales[f"{servicio}_key"]
    return env


def argv(proveedor: str, modelo: str, resume: str | None, cfg_extra: list[str] | None = None) -> list[str]:
    """Orden que se ejecuta dentro del contenedor (detrás de bin/sesion-run, que abre el puente al proxy).
    El mensaje del usuario entra por stdin en todos."""
    if proveedor == "codex":
        base = ["codex", "exec", "--json", "--skip-git-repo-check", *(["-m", modelo] if modelo else [])]  # el contenedor ya trabaja en /trabajo (y «resume» no admite -C)
        return (base[:2] + ["resume", resume] + base[2:] + ["-"]) if resume else base + ["-"]
    if proveedor == "opencode":
        a = ["opencode", "run", "--format", "json", "-m", modelo]
        if resume:
            a += ["--session", resume]
        return a
    raise ValueError(f"{proveedor} no se ejecuta en contenedor")


# ---------- traducción de eventos ----------

def _ev_texto(texto: str) -> dict:
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": texto}]}}


def _ev_delta(texto: str) -> dict:
    return {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": texto}}}


def _ev_tool(nombre: str, entrada: dict) -> dict:
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": nombre, "input": entrada}]}}


class Traductor:
    """Convierte la salida JSONL de una CLI en eventos estilo Claude. Guarda el estado del turno (texto, coste)."""

    def __init__(self, proveedor: str):
        self.p = proveedor
        self.sid: str | None = None
        self.textos: list[str] = []
        self.coste = 0.0
        self.usage: dict = {}
        self.error: str | None = None
        self.cerrado = False

    def linea(self, raw: str) -> list[dict]:
        try:
            ev = json.loads(raw)
        except ValueError:
            return []
        if not isinstance(ev, dict):
            return []
        return getattr(self, f"_{self.p}")(ev)

    # Codex: thread.started · item.completed (agent_message, command_execution, mcp_tool_call…) · turn.completed / turn.failed
    def _codex(self, ev: dict) -> list[dict]:
        t = ev.get("type")
        if t == "thread.started":
            self.sid = ev.get("thread_id")
            return [{"type": "system", "subtype": "init", "session_id": self.sid}]
        if t == "item.completed":
            it = ev.get("item") or {}
            tipo = it.get("type")
            if tipo == "agent_message" and str(it.get("text", "")).strip():
                self.textos.append(it["text"])
                return [_ev_delta(it["text"]), _ev_texto(it["text"])]
            if tipo and tipo not in ("reasoning", "agent_message"):
                etiqueta = it.get("command") or it.get("tool") or it.get("query") or it.get("path") or ""
                nombre = f"{it.get('server')}.{it.get('tool')}" if tipo == "mcp_tool_call" and it.get("server") else tipo
                return [_ev_tool(nombre, {"query": str(etiqueta)[:200]})]
            return []
        if t == "turn.completed":
            self.usage = ev.get("usage") or {}
            return [self._fin()]
        if t in ("turn.failed", "error"):
            err = ev.get("error") or {}
            self.error = str(err.get("message") if isinstance(err, dict) else err or ev.get("message") or "Error de Codex")[:500]
            return [self._fin()]
        return []

    # OpenCode: step_start · text · tool_use · step_finish (coste y tokens) · error
    def _opencode(self, ev: dict) -> list[dict]:
        t = ev.get("type")
        part = ev.get("part") or {}
        out = []
        if ev.get("sessionID") and not self.sid:
            self.sid = ev["sessionID"]
            out.append({"type": "system", "subtype": "init", "session_id": self.sid})
        if t == "text" and str(part.get("text", "")).strip():
            self.textos.append(part["text"])
            out += [_ev_delta(part["text"]), _ev_texto(part["text"])]
        elif t == "tool_use":
            st = part.get("state") or {}
            entrada = st.get("input") if isinstance(st.get("input"), dict) else {}
            etiqueta = entrada.get("filePath") or entrada.get("path") or entrada.get("pattern") or entrada.get("query") or entrada.get("url") or ""
            out.append(_ev_tool(str(part.get("tool") or "herramienta"), {"query": str(etiqueta)[:200]}))
        elif t == "step_finish":
            self.coste += float(part.get("cost") or 0)
            tok = part.get("tokens") or {}
            self.usage = {"input_tokens": self.usage.get("input_tokens", 0) + int(tok.get("input") or 0),
                          "output_tokens": self.usage.get("output_tokens", 0) + int(tok.get("output") or 0)}
        elif t == "error":
            err = ev.get("error") or {}
            self.error = str((err.get("data") or {}).get("message") or err.get("name") or "Error de OpenCode")[:500]
        return out

    def _fin(self) -> dict:
        self.cerrado = True
        r = {"type": "result", "result": "\n\n".join(self.textos).strip(), "session_id": self.sid, "is_error": bool(self.error),
             "total_cost_usd": round(self.coste, 6) if self.coste else None, "usage": self.usage, "proveedor": self.p}
        if self.error and not r["result"]:
            r["result"] = self.error
        return r

    def final(self) -> list[dict]:
        """Al acabar el proceso: OpenCode no manda un «fin de turno» propio."""
        return [] if self.cerrado else [self._fin()]
