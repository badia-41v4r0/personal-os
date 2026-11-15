"""Calendario unificado: una sola vista con todos los ámbitos.

Solo lectura y sin integraciones nuevas: cada capa sale de lo que ya existe (Google por `gcal.py`, el resto de la base).
Ninguna capa inventa datos: si una fuente falla, la capa lo dice y las demás siguen.

Google: se excluyen siempre los calendarios de agenda.json → calendarios_ocultos; el del campus (Canvas) va oculto por defecto (sus entregas ya salen en la
capa Uni y se duplicarían) y se activa con `canvas=true`. Los bloques de estudio ya volcados a Google se muestran una sola vez.
"""
import asyncio
import re
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import agenda as agenda_mod
from ..db import get_db
from ..models import (Assessment, EduCalendarBlock, GymPlannedSession, JobApplication, LifestyleItem, StudyBlock, Task)
from ..security import current_principal

router = APIRouter(prefix="/api/v1/calendar", dependencies=[Depends(current_principal)])

CAPAS = ("google", "uni", "tareas", "trabajo", "gym", "vida")
MAX_DIAS = 62
FECHA = re.compile(r"^\d{4}-\d{2}-\d{2}$")
GYM_OCULTAS = ("descartada", "sustituida", "omitida")
VIDA = {"viaje": "Viaje", "actividad": "Actividad", "compra": "Compra", "garantia": "Garantía", "suscripcion": "Suscripción", "interes": "Interés"}


def _es_familia(nombre: str) -> bool:
    """Calendarios que nunca se enseñan (config agenda.json → calendarios_ocultos, por trozo de nombre)."""
    import ajustes
    ocultos = [str(x).lower() for x in ajustes.leer("agenda").get("calendarios_ocultos") or [] if str(x).strip()]
    return any(p in (nombre or "").lower() for p in ocultos)


def _es_canvas(nombre: str) -> bool:
    return "canvas" in (nombre or "").lower()


def _item(capa: str, id_: str, titulo: str, dia: str, **kw) -> dict:
    return {"id": f"{capa}:{id_}", "capa": capa, "titulo": titulo, "dia": dia, "hasta": kw.pop("hasta", dia),
            "inicio": kw.pop("inicio", None), "fin": kw.pop("fin", None), "hecho": kw.pop("hecho", None),
            "detalle": kw.pop("detalle", ""), "enlace": kw.pop("enlace", None), "clave": kw.pop("clave", None)}


def google(desde: date, hasta: date, canvas: bool, bloques_propios: set[str]) -> tuple[list[dict], str | None]:
    """Eventos de Google en el rango. Sin los ocultos; sin Canvas salvo que se pida; sin los bloques que ya salen en Uni."""
    dias = (hasta - desde).days
    res = agenda_mod._cached(f"calv{desde}{hasta}", lambda: _google_crudo(desde, dias))
    out = []
    for e in res["eventos"]:
        cal = e.get("calendario", "")
        if _es_familia(cal) or (_es_canvas(cal) and not canvas) or e["id"] in bloques_propios:
            continue
        if e["dia"] > hasta.isoformat() or e["hasta"] < desde.isoformat():
            continue
        out.append(_item("google", e["id"], e["titulo"], e["dia"], hasta=e["hasta"], inicio=e["inicio"], fin=e["fin"],
                         detalle=" · ".join(x for x in (cal, e.get("lugar", "")) if x)))
    return out, res["error"]


def _google_crudo(desde: date, dias: int) -> dict:
    import gcal
    try:
        return {"eventos": gcal.agenda(dias, hoy=desde), "error": None}
    except Exception as e:  # noqa: BLE001
        caducado = e.__class__.__name__ == "Caducado" or "invalid_grant" in str(e)
        return {"eventos": [], "error": "El permiso de Google ha caducado: renuévalo en Configuración"
                if caducado else f"Google Calendar no disponible: {str(e)[:120]}"}


