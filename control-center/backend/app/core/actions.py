"""Pasarela de acciones: la única puerta de escritura de los agentes.

Un agente nunca ejecuta: pide. Cada capacidad tiene un nivel:
  1  automático: se ejecuta y queda registrado.
  2  con reglas: se ejecuta si cumple su regla; si no, o si la ejecución leyó contenido externo, pasa a 3.
  3  aprobación: espera al usuario. La aprobación queda ligada al hash del contenido.

Lo que no debe ocurrir nunca (mover dinero, leer secretos, cambiar políticas) no se registra como capacidad: no hay
camino para pedirlo. Los límites en código de gcal.py y correo.py siguen siendo el tope final.
"""
import hashlib
import json
import logging
import threading
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import events
from ..db import get_db, session_scope, utcnow
from ..models import Action, Policy, Revocation, SystemFlag
from ..security import Principal, current_principal, require_admin
from . import notifications

log = logging.getLogger("cc.actions")
router = APIRouter(prefix="/api/v1", dependencies=[Depends(current_principal)])

APPROVAL_TTL = timedelta(hours=24)
KILL_FLAG = "autonomy_paused"
Handler = Callable[[dict, Session], dict]


@dataclass(frozen=True)
class Capability:
    name: str
    level: int
    handler: Handler
    title: str
    rule: Callable[[dict, dict], bool] | None = None  # (payload, límites) -> se puede sin aprobación
    inverse: Handler | None = None  # recibe el resultado de la ejecución
    summary: Callable[[dict], str] | None = None


REGISTRY: dict[str, Capability] = {}
# Nivel que no se puede cambiar desde el panel: lo que sale a terceros sin vuelta atrás (enviar una candidatura)
FIXED_LEVEL: set[str] = set()


def register(cap: Capability) -> Capability:
    if cap.level not in (1, 2, 3):
        raise ValueError(f"{cap.name}: nivel no válido")
    REGISTRY[cap.name] = cap
    return cap


def payload_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _view(a: Action) -> dict:
    return {"id": a.id, "capability": a.capability, "level": a.level, "status": a.status, "actor": a.actor,
            "actor_type": a.actor_type, "reason": a.reason, "summary": a.summary, "payload": a.payload,
            "hash": a.payload_hash, "tainted": a.tainted, "result": a.result, "error": a.error,
            "created_at": a.created_at.isoformat() + "Z", "expires_at": a.expires_at.isoformat() + "Z" if a.expires_at else None,
            "decided_by": a.decided_by, "reversible": bool(REGISTRY.get(a.capability) and REGISTRY[a.capability].inverse)}


def _denied(capability: str, actor: str, reason: str, run_id: str = "") -> dict:
    with session_scope() as db:
        events.audit(db, actor, "action.denied", capability, outcome="denied", actor_type="agent", run_id=run_id, motivo=reason)
    return {"status": "denied", "reason": reason}


def paused(db: Session) -> bool:
    f = db.get(SystemFlag, KILL_FLAG)
    return bool(f and f.value == "1")


def _revoked(db: Session, agent: str, capability: str) -> bool:
    for r in db.scalars(select(Revocation)):
        if r.agent in ("*", agent) and r.capability in ("*", capability):
            return True
    return False


def _notify(a_id: str, summary: str) -> None:
    n = notifications.crear("action", "Jarvis pide tu aprobación", summary, "/tasks/?t=approvals", "acciones")
    threading.Thread(target=notifications._entregar, args=(n,), daemon=True).start()


def _run(action_id: str) -> dict:
    with session_scope() as db:
        a = db.get(Action, action_id)
        cap = REGISTRY[a.capability]
        a.status = "executing"
        payload = dict(a.payload)
    try:
        with session_scope() as db:
            result = cap.handler(payload, db) or {}
    except Exception as e:  # noqa: BLE001  el fallo se registra y se le cuenta al agente, nunca se reintenta a ciegas
        if isinstance(e, KeyError):
            e = ValueError(f"Falta el argumento {e}")
        log.warning("acción %s falló: %s", action_id, e)
        with session_scope() as db:
            a = db.get(Action, action_id)
            a.status, a.error, a.finished_at = "failed", str(e)[:500], utcnow()
            events.audit(db, a.actor, "action.failed", a.capability, outcome="error", actor_type=a.actor_type,
                         run_id=a.run_id, action_id=a.id, error=str(e)[:300])
            return _view(a)
    with session_scope() as db:
        a = db.get(Action, action_id)
        a.status, a.result, a.finished_at = "done", result, utcnow()
        events.audit(db, a.actor, "action.done", a.capability, actor_type=a.actor_type, run_id=a.run_id, action_id=a.id)
        events.publish("action.changed", {"id": a.id, "status": "done"}, db=db)
        return _view(a)


