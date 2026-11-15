"""El asistente de cada apartado del panel. Cada uno tiene su conversación del día, sus herramientas y sus permisos.

Entrenamiento usa el Coach del gym, con su MCP y sus propuestas, más las acciones de orchestrator.GYM_CAPS. Inicio es
Jarvis, que lo ve todo: no pasa por aquí.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..adapters import hostagent
from ..db import session_scope
from ..security import Principal, current_principal, require_admin
from . import modules, orchestrator, runs

router = APIRouter(prefix="/api/v1/assistants", dependencies=[Depends(current_principal)])
COACH = "coach"


class SendIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


def _spec(key: str):
    if key.startswith("onboarding-"):
        mod = key.removeprefix("onboarding-")
        spec = orchestrator.onboarding(mod) if modules.activo(mod) else None
    else:
        spec = orchestrator.SECTIONS.get(key) if modules.asistente_activo(key) else None
    if spec is None:
        raise HTTPException(404, "Asistente desconocido")
    return spec


def _sid(key: str, p: Principal) -> str | None:
    if not key.startswith("onboarding-") and not modules.asistente_activo(key):
        raise HTTPException(404, "Ese apartado está desactivado")
    if key == COACH:
        from ..gym_plan import coach_session
        with session_scope() as db:
            s = coach_session(db, p, crear=False)  # leer no crea: la conversación nace con el primer mensaje
            return s.id if s else None
    spec = _spec(key)
    return runs.section_session_id(spec, runs._day())


@router.get("/{key}/messages")
def messages(key: str, p: Principal = Depends(current_principal)):
    sid = _sid(key, p)
    return runs.session_items(sid) if sid else {"items": [], "next_offset": 0, "claude_session_id": None}


@router.get("/{key}/state")
def state(key: str, p: Principal = Depends(current_principal)):
    sid = _sid(key, p)
    return runs.session_state(sid) if sid else {"current_run": None, "queued": 0, "tmux": None}


@router.post("/{key}/messages")
async def send(key: str, body: SendIn, p: Principal = Depends(require_admin)):
    if not key.startswith("onboarding-") and not modules.asistente_activo(key):
        raise HTTPException(404, "Ese apartado está desactivado")
    if key == COACH:
        from ..gym_plan import ChatIn, coach_chat
        return await coach_chat(ChatIn(text=body.text), p)
    spec = _spec(key)
    return runs.submit(body.text, p.name, specialist=spec)


@router.post("/{key}/interrupt")
async def interrupt(key: str, p: Principal = Depends(require_admin)):
    sid = _sid(key, p)
    if sid:
        await hostagent.call(f"/v1/sessions/{sid}/stop", method="POST")
    return {"ok": True}
