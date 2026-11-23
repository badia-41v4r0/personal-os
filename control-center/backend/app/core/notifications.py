"""Avisos: bandeja del panel y Web Push.

Todo aviso se guarda primero en la bandeja; el push es solo una forma de entregarlo, así que nada se pierde si el
móvil no lo recibe. El backend sale por HTTPS al servicio de push del navegador (Apple en el iPhone) y el contenido
va cifrado de extremo a extremo (RFC 8291): el panel sigue siendo privado y no se abre ningún puerto.

Los scripts del PC dejan avisos en data/control-center/avisos/ (bin/telegram-send.sh): sin credenciales del panel y
sin que el backend vea el token de Telegram. Ningún contenedor monta esa carpeta.
"""
import asyncio
import base64
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from .. import events
from ..config import TZ_NAME, get_settings as settings
from ..db import get_db, session_scope, utcnow
from ..models import Notification, PushSubscription
from ..security import Principal, current_principal, require_admin

log = logging.getLogger("cc.avisos")
router = APIRouter(prefix="/api/v1", dependencies=[Depends(current_principal)])

LEVELS = ("critical", "action", "info", "silent")
DEFAULT_URL = "/bandeja/"
TZ = ZoneInfo(TZ_NAME)
QUIET_FROM, QUIET_TO = (23, 0), (7, 30)  # los `info` de madrugada esperan en la bandeja, sin sonar
PUSH_BODY_MAX = 180
PUSH_TTL = 12 * 3600
# Solo servicios de push reales: el endpoint lo manda el navegador y el backend va a llamarlo.
PUSH_HOSTS = ("push.apple.com", "fcm.googleapis.com", "push.services.mozilla.com", "notify.windows.com")
DAILY_TEST_HOUR = 12
DAILY_TEST_DAYS = 7  # prueba diaria solo la primera semana, para validar el canal
SPOOL_EVERY = 2
SPOOL_MAX_BYTES = 8192
KEEP_READ = timedelta(days=90)


def _spool() -> Path:
    return settings().data_dir / "avisos"


def _vapid_path() -> Path:
    return settings().data_dir / "vapid.pem"


def _vapid():
    """Claves del servidor: se crean una vez. Si se perdieran, habría que volver a activar los avisos en el móvil."""
    from py_vapid import Vapid
    path = _vapid_path()
    if path.exists():
        return Vapid.from_file(str(path))
    v = Vapid()
    v.generate_keys()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(v.private_pem())
    return v


def public_key() -> str:
    from cryptography.hazmat.primitives import serialization
    raw = _vapid().public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _claim_sub() -> str:
    """Contacto del servidor para el servicio de push. py_vapid no admite URL con puerto: va solo el host."""
    if os.environ.get("CC_VAPID_SUB"):
        return os.environ["CC_VAPID_SUB"]
    for origin in settings().allowed_origins:
        u = urlsplit(origin)
        if u.scheme == "https" and u.hostname:
            return f"https://{u.hostname}"
    return "mailto:panel@jarvis.invalid"


def is_quiet(now: datetime | None = None) -> bool:
    local = (now or datetime.now(timezone.utc)).astimezone(TZ)
    t = (local.hour, local.minute)
    return t >= QUIET_FROM or t < QUIET_TO


def _safe_url(url: str) -> str:
    return url if url.startswith("/") and not url.startswith("//") and len(url) <= 255 else DEFAULT_URL


def crear(level: str, title: str, body: str = "", url: str = DEFAULT_URL, source: str = "sistema") -> dict:
    level = level if level in LEVELS else "info"
    title = " ".join(title.split())[:160] or "Aviso"
    with session_scope() as db:
        n = Notification(level=level, title=title, body=body[:4000], url=_safe_url(url), source=source[:48])
        db.add(n)
        db.flush()
        out = {"id": n.id, "level": level, "title": title, "body": n.body, "url": n.url}
        events.publish("notification.created", {"id": n.id, "level": level, "title": title}, db=db)
    return out