def request(capability: str, payload: dict, *, actor: str, actor_type: str = "agent", run_id: str = "", reason: str = "",
            idempotency_key: str | None = None, tainted: bool = False) -> dict:
    cap = REGISTRY.get(capability)
    if cap is None:
        return _denied(capability, actor, "Capacidad desconocida", run_id)
    from . import modules
    if not modules.permitido(capability):
        return _denied(capability, actor, "Ese módulo está desactivado", run_id)
    with session_scope() as db:
        if idempotency_key:
            prev = db.scalar(select(Action).where(Action.idempotency_key == idempotency_key))
            if prev:
                return _view(prev)
        policy = db.get(Policy, capability)
        if actor_type == "agent":
            why = ("La autonomía está en pausa" if paused(db) else
                   "Permiso retirado" if _revoked(db, actor, capability) else
                   "Capacidad desactivada" if policy and not policy.enabled else "")
        else:
            why = ""
    if why:
        return _denied(capability, actor, why, run_id)

    level = cap.level if capability in FIXED_LEVEL else policy.level if policy and policy.level else cap.level
    limits = policy.limits if policy else {}
    if actor_type == "user":
        needs_approval = False  # lo pide el usuario desde el panel: esa es la aprobación
    elif level == 3:
        needs_approval = True
    elif level == 2:
        needs_approval = tainted or not (cap.rule(payload, limits) if cap.rule else False)
    else:
        needs_approval = False

    summary = (cap.summary(payload) if cap.summary else cap.title)[:300]
    aid = str(uuid.uuid4())
    with session_scope() as db:
        db.add(Action(id=aid, capability=capability, level=level, status="pending" if needs_approval else "executing",
                      actor=actor, actor_type=actor_type, run_id=run_id, reason=reason, summary=summary, payload=payload,
                      payload_hash=payload_hash(payload), idempotency_key=idempotency_key, tainted=tainted,
                      expires_at=utcnow() + APPROVAL_TTL if needs_approval else None))
        events.audit(db, actor, "action.requested", capability, actor_type=actor_type, run_id=run_id, action_id=aid, nivel=level)
    if needs_approval:
        _notify(aid, summary)
        with session_scope() as db:
            return _view(db.get(Action, aid))
    return _run(aid)


def decide(action_id: str, approve: bool, seen_hash: str, by: str) -> dict:
    with session_scope() as db:
        a = db.get(Action, action_id)
        if a is None:
            raise HTTPException(404, "Acción no encontrada")
        if a.status != "pending":
            raise HTTPException(409, f"Ya está {a.status}")
        if a.expires_at and a.expires_at < utcnow():
            a.status, a.finished_at = "expired", utcnow()
            events.audit(db, by, "action.expired", a.capability, action_id=a.id)
            raise_expired = True
        else:
            raise_expired = False
            if a.payload_hash != seen_hash or payload_hash(a.payload) != seen_hash:
                raise HTTPException(409, "El contenido ha cambiado desde que lo viste")
            a.decided_by, a.decided_at = by, utcnow()
            if not approve:
                a.status, a.finished_at = "rejected", utcnow()
            events.audit(db, by, "action.approved" if approve else "action.rejected", a.capability, action_id=a.id)
            if not approve:
                events.publish("action.changed", {"id": a.id, "status": "rejected"}, db=db)
                return _view(a)
    if raise_expired:
        raise HTTPException(409, "La aprobación ha caducado")
    return _run(action_id)


def undo(action_id: str, by: str) -> dict:
    with session_scope() as db:
        a = db.get(Action, action_id)
        if a is None:
            raise HTTPException(404, "Acción no encontrada")
        cap = REGISTRY.get(a.capability)
        if a.status != "done":
            raise HTTPException(409, "Solo se puede deshacer una acción terminada")
        if cap is None or cap.inverse is None:
            raise HTTPException(409, "Esta acción no se puede deshacer")
        cap.inverse(dict(a.result), db)
        a.status = "undone"
        events.audit(db, by, "action.undone", a.capability, action_id=a.id)
        events.publish("action.changed", {"id": a.id, "status": "undone"}, db=db)
        return _view(a)


