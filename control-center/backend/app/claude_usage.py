"""Uso del límite de Claude (ventana de 5 horas y semanal) para el Dashboard.

Fuente: el evento `rate_limit_event` que Claude Code emite en cada respuesta (el mismo dato que enseña /usage).
- Cada turno de una conversación independiente del panel lo trae y se guarda.
- Cada 10 min, si no hay un dato más reciente, el Host Agent ejecuta `claude -p /usage`, que Claude Code resuelve
  sin llamar al modelo: 0 tokens, no gasta límite.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select

from . import events
from .adapters import hostagent
from .db import session_scope, utcnow
from .models import ClaudeUsage
from .security import Principal, current_principal, require_admin

log = logging.getLogger("cc.usage")
router = APIRouter(prefix="/api/v1/claude", dependencies=[Depends(current_principal)])
STALE = timedelta(minutes=10)
CHECK_EVERY = 300


def _dt(epoch) -> datetime | None:
    try:
        return datetime.fromtimestamp(float(epoch), tz=timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def parse_event(ev: dict) -> dict | None:
    """rate_limit_event de Claude Code → {five_hour, seven_day} (utilización 0–1 y reinicio)."""
    info = ev.get("rate_limit_info") or {}
    win = info.get("unifiedWindows") or {}
    out = {}
    for k in ("five_hour", "seven_day"):
        w = win.get(k) or {}
        if isinstance(w.get("utilization"), (int, float)):
            out[k] = {"utilization": float(w["utilization"]), "resets_at": w.get("resetsAt")}
    return out or None


def record(data: dict, source: str) -> dict:
    fh, sd = data.get("five_hour") or {}, data.get("seven_day") or {}
    with session_scope() as db:
        row = ClaudeUsage(five_hour=fh.get("utilization"), five_hour_resets=_dt(fh.get("resets_at")),
                          seven_day=sd.get("utilization"), seven_day_resets=_dt(sd.get("resets_at")), source=source)
        db.add(row)
        db.execute(delete(ClaudeUsage).where(ClaudeUsage.ts < utcnow() - timedelta(days=14)))
        db.flush()
        out = _out(row)
        events.publish("claude.usage", out, db=db)
    return out


def _iso(d):
    return d.isoformat() + "Z" if d else None


def _out(r: ClaudeUsage | None) -> dict:
    if r is None:
        return {"available": False}
    return {"available": True, "ts": _iso(r.ts), "source": r.source,
            "five_hour": {"utilization": r.five_hour, "resets_at": _iso(r.five_hour_resets)},
            "seven_day": {"utilization": r.seven_day, "resets_at": _iso(r.seven_day_resets)}}


def latest() -> dict:
    with session_scope() as db:
        return _out(db.scalar(select(ClaudeUsage).order_by(ClaudeUsage.id.desc()).limit(1)))


async def probe() -> dict:
    data = await hostagent.call("/v1/claude/usage", method="POST", timeout=120)
    if data.get("cached"):
        return latest()
    return record(data, "probe")


@router.get("/usage")
def get_usage():
    return latest()


@router.post("/usage/refresh")
async def refresh(p: Principal = Depends(require_admin)):
    with session_scope() as db:
        events.audit(db, p.name, "claude.usage.refresh")
    try:
        return await probe()
    except HTTPException as e:
        raise HTTPException(e.status_code, f"No se pudo consultar el uso: {e.detail}")


async def loop() -> None:
    await asyncio.sleep(20)
    while True:
        try:
            cur = latest()
            ts = datetime.fromisoformat(cur["ts"].rstrip("Z")) if cur.get("available") else None
            if ts is None or utcnow() - ts > STALE:
                await probe()
        except Exception as e:  # noqa: BLE001
            log.warning("uso de Claude: %s", e)
        await asyncio.sleep(CHECK_EVERY)