def _entregar(n: dict) -> int:
    """Envía a todos los dispositivos. Bloqueante: se llama en un hilo."""
    from pywebpush import WebPushException, webpush
    with session_scope() as db:
        subs = [(s.id, s.endpoint, s.p256dh, s.auth) for s in db.scalars(select(PushSubscription))]
    if not subs:
        return 0
    body = n["body"] if len(n["body"]) <= PUSH_BODY_MAX else n["body"][:PUSH_BODY_MAX - 1] + "…"
    data = json.dumps({"id": n["id"], "title": n["title"], "body": body, "url": n["url"]}, ensure_ascii=False)
    urgency = "high" if n["level"] in ("critical", "action") else "normal"
    vapid, sub = _vapid(), _claim_sub()
    ok = 0
    for sid, endpoint, p256dh, auth in subs:
        info = {"endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth}}
        error, gone = "", False
        try:
            webpush(info, data=data, vapid_private_key=vapid, vapid_claims={"sub": sub}, ttl=PUSH_TTL,
                    headers={"Urgency": urgency}, timeout=15)
            ok += 1
        except WebPushException as e:
            status = e.response.status_code if e.response is not None else 0
            gone = status in (404, 410)  # el dispositivo ya no existe: se borra
            error = f"{status}: {e}"[:300]
        except Exception as e:  # noqa: BLE001  (red caída, DNS…)
            error = f"{type(e).__name__}: {e}"[:300]
        with session_scope() as db:
            s = db.get(PushSubscription, sid)
            if s is None:
                continue
            if gone:
                db.delete(s)
            elif error:
                s.last_error = error
            else:
                s.last_ok_at, s.last_error = utcnow(), ""
        if error:
            log.warning("push al dispositivo %s falló: %s", sid, error)
    with session_scope() as db:
        db.execute(update(Notification).where(Notification.id == n["id"]).values(pushed=ok))
    return ok


async def enviar(level: str, title: str, body: str = "", url: str = DEFAULT_URL, source: str = "sistema",
                 force: bool = False) -> dict:
    n = crear(level, title, body, url, source)
    if n["level"] == "silent" or (n["level"] == "info" and is_quiet() and not force):
        return n | {"pushed": 0}
    return n | {"pushed": await asyncio.to_thread(_entregar, n)}


async def ingest_spool() -> int:
    """Convierte en avisos lo que han dejado los scripts del PC."""
    folder = _spool()
    if not folder.is_dir():
        return 0
    done = 0
    for f in sorted(p for p in folder.glob("*.json") if not p.is_symlink())[:50]:
        try:
            if f.stat().st_size > SPOOL_MAX_BYTES:
                raise ValueError("demasiado grande")
            d = json.loads(f.read_text(encoding="utf-8"))
            text = str(d["text"]).strip()
            first, _, rest = text.partition("\n")
            await enviar(str(d.get("level", "info")), first, rest.strip(), str(d.get("url", DEFAULT_URL)), "pc")
            done += 1
        except Exception as e:  # noqa: BLE001  un aviso malo no debe parar los demás
            log.warning("aviso descartado (%s): %s", f.name, e)
        f.unlink(missing_ok=True)
    return done


async def daily_test(now: datetime | None = None) -> bool:
    """Prueba diaria de la primera semana: comprueba que el canal aguanta antes de depender de él."""
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(TZ)
    if local.hour < DAILY_TEST_HOUR:
        return False
    start_of_day = local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).replace(tzinfo=None)
    with session_scope() as db:
        first = db.scalar(select(func.min(PushSubscription.created_at)))
        if first is None or now.replace(tzinfo=None) > first + timedelta(days=DAILY_TEST_DAYS):
            return False
        if db.scalar(select(Notification.id).where(Notification.source == "prueba-diaria",
                                                   Notification.ts >= start_of_day).limit(1)):
            return False
    await enviar("info", "Prueba diaria de avisos", "Si ves esto, el canal funciona. Tócalo para abrir el panel.",
                 source="prueba-diaria")
    return True


def prune(db: Session) -> None:
    db.execute(delete(Notification).where(Notification.read_at.is_not(None), Notification.read_at < utcnow() - KEEP_READ))


async def loop() -> None:
    while True:
        try:
            await ingest_spool()
            await daily_test()
            from . import actions, runs
            await asyncio.to_thread(actions.expire_pending)
            await runs.ingest_orders()
            await runs.maintenance()
        except Exception as e:  # noqa: BLE001
            log.exception("avisos: %s", e)
        await asyncio.sleep(SPOOL_EVERY)


# ---------- API ----------


