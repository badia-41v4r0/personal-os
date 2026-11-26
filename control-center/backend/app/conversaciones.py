"""Conversaciones del chat del panel (estilo ChatGPT): varias por asistente, cada una con su contexto.

Cada conversación es una ChatSession `kind="conversacion"`. En `description` va la clave de su asistente (jarvis, coach o
la de un apartado: tutor, finanzas…) y su título es el primer mensaje. Los turnos usan el mismo motor que el resto:
el especialista del apartado con sus permisos (core.runs) o, para el Coach, sus herramientas del gym (sessions).
El texto y las herramientas llegan en directo con `session.delta` y `session.tool`; los pasos quedan guardados como
mensajes `role="tool"` para el «Ha mirado X cosas» de cada respuesta.

La sesión compartida con Telegram queda para avisos: no pasa por aquí.
"""
import asyncio
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from . import events, sessions
from .core import modules, orchestrator, runs
from .db import get_db, session_scope, utcnow
from .models import AgentRun, ChatSession, Message
from .security import Principal, current_principal, require_admin

router = APIRouter(prefix="/api/v1/conversaciones", dependencies=[Depends(current_principal)])
KIND = "conversacion"
JARVIS, COACH, CONSTRUCTOR = "jarvis", "coach", "constructor"
TITULO_MAX = 70
_tasks: set[asyncio.Task] = set()


def _iso(d):
    return d.isoformat() + "Z" if d else None


def _activo(key: str) -> bool:
    if key == JARVIS:
        return True
    if key not in (COACH, CONSTRUCTOR) and key not in orchestrator.SECTIONS:
        return False
    return modules.asistente_activo(key)


def titulo(texto: str) -> str:
    """El primer mensaje, en una línea y cortado por una palabra."""
    t = re.sub(r"\s+", " ", texto.split("\n\n📎")[0]).strip() or "Archivos adjuntos"
    if len(t) <= TITULO_MAX:
        return t
    corte = t[:TITULO_MAX].rsplit(" ", 1)[0]
    return (corte if len(corte) > 20 else t[:TITULO_MAX]).rstrip(" ,.;:") + "…"


def _spec(c: ChatSession) -> orchestrator.Specialist:
    key = c.description
    if key == JARVIS:
        nombre = (c.permissions or {}).get("especialista", "jarvis")
        return orchestrator.SPECIALISTS.get(nombre, orchestrator.DEFAULT)
    return orchestrator.SECTIONS[key]


def _conv(c: ChatSession, mensajes: int | None = None) -> dict:
    return {"id": c.id, "asistente": c.description, "titulo": c.name, "estado": c.status,
            "creada": _iso(c.created_at), "actividad": _iso(c.last_activity), "mensajes": mensajes}


def _get(db: Session, cid: str) -> ChatSession:
    c = db.get(ChatSession, cid)
    if c is None or c.kind != KIND or c.status == "archived":
        raise HTTPException(404, "Conversación no encontrada")
    if not _activo(c.description):
        raise HTTPException(404, "Ese apartado está desactivado")
    return c


@router.get("")
def listar(asistente: str | None = None, q: str = "", limit: int = 60, db: Session = Depends(get_db)):
    """Las conversaciones con algún mensaje, de la más reciente a la más antigua. `q` busca en el título y en lo dicho."""
    n = select(func.count(Message.id)).where(Message.session_id == ChatSession.id, Message.role.in_(("user", "assistant"))).scalar_subquery()
    sel = select(ChatSession, n).where(ChatSession.kind == KIND, ChatSession.status != "archived",
                                       exists().where(Message.session_id == ChatSession.id))
    if asistente:
        sel = sel.where(ChatSession.description == asistente)
    q = q.strip()
    if q:
        patron = f"%{q[:100]}%"
        sel = sel.where(or_(ChatSession.name.ilike(patron), exists().where(
            Message.session_id == ChatSession.id, Message.role.in_(("user", "assistant")), Message.content.ilike(patron))))
    rows = db.execute(sel.order_by(ChatSession.last_activity.desc()).limit(min(max(limit, 1), 200))).all()
    return [_conv(c, m) for c, m in rows if _activo(c.description)]


class CrearIn(BaseModel):
    asistente: str = Field(min_length=1, max_length=40)
    texto: str = Field("", max_length=20_000)  # el primer mensaje: da el título y, en Jarvis, el especialista


def crear_conversacion(asistente: str, texto: str, p: Principal) -> str:
    if not _activo(asistente):
        raise HTTPException(404, "Asistente desconocido o desactivado")
    cid, nombre = str(uuid.uuid4()), titulo(texto)
    if asistente == CONSTRUCTOR:  # una sola personalización abierta a la vez (409 si ya hay otra)
        from . import constructor
        return constructor.crear_conversacion(texto, p, nombre)
    if asistente == COACH:
        from .gym_plan import coach_prompt, coach_scope
        with session_scope() as db:
            db.add(ChatSession(id=cid, kind=KIND, name=nombre, description=COACH, model="sonnet", workdir=f"data/sesiones/{cid}/trabajo",
                               permissions={"level": "read", "internet": False, "vault": True, "gym": True, "system_prompt": coach_prompt(), **coach_scope(),
                                            "minutes": 15, "vc": {"enabled": False, "profile": "terminal", "vc_id": None}, "subagents": False,
                                            "asistente": COACH}))
    else:
        spec = orchestrator.pick(texto) if asistente == JARVIS else orchestrator.SECTIONS[asistente]
        runs.ensure(spec, sid=cid, nombre=nombre, kind=KIND)
        with session_scope() as db:
            c = db.get(ChatSession, cid)
            c.description = asistente
            c.permissions = {**(c.permissions or {}), "asistente": asistente, "especialista": spec.name}
    with session_scope() as db:
        events.audit(db, p.name, "chat.conversacion.create", target=cid, asistente=asistente)
    return cid


