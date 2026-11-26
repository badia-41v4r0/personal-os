"""Constructor: personaliza el panel hablando con él desde el chat, con vista previa antes de aplicar nada.

- Es un asistente más del chat flotante (`asistente="constructor"`), del módulo «constructor» (activo por defecto en las
  instalaciones nuevas; se apaga en Ajustes → Módulos).
- **Una personalización a la vez:** la primera conversación del Constructor reserva la vista previa
  (data/constructor/personalizacion.json). Mientras esté abierta no se puede empezar otra; se cierra al aplicar o al
  descartar. Una conversación cerrada se puede retomar (vuelve a abrir una copia nueva) si no hay otra abierta.
- Cada turno lo ejecuta el Host Agent fuera del panel (control-center/cambios/constructor.py, en el PC del usuario y
  encerrado con bubblewrap). Su salida va a data/constructor/turnos/<run>.ndjson; aquí se lee según crece y se emite
  como en el resto de chats (`session.delta`, `session.tool`). Si el panel se reinicia, `recover()` retoma la lectura.
- Aplicar y descartar pasan por el supervisor de cambios (copia de seguridad, vuelta atrás automática).
"""
import asyncio
import json
import threading
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from . import events
from .adapters import hostagent
from .config import get_settings
from .db import session_scope, utcnow
from .models import AgentRun, ChatSession, Message
from .security import Principal, current_principal, require_admin

router = APIRouter(prefix="/api/v1/constructor", dependencies=[Depends(current_principal)])
ASISTENTE = "constructor"
KIND = "conversacion"
MODELO = "opus"  # programar bien importa más que la velocidad (en otros motores, su perfil «profundo»)
ESPERA_PREPARAR = 25 * 60
_tasks: set[asyncio.Task] = set()
_crear_lock = threading.Lock()
SECRETOS = ("token", "db_url")


def _dir() -> Path:
    return get_settings().constructor_dir


