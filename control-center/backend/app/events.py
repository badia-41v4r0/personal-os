"""Bus de eventos: cada evento se guarda con id secuencial (tabla events) y se reparte a los suscriptores
en vivo. Un cliente que se desconecta reanuda pidiendo los eventos con id > el último que vio.
Auditoría: registro aparte, solo de acciones sensibles."""
import asyncio
import hashlib
import json
from datetime import datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .db import session_scope, utcnow
from .models import AuditLog, Event

_subscribers: set[asyncio.Queue] = set()
_loop: asyncio.AbstractEventLoop | None = None


def bind_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


def loop() -> asyncio.AbstractEventLoop | None:
    return _loop if _loop is not None and _loop.is_running() else None


def _serialize(e: Event) -> dict:
    return {"id": e.id, "ts": e.ts.isoformat() + "Z", "type": e.type, "source": e.source, "payload": e.payload}


def publish(type_: str, payload: dict[str, Any] | None = None, source: str = "backend",
            db: Session | None = None) -> dict:
    def _write(s: Session) -> dict:
        ev = Event(type=type_, source=source, payload=payload or {})
        s.add(ev)
        s.flush()
        return _serialize(ev)

    if db is not None:
        data = _write(db)
    else:
        with session_scope() as s:
            data = _write(s)
    for q in list(_subscribers):
        if _loop is not None and _loop.is_running():
            _loop.call_soon_threadsafe(_put, q, data)
    return data


def broadcast(type_: str, payload: dict[str, Any]) -> None:
    """Evento efímero (sin id ni base de datos): trozos de texto en streaming. Si se pierde, el mensaje
    completo se guarda igualmente al terminar el turno."""
    data = {"id": 0, "type": type_, "source": "stream", "payload": payload}
    for q in list(_subscribers):
        if _loop is not None and _loop.is_running():
            _loop.call_soon_threadsafe(_put, q, data)


def _put(q: asyncio.Queue, data: dict) -> None:
    try:
        q.put_nowait(data)
    except asyncio.QueueFull:
        # Cliente lento: se le marca y el WebSocket se cierra; el cliente reanuda por id
        q.overflow = True  # type: ignore[attr-defined]


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=1000)
    _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    _subscribers.discard(q)


def events_after(db: Session, after: int, limit: int = 500) -> list[dict]:
    rows = db.scalars(select(Event).where(Event.id > after).order_by(Event.id).limit(limit))
    return [_serialize(e) for e in rows]


def _hash(prev: str, ts: datetime, actor: str, action: str, target: str, outcome: str, detail: dict) -> str:
    raw = json.dumps([prev, ts.isoformat(), actor, action, target, outcome, detail], sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def audit(db: Session, actor: str, action: str, target: str = "", outcome: str = "ok", ip: str = "",
          actor_type: str = "user", run_id: str = "", action_id: str = "", **detail) -> None:
    """Cada fila encadena la huella de la anterior: cambiar o borrar una rompe la cadena (verify_chain)."""
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(7283401)"))  # dos auditorías a la vez no bifurcan la cadena
    prev = db.scalar(select(AuditLog.hash).order_by(AuditLog.id.desc()).limit(1)) or ""
    ts, target = utcnow(), target[:255]
    db.add(AuditLog(ts=ts, actor=actor, action=action, target=target, outcome=outcome, ip=ip, detail=detail,
                    actor_type=actor_type, run_id=run_id, action_id=action_id, prev_hash=prev,
                    hash=_hash(prev, ts, actor, action, target, outcome, detail)))
    db.flush()


def verify_chain(db: Session) -> dict:
    """Recorre la auditoría. Las filas anteriores a la cadena (sin huella) se saltan."""
    prev, checked = None, 0
    for r in db.scalars(select(AuditLog).where(AuditLog.hash != "").order_by(AuditLog.id)):
        if prev is not None and r.prev_hash != prev:
            return {"ok": False, "checked": checked, "broken_at": r.id}
        if r.hash != _hash(r.prev_hash, r.ts, r.actor, r.action, r.target, r.outcome, r.detail):
            return {"ok": False, "checked": checked, "broken_at": r.id}
        prev, checked = r.hash, checked + 1
    return {"ok": True, "checked": checked, "broken_at": None}
