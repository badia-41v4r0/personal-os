"""Objetivos, hábitos, salud, carrera, educación y estilo de vida.

Tareas, entrenos y notas de la uni siguen en la vault mientras Jarvis escriba allí: aquí solo se leen. Lo que nace
nuevo vive en la base de datos desde el principio.
"""
import json
import re
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import agenda as agenda_mod
from .. import events
from ..config import get_settings
from ..core import memory
from ..db import get_db, utcnow
from ..models import Assessment, Goal, Habit, HabitLog, HealthLog, JobApplication, LifestyleItem, Milestone, StudyBlock
from ..security import Principal, current_principal, require_admin
from . import mirror

ENTREGAS_ATRAS = 14  # días que una entrega pasada sigue a la vista si no se ha marcado

router = APIRouter(prefix="/api/v1/me", dependencies=[Depends(current_principal)])
ESTADOS = ("interés", "aplicado", "entrevista", "oferta", "descartado")
FOLLOW_UP_DIAS = 7
FECHA = r"^\d{4}-\d{2}-\d{2}$"


# ---------- objetivos ----------


def goal_view(db: Session, g: Goal) -> dict:
    hitos = list(db.scalars(select(Milestone).where(Milestone.goal_id == g.id).order_by(Milestone.id)))
    hechos = sum(1 for m in hitos if m.done_at)
    # El progreso sale de hitos reales: sin hitos no hay porcentaje que inventar
    return {"id": g.id, "titulo": g.title, "area": g.area, "horizonte": g.horizon, "estado": g.status, "fecha": g.target_date, "porque": g.why,
            "progreso": round(100 * hechos / len(hitos)) if hitos else None,
            "hitos": [{"id": m.id, "titulo": m.title, "hecho": m.done_at is not None} for m in hitos]}


def active_goals(db: Session) -> list[dict]:
    return [goal_view(db, g) for g in db.scalars(select(Goal).where(Goal.status == "active").order_by(Goal.id))]


class GoalIn(BaseModel):
    titulo: str = Field(min_length=1, max_length=200)
    area: str = Field(default="personal", max_length=32)
    horizonte: str = Field(default="medio", pattern="^(corto|medio|largo)$")
    fecha: str | None = Field(default=None, pattern=FECHA)
    porque: str = ""


class TitleIn(BaseModel):
    titulo: str = Field(min_length=1, max_length=200)


class StatusIn(BaseModel):
    estado: str = Field(pattern="^(active|done|abandoned)$")


@router.get("/goals")
def goals(db: Session = Depends(get_db)):
    return [goal_view(db, g) for g in db.scalars(select(Goal).order_by(Goal.status, Goal.id))]