def expire_pending() -> int:
    n = 0
    with session_scope() as db:
        for a in db.scalars(select(Action).where(Action.status == "pending", Action.expires_at < utcnow())):
            a.status, a.finished_at = "expired", utcnow()
            events.audit(db, "sistema", "action.expired", a.capability, action_id=a.id, actor_type="system")
            n += 1
    return n


# ---------- API (solo el usuario; los agentes llegan por el MCP pos, nunca por aquí) ----------


class DecideIn(BaseModel):
    aprobar: bool
    hash: str = Field(min_length=64, max_length=64)


class PauseIn(BaseModel):
    pausado: bool


class RevokeIn(BaseModel):
    agente: str = Field(default="*", max_length=80)
    capacidad: str = Field(default="*", max_length=80)
    motivo: str = Field(default="", max_length=300)


class PolicyIn(BaseModel):
    nivel: int | None = Field(default=None, ge=1, le=3)
    limites: dict[str, Any] = Field(default_factory=dict)
    activa: bool = True


@router.get("/actions")
def listar(estado: str | None = None, limit: int = 100, db: Session = Depends(get_db)):
    q = select(Action).order_by(Action.created_at.desc()).limit(min(max(limit, 1), 500))
    if estado:
        q = q.where(Action.status == estado)
    return [_view(a) for a in db.scalars(q)]


@router.get("/actions/capabilities")
def capacidades(db: Session = Depends(get_db)):
    pol = {p.capability: p for p in db.scalars(select(Policy))}
    return [{"name": c.name, "title": c.title, "level": pol[c.name].level or c.level if c.name in pol else c.level,
             "default_level": c.level, "enabled": pol[c.name].enabled if c.name in pol else True,
             "reversible": c.inverse is not None} for c in sorted(REGISTRY.values(), key=lambda c: c.name)]


@router.post("/actions/{aid}/decide")
def decidir(aid: str, body: DecideIn, p: Principal = Depends(require_admin)):
    return decide(aid, body.aprobar, body.hash, p.name)


@router.post("/actions/{aid}/undo")
def deshacer(aid: str, p: Principal = Depends(require_admin)):
    return undo(aid, p.name)


@router.get("/autonomy")
def autonomia(db: Session = Depends(get_db)):
    rev = [{"id": r.id, "agente": r.agent, "capacidad": r.capability, "motivo": r.reason} for r in db.scalars(select(Revocation))]
    return {"pausado": paused(db), "revocaciones": rev}


@router.post("/autonomy/pause")
def pausar(body: PauseIn, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    f = db.get(SystemFlag, KILL_FLAG) or SystemFlag(key=KILL_FLAG)
    f.value, f.updated_by, f.updated_at = "1" if body.pausado else "0", p.name, utcnow()
    db.add(f)
    events.audit(db, p.name, "autonomy.pause" if body.pausado else "autonomy.resume")
    return {"pausado": body.pausado}


@router.post("/autonomy/revocations")
def revocar(body: RevokeIn, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    r = Revocation(agent=body.agente, capability=body.capacidad, reason=body.motivo, created_by=p.name)
    db.add(r)
    db.flush()
    events.audit(db, p.name, "autonomy.revoke", f"{body.agente}/{body.capacidad}")
    return {"id": r.id}


@router.delete("/autonomy/revocations/{rid}")
def restaurar(rid: int, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    r = db.get(Revocation, rid)
    if r is None:
        raise HTTPException(404, "No existe")
    events.audit(db, p.name, "autonomy.restore", f"{r.agent}/{r.capability}")
    db.delete(r)
    return {"ok": True}


@router.put("/actions/capabilities/{name}")
def ajustar(name: str, body: PolicyIn, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    if name not in REGISTRY:
        raise HTTPException(404, "Capacidad desconocida")
    if name in FIXED_LEVEL and body.nivel not in (None, REGISTRY[name].level):
        raise HTTPException(409, "Esta capacidad pide siempre tu aprobación: su nivel no se puede cambiar")
    pol = db.get(Policy, name) or Policy(capability=name)
    pol.level, pol.limits, pol.enabled, pol.updated_by, pol.updated_at = body.nivel, body.limites, body.activa, p.name, utcnow()
    db.add(pol)
    events.audit(db, p.name, "policy.update", name, nivel=body.nivel, activa=body.activa)
    return {"ok": True}
