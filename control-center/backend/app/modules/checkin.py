"""Check-ins de la mañana y de la noche, en la portada.

La BD es la fuente: un check-in por día y franja (guardar otra vez lo corrige). Los hábitos son los de `personal`
(`/me/habits/{id}/toggle`). El check-in de la noche puede además encargar el cierre del día a la rutina `cierre`,
que es quien escribe el diario (mientras el diario siga en la vault).
"""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import events
from ..core import memory
from ..db import get_db, utcnow
from ..models import CheckIn, Habit, HabitLog
from ..security import Principal, current_principal, require_admin
from . import personal
from ..config import TZ_NAME

TZ = ZoneInfo(TZ_NAME)
SLOTS = ("manana", "noche")
FECHA = r"^\d{4}-\d{2}-\d{2}$"
NOCHE_DESDE = 19  # a partir de esta hora la portada sugiere el check-in de la noche
MANANA_HASTA = 14

router = APIRouter(prefix="/api/v1/me/checkin", dependencies=[Depends(current_principal)])


def today() -> date:
    return datetime.now(timezone.utc).astimezone(TZ).date()


def _view(c: CheckIn | None) -> dict | None:
    if c is None:
        return None
    return {"mood": c.mood, "energy": c.energy, "sleep_h": c.sleep_h, "intention": c.intention, "note": c.note,
            "at": c.updated_at.isoformat() + "Z"}


def habits_of(db: Session, day: date) -> list[dict]:
    out = []
    for h in db.scalars(select(Habit).where(Habit.active.is_(True)).order_by(Habit.id)):
        days = set(db.scalars(select(HabitLog.day).where(HabitLog.habit_id == h.id)))
        out.append({"id": h.id, "nombre": h.name, "hoy": day.isoformat() in days, "racha": personal.streak(days, day)})
    return out


def suggested(done: dict, hour: int) -> str | None:
    """Qué franja toca ahora: de mañana hasta las 14, de noche desde las 19 y, entre medias, la que falte."""
    if hour < MANANA_HASTA:
        return None if done["manana"] else "manana"
    if hour >= NOCHE_DESDE:
        return None if done["noche"] else "noche"
    return "manana" if not done["manana"] else ("noche" if not done["noche"] else None)


def view(db: Session, day: date, hour: int | None = None) -> dict:
    rows = {c.slot: c for c in db.scalars(select(CheckIn).where(CheckIn.day == day.isoformat()))}
    done = {s: s in rows for s in SLOTS}
    hour = datetime.now(timezone.utc).astimezone(TZ).hour if hour is None else hour
    return {"dia": day.isoformat(), "manana": _view(rows.get("manana")), "noche": _view(rows.get("noche")),
            "sugerido": suggested(done, hour) if day == today() else None, "habitos": habits_of(db, day)}


def summary(db: Session, day: date, dias: int = 7) -> dict | None:
    """Medias de los últimos `dias` días para «Estado general». Sin ningún check-in no hay estado: None."""
    desde = (day - timedelta(days=dias - 1)).isoformat()
    rows = list(db.scalars(select(CheckIn).where(CheckIn.day >= desde, CheckIn.day <= day.isoformat())))
    if not rows:
        return None

    def media(vals):
        vals = [v for v in vals if v is not None]
        return round(sum(vals) / len(vals), 1) if vals else None
    habitos = habits_of(db, day)
    return {"dias": dias, "checkins": len(rows), "de": dias * 2, "animo": media(c.mood for c in rows),
            "energia": media(c.energy for c in rows), "sueno": media(c.sleep_h for c in rows if c.slot == "manana"),
            "habitos_hoy": [sum(1 for h in habitos if h["hoy"]), len(habitos)]}


class CheckInIn(BaseModel):
    slot: str = Field(pattern=r"^(manana|noche)$")
    dia: str | None = Field(default=None, pattern=FECHA)
    mood: int | None = Field(default=None, ge=1, le=5)
    energy: int | None = Field(default=None, ge=1, le=5)
    sleep_h: float | None = Field(default=None, ge=0, le=24)
    intention: str = Field(default="", max_length=300)
    note: str = Field(default="", max_length=1000)


