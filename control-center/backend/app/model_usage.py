"""Uso normalizado de todos los proveedores de Jarvis.

Cada CLI conserva su propio formato; esta capa solo guarda ventanas {nombre, utilización
0..1, reinicio} y calcula la sugerencia de relevo.  No estima ni inventa consumo.  Claude
reutiliza `claude_usage.probe`, así que no se le pregunta dos veces.
"""
import asyncio
import json
import logging
import os
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select

from . import claude_usage, events
from .adapters import hostagent
from .config import get_settings
from .db import session_scope, utcnow
from .models import ProviderUsage
from .model_policy import choose
from .security import Principal, current_principal, require_admin

log = logging.getLogger("cc.models")
router = APIRouter(prefix="/api/v1/models", dependencies=[Depends(current_principal)])
STALE, CHECK_EVERY = timedelta(minutes=10), 300
PROVIDERS = {
    "claude": ("Claude Code", "Claude"),
    "antigravity-flash": ("Antigravity", "Gemini 3.8 Flash"),
    "antigravity-opus": ("Antigravity", "Claude Opus 4.6"),
    "codex-terra": ("Codex", "GPT-5.6 Terra"),
}


def _dt(v) -> datetime | None:
    """Reinicio en segundos o ISO → UTC sin zona."""
    try:
        d = datetime.fromtimestamp(float(v), timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        try:
            d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        except ValueError:
            return None
    return d.astimezone(timezone.utc).replace(tzinfo=None) if d.tzinfo else d


def _window(w) -> dict | None:
    if not isinstance(w, dict) or not isinstance(w.get("utilization"), (float, int)):
        return None
    reset = _dt(w.get("resets_at"))
    return {"name": str(w.get("name") or "default"), "utilization": float(w["utilization"]),
            "resets_at": reset.isoformat() + "Z" if reset else None}


def _out(r: ProviderUsage | None) -> dict:
    if r is None:
        return {"available": False, "windows": []}
    return {"available": r.available, "ts": r.ts.isoformat() + "Z", "provider": r.provider, "model": r.model,
            "windows": r.windows or [], "error": r.error or None, "source": r.source}


def latest() -> dict[str, dict]:
    with session_scope() as db:
        result = {}
        for key, (provider, model) in PROVIDERS.items():
            row = db.scalar(select(ProviderUsage).where(ProviderUsage.key == key).order_by(ProviderUsage.id.desc()).limit(1))
            result[key] = _out(row) | {"provider": provider, "model": model}
        return result


def _measured(value) -> datetime | None:
    if not isinstance(value, (int, float)):
        return None
    return datetime.fromtimestamp(value, timezone.utc).replace(tzinfo=None)


def record(key: str, raw: dict, source: str = "probe") -> dict:
    provider, model = PROVIDERS[key]
    windows = [w for w in map(_window, raw.get("windows", [])) if w]
    with session_scope() as db:
        row = ProviderUsage(key=key, provider=provider, model=model, available=bool(raw.get("available")),
                            windows=windows, error=str(raw.get("error") or "")[:500], source=source)
        measured = _measured(raw.get("measured_at"))
        if measured:  # el dato es de cuando se midió, no de cuando se leyó
            row.ts = measured
        db.add(row)
        db.execute(delete(ProviderUsage).where(ProviderUsage.ts < utcnow() - timedelta(days=14)))
        db.flush()
        out = _out(row)
        events.publish("models.usage", {"key": key, **out}, db=db)
    return out


def _claude_raw(data: dict) -> dict:
    windows = [{"name": k, **data[k]} for k in ("five_hour", "seven_day") if (data.get(k) or {}).get("utilization") is not None]
    return {"available": bool(windows), "windows": windows, "error": "" if windows else "Claude Code no devolvió el uso"}


async def probe(key: str) -> dict:
    try:
        raw = _claude_raw(await claude_usage.probe()) if key == "claude" else \
            await hostagent.call(f"/v1/models/{key}/usage", method="POST", timeout=120)
    except HTTPException as e:
        raw = {"available": False, "error": e.detail, "windows": []}
    return record(key, raw)


def publish_status() -> None:
    """orq-top lee este archivo: así enseña la misma decisión y no necesita la base del panel."""
    rows = latest()
    path = get_settings().data_dir / "models-status.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"ts": utcnow().isoformat() + "Z", "choice": asdict(choose(rows)), "providers": rows}, ensure_ascii=False))
    os.replace(tmp, path)


async def probe_all() -> dict:
    out = {key: await probe(key) for key in PROVIDERS}
    publish_status()
    return out


@router.get("/usage")
def get_usage():
    return {"providers": latest()}


@router.get("/choice")
def get_choice():
    return asdict(choose(latest()))


@router.post("/usage/refresh")
async def refresh(p: Principal = Depends(require_admin)):
    with session_scope() as db:
        events.audit(db, p.name, "models.usage.refresh")
    return {"providers": await probe_all()}


def _stale(rows: dict[str, dict]) -> bool:
    return any(not r.get("ts") or utcnow() - datetime.fromisoformat(r["ts"].rstrip("Z")) > STALE for r in rows.values())


async def loop() -> None:
    await asyncio.sleep(20)
    while True:
        try:
            if _stale(latest()):
                await probe_all()
            else:
                publish_status()
        except Exception as e:  # noqa: BLE001
            log.warning("uso de modelos: %s", e)
        await asyncio.sleep(CHECK_EVERY)