@router.post("/goals")
def add_goal(body: GoalIn, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    g = Goal(title=body.titulo, area=body.area, horizon=body.horizonte, target_date=body.fecha, why=body.porque)
    db.add(g)
    db.flush()
    memory.log_event(db, "goals", "goal.created", body.titulo)
    events.audit(db, p.name, "goal.create", str(g.id))
    return goal_view(db, g)


@router.post("/goals/{gid}/milestones")
def add_milestone(gid: int, body: TitleIn, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    if db.get(Goal, gid) is None:
        raise HTTPException(404, "Objetivo no encontrado")
    db.add(Milestone(goal_id=gid, title=body.titulo))
    db.flush()
    return goal_view(db, db.get(Goal, gid))


@router.post("/milestones/{mid}/toggle")
def toggle_milestone(mid: int, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    m = db.get(Milestone, mid)
    if m is None:
        raise HTTPException(404, "Hito no encontrado")
    m.done_at = None if m.done_at else utcnow()
    db.flush()
    return goal_view(db, db.get(Goal, m.goal_id))


@router.post("/goals/{gid}/status")
def goal_status(gid: int, body: StatusIn, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    g = db.get(Goal, gid)
    if g is None:
        raise HTTPException(404, "Objetivo no encontrado")
    g.status = body.estado
    memory.log_event(db, "goals", f"goal.{body.estado}", g.title)
    events.audit(db, p.name, "goal.status", str(gid), estado=body.estado)
    return goal_view(db, g)


# ---------- hábitos ----------


def streak(days: set[str], today: date) -> int:
    """Días seguidos hasta hoy. Hoy sin marcar no rompe la racha: aún hay tiempo."""
    d = today if today.isoformat() in days else today - timedelta(days=1)
    n = 0
    while d.isoformat() in days:
        n += 1
        d -= timedelta(days=1)
    return n


class HabitIn(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)


class DayIn(BaseModel):
    dia: str | None = Field(default=None, pattern=FECHA)


@router.get("/habits")
def habits(db: Session = Depends(get_db)):
    hoy, out = date.today(), []
    for h in db.scalars(select(Habit).where(Habit.active.is_(True)).order_by(Habit.id)):
        days = set(db.scalars(select(HabitLog.day).where(HabitLog.habit_id == h.id)))
        out.append({"id": h.id, "nombre": h.name, "hoy": hoy.isoformat() in days, "racha": streak(days, hoy),
                    "semana": [(hoy - timedelta(days=i)).isoformat() in days for i in range(6, -1, -1)]})
    return out


@router.post("/habits")
def add_habit(body: HabitIn, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    if db.scalar(select(Habit).where(Habit.name == body.nombre)):
        raise HTTPException(409, "Ya existe ese hábito")
    h = Habit(name=body.nombre)
    db.add(h)
    db.flush()
    events.audit(db, p.name, "habit.create", body.nombre)
    return {"id": h.id}


@router.post("/habits/{hid}/toggle")
def toggle_habit(hid: int, body: DayIn, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    if db.get(Habit, hid) is None:
        raise HTTPException(404, "Hábito no encontrado")
    dia = body.dia or date.today().isoformat()
    log = db.scalar(select(HabitLog).where(HabitLog.habit_id == hid, HabitLog.day == dia))
    if log:
        db.delete(log)
    else:
        db.add(HabitLog(habit_id=hid, day=dia))
    return {"hecho": log is None}


# ---------- salud ----------


class HealthIn(BaseModel):
    metrica: str = Field(min_length=1, max_length=32, pattern=r"^[a-záéíóúñ_ ]+$")
    valor: float
    dia: str | None = Field(default=None, pattern=FECHA)
    nota: str = Field(default="", max_length=300)


@router.get("/health")
def health(db: Session = Depends(get_db)):
    rows = list(db.scalars(select(HealthLog).order_by(HealthLog.day.desc(), HealthLog.id.desc()).limit(500)))
    series: dict[str, list[dict]] = {}
    for r in reversed(rows):
        series.setdefault(r.metric, []).append({"dia": r.day, "valor": r.value})
    return {"series": series, "ultimas": [{"id": r.id, "dia": r.day, "metrica": r.metric, "valor": r.value, "nota": r.note} for r in rows[:20]]}


@router.post("/health")
def add_health(body: HealthIn, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    r = HealthLog(day=body.dia or date.today().isoformat(), metric=body.metrica, value=body.valor, note=body.nota)
    db.add(r)
    db.flush()
    memory.log_event(db, "health", "health.logged", body.metrica, {"valor": body.valor})
    return {"id": r.id}


# ---------- carrera ----------


class ApplicationIn(BaseModel):
    empresa: str = Field(min_length=1, max_length=160)
    puesto: str = Field(min_length=1, max_length=200)
    enlace: str = Field(default="", max_length=500)
    estado: str = Field(default="interés")
    proximo_paso: str = Field(default="", max_length=300)


class ApplicationPatch(BaseModel):
    estado: str | None = None
    proximo_paso: str | None = Field(default=None, max_length=300)
    follow_up: str | None = Field(default=None, pattern=FECHA)


def _app(a: JobApplication) -> dict:
    return {"id": a.id, "empresa": a.company, "puesto": a.role, "estado": a.status, "enlace": a.link, "proximo_paso": a.next_step, "follow_up": a.follow_up}


def _estado(valor: str) -> str:
    if valor not in ESTADOS:
        raise HTTPException(422, f"Estado no válido: {', '.join(ESTADOS)}")
    return valor


@router.get("/career")
def career(db: Session = Depends(get_db)):
    ofertas: list[dict] = []
    try:
        vistas = json.loads((get_settings().vault / "Jarvis/Sistema/ofertas-vistas.json").read_text(encoding="utf-8"))
        limite = (date.today() - timedelta(days=14)).isoformat()
        buenas = [o for o in vistas.values() if o.get("visto", "") >= limite and int(o.get("puntos") or 0) >= 2]
        buenas.sort(key=lambda o: (-int(o.get("puntos") or 0), o.get("visto", "")))
        ofertas = [{k: o.get(k) for k in ("id", "titulo", "empresa", "lugar", "enlace", "puntos", "visto")} for o in buenas[:30]]
    except (OSError, ValueError):
        pass
    apps = [_app(a) for a in db.scalars(select(JobApplication).order_by(JobApplication.updated_at.desc()))]
    return {"candidaturas": apps, "ofertas": ofertas, "estados": ESTADOS, "estado_laboral": memory.current_facts(db, "carrera")}


@router.post("/career/applications")
def add_application(body: ApplicationIn, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    a = JobApplication(company=body.empresa, role=body.puesto, link=body.enlace, status=_estado(body.estado), next_step=body.proximo_paso)
    if a.status == "aplicado":
        a.follow_up = (date.today() + timedelta(days=FOLLOW_UP_DIAS)).isoformat()
    db.add(a)
    db.flush()
    memory.log_event(db, "career", "application.created", f"{body.empresa}: {body.puesto}")
    events.audit(db, p.name, "career.application", str(a.id))
    mirror.export_jobs(db)
    return _app(a)


@router.patch("/career/applications/{aid}")
def patch_application(aid: int, body: ApplicationPatch, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    a = db.get(JobApplication, aid)
    if a is None:
        raise HTTPException(404, "Candidatura no encontrada")
    if body.estado and body.estado != a.status:
        memory.log_event(db, "career", "application.status", f"{a.company}: {a.status} → {body.estado}")
        a.status = _estado(body.estado)
        if a.status == "aplicado" and not body.follow_up:
            a.follow_up = (date.today() + timedelta(days=FOLLOW_UP_DIAS)).isoformat()
    if body.proximo_paso is not None:
        a.next_step = body.proximo_paso
    if body.follow_up:
        a.follow_up = body.follow_up
    a.updated_at = utcnow()
    db.flush()
    mirror.export_jobs(db)
    return _app(a)



@router.delete("/career/applications/{aid}")
def delete_application(aid: int, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    """Borra una candidatura (p. ej. duplicada). No se puede si tiene una solicitud del agente en marcha."""
    from ..models import ApplicationRun
    from .applications import ACTIVOS
    a = db.get(JobApplication, aid)
    if a is None:
        raise HTTPException(404, "Candidatura no encontrada")
    if db.scalar(select(ApplicationRun.id).where(ApplicationRun.application_id == aid, ApplicationRun.status.in_(ACTIVOS))):
        raise HTTPException(409, "Tiene una solicitud en marcha: descártala antes de borrar la candidatura")
    for r in db.scalars(select(ApplicationRun).where(ApplicationRun.application_id == aid)):
        db.delete(r)
    memory.log_event(db, "career", "application.deleted", f"{a.company}: {a.role}")
    events.audit(db, p.name, "career.application.delete", str(aid))
    db.delete(a)
    db.flush()
    mirror.export_jobs(db)
    return {"ok": True}

# ---------- educación ----------

FILA = re.compile(r"^\|(.+)\|$")


def notas_resumen(texto: str) -> list[dict]:
    """Lee la tabla ## Resumen de Notas-Uni.md, que mantiene collectors/notas.py."""
    try:
        tabla = texto.split("## Resumen", 1)[1].split("\n## ", 1)[0]
    except IndexError:
        return []
    filas = [[c.strip() for c in FILA.match(x.strip())[1].split("|")] for x in tabla.splitlines() if FILA.match(x.strip())]
    if len(filas) < 2:
        return []
    cab = filas[0]
    return [dict(zip(cab, f)) for f in filas[1:] if not set("".join(f)) <= {"-", " ", ":"}]


def _uni_items() -> dict:
    """Todo lo marcable de la uni. Cada elemento lleva su `clave`, que es lo que entiende marcar."""
    from lib import load_json
    import tareas
    import uni
    hoy = date.today()
    data = uni.recoger(hoy, 45)
    pasadas = uni.recoger(hoy - timedelta(days=ENTREGAS_ATRAS), ENTREGAS_ATRAS - 1)["entregas"]
    hechos, marcas = load_json(tareas.HECHOS, {}), tareas.marcas_panel()

    def hecho(clave: str, base: bool = False) -> bool:
        return marcas.get(clave, base or clave in hechos)

    entregas = []
    for e in [*pasadas, *data.get("entregas", [])]:
        clave = f"entrega|{e['fecha']}|{e['texto']}"
        h, atrasada = hecho(clave, e["hecho"]), e["fecha"] < hoy.isoformat()
        if not atrasada or not h:  # lo pasado solo sigue a la vista mientras esté sin marcar
            entregas.append(e | {"clave": clave, "hecho": h, "atrasada": atrasada})
    bloques = [{"clave": f"estudio|{hoy.isoformat()}|{b}", "texto": b} for b in data.get("bloques", [])]
    return {"entregas": entregas, "bloques_hoy": [b | {"hecho": hecho(b["clave"])} for b in bloques],
            "objetivos_semana": [o | {"clave": f"objetivo|{o['texto']}"} for o in uni.objetivos_semana(hoy)]}


@router.get("/education")
def education():
    from .. import agenda
    try:
        notas = notas_resumen((get_settings().vault / "Jarvis/Areas/Notas-Uni.md").read_text(encoding="utf-8"))
    except OSError:
        notas = []
    t = agenda.tasks()
    uni_t = [{"texto": x["texto"], "fecha": x["fecha"], "atrasada": x.get("atrasada", False), "hecho": False} for x in t["pendientes"] if x["area"] == "uni"]
    return {**_uni_items(), "tareas": uni_t, "notas": notas}


class UniCheckIn(BaseModel):
    clave: str = Field(min_length=3, max_length=800)
    hecho: bool = True


def _clave_en_la_base(db: Session, clave: str) -> bool:
    """Bloques y entregas de cualquier fecha (calendario: días pasados o futuros) mientras sigan en el plan.
    Se valida contra filas reales: una clave inventada sigue sin escribir nada."""
    tipo, _, resto = clave.partition("|")
    dia, _, texto = resto.partition("|")
    if tipo == "estudio":
        return db.scalar(select(StudyBlock.id).where(StudyBlock.day == dia, StudyBlock.text == texto)) is not None
    if tipo == "entrega":
        return db.scalar(select(Assessment.id).where(Assessment.due == dia, Assessment.title == texto, Assessment.removed_at.is_(None))) is not None
    return False


def uni_check(clave: str, hecho: bool, actor: str, db: Session) -> dict:
    """Lo que está en la lista de la uni o en el plan (bloques y entregas de cualquier día): una clave inventada no escribe nada."""
    import tareas
    import uni
    i = _uni_items()
    if clave not in {x["clave"] for lista in i.values() for x in lista} and not _clave_en_la_base(db, clave):
        raise HTTPException(404, "Eso ya no está en tu lista de la uni")
    tipo, _, resto = clave.partition("|")
    if tipo == "objetivo":
        uni.marcar_objetivo(resto, hecho)
    else:
        from . import vault_sync  # la base manda; hechos.json y la casilla del Panel son copias
        with db.begin_nested():
            vault_sync.sync_hechos(db)  # recoge antes lo que build.py u Obsidian hayan marcado
        vault_sync.set_hecho(db, clave, hecho)
        tareas.casilla_panel(clave, hecho)
        if tipo == "entrega":
            fecha, _, texto = resto.partition("|")
            uni.marcar_entrega(fecha, texto, hecho)
            from . import vault_sync
            with db.begin_nested():
                vault_sync.sync_uni(db)
    events.audit(db, actor, "uni.check", clave[:255], hecho=hecho)
    events.publish("uni.updated", {"clave": clave[:200]}, db=db)
    return {"clave": clave, "hecho": hecho}


@router.post("/education/check")
def education_check(body: UniCheckIn, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    return uni_check(body.clave, body.hecho, p.name, db)


# ---------- estilo de vida ----------


class ItemIn(BaseModel):
    tipo: str = Field(pattern="^(viaje|actividad|compra|garantia|suscripcion|interes)$")
    titulo: str = Field(min_length=1, max_length=200)
    dia: str | None = Field(default=None, pattern=FECHA)
    nota: str = ""


@router.get("/lifestyle")
def lifestyle(db: Session = Depends(get_db)):
    q = select(LifestyleItem).order_by(LifestyleItem.day.is_(None), LifestyleItem.day, LifestyleItem.id)
    return [{"id": i.id, "tipo": i.kind, "titulo": i.title, "dia": i.day, "nota": i.note} for i in db.scalars(q)]


@router.post("/lifestyle")
def add_item(body: ItemIn, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    i = LifestyleItem(kind=body.tipo, title=body.titulo, day=body.dia, note=body.nota)
    db.add(i)
    db.flush()
    memory.log_event(db, "lifestyle", f"{body.tipo}.created", body.titulo)
    return {"id": i.id}


@router.delete("/lifestyle/{iid}")
def del_item(iid: int, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    i = db.get(LifestyleItem, iid)
    if i is None:
        raise HTTPException(404, "No encontrado")
    events.audit(db, p.name, "lifestyle.delete", i.title)
    db.delete(i)
    return {"ok": True}