@router.get("")
def get_checkin(dia: str | None = None, db: Session = Depends(get_db)):
    try:
        day = date.fromisoformat(dia) if dia else today()
    except ValueError:
        raise HTTPException(422, "Fecha no válida")
    return view(db, day)


@router.put("")
def put_checkin(body: CheckInIn, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    day = body.dia or today().isoformat()
    if date.fromisoformat(day) > today():
        raise HTTPException(422, "No se puede hacer el check-in de un día futuro")
    if body.mood is None and body.energy is None and body.sleep_h is None and not body.intention.strip() and not body.note.strip():
        raise HTTPException(422, "Cuéntame algo: ánimo, energía, sueño o una nota")
    c = db.scalar(select(CheckIn).where(CheckIn.day == day, CheckIn.slot == body.slot))
    nuevo = c is None
    if nuevo:
        c = CheckIn(day=day, slot=body.slot)
        db.add(c)
    c.mood, c.energy, c.sleep_h = body.mood, body.energy, body.sleep_h
    c.intention, c.note, c.updated_at = body.intention.strip(), body.note.strip(), utcnow()
    db.flush()
    memory.log_event(db, "health", f"checkin.{body.slot}", f"Check-in {day}",
                     {"mood": c.mood, "energy": c.energy, "sleep_h": c.sleep_h})
    events.audit(db, p.name, "checkin.save", f"{day}:{body.slot}", nuevo=nuevo)
    return view(db, date.fromisoformat(day))


def close_summary(db: Session, day: date) -> str:
    """Lo que cuenta el usuario para el cierre del día: su check-in de la noche y los hábitos de hoy."""
    c = db.scalar(select(CheckIn).where(CheckIn.day == day.isoformat(), CheckIn.slot == "noche"))
    if c is None:
        raise HTTPException(409, "Haz primero el check-in de la noche")
    hs = habits_of(db, day)
    partes = [f"Check-in de la noche del {day.isoformat()} (hecho en el panel)."]
    if c.mood:
        partes.append(f"Ánimo: {c.mood}/5.")
    if c.energy:
        partes.append(f"Energía: {c.energy}/5.")
    if c.note:
        partes.append(f"Cómo ha ido el día, según el usuario: {c.note}")
    if hs:
        partes.append("Hábitos de hoy: " + ", ".join(f"{h['nombre']} {'✓' if h['hoy'] else '✗'}" for h in hs) + ".")
    return " ".join(partes)


@router.post("/close")
def close_day(p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    """Encarga el cierre del día a la rutina `cierre` con lo del check-in (el diario lo escribe ella)."""
    from ..core import runs
    day = today()
    texto = close_summary(db, day)
    runs.order_routine("cierre", f"Haz el cierre manual del día según /vault/Jarvis/Sistema/cierre.md. Lo que cuenta el usuario:\n\n{texto}")
    events.audit(db, p.name, "checkin.close", day.isoformat())
    return {"encargado": True}


def pending(db: Session, day: date, slot: str) -> list[dict]:
    """Recordatorio de la franja si aún no se ha hecho (lo envía reminders; una vez por día y franja)."""
    if db.scalar(select(CheckIn).where(CheckIn.day == day.isoformat(), CheckIn.slot == slot)):
        return []
    if slot == "manana":
        return [{"key": f"rec:checkin:manana:{day.isoformat()}", "title": "Check-in de la mañana",
                 "body": "¿Cómo has dormido y qué es lo más importante hoy?", "url": "/", "level": "info"}]
    return [{"key": f"rec:checkin:noche:{day.isoformat()}", "title": "¿Cómo ha ido el día?",
             "body": "Haz el check-in de la noche y cierra el día en Inicio.", "url": "/", "level": "action"}]
