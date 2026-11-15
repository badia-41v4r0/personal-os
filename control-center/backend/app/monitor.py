"""Monitor: historial de métricas, alertas y retención.

Cada minuto el backend pide al Host Agent métricas, servicios, contenedores y el estado de tmux, guarda una
muestra (14 días) y evalúa reglas. Una alerta por clave: se abre, sigue abierta mientras dure y se resuelve
sola. Las críticas se avisan a través del Host Agent (bin/telegram-send.sh, que además deja el aviso para la bandeja
y el push; el backend no ve el token), como mucho una vez cada 6 horas por clave.
"""
import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from . import events
from .config import INSTANCE
from .adapters import hostagent
from .core import notifications
from .db import get_db, session_scope, utcnow
from .models import Alert, Event, MetricSample
from .security import Principal, current_principal, require_admin
from .marca import asistente

log = logging.getLogger("cc.monitor")
router = APIRouter(prefix="/api/v1", dependencies=[Depends(current_principal)])

INTERVAL = 60
KEEP_SAMPLES = timedelta(days=14)
KEEP_EVENTS = timedelta(days=14)
KEEP_CHAT_EVENTS = timedelta(days=2)
NOTIFY_EVERY = timedelta(hours=6)
SUSTAINED = 5  # muestras seguidas (≈5 min) para CPU y RAM


@dataclass
class Finding:
    key: str
    severity: str
    title: str
    detail: str = ""


def evaluate(snap: dict, recent: list[dict]) -> list[Finding]:
    """Reglas. `snap`: lo leído ahora; `recent`: últimas muestras (la actual incluida), de antigua a nueva."""
    out: list[Finding] = []
    if snap.get("host_agent") is False:
        out.append(Finding("hostagent:down", "critical", "El Host Agent no responde",
                           f"Sin él no hay métricas ni se puede escribir a {asistente()} desde el panel."))
        return out
    m = snap.get("metrics") or {}
    last = recent[-SUSTAINED:]
    if len(last) == SUSTAINED and all(s["cpu"] >= 90 for s in last):
        out.append(Finding("cpu:alta", "warning", "CPU por encima del 90 % durante 5 min", f"Ahora {m['cpu']['pct']:.0f} %"))
    if len(last) == SUSTAINED and all(s["mem"] >= 92 for s in last):
        out.append(Finding("ram:alta", "warning", "RAM por encima del 92 % durante 5 min", f"Ahora {m['memory']['pct']:.0f} %"))
    for d in m.get("disks", []):
        if d["pct"] >= 97:
            out.append(Finding(f"disco:{d['mount']}", "critical", f"Disco {d['mount']} casi lleno", f"{d['pct']:.0f} %"))
        elif d["pct"] >= 90:
            out.append(Finding(f"disco:{d['mount']}", "warning", f"Disco {d['mount']} por encima del 90 %", f"{d['pct']:.0f} %"))
    for chip, t in (m.get("temperatures") or {}).items():
        if t >= 90:
            out.append(Finding(f"temp:{chip}", "warning", f"Temperatura alta ({chip})", f"{t:.0f} °C"))
    for g in m.get("gpu") or []:
        if g["temp_c"] >= 85:
            out.append(Finding("temp:gpu", "warning", "GPU caliente", f"{g['temp_c']:.0f} °C"))
    for u in snap.get("services") or []:
        if u.get("scope") != "user":
            if u.get("ActiveState") != "active":
                out.append(Finding(f"unidad:{u['Id']}", "critical", f"{u['Id']} no está activo", u.get("SubState", "")))
            continue
        if u.get("ActiveState") == "failed" or (u.get("Result") and u["Result"] not in ("success", "")):
            out.append(Finding(f"unidad:{u['Id']}", "critical", f"{u['Id']} ha fallado", f"Resultado: {u.get('Result')}"))
    conts = snap.get("containers")
    if conts is not None:
        j = next((c for c in conts if c["Names"] == INSTANCE), None)
        if not j or j["State"] != "running":
            out.append(Finding(f"contenedor:{INSTANCE}", "critical", f"El contenedor de {asistente()} no está en marcha",
                               j["Status"] if j else "No existe"))
    return out


def _sample(m: dict) -> dict:
    temps = list((m.get("temperatures") or {}).values())
    g = (m.get("gpu") or [None])[0]
    return {"cpu": m["cpu"]["pct"], "mem": m["memory"]["pct"], "swap": m["swap"]["pct"],
            "temp": max(temps) if temps else None,
            "gpu": g["util_pct"] if g else None, "vram": 100 * g["vram_used_mb"] / g["vram_total_mb"] if g else None,
            "gpu_temp": g["temp_c"] if g else None,
            "disk": max((d["pct"] for d in m.get("disks", [])), default=0.0),
            "net_sent": m["net"]["bytes_sent"], "net_recv": m["net"]["bytes_recv"]}


async def snapshot() -> dict:
    snap: dict = {}
    try:
        snap["metrics"] = await hostagent.call("/v1/metrics")
    except Exception:  # noqa: BLE001
        snap["host_agent"] = False
        return snap
    snap["host_agent"] = True
    for key, path in (("services", "/v1/services"), ("containers", "/v1/containers")):
        try:
            snap[key] = await hostagent.call(path)
        except Exception:  # noqa: BLE001
            snap[key] = None
    return snap


async def notify(text: str) -> bool:
    try:
        await hostagent.call("/v1/notify/telegram", method="POST", json={"text": text, "level": "critical"}, timeout=30)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("aviso por Telegram falló: %s", e)
        return False