def uni(db: Session, d: str, h: str) -> list[dict]:
    from .education import _hechos, _hecho, _horas, codigo_de
    hechos, marcas = _hechos()
    out = []
    for e in db.scalars(select(Assessment).where(Assessment.removed_at.is_(None), Assessment.due >= d, Assessment.due <= h)):
        clave = f"entrega|{e.due}|{e.title}"
        out.append(_item("uni", f"e{e.id}", f"📌 {e.title}", e.due, inicio=e.due_time or None, clave=clave, enlace="/educacion/",
                         hecho=_hecho(clave, hechos, marcas, e.done), detalle="Entrega"))
    for b in db.scalars(select(StudyBlock).where(StudyBlock.day >= d, StudyBlock.day <= h).order_by(StudyBlock.day, StudyBlock.slot)):
        clave = f"estudio|{b.day}|{b.text}"
        horas = _horas(b.slot, date.fromisoformat(b.day))
        m = re.match(r"(\d{1,2}:\d{2})\D+(\d{1,2}:\d{2})", horas)
        out.append(_item("uni", f"b{b.id}", f"📚 {' '.join(b.text.split())[:120]}", b.day, inicio=m[1].zfill(5) if m else None,
                         fin=m[2].zfill(5) if m else None, clave=clave, enlace="/educacion/", hecho=_hecho(clave, hechos, marcas),
                         detalle=f"Estudio · {codigo_de(b.text)}".rstrip(" ·")))
    return out


def tareas(db: Session, d: str, h: str) -> list[dict]:
    q = select(Task).where(Task.removed_at.is_(None), Task.due >= d, Task.due <= h)
    return [_item("tareas", str(t.id), t.text, t.due, hecho=t.done, enlace="/tasks/?t=tasks", detalle=t.area) for t in db.scalars(q)]


def trabajo(db: Session, d: str, h: str) -> list[dict]:
    q = select(JobApplication).where(JobApplication.follow_up >= d, JobApplication.follow_up <= h,
                                     JobApplication.status.not_in(("descartado", "oferta")))
    return [_item("trabajo", str(a.id), f"Seguimiento: {a.company} · {a.role}", a.follow_up, enlace="/carrera/", detalle=a.status)
            for a in db.scalars(q)]


def gym(db: Session, d: str, h: str) -> list[dict]:
    q = select(GymPlannedSession).where(GymPlannedSession.date >= d, GymPlannedSession.date <= h,
                                        GymPlannedSession.status.not_in(GYM_OCULTAS))
    return [_item("gym", s.id, f"🏋️ {s.name}", s.date, enlace="/gym/", hecho=s.status == "hecha",
                  detalle="Pospuesta" if s.status == "pospuesta" else "Sesión planificada") for s in db.scalars(q)]


def vida(db: Session, d: str, h: str) -> list[dict]:
    q = select(LifestyleItem).where(LifestyleItem.day >= d, LifestyleItem.day <= h)
    return [_item("vida", str(i.id), i.title, i.day, enlace="/estilo-de-vida/", detalle=VIDA.get(i.kind, i.kind)) for i in db.scalars(q)]


LOCALES = {"uni": uni, "tareas": tareas, "trabajo": trabajo, "gym": gym, "vida": vida}


@router.get("")
async def calendar(desde: str, hasta: str, capas: str = ",".join(CAPAS), canvas: bool = False, refresh: bool = False,
                   db: Session = Depends(get_db)):
    if not (FECHA.match(desde) and FECHA.match(hasta)):
        raise HTTPException(422, "Fechas AAAA-MM-DD")
    ini, fin = date.fromisoformat(desde), date.fromisoformat(hasta)
    if fin < ini or (fin - ini).days > MAX_DIAS:
        raise HTTPException(422, f"El rango va de 0 a {MAX_DIAS} días")
    pedidas = [c for c in capas.split(",") if c in CAPAS]
    if refresh:
        agenda_mod._cache.clear()
    items: list[dict] = []
    errores: dict[str, str] = {}
    if "tareas" in pedidas:
        try:
            agenda_mod.importar_tareas(db)  # como la página Tareas: lo cambiado en Tareas.md fuera del panel
        except Exception as e:  # noqa: BLE001
            errores["tareas"] = f"No pude actualizar desde Tareas.md: {str(e)[:100]}"
    for c in pedidas:
        if c == "google":
            continue
        try:
            items += LOCALES[c](db, desde, hasta)
        except Exception as e:  # noqa: BLE001  una capa rota no tumba el calendario
            errores[c] = str(e)[:120]
    if "google" in pedidas:
        propios = {b.event_id for b in db.scalars(select(EduCalendarBlock).where(EduCalendarBlock.day >= desde, EduCalendarBlock.day <= hasta))}
        loop = asyncio.get_running_loop()
        g, err = await loop.run_in_executor(None, google, ini, fin, canvas, propios)
        items += g
        if err:
            errores["google"] = err
    items.sort(key=lambda i: (i["dia"], i["inicio"] or "", i["titulo"]))
    return {"desde": desde, "hasta": hasta, "hoy": date.today().isoformat(), "capas": pedidas, "items": items, "errores": errores}