def personalizacion() -> dict | None:
    """La personalización abierta, tal cual (con el token de la vista previa: solo para el proxy)."""
    try:
        return json.loads((_dir() / "personalizacion.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def publica(p: dict | None) -> dict | None:
    return {k: v for k, v in p.items() if k not in SECRETOS} if p else None


def _spawn(coro) -> None:
    t = asyncio.create_task(coro)
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)


# ---------- conversaciones ----------

def crear_conversacion(texto: str, p: Principal, nombre: str, version: str | None = None) -> str:
    """Crea la conversación y reserva la vista previa. 409 si ya hay otra personalización abierta."""
    with _crear_lock:
        abierta = personalizacion()
        if abierta:
            raise HTTPException(409, "Ya tienes una personalización abierta. Termínala (aplica o descarta los cambios) "
                                     "antes de empezar otra.")
        cid = str(uuid.uuid4())
        with session_scope() as db:
            db.add(ChatSession(id=cid, kind=KIND, name=nombre, description=ASISTENTE, model=MODELO,
                               workdir="data/constructor/copia", permissions={"asistente": ASISTENTE}))
            events.audit(db, p.name, "chat.conversacion.create", target=cid, asistente=ASISTENTE)
        try:
            hostagent.call_sync("/v1/constructor/abrir", method="POST", timeout=60,
                                json={"conversacion": cid, **({"version": version} if version else {})})
        except HTTPException:
            with session_scope() as db:
                c = db.get(ChatSession, cid)
                if c:
                    c.status = "archived"
            raise
    return cid


async def enviar(cid: str, prompt: str, p: Principal) -> dict:
    abierta = personalizacion()
    if abierta and abierta.get("conversacion") != cid:
        raise HTTPException(409, "Hay otra personalización abierta: termínala antes de seguir con esta.")
    if not abierta:  # conversación ya aplicada o descartada: se retoma con una copia nueva del panel actual
        await hostagent.call("/v1/constructor/abrir", method="POST", json={"conversacion": cid}, timeout=60)
    run_id = str(uuid.uuid4())
    with session_scope() as db:
        c = db.get(ChatSession, cid)
        c.last_activity = utcnow()
        db.add(AgentRun(id=run_id, session_id=cid, agent_id=None, channel="web", status="queued"))
        db.add(Message(session_id=cid, role="user", channel="web", content=prompt, run_id=run_id))
        events.audit(db, p.name, "chat.conversacion.send", target=cid, run=run_id, chars=len(prompt))
        events.publish("run.queued", {"run_id": run_id, "session_id": cid}, db=db)
    _spawn(_turno(cid, run_id, prompt))
    return {"run_id": run_id, "status": "queued"}


def _set_run(run_id: str, **f) -> None:
    with session_scope() as db:
        r = db.get(AgentRun, run_id)
        for k, v in f.items():
            setattr(r, k, v)


def _fin_con_error(cid: str, run_id: str, error: str) -> None:
    _set_run(run_id, status="error", error=error[:500], started_at=utcnow(), ended_at=utcnow())
    with session_scope() as db:
        db.add(Message(session_id=cid, role="assistant", channel="web", content=error, run_id=run_id))
        db.get(ChatSession, cid).status = "idle"
    events.publish("run.finished", {"run_id": run_id, "session_id": cid, "status": "error", "tools": 0})


async def _esperar_copia(cid: str, run_id: str) -> str | None:
    """Espera a que la copia del código esté lista (la primera vez tarda unos minutos). Devuelve un error o None."""
    visto, fin = "", time.monotonic() + ESPERA_PREPARAR
    while time.monotonic() < fin:
        p = personalizacion()
        if p is None:
            return "La personalización se ha cerrado mientras se preparaba."
        if p.get("estado") == "error":
            return f"No he podido preparar la copia del panel: {p.get('error') or 'error desconocido'}. Descarta y vuelve a intentarlo."
        if p.get("estado") in ("lista", "dormida") and (_dir() / "copia/.git").exists():
            if p.get("estado") == "dormida":
                try:
                    await hostagent.call("/v1/constructor/arrancar", method="POST", timeout=30)
                except HTTPException:
                    pass
            return None
        paso = p.get("paso") or "Preparando"
        if paso != visto:
            visto = paso
            events.broadcast("session.tool", {"session_id": cid, "run_id": run_id, "tool": "Preparando", "input": paso})
        await asyncio.sleep(1.5)
    return "La copia del panel tarda demasiado en prepararse. Mira Ajustes → Versiones o descarta y vuelve a intentarlo."


async def _turno(cid: str, run_id: str, prompt: str) -> None:
    from .core import proveedores as motor
    events.publish("run.started", {"run_id": run_id, "session_id": cid})
    _set_run(run_id, status="running", started_at=utcnow())
    with session_scope() as db:
        db.get(ChatSession, cid).status = "running"
    error = await _esperar_copia(cid, run_id)
    if error:
        _fin_con_error(cid, run_id, error)
        return
    with session_scope() as db:
        s = db.get(ChatSession, cid)
        run = db.get(AgentRun, run_id)
        if run.status != "running":  # interrumpida mientras se preparaba
            s.status = "idle"
            return
        t = motor.turno(db, s.model, {})
        resume = s.claude_session_id if (s.permissions or {}).get("resume_provider", "claude") == t.proveedor else None
    if t.error:
        _fin_con_error(cid, run_id, t.error)
        return
    if t.proveedor not in ("claude", "codex", "opencode"):
        _fin_con_error(cid, run_id, f"El Constructor no puede usar {motor.NOMBRES.get(t.proveedor, t.proveedor)}.")
        return
    try:
        await hostagent.call("/v1/constructor/turno", method="POST", timeout=60,
                             json={"run_id": run_id, "prompt": prompt, "proveedor": t.proveedor, "modelo": t.modelo, "resume": resume})
    except HTTPException as e:
        _fin_con_error(cid, run_id, str(e.detail))
        return
    await seguir(cid, run_id, t.proveedor)


def _etiqueta(inp: dict) -> str:
    for k in ("description", "file_path", "path", "pattern", "command", "url", "query", "prompt"):
        if inp.get(k):
            return str(inp[k])
    return ""


async def seguir(cid: str, run_id: str, proveedor: str = "claude", reanudado: bool = False) -> None:
    """Lee la salida del turno según crece y la emite; al llegar `_exit`, guarda la respuesta."""
    f = _dir() / "turnos" / f"{run_id}.ndjson"
    marca = _dir() / "turnos" / f"{run_id}.en-curso"
    pos, resto = 0, b""
    tools, pasos, texto, final, usage, error, claude_sid, terminado = [], [], [], None, {}, "", None, False
    ultimo = time.monotonic()
    while not terminado:
        datos = b""
        try:
            with f.open("rb") as fh:
                fh.seek(pos)
                datos = fh.read()
        except OSError:
            pass
        if datos:
            pos += len(datos)
            ultimo = time.monotonic()
            *lineas, resto = (resto + datos).split(b"\n")
            for linea in lineas:
                try:
                    ev = json.loads(linea)
                except ValueError:
                    continue
                tipo = ev.get("type")
                if tipo == "system" and ev.get("subtype") == "init":
                    claude_sid = ev.get("session_id") or claude_sid
                elif tipo == "stream_event" and not reanudado:
                    e = ev.get("event") or {}
                    d = e.get("delta") or {}
                    if e.get("type") == "content_block_delta" and d.get("type") == "text_delta":
                        events.broadcast("session.delta", {"session_id": cid, "run_id": run_id, "text": d.get("text", "")})
                elif tipo == "assistant":
                    for c in (ev.get("message") or {}).get("content") or []:
                        if c.get("type") == "tool_use":
                            label = _etiqueta(c.get("input") or {})
                            tools.append(c.get("name", ""))
                            pasos.append(f"{c.get('name')} {label[:300]}".strip())
                            events.broadcast("session.tool", {"session_id": cid, "run_id": run_id, "tool": c.get("name"), "input": label[:200]})
                        elif c.get("type") == "text" and c.get("text", "").strip():
                            texto.append(c["text"])
                elif tipo == "result":
                    final = ev.get("result")
                    claude_sid = ev.get("session_id") or claude_sid
                    usage = {"cost_usd": ev.get("total_cost_usd"), "duration_ms": ev.get("duration_ms"), "turns": ev.get("num_turns"),
                             **(ev.get("usage") or {}), "provider": proveedor}
                    if ev.get("is_error"):
                        error = str(final or ev.get("subtype"))[:500]
                elif tipo == "_error":
                    error = ev.get("error", "error")
                elif tipo == "_exit":
                    if ev.get("code"):
                        error = error or f"El Constructor terminó con código {ev['code']}: {ev.get('stderr', '')[-300:]}"
                    terminado = True
            continue
        if not marca.exists() and time.monotonic() - ultimo > 20:
            error = error or "El Constructor se paró sin terminar"
            break
        await asyncio.sleep(0.4)
    answer = (final if isinstance(final, str) and final.strip() else "\n\n".join(texto)).strip()
    with session_scope() as db:
        run = db.get(AgentRun, run_id)
        interrumpida = run.status == "interrupted"
        for paso in pasos:
            db.add(Message(session_id=cid, role="tool", channel="web", run_id=run_id, content=paso))
        if answer:
            db.add(Message(session_id=cid, role="assistant", channel="web", content=answer, run_id=run_id))
        elif error and not interrumpida:
            db.add(Message(session_id=cid, role="assistant", channel="web", content=f"⚠️ {error}", run_id=run_id))
        run.tools_used, run.usage, run.result, run.ended_at = tools, usage, answer[-8000:], utcnow()
        if not interrumpida:
            run.status, run.error = ("error", error) if error and not answer else ("done", error)
        s = db.get(ChatSession, cid)
        if claude_sid:
            s.claude_session_id = claude_sid
            s.permissions = {**(s.permissions or {}), "resume_provider": proveedor}
        s.status, s.last_activity = "idle", utcnow()
        status = run.status
    events.publish("run.finished", {"run_id": run_id, "session_id": cid, "status": status, "tools": len(tools)})
    p = personalizacion()
    if p and p.get("conversacion") == cid and p.get("estado") in ("lista", "dormida"):
        try:  # tras resolver una actualización, o si se durmió: que la vista previa esté en marcha
            await hostagent.call("/v1/constructor/arrancar", method="POST", timeout=30)
        except HTTPException:
            pass


def recover() -> None:
    """Al arrancar el panel: los turnos del Constructor siguen vivos fuera (su unidad); se vuelve a leer su salida."""
    if get_settings().vista_previa:
        return
    pendientes = []
    with session_scope() as db:
        q = select(AgentRun, ChatSession).join(ChatSession, ChatSession.id == AgentRun.session_id).where(
            ChatSession.kind == KIND, ChatSession.description == ASISTENTE, AgentRun.status.in_(("queued", "running")))
        for run, s in db.execute(q).all():
            if (_dir() / "turnos" / f"{run.id}.json").exists():
                pendientes.append((s.id, run.id, (s.permissions or {}).get("resume_provider", "claude")))
            else:
                run.status, run.ended_at, run.error = "error", utcnow(), "El panel se reinició mientras se preparaba"
                s.status = "idle"
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    for cid, run_id, prov in pendientes:
        _spawn(seguir(cid, run_id, prov, reanudado=True))


async def interrumpir() -> None:
    try:
        await hostagent.call("/v1/constructor/parar", method="POST", timeout=60)
    except HTTPException:
        pass


# ---------- API ----------

@router.get("")
async def estado():
    """La personalización abierta (si hay) y en qué está: preparando, vista previa en marcha, trabajando, aplicando."""
    p = personalizacion()
    unidades = {}
    try:
        unidades = await hostagent.call("/v1/constructor", timeout=15)
    except HTTPException:
        pass
    from .cambios import progreso_actual
    return {"personalizacion": publica(p), "url": "/vista-previa/" if p else None,
            "vista_previa": unidades.get("vista_previa", False), "trabajando": unidades.get("trabajando", False),
            "preparando": unidades.get("preparando", False), "aplicando": unidades.get("cambios", False),
            "bwrap": unidades.get("bwrap", True), "ultima_operacion": progreso_actual()}


class AplicarIn(BaseModel):
    titulo: str | None = Field(None, max_length=120)


@router.post("/aplicar")
async def aplicar(body: AplicarIn, p: Principal = Depends(require_admin)):
    """Lleva los cambios de la vista previa al panel real (supervisor: copia, despliegue y vuelta atrás si falla)."""
    abierta = personalizacion()
    if not abierta:
        raise HTTPException(409, "No hay ninguna personalización abierta")
    titulo = body.titulo
    if not titulo:
        with session_scope() as db:
            c = db.get(ChatSession, abierta.get("conversacion") or "")
            titulo = c.name if c else "Cambios del Constructor"
    r = await hostagent.call("/v1/cambios/aplicar", method="POST", json={"titulo": titulo}, timeout=60)
    with session_scope() as db:
        events.audit(db, p.name, "constructor.aplicar", target=abierta.get("conversacion"), titulo=titulo)
    events.publish("cambios.iniciado", {"op": "aplicar"})
    return r


@router.post("/descartar")
async def descartar(p: Principal = Depends(require_admin)):
    abierta = personalizacion()
    if not abierta:
        return {"ok": True}
    r = await hostagent.call("/v1/constructor/cerrar", method="POST", json={"motivo": "descartada"}, timeout=200)
    with session_scope() as db:
        events.audit(db, p.name, "constructor.descartar", target=abierta.get("conversacion"))
    events.publish("constructor.cerrada", {"conversacion": abierta.get("conversacion")})
    return r


class ActualizacionIn(BaseModel):
    version: str = Field(pattern=r"^v?\d{1,4}\.\d{1,4}\.\d{1,4}$")


@router.post("/actualizacion")
async def juntar_actualizacion(body: ActualizacionIn, p: Principal = Depends(require_admin)):
    """La versión nueva choca con las personalizaciones: el Constructor las junta en una vista previa (luego se aplica
    como cualquier otro cambio)."""
    v = "v" + body.version.lstrip("v")
    texto = (f"Quiero actualizar Personal OS a la versión {v.lstrip('v')}, pero choca con mis personalizaciones. Junta la "
             "versión nueva con mis cambios: conserva lo mío y lo nuevo de la versión, recompila la vista previa y "
             "explícame qué has decidido en cada conflicto.")
    cid = await asyncio.to_thread(crear_conversacion, texto, p, f"Actualizar a {v.lstrip('v')}", v)
    await enviar(cid, texto, p)
    return {"conversacion": cid}


@router.post("/despertar")
async def despertar(p: Principal = Depends(require_admin)):
    return await hostagent.call("/v1/constructor/arrancar", method="POST", timeout=30)