@router.post("")
def crear(body: CrearIn, p: Principal = Depends(require_admin)):
    """Crea la conversación vacía (para poder subirle adjuntos). El primer mensaje se envía después, con /mensajes."""
    cid = crear_conversacion(body.asistente, body.texto, p)
    with session_scope() as db:
        return _conv(db.get(ChatSession, cid), 0)


@router.get("/{cid}")
def ver(cid: str, db: Session = Depends(get_db)):
    """La conversación entera: mensajes, pasos (role=tool) y el estado de cada respuesta."""
    c = _get(db, cid)
    msgs = db.scalars(select(Message).where(Message.session_id == cid, Message.role.in_(("user", "assistant", "tool"))).order_by(Message.id))
    rs = db.scalars(select(AgentRun).where(AgentRun.session_id == cid).order_by(AgentRun.created_at))
    return {"conversacion": _conv(c),
            "mensajes": [{"id": m.id, "rol": m.role, "texto": m.content, "run_id": m.run_id, "ts": _iso(m.created_at)} for m in msgs],
            "respuestas": [{"id": r.id, "estado": r.status, "inicio": _iso(r.started_at), "fin": _iso(r.ended_at),
                            "creada": _iso(r.created_at), "error": r.error or ""} for r in rs]}


class EnviarIn(BaseModel):
    texto: str = Field("", max_length=20_000)
    adjuntos: list[str] = Field(default_factory=list, max_length=sessions.MAX_FILES)


@router.post("/{cid}/mensajes")
async def enviar(cid: str, body: EnviarIn, p: Principal = Depends(require_admin)):
    with session_scope() as db:
        c = _get(db, cid)
        key, ocupada = c.description, db.scalar(select(AgentRun.id).where(
            AgentRun.session_id == cid, AgentRun.status.in_(("queued", "running"))).limit(1))
        spec = None if key in (COACH, CONSTRUCTOR) else _spec(c)
    if ocupada:
        raise HTTPException(409, "Aún está respondiendo: espera o interrúmpelo")
    prompt = sessions._prompt_with_files(cid, body.texto, body.adjuntos)
    if key == CONSTRUCTOR:
        from . import constructor
        return await constructor.enviar(cid, prompt, p)
    if key == COACH:
        from .gym_plan import coach_prompt, coach_scope
        run_id = str(uuid.uuid4())
        with session_scope() as db:
            c = db.get(ChatSession, cid)
            c.permissions = {**(c.permissions or {}), "system_prompt": coach_prompt(), **coach_scope()}  # al día en cada turno
            c.last_activity = utcnow()
            db.add(AgentRun(id=run_id, session_id=cid, agent_id=None, channel="web", status="queued"))
            db.add(Message(session_id=cid, role="user", channel="web", content=prompt, run_id=run_id))
            events.audit(db, p.name, "chat.conversacion.send", target=cid, run=run_id, chars=len(body.texto))
            events.publish("run.queued", {"run_id": run_id, "session_id": cid}, db=db)
        t = asyncio.create_task(sessions._run(cid, run_id, prompt))
        _tasks.add(t)
        t.add_done_callback(_tasks.discard)
        return {"run_id": run_id, "status": "queued"}
    r = await asyncio.to_thread(runs.submit, prompt, p.name, specialist=spec, sid=cid)
    with session_scope() as db:
        db.get(ChatSession, cid).last_activity = utcnow()
    return r


@router.post("/{cid}/interrumpir")
async def interrumpir(cid: str, p: Principal = Depends(require_admin)):
    from .adapters import hostagent
    with session_scope() as db:
        asistente = _get(db, cid).description
        pendientes = list(db.scalars(select(AgentRun).where(AgentRun.session_id == cid, AgentRun.status.in_(("queued", "running")))))
        for r in pendientes:
            r.status, r.ended_at, r.error = "interrupted", utcnow(), "Interrumpida desde el panel"
        ids = [r.id for r in pendientes]
        events.audit(db, p.name, "chat.conversacion.interrupt", target=cid)
    for i in ids:
        events.publish("run.interrupted", {"run_id": i, "session_id": cid})
    if asistente == CONSTRUCTOR:
        from . import constructor
        await constructor.interrumpir()
        return {"interrumpidas": ids}
    try:
        await hostagent.call(f"/v1/sessions/{cid}/stop", method="POST")
    except Exception:  # noqa: BLE001  sin contenedor en marcha no hay nada que parar
        pass
    return {"interrumpidas": ids}


@router.post("/{cid}/adjuntos")
async def adjuntar(cid: str, request: Request, name: str, p: Principal = Depends(require_admin)):
    with session_scope() as db:
        _get(db, cid)
    return await sessions.guardar_adjunto(cid, request, name, p.name, kinds=(KIND,))


class CambiarIn(BaseModel):
    titulo: str = Field(min_length=1, max_length=120)


@router.patch("/{cid}")
def renombrar(cid: str, body: CambiarIn, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    c = _get(db, cid)
    c.name = body.titulo.strip()[:120]
    events.audit(db, p.name, "chat.conversacion.rename", target=cid)
    return _conv(c)


@router.delete("/{cid}")
def archivar(cid: str, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    """No se borra: se archiva (deja de verse, pero sigue en la base y en la memoria)."""
    c = _get(db, cid)
    c.status = "archived"
    events.audit(db, p.name, "chat.conversacion.archive", target=cid)
    return {"ok": True}