def _ser(n: Notification) -> dict:
    return {"id": n.id, "ts": n.ts.isoformat() + "Z", "level": n.level, "title": n.title, "body": n.body, "url": n.url,
            "source": n.source, "read": n.read_at is not None, "pushed": n.pushed}


def _ser_sub(s: PushSubscription) -> dict:
    return {"id": s.id, "label": s.label, "host": urlsplit(s.endpoint).hostname or "",
            "created_at": s.created_at.isoformat() + "Z",
            "last_ok_at": s.last_ok_at.isoformat() + "Z" if s.last_ok_at else None, "last_error": s.last_error}


@router.get("/notifications")
def listar(limit: int = 100, db: Session = Depends(get_db)):
    rows = db.scalars(select(Notification).order_by(Notification.id.desc()).limit(min(max(limit, 1), 500)))
    return [_ser(n) for n in rows]


@router.get("/notifications/count")
def contar(db: Session = Depends(get_db)):
    """Para la campana: avisos sin leer y lo que espera tu decisión (acciones y solicitudes de permisos)."""
    from ..approvals import requests_
    from ..models import Action
    unread = db.scalar(select(func.count()).select_from(Notification).where(Notification.read_at.is_(None)))
    acciones = db.scalar(select(func.count()).select_from(Action).where(Action.status == "pending"))
    try:
        solicitudes = len(requests_()["pendientes"])
    except OSError:
        solicitudes = 0
    return {"unread": unread, "por_decidir": acciones + solicitudes, "acciones": acciones, "solicitudes": solicitudes}


@router.post("/notifications/read-all", dependencies=[Depends(require_admin)])
def leer_todas(db: Session = Depends(get_db)):
    db.execute(update(Notification).where(Notification.read_at.is_(None)).values(read_at=utcnow()))
    return {"ok": True}


@router.post("/notifications/{nid}/read", dependencies=[Depends(require_admin)])
def leer(nid: int, db: Session = Depends(get_db)):
    n = db.get(Notification, nid)
    if n is None:
        raise HTTPException(404, "Aviso no encontrado")
    n.read_at = n.read_at or utcnow()
    return {"ok": True}


class KeysIn(BaseModel):
    p256dh: str = Field(min_length=20, max_length=200)
    auth: str = Field(min_length=8, max_length=100)


class SubscriptionIn(BaseModel):
    endpoint: str = Field(max_length=1024)
    keys: KeysIn
    label: str = Field(default="", max_length=120)


def _endpoint_ok(url: str) -> bool:
    u = urlsplit(url)
    host = (u.hostname or "").lower()
    return u.scheme == "https" and u.port in (None, 443) and any(host == h or host.endswith("." + h) for h in PUSH_HOSTS)


@router.get("/push/config")
def push_config(db: Session = Depends(get_db)):
    subs = db.scalars(select(PushSubscription).order_by(PushSubscription.id))
    return {"public_key": public_key(), "subscriptions": [_ser_sub(s) for s in subs]}


@router.post("/push/subscriptions")
def suscribir(body: SubscriptionIn, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    if not _endpoint_ok(body.endpoint):
        raise HTTPException(422, "Servicio de push no admitido")
    s = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == body.endpoint))
    nueva = s is None
    if nueva:
        s = PushSubscription(endpoint=body.endpoint, p256dh=body.keys.p256dh, auth=body.keys.auth, label=body.label)
        db.add(s)
    else:
        s.p256dh, s.auth = body.keys.p256dh, body.keys.auth
        s.label = body.label or s.label
    db.flush()
    if nueva:
        events.audit(db, p.name, "push.subscribe", s.label or urlsplit(body.endpoint).hostname or "")
    return _ser_sub(s)


@router.delete("/push/subscriptions/{sid}")
def desuscribir(sid: int, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    s = db.get(PushSubscription, sid)
    if s is None:
        raise HTTPException(404, "Dispositivo no encontrado")
    events.audit(db, p.name, "push.unsubscribe", s.label)
    db.delete(s)
    return {"ok": True}


@router.post("/push/test", dependencies=[Depends(require_admin)])
async def probar():
    n = await enviar("action", "Prueba de avisos", "Si ves esto, las notificaciones funcionan.", source="prueba", force=True)
    return {"pushed": n["pushed"], "id": n["id"]}
