"""Avisos proactivos sin modelo: vencimientos, seguimientos, entregas y presupuesto.

Cada recordatorio sale una vez: su clave queda en `source` y no se repite.
"""
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core import notifications
from ..db import session_scope
from ..models import Assessment, EduCanvasChange, EduCard, JobApplication, LifestyleItem, Notification
from . import finance

HORA = 9
AVISO_DIAS = {"garantia": 14, "suscripcion": 7, "viaje": 7, "actividad": 2, "compra": 0, "interes": 0}
TIPO = {"garantia": "Vence la garantía", "suscripcion": "Se renueva la suscripción", "viaje": "Viaje cerca", "actividad": "Actividad cerca"}


GOOGLE_AVISO_DIAS = 2  # días que quedan (de 7 en modo Prueba) para empezar a avisar


def google_pending(cuentas: list[dict], today: date) -> list[dict]:
    """Un aviso al día por cuenta cuando le quedan <= 2 días o ya caducó, hasta que se renueve."""
    out = []
    for c in cuentas or []:
        dr = c.get("dias_restantes")
        if not c.get("autorizada") or c.get("caducada") or (dr is not None and dr <= GOOGLE_AVISO_DIAS):
            caducada = not c.get("autorizada") or c.get("caducada") or (dr is not None and dr <= 0)
            out.append({"key": f"rec:google:{c['cuenta']}:{today.isoformat()}",
                        "title": "El permiso de Google ha caducado" if caducada else "El permiso de Google caduca pronto",
                        "body": f"{c.get('email', c['cuenta'])}: renuévalo en Ajustes → Conexiones (dos toques).",
                        "url": "/ajustes/", "level": "action"})
    return out


async def _google() -> list[dict]:
    """Estado de los tokens por el Host Agent. Si no responde, no se avisa de nada (mejor callar que inventar)."""
    from ..adapters import hostagent
    try:
        return await hostagent.call("/v1/google/status")
    except Exception:  # noqa: BLE001
        return []


def pending(db: Session, today: date, google: list[dict] | None = None) -> list[dict]:
    out = google_pending(google or [], today)
    for i in db.scalars(select(LifestyleItem).where(LifestyleItem.day.is_not(None))):
        dias = (date.fromisoformat(i.day) - today).days
        if 0 <= dias <= AVISO_DIAS.get(i.kind, 0):
            out.append({"key": f"rec:vida:{i.id}:{i.day}", "title": TIPO.get(i.kind, "Recordatorio"), "body": f"{i.title}: {i.day}", "url": "/estilo-de-vida/", "level": "info"})
    for a in db.scalars(select(JobApplication).where(JobApplication.follow_up.is_not(None), JobApplication.follow_up <= today.isoformat())):
        if a.status not in ("descartado", "oferta"):
            out.append({"key": f"rec:job:{a.id}:{a.follow_up}", "title": "Toca hacer seguimiento", "body": f"{a.company}: {a.role}", "url": "/carrera/", "level": "action"})
    limite = (today + timedelta(days=2)).isoformat()
    q = select(Assessment).where(Assessment.done.is_(False), Assessment.removed_at.is_(None), Assessment.due >= today.isoformat(), Assessment.due <= limite)
    for e in db.scalars(q):
        out.append({"key": f"rec:uni:{e.id}", "title": "Entrega cerca", "body": f"{e.title}: {e.due}", "url": "/educacion/", "level": "action"})
    # Canvas movió, añadió o retiró una fecha: avisa una sola vez por cambio (la clave lleva el id)
    for c in db.scalars(select(EduCanvasChange).where(EduCanvasChange.seen.is_(False)).order_by(EduCanvasChange.id).limit(10)):
        txt = {"nuevo": f"Nuevo en Canvas: {c.title} ({c.new[:10]})", "movido": f"Canvas movió {c.title}: {c.old[:10]} → {c.new[:10]}", "retirado": f"Canvas retiró {c.title} ({c.old[:10]})"}[c.kind]
        out.append({"key": f"rec:canvas:{c.id}", "title": "Cambio en Canvas", "body": txt, "url": "/educacion/", "level": "action"})
    pendientes = db.scalar(select(func.count()).select_from(EduCard).where(EduCard.suspended.is_(False), EduCard.due <= today.isoformat())) or 0
    if pendientes >= 10:
        out.append({"key": f"rec:cards:{today.isoformat()}", "title": "Repaso pendiente", "body": f"{pendientes} tarjetas esperan en Educación", "url": "/educacion/", "level": "info"})
    mes = today.strftime("%Y-%m")
    for b in finance.budget_status(db, mes):
        if b["excedido"]:  # sin importes: el push pasa por el servicio de Apple
            out.append({"key": f"rec:gasto:{mes}:{b['cuenta']}", "title": "Presupuesto superado", "body": b["cuenta"].split(":")[-1], "url": "/finanzas/", "level": "action"})
    return out


async def _canvas() -> None:
    """Lee Canvas por Google Calendar antes de los avisos. Si Google falla, el resto de recordatorios sale igual."""
    import asyncio
    import logging

    from . import education
    try:
        def leer():
            with session_scope() as db:
                return education.check_canvas(db)
        await asyncio.to_thread(leer)
    except Exception as e:  # noqa: BLE001
        logging.getLogger(__name__).warning("Canvas: %s", str(e)[:150])


async def _send_new(items: list[dict], ya: set[str]) -> int:
    n = 0
    for it in items:
        key = it["key"][:48]
        if key not in ya:
            await notifications.enviar(it["level"], it["title"], it["body"], it["url"], key)
            n += 1
    return n


async def run(today: date | None = None) -> int:
    today = today or date.today()
    await _canvas()
    google = await _google()
    with session_scope() as db:
        items = pending(db, today, google)
        ya = set(db.scalars(select(Notification.source).where(Notification.source.like("rec:%"))))
    return await _send_new(items, ya)


async def run_night(today: date) -> int:
    """22:30: si no se ha hecho el check-in de la noche, un aviso (la mañana se ve en Inicio, sin push)."""
    from . import checkin
    with session_scope() as db:
        items = checkin.pending(db, today, "noche")
        ya = set(db.scalars(select(Notification.source).where(Notification.source.like("rec:checkin:%"))))
    return await _send_new(items, ya)
