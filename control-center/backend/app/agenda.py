"""Agenda y productividad: reutiliza los recopiladores existentes (sin integraciones nuevas).

- Calendario: collectors/gcal.py (`agenda`), mismo token y mismos límites que Jarvis.
- Correo: collectors/correo.py (`resumen`: sin leer de las últimas 24 h por cuenta).
- Uni: collectors/uni.py (plan de hoy, entregas y eventos de las notas semanales).
- Tareas: collectors/tareas.py (Jarvis/Tareas.md).
Las llamadas a Google y Zoho se cachean 5 minutos y nunca rompen la página: si fallan, se dice por qué.
"""
import asyncio
import sys
import time
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import ROOT, get_settings
from . import events
from .db import get_db, utcnow
from .security import Principal, current_principal, require_admin

sys.path.insert(0, str(ROOT / "collectors"))

router = APIRouter(prefix="/api/v1", dependencies=[Depends(current_principal)])
TTL = 300
_visto: tuple | None = None  # última versión de Tareas.md ya importada
_cache: dict[str, tuple[float, object]] = {}
_caducada: dict[str, bool] = {}  # cuenta de Google -> la última llamada dijo que el permiso caducó


def caducadas() -> dict[str, bool]:
    return dict(_caducada)


def google_renovado(cuenta: str) -> None:
    """Tras renovar: olvida el fallo y la caché para que Agenda y correo se actualicen ya."""
    _caducada.pop(cuenta, None)
    _cache.clear()


def _es_caducado(e: object) -> bool:
    return e.__class__.__name__ == "Caducado" or "invalid_grant" in str(e) or "ha caducado" in str(e)


def _cached(key: str, fn, ttl: int = TTL):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = fn()
    _cache[key] = (time.time(), val)
    return val


def calendario(dias: int) -> dict:
    import gcal
    try:
        return {"eventos": gcal.agenda(dias), "error": None}
    except Exception as e:  # noqa: BLE001
        caducado = _es_caducado(e)
        if caducado:
            _caducada["personal"] = True
        return {"eventos": [], "error": "El permiso de Google ha caducado: renuévalo en Ajustes → Conexiones"
                if caducado else f"Calendario no disponible: {str(e)[:120]}"}


def correo() -> dict:
    import correo as c
    try:
        out = {}
        for cuenta, v in c.resumen(8).items():
            if isinstance(v, dict) and "error" in v:
                if cuenta in ("personal", "gmail", "secundaria") and _es_caducado(v["error"]):
                    _caducada["secundaria" if cuenta == "secundaria" else "personal"] = True
                out[cuenta] = {"error": v["error"]}
            else:
                out[cuenta] = {"mensajes": v}
        return out
    except Exception as e:  # noqa: BLE001
        return {"_": {"error": str(e)[:120]}}


def tareas_hoy() -> dict:
    import tareas
    return tareas.recoger(date.today(), 7)


def uni_semana() -> dict:
    import uni
    return uni.recoger(date.today(), 14)


def _listado(carpeta: str, n: int) -> list[dict]:
    d = get_settings().vault / "Jarvis" / carpeta
    if not d.is_dir():
        return []
    files = sorted((f for f in d.glob("*.md") if not f.name.startswith(".")), key=lambda f: f.name, reverse=True)[:n]
    return [{"path": f"Jarvis/{carpeta}/{f.name}", "name": f.stem} for f in files]


@router.get("/agenda")
async def agenda(dias: int = 7, refresh: bool = False):
    dias = max(0, min(dias, 31))
    if refresh:
        _cache.clear()
    loop = asyncio.get_running_loop()
    cal, mail = await asyncio.gather(
        loop.run_in_executor(None, _cached, f"cal{dias}", lambda: calendario(dias)),
        loop.run_in_executor(None, _cached, "mail", correo),
    )
    digest = get_settings().vault / "Jarvis/Sistema/digest.md"
    return {
        "hoy": date.today().isoformat(),
        "calendario": cal,
        "correo": mail,
        "uni": uni_semana(),
        "tareas": tareas_hoy(),
        "briefings": _listado("Briefings", 7),
        "diario": _listado("Diario", 7),
        "digest": {"path": "Jarvis/Sistema/digest.md",
                   "mtime": datetime.fromtimestamp(digest.stat().st_mtime).isoformat() if digest.exists() else None},
        "cache_s": TTL,
    }