async def apply(findings: list[Finding]) -> None:
    now = utcnow()
    to_notify: list[tuple[int, Finding]] = []
    with session_scope() as db:
        open_ = {a.key: a for a in db.scalars(select(Alert).where(Alert.status == "open"))}
        seen = set()
        for f in findings:
            seen.add(f.key)
            a = open_.get(f.key)
            if a is None:
                a = Alert(key=f.key, severity=f.severity, title=f.title, detail=f.detail, started_at=now)
                db.add(a)
                db.flush()
                events.publish("alert.raised", {"id": a.id, "key": f.key, "severity": f.severity, "title": f.title}, db=db)
            else:
                a.detail, a.severity, a.title = f.detail, f.severity, f.title
            if f.severity == "critical" and not a.notified:
                recent_notice = db.scalar(select(func.max(Alert.started_at)).where(
                    Alert.key == f.key, Alert.notified.is_(True), Alert.started_at > now - NOTIFY_EVERY))
                if recent_notice is None:
                    to_notify.append((a.id, f))
                a.notified = True  # aunque se omita por el límite, no se reintenta en cada minuto
        for key, a in open_.items():
            if key not in seen:
                a.status, a.resolved_at = "resolved", now
                events.publish("alert.resolved", {"id": a.id, "key": key, "title": a.title}, db=db)
    for _, f in to_notify:
        await notify(f"⚠️ Control Center: {f.title}" + (f"\n{f.detail}" if f.detail else ""))


def prune(db: Session) -> None:
    now = utcnow()
    db.execute(delete(MetricSample).where(MetricSample.ts < now - KEEP_SAMPLES))
    db.execute(delete(Event).where(Event.type == "chat.updated", Event.ts < now - KEEP_CHAT_EVENTS))
    db.execute(delete(Event).where(Event.ts < now - KEEP_EVENTS))
    db.execute(delete(Alert).where(Alert.status == "resolved", Alert.resolved_at < now - timedelta(days=30)))
    notifications.prune(db)


async def tick() -> None:
    snap = await snapshot()
    recent: list[dict] = []
    with session_scope() as db:
        if snap.get("metrics"):
            s = _sample(snap["metrics"])
            db.add(MetricSample(**s))
            db.flush()
        rows = db.scalars(select(MetricSample).order_by(MetricSample.id.desc()).limit(SUSTAINED))
        recent = [{"cpu": r.cpu, "mem": r.mem} for r in reversed(list(rows))]
        prune(db)
    await apply(evaluate(snap, recent))


async def loop() -> None:
    await asyncio.sleep(5)
    while True:
        try:
            await tick()
        except Exception as e:  # noqa: BLE001
            log.exception("monitor: %s", e)
        await asyncio.sleep(INTERVAL)


_task: asyncio.Task | None = None


def start() -> None:
    global _task
    _task = asyncio.create_task(loop())


async def stop() -> None:
    if _task:
        _task.cancel()


# ---------- API ----------

RANGES = {"1h": timedelta(hours=1), "6h": timedelta(hours=6), "24h": timedelta(hours=24),
          "7d": timedelta(days=7), "14d": timedelta(days=14)}


@router.get("/system/metrics/history")
def history(rng: str = Query("24h", alias="range"), db: Session = Depends(get_db)):
    if rng not in RANGES:
        raise HTTPException(422, f"range: {', '.join(RANGES)}")
    since = utcnow() - RANGES[rng]
    rows = list(db.scalars(select(MetricSample).where(MetricSample.ts >= since).order_by(MetricSample.ts)))
    # Reducir a ≤ 240 puntos (media por tramo); la red se convierte en velocidad (KB/s)
    step = max(1, len(rows) // 240)
    out = []
    for i in range(0, len(rows), step):
        chunk = rows[i:i + step]
        avg = lambda k: (lambda v: round(sum(v) / len(v), 1) if v else None)([getattr(r, k) for r in chunk if getattr(r, k) is not None])  # noqa: E731
        prev = rows[i - 1] if i else None
        last = chunk[-1]
        rate = lambda k: (max(0, getattr(last, k) - getattr(prev, k)) / max(1, (last.ts - prev.ts).total_seconds()) / 1024) if prev else None  # noqa: E731
        out.append({"ts": chunk[0].ts.isoformat() + "Z", "cpu": avg("cpu"), "mem": avg("mem"), "swap": avg("swap"),
                    "temp": avg("temp"), "gpu": avg("gpu"), "vram": avg("vram"), "gpu_temp": avg("gpu_temp"),
                    "disk": avg("disk"), "net_up": round(rate("net_sent"), 1) if prev else None,
                    "net_down": round(rate("net_recv"), 1) if prev else None})
    return {"range": rng, "points": out, "interval_s": INTERVAL * step}


@router.get("/alerts")
def alerts(status: str = "open", limit: int = 50, db: Session = Depends(get_db)):
    q = select(Alert).order_by(Alert.started_at.desc()).limit(min(max(limit, 1), 200))
    if status != "all":
        q = q.where(Alert.status == status)
    iso = lambda d: d.isoformat() + "Z" if d else None  # noqa: E731
    return [{"id": a.id, "key": a.key, "severity": a.severity, "title": a.title, "detail": a.detail, "status": a.status,
             "started_at": iso(a.started_at), "resolved_at": iso(a.resolved_at), "notified": a.notified}
            for a in db.scalars(q)]


@router.post("/alerts/{aid}/resolve")
def resolve_alert(aid: int, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    a = db.get(Alert, aid)
    if a is None:
        raise HTTPException(404, "Alerta no encontrada")
    a.status, a.resolved_at = "resolved", datetime.utcnow()
    events.audit(db, p.name, "alert.resolve", target=a.key)
    events.publish("alert.resolved", {"id": a.id, "key": a.key, "title": a.title}, db=db)
    return {"ok": True}