def importar_tareas(db) -> None:
    """Si Tareas.md cambió (Obsidian, una rutina, el Panel, Jarvis), la importa a la base antes de leerla."""
    import tareas
    from .modules import vault_sync
    global _visto
    version = (tareas.TAREAS, tareas.TAREAS.stat().st_mtime_ns if tareas.TAREAS.exists() else None)
    if version != _visto:
        vault_sync.sync_tasks(db, tareas.TAREAS)
        _visto = version
        db.flush()


@router.get("/tasks")
def tasks():
    """Las tareas salen de la base. Si Tareas.md cambió (Obsidian, una rutina, el Panel), antes se importa."""
    import tareas
    from .db import session_scope
    from .models import Task
    with session_scope() as db:
        importar_tareas(db)
        todas = [{"texto": t.text, "fecha": t.due, "area": t.area, "hecho": t.done, "hecho_el": t.done_on}
                 for t in db.scalars(select(Task).where(Task.removed_at.is_(None)))]
    if not todas:  # instalación nueva: sin tareas, pero con sus áreas (el formulario de «Nueva tarea» las necesita)
        return {"pendientes": [], "hechas": [], "areas": tareas.ajustes.areas(), "fuente": "Jarvis/Tareas.md"}
    hoy = date.today().isoformat()
    pend = [t | {"atrasada": bool(t["fecha"] and t["fecha"] < hoy)} for t in todas if not t["hecho"]]
    pend.sort(key=lambda t: (t["fecha"] is None, t["fecha"] or ""))
    hechas = sorted((t for t in todas if t["hecho"]), key=lambda t: t["hecho_el"] or "", reverse=True)[:30]
    return {"pendientes": pend, "hechas": hechas, "areas": tareas.ajustes.areas(), "fuente": "Jarvis/Tareas.md"}


class TaskDoneIn(BaseModel):
    texto: str = Field(..., min_length=1, max_length=500)
    hecho: bool = True


@router.post("/tasks/done")
def task_done(body: TaskDoneIn, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    """Marca o desmarca una tarea. La base manda: Tareas.md se rehace como copia y se pone igual su casilla del Panel."""
    import tareas
    from .models import Task
    from .modules import mirror
    t = db.scalar(select(Task).where(Task.text == body.texto, Task.done.is_(not body.hecho), Task.removed_at.is_(None))
                  .order_by(Task.due.is_(None), Task.due, Task.id).limit(1))
    if t is None:
        raise HTTPException(409, "No encuentro esa tarea " + ("pendiente" if body.hecho else "hecha") + ": puede que ya haya cambiado")
    t.done, t.done_on, t.updated_at = body.hecho, (date.today().isoformat() if body.hecho else None), utcnow()
    db.flush()
    mirror.export_tasks(db, tareas.TAREAS)
    panel = tareas.casilla_tarea(t.text, body.hecho)
    events.audit(db, p.name, "task.done" if body.hecho else "task.undone", target=body.texto[:255], panel=panel)
    events.publish("tasks.changed", {"texto": body.texto[:120], "hecho": body.hecho}, db=db)
    return {"ok": True, "tareas": 1, "panel": panel}


class TaskNewIn(BaseModel):
    texto: str = Field(..., min_length=1, max_length=300)
    fecha: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    area: str = Field(default="personal", max_length=16)


@router.post("/tasks")
def task_new(body: TaskNewIn, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    """Crea una tarea en la base (Tareas.md se rehace como copia). Es la misma función que usan Jarvis y las rutinas."""
    from .modules import agent_caps
    try:
        r = agent_caps.task_create({"texto": body.texto, "fecha": body.fecha, "area": body.area}, db)
    except ValueError as e:
        raise HTTPException(422, str(e))
    events.audit(db, p.name, "task.create", target=body.texto[:255], repetida=bool(r.get("repetida")))
    events.publish("tasks.changed", {"texto": body.texto[:120]}, db=db)
    return {"ok": True, **r}

