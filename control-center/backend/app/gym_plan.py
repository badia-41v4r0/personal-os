"""Gym 2.0: lo que es del entrenador. Planificación (con versiones), rutinas (con versiones), ajustes y alias de
ejercicios, sensaciones, decisiones del entrenador, informes, importación de Hevy y el Coach.

Reglas:
- Nada se aplica solo: una recomendación es una recomendación hasta que el usuario la acepta. Las rutinas activas y las
  sesiones planificadas no se modifican en silencio: cada cambio es una versión nueva con autor y motivo.
- Los cálculos están en collectors/gym_coach.py; aquí solo se guardan estados y se validan entradas.
- Gym.md sigue siendo la fuente de los entrenos. La importación de Hevy solo AÑADE sesiones nuevas (mismo criterio
  que collectors/hevy_import.py) y guarda la trazabilidad (id externo, duración, filas originales) en SQLite.
"""
import hashlib
import json
import re
import sys
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import events, gym
from .adapters import hostagent
from .config import ROOT, get_settings
from .db import get_db, session_scope, utcnow
from .gym import (ajustes as ajustes_ej, contexto, correcciones, duraciones as duraciones_ses, hoy, log_d, path, plan_d,
                  planificadas, rutina_activa, sesiones)
from .models import (ChatSession, GymCoachDecision, GymExerciseAlias, GymExerciseSetting, GymHevyWorkout, GymImport,
                     GymPause, GymPlannedSession, GymPlannedVersion, GymRecoveryLog, GymReport, GymRoutine, GymRoutineVersion,
                     UserPreference)
from .security import Principal, current_principal, require_admin

sys.path.insert(0, str(ROOT / "collectors"))
import gym_coach as gc  # noqa: E402
import gym_stats  # noqa: E402

router = APIRouter(prefix="/api/v1/gym", dependencies=[Depends(current_principal)])
COACH_MD = ROOT / "control-center/gym/coach.md"
MAX_CSV = 5 * 1024 * 1024


def _iso(d):
    return d.isoformat() + "Z" if d else None


def _fecha(s: str) -> str:
    try:
        return date.fromisoformat(s).isoformat()
    except (TypeError, ValueError):
        raise HTTPException(422, "Fecha no válida (AAAA-MM-DD)")


# ---------- ajustes y alias de ejercicios ----------

class SettingsIn(BaseModel):
    rep_min: int | None = Field(None, ge=1, le=50)
    rep_max: int | None = Field(None, ge=1, le=60)
    series: int | None = Field(None, ge=1, le=10)
    incremento_kg: float | None = Field(None, gt=0, le=50)
    metodo: str | None = Field(None, pattern="^(top_set|doble_progresion)$")
    descanso_s: int | None = Field(None, ge=0, le=900)
    categoria: str | None = Field(None, pattern="^(compuesto|maquina|aislamiento|peso_corporal|cardio)$")
    rir_top: int | None = Field(None, ge=0, le=5)
    principales: list[str] | None = None
    secundarios: list[str] | None = None
    notas: str | None = Field(None, max_length=500)


@router.put("/exercises/{eid}/settings")
def put_settings(eid: str, body: SettingsIn, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    grupos = set(gym_stats._reglas()["grupos"])
    for lst in (body.principales, body.secundarios):
        if lst is not None and not set(lst) <= grupos:
            raise HTTPException(422, f"Músculo desconocido: {', '.join(sorted(set(lst) - grupos))}")
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    if "rep_min" in data and "rep_max" in data and data["rep_min"] > data["rep_max"]:
        raise HTTPException(422, "El mínimo del rango no puede ser mayor que el máximo")
    s = db.get(GymExerciseSetting, eid)
    if s is None:
        s = GymExerciseSetting(exercise_id=eid)
        db.add(s)
    antes = dict(s.settings or {})
    s.settings, s.updated_by, s.updated_at = data, p.name, utcnow()
    events.audit(db, p.name, "gym.exercise.settings", target=eid, antes=antes, despues=data)
    events.publish("gym.updated", {"what": "settings", "exercise_id": eid}, db=db)
    return {"exercise_id": eid, "settings": data}


class AliasIn(BaseModel):
    nombre: str = Field(min_length=1, max_length=160)
    exercise_id: str = Field(min_length=1, max_length=120, pattern="^[a-z0-9-]+$")


@router.post("/exercises/aliases")
def add_alias(body: AliasIn, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    alias = gym_stats.norm(body.nombre)
    if gym_stats.slug(alias) == body.exercise_id:
        raise HTTPException(422, "Ese nombre ya corresponde a ese ejercicio")
    a = db.get(GymExerciseAlias, alias) or GymExerciseAlias(alias=alias)
    a.exercise_id, a.created_by, a.created_at = body.exercise_id, p.name, utcnow()
    db.merge(a)
    events.audit(db, p.name, "gym.exercise.alias", target=alias, exercise_id=body.exercise_id)
    events.publish("gym.updated", {"what": "alias"}, db=db)
    return {"alias": alias, "exercise_id": body.exercise_id}


@router.delete("/exercises/aliases/{alias}")
def del_alias(alias: str, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    a = db.get(GymExerciseAlias, alias)
    if not a:
        raise HTTPException(404, "Alias no encontrado")
    db.delete(a)
    events.audit(db, p.name, "gym.exercise.alias.delete", target=alias)
    return {"ok": True}


# ---------- sensaciones ----------

class RecoveryIn(BaseModel):
    fecha: str
    energia: int | None = Field(None, ge=1, le=5)
    sueno: int | None = Field(None, ge=1, le=5)
    sueno_horas: float | None = Field(None, ge=0, le=16)
    agujetas: int | None = Field(None, ge=1, le=5)
    motivacion: int | None = Field(None, ge=1, le=5)
    estres: int | None = Field(None, ge=1, le=5)
    molestia_zona: str = Field("", max_length=64)
    molestia_intensidad: int | None = Field(None, ge=1, le=5)
    notas: str = Field("", max_length=1000)


@router.get("/recovery")
def recovery(db: Session = Depends(get_db)):
    c = contexto(db)
    zonas = gc.molestias(c["perfil"], c["logs"], hoy())
    r = gc.recuperacion(c["sesiones"], c["logs"], hoy(), zonas)
    r["registros"] = c["logs"][::-1][:60]
    r["pausas"] = c["pausas"][::-1][:30]
    return r


@router.post("/recovery")
def post_recovery(body: RecoveryIn, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    f = _fecha(body.fecha)
    if f > hoy().isoformat():
        raise HTTPException(422, "No se pueden registrar sensaciones de días futuros")
    l = db.scalar(select(GymRecoveryLog).where(GymRecoveryLog.date == f))
    nuevo = l is None
    if nuevo:
        l = GymRecoveryLog(date=f)
        db.add(l)
    for k, v in body.model_dump().items():
        if k != "fecha":
            setattr(l, k, v.strip() if isinstance(v, str) else v)
    l.updated_at = utcnow()
    events.audit(db, p.name, "gym.recovery." + ("create" if nuevo else "update"), target=f)
    events.publish("gym.updated", {"what": "recovery", "fecha": f}, db=db)
    db.flush()
    return log_d(l)


@router.delete("/recovery/{fecha}")
def del_recovery(fecha: str, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    l = db.scalar(select(GymRecoveryLog).where(GymRecoveryLog.date == _fecha(fecha)))
    if not l:
        raise HTTPException(404, "No hay registro ese día")
    db.delete(l)
    events.audit(db, p.name, "gym.recovery.delete", target=fecha)
    return {"ok": True}


# ---------- periodos sin entrenar ----------

class PauseIn(BaseModel):
    desde: str
    hasta: str | None = None  # sin fin = en curso
    motivo: str = Field("enfermedad", pattern="^(enfermedad|lesion|vacaciones|otro)$")
    nota: str = Field("", max_length=500)


def crear_pausa(db: Session, body: PauseIn, actor: str) -> dict:
    """Valida y guarda un periodo sin entrenar. La comparten el panel y la acción `gym.pause.log` de los agentes."""
    d = _fecha(body.desde)
    h = _fecha(body.hasta) if body.hasta else None
    if h and h < d:
        raise HTTPException(422, "La fecha de fin no puede ser anterior a la de inicio")
    if d > (hoy() + timedelta(days=60)).isoformat():
        raise HTTPException(422, "Como mucho, una pausa que empiece en los próximos 60 días")
    for x in db.scalars(select(GymPause)):
        if d <= (x.end or "9999-12-31") and (h or "9999-12-31") >= x.start:
            raise HTTPException(409, f"Se solapa con la pausa del {x.start}" + (f" al {x.end}" if x.end else " (en curso)"))
    x = GymPause(start=d, end=h, reason=body.motivo, note=body.nota.strip(), created_by=actor[:64])
    db.add(x)
    db.flush()
    events.audit(db, actor, "gym.pause.create", target=f"{d}..{h or ''}", motivo=body.motivo)
    events.publish("gym.updated", {"what": "pause"}, db=db)
    return gym.pausa_d(x)


@router.get("/pauses")
def get_pauses(db: Session = Depends(get_db)):
    return gym.pausas(db)[::-1]


@router.post("/pauses")
def post_pause(body: PauseIn, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    return crear_pausa(db, body, p.name)


@router.post("/pauses/{pid}/end")
def end_pause(pid: int, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    """Termina hoy una pausa en curso (o ayer, si empezó antes de hoy y hoy ya entrenas)."""
    x = db.get(GymPause, pid)
    if x is None:
        raise HTTPException(404, "Pausa no encontrada")
    if x.end:
        raise HTTPException(409, "Esa pausa ya tiene fecha de fin")
    x.end = max(x.start, (hoy() - timedelta(days=1)).isoformat())
    events.audit(db, p.name, "gym.pause.end", target=str(pid), hasta=x.end)
    events.publish("gym.updated", {"what": "pause"}, db=db)
    return gym.pausa_d(x)


@router.delete("/pauses/{pid}")
def delete_pause(pid: int, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    x = db.get(GymPause, pid)
    if x is None:
        raise HTTPException(404, "Pausa no encontrada")
    db.delete(x)
    events.audit(db, p.name, "gym.pause.delete", target=str(pid))
    events.publish("gym.updated", {"what": "pause"}, db=db)
    return {"ok": True}


# ---------- calendario ----------

@router.get("/calendar")
def calendar(desde: str | None = None, hasta: str | None = None, db: Session = Depends(get_db)):
    h = hoy()
    d0 = date.fromisoformat(_fecha(desde)) if desde else h - timedelta(days=h.weekday())
    d1 = date.fromisoformat(_fecha(hasta)) if hasta else d0 + timedelta(days=6)
    if (d1 - d0).days > 62 or d1 < d0:
        raise HTTPException(422, "Rango de 1 a 62 días")
    c = contexto(db)
    return {"desde": d0.isoformat(), "hasta": d1.isoformat(),
            "dias": gc.calendario(c["sesiones"], d0, d1, h, c["rutina"], c["planificadas"], c["pausas"]),
            "reprogramar": gc.reprogramar(c["sesiones"], h, c["rutina"], c["planificadas"], c["pausas"]),
            "rutina": {k: c["rutina"][k] for k in ("id", "nombre", "version")} if c["rutina"] else None,
            "dias_rutina": gc.dias_rutina(c["rutina"])}


# ---------- recomendaciones ----------

def huella(prop: dict | None) -> str:
    if not prop:
        return ""
    base = [prop["fecha"], prop["nombre"], [(e["id"], (e["objetivo"] or {}).get("top"), e["series"]) for e in prop["ejercicios"]]]
    return hashlib.sha1(json.dumps(base, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _propuesta(db: Session, fecha: str | None = None, nombre: str | None = None) -> tuple[dict | None, dict]:
    c = contexto(db)
    f = date.fromisoformat(fecha) if fecha else None
    prop = gc.proponer_sesion(c["sesiones"], hoy(), c["rutina"], c["ajustes"], c["logs"], c["perfil"],
                              fecha=f, nombre=nombre, planificadas=c["planificadas"], duraciones=c["duraciones"],
                              pausas=c["pausas"])
    if prop:
        prop["huella"] = huella(prop)
    return prop, c


@router.get("/recommendations")
def recommendations(fecha: str | None = None, nombre: str | None = None, db: Session = Depends(get_db)):
    if bool(fecha) != bool(nombre):
        raise HTTPException(422, "Indica fecha y nombre, o ninguno")
    prop, c = _propuesta(db, fecha and _fecha(fecha), nombre)
    ya = next((p for p in c["planificadas"] if prop and p["fecha"] == prop["fecha"] and p["estado"] in ("aceptada", "pospuesta", "hecha")), None)
    dec = db.scalars(select(GymCoachDecision).where(GymCoachDecision.status == "propuesta").order_by(GymCoachDecision.id.desc()))
    return {"siguiente": prop, "planificada": ya,
            "reprogramar": [r | {"id": f"reprog-{r['desde']}"} for r in gc.reprogramar(c["sesiones"], hoy(), c["rutina"], c["planificadas"], c["pausas"])],
            "decisiones": [decision_d(d) for d in dec], "niveles": gc.NIVELES}


class AcceptIn(BaseModel):
    huella: str | None = None
    fecha: str | None = None  # posponer a esta fecha
    nota: str = Field("", max_length=500)


def _registrar_decisiones_motor(db: Session, plan_id: str, prop: dict, actor: str) -> None:
    """Al aceptar un plan, las decisiones con peso (subir, bajar, mantener, precaución, lastre) quedan registradas
    para evaluarlas después con el entreno real."""
    for e in prop["ejercicios"]:
        o = e.get("objetivo") or {}
        if o.get("accion") not in ("subir_peso", "bajar_peso", "mantener", "precaucion", "lastre"):
            continue
        db.add(GymCoachDecision(apply_date=prop["fecha"], scope="ejercicio", target=e["nombre"], exercise_id=e["id"],
                                kind=o["accion"] if o["accion"] != "lastre" else "subir_peso",
                                situation=(o.get("ultimo") or {}).get("series") and "Último: " + ", ".join(o["ultimo"]["series"]) or "",
                                evidence=o.get("evidencia", []), recommendation=o.get("motivo", ""), reason=o.get("motivo", ""),
                                expected=f"Top set {o['top']['peso'] if o['top'] and o['top']['peso'] is not None else 'PC'}"
                                         f"×{o['top']['reps'] if o['top'] else '?'} el {prop['fecha']}",
                                objective={"peso": (o.get("top") or {}).get("peso"), "reps": (o.get("top") or {}).get("reps")},
                                payload={"plan_id": plan_id}, status="aceptada", source="motor", decided_by=actor,
                                decided_at=utcnow()))


def crear_plan(db: Session, fecha: str, nombre: str, ejercicios: list[dict], justificacion: str, actor: str,
               motivo: str = "", estado: str = "aceptada", origen_fecha: str | None = None) -> GymPlannedSession:
    # Una sola planificación viva por fecha: la anterior queda «sustituida» (no se borra)
    for old in db.scalars(select(GymPlannedSession).where(GymPlannedSession.date == fecha,
                                                          GymPlannedSession.status.in_(("aceptada", "pospuesta")))):
        old.status, old.updated_at = "sustituida", utcnow()
    rut = rutina_activa(db)
    p = GymPlannedSession(id=str(uuid.uuid4()), date=fecha, name=nombre, status=estado, current_version=1,
                          origin_date=origen_fecha, routine_id=rut["id"] if rut else None,
                          routine_version=rut["version"] if rut else None, created_by=actor)
    db.add(p)
    db.add(GymPlannedVersion(planned_id=p.id, version=1, exercises=ejercicios, rationale=justificacion, author=actor,
                             reason=motivo or "Plan aceptado"))
    db.flush()
    return p


@router.post("/recommendations/{rid}/accept")
def accept(rid: str, body: AcceptIn, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    if rid == "siguiente":
        prop, _ = _propuesta(db)
        if not prop:
            raise HTTPException(404, "No hay una próxima sesión que recomendar")
        if body.huella and body.huella != prop["huella"]:
            raise HTTPException(409, "La recomendación ha cambiado desde que la viste (hay datos nuevos). Vuelve a mirarla.")
        fecha = _fecha(body.fecha) if body.fecha else prop["fecha"]
        if fecha < hoy().isoformat():
            raise HTTPException(422, "No se puede planificar en el pasado")
        plan = crear_plan(db, fecha, prop["nombre"], prop["ejercicios"], prop["justificacion"], p.name,
                          "Pospuesta desde " + prop["fecha"] if fecha != prop["fecha"] else "Recomendación aceptada",
                          origen_fecha=prop["fecha"] if fecha != prop["fecha"] else None)
        _registrar_decisiones_motor(db, plan.id, prop | {"fecha": fecha}, p.name)
        events.audit(db, p.name, "gym.plan.accept", target=plan.id, fecha=fecha, nombre=prop["nombre"], huella=prop["huella"])
        events.publish("gym.updated", {"what": "plan", "id": plan.id}, db=db)
        return plan_d(plan, db.scalar(select(GymPlannedVersion).where(GymPlannedVersion.planned_id == plan.id)))
    if rid.startswith("reprog-"):
        c = contexto(db)
        r = next((x for x in gc.reprogramar(c["sesiones"], hoy(), c["rutina"], c["planificadas"], c["pausas"]) if f"reprog-{x['desde']}" == rid), None)
        if not r:
            raise HTTPException(404, "Esa propuesta ya no está vigente")
        if r["tipo"] == "omitir":
            plan = crear_plan(db, r["desde"], r["sesion"], [], r["motivo"], p.name, "Sesión perdida: no se recupera", estado="omitida")
        else:
            prop, _ = _propuesta(db, r["hasta"], r["sesion"])
            plan = crear_plan(db, r["hasta"], r["sesion"], prop["ejercicios"] if prop else [], r["motivo"], p.name,
                              f"Reprogramada desde el {r['desde']}", origen_fecha=r["desde"])
        events.audit(db, p.name, "gym.plan.reschedule", target=plan.id, desde=r["desde"], hasta=r["hasta"])
        events.publish("gym.updated", {"what": "plan", "id": plan.id}, db=db)
        return {"ok": True, "plan_id": plan.id}
    if rid.isdigit():
        return decide(int(rid), "aceptada", p, db)
    raise HTTPException(404, "Recomendación no encontrada")


@router.post("/recommendations/{rid}/reject")
def reject(rid: str, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    if rid.isdigit():
        return decide(int(rid), "rechazada", p, db)
    raise HTTPException(422, "Solo se rechazan propuestas del entrenador; el resto simplemente no se aceptan")


# ---------- sesiones planificadas ----------

class PlannedExerciseIn(BaseModel):
    id: str | None = Field(None, max_length=120)
    nombre: str = Field(min_length=1, max_length=160)
    series: int = Field(3, ge=1, le=10)
    rep_min: int = Field(6, ge=1, le=50)
    rep_max: int = Field(10, ge=1, le=60)
    peso: float | None = Field(None, ge=0, le=1000)
    reps: int | None = Field(None, ge=1, le=60)
    backoff_peso: float | None = Field(None, ge=0, le=1000)
    descanso_s: int = Field(120, ge=0, le=900)
    notas: str = Field("", max_length=500)


def _sin_cambios(x: PlannedExerciseIn, p: dict) -> bool:
    o = p.get("objetivo") or {}
    top = o.get("top") or {}
    bo = (o.get("backoffs") or [{}])[0] if o.get("backoffs") else {}
    rango = p.get("rango") or [None, None]
    return (x.nombre == p.get("nombre") and x.series == p.get("series") and [x.rep_min, x.rep_max] == list(rango)
            and x.peso == top.get("peso") and (x.reps or None) == (top.get("reps") if isinstance(top.get("reps"), int) else None)
            and (x.backoff_peso is None or x.backoff_peso == bo.get("peso")) and x.descanso_s == p.get("descanso_s")
            and (x.notas or "") == (p.get("notas") or ""))


def ejercicio_plan(x: PlannedExerciseIn, previo: dict | None = None) -> dict:
    """Formato guardado (el mismo que produce el motor), a partir de lo editado a mano."""
    eid = x.id or gym_stats.slug(gym_stats.norm(x.nombre))
    if previo and previo.get("id") == eid and _sin_cambios(x, previo):
        return previo  # sin cambios: conserva el objetivo y la explicación del motor
    tipo, pri, sec = gym_stats.clasificar(x.nombre)
    top = {"peso": x.peso, "reps": x.reps or x.rep_min, "rir": 0}
    bw = x.backoff_peso if x.backoff_peso is not None else (round(x.peso * 0.9 / 2.5) * 2.5 if x.peso else None)
    bos = [{"peso": bw, "reps": f"{x.rep_min}–{x.rep_max}", "rir": "1–2"} for _ in range(x.series - 1)]
    obj = dict((previo or {}).get("objetivo") or {})
    obj |= {"top": top, "backoffs": bos, "series_objetivo": [top] + bos, "rango": [x.rep_min, x.rep_max]}
    if x.notas:
        obj["motivo"] = x.notas
    obj.setdefault("accion", "manual")
    obj.setdefault("motivo", "Modificado a mano")
    return {**(previo or {}), "id": eid, "nombre": x.nombre, "series": x.series, "rango": [x.rep_min, x.rep_max],
            "descanso_s": x.descanso_s, "objetivo": obj, "principales": (previo or {}).get("principales", pri),
            "secundarios": (previo or {}).get("secundarios", sec), "notas": x.notas, "editado": True}


class PlanIn(BaseModel):
    fecha: str
    nombre: str = Field(min_length=1, max_length=120)
    ejercicios: list[PlannedExerciseIn] | None = None  # None = los de la recomendación para esa fecha
    motivo: str = Field("", max_length=500)


@router.get("/plans")
def plans(desde: str | None = None, hasta: str | None = None, todas: bool = False, db: Session = Depends(get_db)):
    c = contexto(db)
    ses = {s.id: s for s in c["sesiones"]}
    out = []
    for pl in planificadas(db, desde and _fecha(desde), hasta and _fecha(hasta))[::-1]:
        if not todas and pl["estado"] in ("sustituida", "descartada"):
            continue
        pl["comparacion"] = gc.comparar(pl, ses.get(pl["workout_id"])) if pl["workout_id"] else None
        out.append(pl)
    return out


@router.post("/plans")
def create_plan(body: PlanIn, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    f = _fecha(body.fecha)
    if f < hoy().isoformat():
        raise HTTPException(422, "No se puede planificar en el pasado")
    if body.ejercicios is None:
        prop, _ = _propuesta(db, f, body.nombre)
        if not prop:
            raise HTTPException(404, "No hay datos para proponer esa sesión")
        ejs, just = prop["ejercicios"], prop["justificacion"]
    else:
        ejs, just = [ejercicio_plan(x) for x in body.ejercicios], body.motivo or "Planificada a mano"
    plan = crear_plan(db, f, body.nombre, ejs, just, p.name, body.motivo or "Creada desde el panel")
    events.audit(db, p.name, "gym.plan.create", target=plan.id, fecha=f, nombre=body.nombre, ejercicios=len(ejs))
    events.publish("gym.updated", {"what": "plan", "id": plan.id}, db=db)
    return plan_d(plan, db.scalar(select(GymPlannedVersion).where(GymPlannedVersion.planned_id == plan.id)))


def _plan(db: Session, pid: str) -> GymPlannedSession:
    pl = db.get(GymPlannedSession, pid)
    if not pl:
        raise HTTPException(404, "Sesión planificada no encontrada")
    return pl


@router.get("/plans/{pid}")
def plan(pid: str, db: Session = Depends(get_db)):
    pl = _plan(db, pid)
    c = contexto(db)  # antes de leer: sincroniza la asociación automática con Gym.md
    vs = list(db.scalars(select(GymPlannedVersion).where(GymPlannedVersion.planned_id == pid).order_by(GymPlannedVersion.version)))
    cur = next((v for v in vs if v.version == pl.current_version), None)
    d = plan_d(pl, cur)
    ses = {s.id: s for s in c["sesiones"]}
    d["comparacion"] = gc.comparar(d, ses.get(pl.workout_id)) if pl.workout_id else None
    d["versiones"] = [{"version": v.version, "autor": v.author, "motivo": v.reason, "fecha": _iso(v.created_at),
                       "ejercicios": v.exercises} for v in vs]
    d["candidatas"] = [{"id": s.id, "fecha": s.fecha, "nombre": s.nombre} for s in c["sesiones"]
                       if abs((date.fromisoformat(s.fecha) - date.fromisoformat(pl.date)).days) <= 3]
    return d


class PlanPatch(BaseModel):
    ejercicios: list[PlannedExerciseIn] | None = None
    estado: str | None = Field(None, pattern="^(aceptada|pospuesta|omitida|descartada)$")
    fecha: str | None = None
    motivo: str = Field("", max_length=500)
    version_base: int | None = None


@router.patch("/plans/{pid}")
def patch_plan(pid: str, body: PlanPatch, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    pl = _plan(db, pid)
    if body.version_base is not None and body.version_base != pl.current_version:
        raise HTTPException(409, "La planificación ha cambiado desde que la abriste. Recárgala.")
    if pl.status in ("sustituida",):
        raise HTTPException(409, "Esta planificación ya fue sustituida por otra")
    cambios = []
    if body.ejercicios is not None:
        if pl.workout_id:
            raise HTTPException(409, "Ya está asociada a un entreno realizado: no se cambia lo que estaba previsto")
        cur = db.scalar(select(GymPlannedVersion).where(GymPlannedVersion.planned_id == pid,
                                                        GymPlannedVersion.version == pl.current_version))
        previos = {e["id"]: e for e in (cur.exercises if cur else [])}
        ejs = [ejercicio_plan(x, previos.get(x.id or "")) for x in body.ejercicios]
        pl.current_version += 1
        db.add(GymPlannedVersion(planned_id=pid, version=pl.current_version, exercises=ejs,
                                 rationale=cur.rationale if cur else "", author=p.name, reason=body.motivo or "Modificada"))
        cambios.append(f"ejercicios v{pl.current_version}")
    if body.fecha:
        f = _fecha(body.fecha)
        if f != pl.date:
            if f < hoy().isoformat():
                raise HTTPException(422, "No se puede mover al pasado")
            pl.origin_date = pl.origin_date or pl.date
            pl.date = f
            cambios.append(f"fecha → {f}")
    if body.estado:
        pl.status = body.estado
        cambios.append(f"estado → {body.estado}")
    pl.updated_at = utcnow()
    events.audit(db, p.name, "gym.plan.update", target=pid, cambios=cambios, motivo=body.motivo)
    events.publish("gym.updated", {"what": "plan", "id": pid}, db=db)
    db.flush()
    return plan(pid, db)


class LinkIn(BaseModel):
    workout_id: str | None = None


@router.post("/plans/{pid}/link")
def link_plan(pid: str, body: LinkIn, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    """Asociación manual con un entreno de Gym.md (o quitarla). Una asociación manual no la cambia el sistema."""
    pl = _plan(db, pid)
    if body.workout_id:
        if not any(s.id == body.workout_id for s in sesiones(correcciones(db))):
            raise HTTPException(404, "Ese entreno no existe en Gym.md")
        pl.workout_id, pl.link_mode, pl.status = body.workout_id, "manual", "hecha"
    else:
        pl.workout_id, pl.link_mode, pl.status = None, "manual", "aceptada"
    events.audit(db, p.name, "gym.plan.link", target=pid, workout=body.workout_id)
    events.publish("gym.updated", {"what": "plan", "id": pid}, db=db)
    return {"ok": True}


# ---------- rutinas ----------

class RoutineExercise(BaseModel):
    id: str | None = Field(None, max_length=120)
    nombre: str = Field(min_length=1, max_length=160)
    series: int = Field(3, ge=1, le=10)
    rep_min: int = Field(6, ge=1, le=50)
    rep_max: int = Field(10, ge=1, le=60)
    descanso_s: int = Field(120, ge=0, le=900)
    metodo: str = Field("top_set", pattern="^(top_set|doble_progresion)$")
    incremento_kg: float | None = Field(None, gt=0, le=50)


class RoutineDay(BaseModel):
    nombre: str = Field(min_length=1, max_length=60)
    ejercicios: list[RoutineExercise] = Field(default_factory=list, max_length=15)


class RoutineSpec(BaseModel):
    dias: dict[str, RoutineDay]
    notas: str = Field("", max_length=2000)


def _spec(s: RoutineSpec) -> dict:
    out = {"dias": {}, "notas": s.notas}
    for k, d in s.dias.items():
        if k not in {str(i) for i in range(7)}:
            raise HTTPException(422, "Los días van de 0 (lunes) a 6 (domingo)")
        ejs = []
        for e in d.ejercicios:
            if e.rep_min > e.rep_max:
                raise HTTPException(422, f"{e.nombre}: el mínimo del rango es mayor que el máximo")
            ejs.append(e.model_dump() | {"id": e.id or gym_stats.slug(gym_stats.norm(e.nombre))})
        out["dias"][k] = {"nombre": d.nombre, "ejercicios": ejs}
    return out


def _diff(a: dict, b: dict) -> list[str]:
    """Resumen legible de lo que cambia entre dos versiones."""
    out = []
    da, db_ = a.get("dias", {}), b.get("dias", {})
    for k in sorted(set(da) | set(db_)):
        dia = gc.DIAS[int(k)]
        x, y = da.get(k), db_.get(k)
        if not x:
            out.append(f"{dia}: nuevo día «{y['nombre']}»")
            continue
        if not y:
            out.append(f"{dia}: se quita «{x['nombre']}»")
            continue
        if x["nombre"] != y["nombre"]:
            out.append(f"{dia}: «{x['nombre']}» → «{y['nombre']}»")
        ex = {e["id"]: e for e in x["ejercicios"]}
        ey = {e["id"]: e for e in y["ejercicios"]}
        for i in ey.keys() - ex.keys():
            out.append(f"{dia}: + {ey[i]['nombre']}")
        for i in ex.keys() - ey.keys():
            out.append(f"{dia}: − {ex[i]['nombre']}")
        for i in ex.keys() & ey.keys():
            cambios = [f"{k2} {ex[i].get(k2)}→{ey[i].get(k2)}" for k2 in ("series", "rep_min", "rep_max", "descanso_s", "metodo", "incremento_kg")
                       if ex[i].get(k2) != ey[i].get(k2)]
            if cambios:
                out.append(f"{dia}: {ey[i]['nombre']} ({', '.join(cambios)})")
        if [e["id"] for e in x["ejercicios"] if e["id"] in ey] != [e["id"] for e in y["ejercicios"] if e["id"] in ex]:
            out.append(f"{dia}: cambia el orden")
    if a.get("notas", "") != b.get("notas", ""):
        out.append("notas")
    return out


def routine_d(db: Session, r: GymRoutine, versiones: bool = False) -> dict:
    vs = list(db.scalars(select(GymRoutineVersion).where(GymRoutineVersion.routine_id == r.id).order_by(GymRoutineVersion.version)))
    cur = next((v for v in vs if v.version == r.current_version), None)
    d = {"id": r.id, "nombre": r.name, "estado": r.status, "version": r.current_version, "creada_por": r.created_by,
         "creada": _iso(r.created_at), "actualizada": _iso(r.updated_at), "spec": cur.spec if cur else {}}
    if versiones:
        ses = sesiones(correcciones(db))
        pls = planificadas(db)
        sesmap = {s.id: s for s in ses}
        lista = []
        for i, v in enumerate(vs):
            ini = v.created_at.date().isoformat()
            fin = vs[i + 1].created_at.date().isoformat() if i + 1 < len(vs) else None
            hechas = [s for s in ses if s.fecha >= ini and (fin is None or s.fecha < fin)]
            planes = [p for p in pls if p["rutina_id"] == r.id and p["rutina_version"] == v.version and p["workout_id"]]
            cums = [gc.comparar(p, sesmap.get(p["workout_id"]))["cumplimiento"] for p in planes if sesmap.get(p["workout_id"])]
            cums = [x for x in cums if x is not None]
            lista.append({"version": v.version, "autor": v.author, "motivo": v.reason, "cambios": v.changes,
                          "fecha": _iso(v.created_at), "spec": v.spec,
                          "resultados": {"desde": ini, "hasta": fin, "sesiones": len(hechas),
                                         "planes_cumplidos": len(cums),
                                         "cumplimiento_medio": round(sum(cums) / len(cums)) if cums else None,
                                         "nivel": "calculado"}})
        d["versiones"] = lista[::-1]
    return d


@router.get("/routines")
def routines(db: Session = Depends(get_db)):
    return [routine_d(db, r) for r in db.scalars(select(GymRoutine).order_by(GymRoutine.status, GymRoutine.updated_at.desc()))]


class RoutineIn(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    spec: RoutineSpec | None = None
    desde_historial: bool = False
    motivo: str = Field("", max_length=500)


@router.post("/routines")
def create_routine(body: RoutineIn, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    if body.spec is None and not body.desde_historial:
        raise HTTPException(422, "Indica la rutina o créala a partir de tu historial")
    spec = _spec(body.spec) if body.spec else gc.rutina_desde_historial(sesiones(correcciones(db)))
    r = GymRoutine(id=str(uuid.uuid4()), name=body.nombre, status="draft", current_version=1, created_by=p.name)
    db.add(r)
    db.add(GymRoutineVersion(routine_id=r.id, version=1, spec=spec, author=p.name,
                             reason=body.motivo or ("Creada a partir del historial" if body.desde_historial else "Creada"),
                             changes=["versión inicial"]))
    events.audit(db, p.name, "gym.routine.create", target=r.id, nombre=body.nombre, historial=body.desde_historial)
    events.publish("gym.updated", {"what": "routine", "id": r.id}, db=db)
    db.flush()
    return routine_d(db, r, True)


def _routine(db: Session, rid: str) -> GymRoutine:
    r = db.get(GymRoutine, rid)
    if not r:
        raise HTTPException(404, "Rutina no encontrada")
    return r


@router.get("/routines/{rid}")
def routine(rid: str, db: Session = Depends(get_db)):
    return routine_d(db, _routine(db, rid), True)


class RoutinePatch(BaseModel):
    nombre: str | None = Field(None, min_length=1, max_length=120)
    spec: RoutineSpec | None = None
    estado: str | None = Field(None, pattern="^(draft|active|archived)$")
    motivo: str = Field("", max_length=500)
    confirmar: bool = False  # obligatorio para cambiar la rutina activa o activar una
    version_base: int | None = None


def nueva_version(db: Session, r: GymRoutine, spec: dict, autor: str, motivo: str) -> list[str]:
    cur = db.scalar(select(GymRoutineVersion).where(GymRoutineVersion.routine_id == r.id,
                                                    GymRoutineVersion.version == r.current_version))
    cambios = _diff(cur.spec if cur else {}, spec)
    if not cambios:
        return []
    r.current_version += 1
    db.add(GymRoutineVersion(routine_id=r.id, version=r.current_version, spec=spec, author=autor, reason=motivo, changes=cambios))
    return cambios


@router.patch("/routines/{rid}")
def patch_routine(rid: str, body: RoutinePatch, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    r = _routine(db, rid)
    if body.version_base is not None and body.version_base != r.current_version:
        raise HTTPException(409, "La rutina ha cambiado desde que la abriste. Recárgala.")
    activa = r.status == "active"
    if (body.spec is not None and activa or body.estado == "active" and not activa) and not body.confirmar:
        raise HTTPException(428, "Es la rutina activa (o vas a activarla): confirma el cambio")
    if body.spec is not None and activa and not body.motivo.strip():
        raise HTTPException(422, "Explica el motivo del cambio de la rutina activa")
    cambios = []
    if body.nombre:
        r.name = body.nombre
        cambios.append("nombre")
    if body.spec is not None:
        c = nueva_version(db, r, _spec(body.spec), p.name, body.motivo or "Editada")
        cambios += c
    if body.estado and body.estado != r.status:
        if body.estado == "active":
            for o in db.scalars(select(GymRoutine).where(GymRoutine.status == "active", GymRoutine.id != r.id)):
                o.status, o.updated_at = "draft", utcnow()
                events.audit(db, p.name, "gym.routine.deactivate", target=o.id, motivo=f"Se activa «{r.name}»")
        r.status = body.estado
        cambios.append(f"estado → {body.estado}")
    r.updated_at = utcnow()
    events.audit(db, p.name, "gym.routine.update", target=rid, cambios=cambios, motivo=body.motivo)
    events.publish("gym.updated", {"what": "routine", "id": rid}, db=db)
    db.flush()
    return routine_d(db, r, True)


@router.post("/routines/{rid}/duplicate")
def duplicate_routine(rid: str, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    r = _routine(db, rid)
    cur = db.scalar(select(GymRoutineVersion).where(GymRoutineVersion.routine_id == rid, GymRoutineVersion.version == r.current_version))
    n = GymRoutine(id=str(uuid.uuid4()), name=f"{r.name} (copia)", status="draft", created_by=p.name)
    db.add(n)
    db.add(GymRoutineVersion(routine_id=n.id, version=1, spec=cur.spec if cur else {"dias": {}}, author=p.name,
                             reason=f"Copia de «{r.name}» v{r.current_version}", changes=["versión inicial"]))
    events.audit(db, p.name, "gym.routine.duplicate", target=n.id, origen=rid)
    db.flush()
    return routine_d(db, n, True)


class RestoreIn(BaseModel):
    confirmar: bool = False
    motivo: str = Field("", max_length=500)


@router.post("/routines/{rid}/restore/{version}")
def restore_routine(rid: str, version: int, body: RestoreIn, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    r = _routine(db, rid)
    v = db.scalar(select(GymRoutineVersion).where(GymRoutineVersion.routine_id == rid, GymRoutineVersion.version == version))
    if not v:
        raise HTTPException(404, "Versión no encontrada")
    if r.status == "active" and not body.confirmar:
        raise HTTPException(428, "Es la rutina activa: confirma la restauración")
    cambios = nueva_version(db, r, v.spec, p.name, body.motivo or f"Restaurada la v{version}")
    r.updated_at = utcnow()
    events.audit(db, p.name, "gym.routine.restore", target=rid, version=version)
    db.flush()
    return routine_d(db, r, True) | {"cambios": cambios}


# ---------- decisiones del entrenador ----------

def decision_d(d: GymCoachDecision) -> dict:
    return {"id": d.id, "fecha": _iso(d.created_at), "fecha_aplicacion": d.apply_date, "alcance": d.scope,
            "objetivo_de": d.target, "ejercicio_id": d.exercise_id, "tipo": d.kind, "situacion": d.situation,
            "datos": d.evidence, "recomendacion": d.recommendation, "motivo": d.reason, "resultado_esperado": d.expected,
            "objetivo": d.objective, "estado": d.status, "fuente": d.source, "evaluacion": d.evaluation or None,
            "evaluada": _iso(d.evaluated_at), "decidida_por": d.decided_by, "decidida": _iso(d.decided_at),
            "payload": d.payload, "run_id": d.run_id}


def evaluar(db: Session, ses) -> None:
    for d in db.scalars(select(GymCoachDecision).where(GymCoachDecision.status.in_(("aceptada", "aplicada")),
                                                       GymCoachDecision.exercise_id.is_not(None))):
        if (d.evaluation or {}).get("estado") not in (None, "pendiente"):
            continue
        ev = gc.evaluar_decision({"ejercicio_id": d.exercise_id, "objetivo": d.objective,
                                  "fecha": d.apply_date or d.created_at.date().isoformat()}, ses)
        if ev:
            d.evaluation = ev
            if ev["estado"] != "pendiente":
                d.evaluated_at = utcnow()


@router.get("/coach/decisions")
def decisions(estado: str | None = None, ejercicio: str | None = None, limite: int = Query(100, ge=1, le=500),
              db: Session = Depends(get_db)):
    evaluar(db, sesiones(correcciones(db)))
    q = select(GymCoachDecision)
    if estado:
        q = q.where(GymCoachDecision.status == estado)
    if ejercicio:
        q = q.where(GymCoachDecision.exercise_id == ejercicio)
    return [decision_d(d) for d in db.scalars(q.order_by(GymCoachDecision.id.desc()).limit(limite))]


KINDS = "^(subir_peso|mantener|bajar_peso|mas_reps|reducir_volumen|cambiar_ejercicio|frecuencia|reorganizar|descarga|otro)$"


class DecisionIn(BaseModel):
    alcance: str = Field("ejercicio", pattern="^(ejercicio|musculo|rutina|general)$")
    objetivo_de: str = Field("", max_length=160)
    ejercicio_id: str | None = Field(None, max_length=120)
    tipo: str = Field(pattern=KINDS)
    situacion: str = Field("", max_length=2000)
    datos: list[str] = Field(default_factory=list, max_length=20)
    recomendacion: str = Field(min_length=1, max_length=2000)
    motivo: str = Field("", max_length=2000)
    resultado_esperado: str = Field("", max_length=1000)
    peso: float | None = Field(None, ge=0, le=1000)
    reps: int | None = Field(None, ge=1, le=60)
    fecha_aplicacion: str | None = None


@router.post("/coach/decisions")
def create_decision(body: DecisionIn, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    d = GymCoachDecision(scope=body.alcance, target=body.objetivo_de, exercise_id=body.ejercicio_id, kind=body.tipo,
                         situation=body.situacion, evidence=body.datos, recommendation=body.recomendacion,
                         reason=body.motivo, expected=body.resultado_esperado,
                         objective={"peso": body.peso, "reps": body.reps} if body.reps else {},
                         apply_date=_fecha(body.fecha_aplicacion) if body.fecha_aplicacion else None,
                         status="aceptada", source="usuario", decided_by=p.name, decided_at=utcnow())
    db.add(d)
    db.flush()
    events.audit(db, p.name, "gym.decision.create", target=str(d.id), tipo=body.tipo)
    return decision_d(d)


class DecideIn(BaseModel):
    confirmar: bool = False


def decide(did: int, estado: str, p: Principal, db: Session, confirmar: bool = False) -> dict:
    d = db.get(GymCoachDecision, did)
    if not d:
        raise HTTPException(404, "Decisión no encontrada")
    if d.status != "propuesta":
        raise HTTPException(409, f"Ya está {d.status}")
    if (estado == "aceptada" and d.kind == "reorganizar" and (d.payload or {}).get("rutina") and not confirmar
            and db.scalar(select(GymRoutine).where(GymRoutine.status == "active"))):
        raise HTTPException(428, "Cambia la rutina activa: confirma el cambio")
    d.status, d.decided_by, d.decided_at = estado, p.name, utcnow()
    aplicado = None
    # Una propuesta de rutina aceptada crea una versión nueva (de la activa o de una rutina nueva en borrador)
    if estado == "aceptada" and d.kind == "reorganizar" and (d.payload or {}).get("rutina"):
        try:
            spec = _spec(RoutineSpec.model_validate(d.payload["rutina"]))
        except Exception as e:  # noqa: BLE001
            raise HTTPException(422, f"La rutina propuesta no es válida: {e}")
        act = db.scalar(select(GymRoutine).where(GymRoutine.status == "active"))
        if act:
            cambios = nueva_version(db, act, spec, f"coach (aceptado por {p.name})", d.reason or d.recommendation)
            aplicado = {"rutina_id": act.id, "version": act.current_version, "cambios": cambios}
        else:
            r = GymRoutine(id=str(uuid.uuid4()), name=d.payload.get("nombre") or "Rutina propuesta", status="draft",
                           created_by=f"coach/{p.name}")
            db.add(r)
            db.add(GymRoutineVersion(routine_id=r.id, version=1, spec=spec, author=f"coach (aceptado por {p.name})",
                                     reason=d.reason or d.recommendation, changes=["versión inicial"]))
            aplicado = {"rutina_id": r.id, "version": 1, "borrador": True}
        d.status = "aplicada"
        d.payload = dict(d.payload) | {"aplicado": aplicado}
    events.audit(db, p.name, f"gym.decision.{estado}", target=str(did), aplicado=aplicado)
    events.publish("gym.updated", {"what": "decision", "id": did}, db=db)
    db.flush()
    return decision_d(d)


@router.post("/coach/decisions/{did}/accept")
def accept_decision(did: int, body: DecideIn | None = None, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    return decide(did, "aceptada", p, db, bool(body and body.confirmar))


@router.post("/coach/decisions/{did}/reject")
def reject_decision(did: int, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    return decide(did, "rechazada", p, db)


# ---------- informes ----------

def _periodo(tipo: str, desde: date) -> tuple[date, date]:
    if tipo == "semanal":
        d0 = desde - timedelta(days=desde.weekday())
        return d0, d0 + timedelta(days=6)
    d0 = desde.replace(day=1)
    d1 = (d0.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    return d0, d1


def generar(db: Session, tipo: str, d0: date, d1: date, regenerar: bool = False) -> GymReport:
    rep = db.scalar(select(GymReport).where(GymReport.kind == tipo, GymReport.period_start == d0.isoformat()))
    if rep and not regenerar:
        return rep
    c = contexto(db)
    vers = []
    for v in db.scalars(select(GymRoutineVersion)):
        vers.append({"rutina_id": v.routine_id, "version": v.version, "fecha": v.created_at.isoformat(), "motivo": v.reason,
                     "cambios": v.changes})
    decs = [decision_d(d) for d in db.scalars(select(GymCoachDecision))]
    data = gc.informe(c["sesiones"], tipo, d0, d1, c["rutina"], c["planificadas"], decs, vers, c["logs"], c["perfil"],
                      pausas=c["pausas"])
    if rep is None:
        rep = GymReport(kind=tipo, period_start=d0.isoformat(), period_end=d1.isoformat(), data=data)
        db.add(rep)
    else:
        rep.data, rep.updated_at = data, utcnow()
    db.flush()
    return rep


def report_d(r: GymReport, full: bool = False) -> dict:
    d = {"id": r.id, "tipo": r.kind, "desde": r.period_start, "hasta": r.period_end, "creado": _iso(r.created_at),
         "actualizado": _iso(r.updated_at), "enviado": _iso(r.sent_at),
         "resumen": {k: r.data.get(k) for k in ("sesiones_hechas", "sesiones_previstas", "cumplimiento", "volumen_kg", "series")}}
    if full:
        d["datos"] = r.data
    return d


@router.get("/reports")
def reports(tipo: str | None = Query(None, pattern="^(semanal|mensual)$"), db: Session = Depends(get_db)):
    """Asegura los informes de los periodos ya cerrados (8 semanas y 3 meses) y los lista. Sin duplicados:
    uno por tipo y periodo (restricción única)."""
    ses = sesiones(correcciones(db))
    h = hoy()
    if ses:
        primera = date.fromisoformat(ses[0].fecha)
        lunes = h - timedelta(days=h.weekday())
        for i in range(1, 9):
            d0 = lunes - timedelta(weeks=i)
            if d0 + timedelta(days=6) >= primera:
                generar(db, "semanal", d0, d0 + timedelta(days=6))
        m = h.replace(day=1)
        for _ in range(3):
            m = (m - timedelta(days=1)).replace(day=1)
            d0, d1 = _periodo("mensual", m)
            if d1 >= primera:
                generar(db, "mensual", d0, d1)
    q = select(GymReport)
    if tipo:
        q = q.where(GymReport.kind == tipo)
    return [report_d(r) for r in db.scalars(q.order_by(GymReport.period_start.desc()))]


@router.get("/reports/{rid}")
def report(rid: int, db: Session = Depends(get_db)):
    r = db.get(GymReport, rid)
    if not r:
        raise HTTPException(404, "Informe no encontrado")
    return report_d(r, True)


class GenerateIn(BaseModel):
    tipo: str = Field(pattern="^(semanal|mensual)$")
    desde: str


@router.post("/reports/generate")
def generate(body: GenerateIn, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    d0, d1 = _periodo(body.tipo, date.fromisoformat(_fecha(body.desde)))
    if d0 > hoy():
        raise HTTPException(422, "Ese periodo aún no ha empezado")
    r = generar(db, body.tipo, d0, d1, regenerar=True)
    events.audit(db, p.name, "gym.report.generate", target=str(r.id), tipo=body.tipo, desde=d0.isoformat())
    return report_d(r, True)


@router.post("/reports/{rid}/send")
async def send_report(rid: int, p: Principal = Depends(require_admin)):
    with session_scope() as db:
        r = db.get(GymReport, rid)
        if not r:
            raise HTTPException(404, "Informe no encontrado")
        texto = r.data.get("texto") or gc.texto_informe(r.data)
    await hostagent.call("/v1/notify/telegram", method="POST", json={"text": texto[:3500]}, timeout=30)
    with session_scope() as db:
        r = db.get(GymReport, rid)
        r.sent_at = utcnow()
        events.audit(db, p.name, "gym.report.send", target=str(rid), canal="telegram")
    return {"ok": True}


# ---------- importación de Hevy ----------

def _hevy():
    import hevy_import
    return hevy_import


def inbox_telegram() -> Path:
    import os
    return Path(os.environ.get("CC_TELEGRAM_INBOX", str(ROOT / "data/home/.claude/channels/telegram/inbox")))


def _es_hevy(p: Path) -> bool:
    try:
        with p.open(encoding="utf-8-sig") as f:
            cab = f.readline()
        return all(c in cab for c in ("start_time", "exercise_title", "weight_kg"))
    except OSError:
        return False


def csv_telegram(db: Session) -> list[dict]:
    d = inbox_telegram()
    if not d.is_dir():
        return []
    aplicados = {i.sha256 for i in db.scalars(select(GymImport).where(GymImport.status == "applied"))}
    out = []
    for f in sorted(d.glob("*.csv"), key=lambda x: x.stat().st_mtime, reverse=True)[:20]:
        if f.is_symlink() or f.stat().st_size > MAX_CSV or not _es_hevy(f):
            continue
        sha = hashlib.sha256(f.read_bytes()).hexdigest()
        out.append({"archivo": f.name, "tamano": f.stat().st_size, "fecha": datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="minutes"),
                    "sha256": sha, "importado": sha in aplicados})
    return out


def csv_telegram_pendientes(db: Session) -> int:
    return sum(1 for x in csv_telegram(db) if not x["importado"])


class ImportIn(BaseModel):
    texto: str | None = Field(None, max_length=MAX_CSV)
    archivo: str = Field("", max_length=255)
    telegram: str | None = Field(None, max_length=255, pattern=r"^[\w.\-]+\.csv$")
    desde: str | None = None


def _preview(db: Session, texto: str, archivo: str, desde: str | None, actor: str, fuente: str) -> dict:
    h = _hevy()
    sha = hashlib.sha256(texto.encode()).hexdigest()
    ses = sesiones(correcciones(db))
    d = date.fromisoformat(_fecha(desde)) if desde else (date.fromisoformat(ses[0].fecha) if ses else None)
    r = h.leer(texto, d)
    plan = h.planificar(r["entrenos"], {s.fecha for s in ses})
    resumen = {"desde": d.isoformat() if d else None, "entrenos": len(r["entrenos"]),
               "nuevos": [{"fecha": w["fecha"], "sesion": w["sesion"], "titulo": w["titulo"], "duracion_min": w["duracion_min"],
                           "ejercicios": len(w["ejercicios"]), "bloque": h.bloque(w)} for w in plan["nuevos"]],
               "ya_registrados": [{"fecha": w["fecha"], "titulo": w["titulo"], "duracion_min": w["duracion_min"]} for w in plan["ya_registrados"]],
               "misma_fecha": [{"fecha": w["fecha"], "titulo": w["titulo"]} for w in plan["misma_fecha"]],
               "avisos": r["avisos"][:50]}
    imp = GymImport(source=fuente, filename=archivo[:255], sha256=sha, status="preview" if not r["errores"] or r["entrenos"] else "error",
                    summary=resumen, errors=r["errores"][:100], actor=actor)
    db.add(imp)
    db.flush()
    # el texto se guarda aparte (no en la base): hace falta para aplicar exactamente lo que se previsualizó
    dirp = get_settings().data_dir / "gym-imports"
    dirp.mkdir(parents=True, exist_ok=True)
    dirp.chmod(0o700)
    (dirp / f"{imp.id}.csv").write_text(texto, encoding="utf-8")
    (dirp / f"{imp.id}.csv").chmod(0o600)
    events.audit(db, actor, "gym.import.preview", target=str(imp.id), archivo=archivo, sha=sha[:12], nuevos=len(plan["nuevos"]),
                 errores=len(r["errores"]))
    return import_d(imp)


def import_d(i: GymImport) -> dict:
    return {"id": i.id, "fecha": _iso(i.created_at), "fuente": i.source, "archivo": i.filename, "sha256": i.sha256,
            "estado": i.status, "resumen": i.summary, "errores": i.errors, "actor": i.actor}


@router.post("/import/hevy")
def import_hevy(body: ImportIn, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    if body.telegram:
        f = inbox_telegram() / body.telegram
        if not f.is_file() or f.is_symlink() or f.resolve().parent != inbox_telegram().resolve() or not _es_hevy(f):
            raise HTTPException(404, "Ese CSV de Hevy no está en la bandeja de Telegram")
        if f.stat().st_size > MAX_CSV:
            raise HTTPException(413, "Archivo demasiado grande")
        return _preview(db, f.read_text(encoding="utf-8-sig"), body.telegram, body.desde, p.name, "telegram")
    if not body.texto:
        raise HTTPException(422, "Falta el CSV")
    return _preview(db, body.texto, body.archivo, body.desde, p.name, "hevy_csv")


@router.get("/imports")
def imports(db: Session = Depends(get_db)):
    return {"importaciones": [import_d(i) for i in db.scalars(select(GymImport).order_by(GymImport.id.desc()).limit(30))],
            "telegram": csv_telegram(db), "bandeja": str(inbox_telegram().relative_to(ROOT)) if inbox_telegram().is_relative_to(ROOT) else "",
            "trazas": db.query(GymHevyWorkout).count()}


@router.post("/import/{iid}/apply")
def apply_import(iid: int, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    """Añade a Gym.md solo las sesiones nuevas que se vieron en la vista previa (escritura atómica) y guarda la
    trazabilidad de todos los entrenos del CSV (id externo, duración y filas originales)."""
    imp = db.get(GymImport, iid)
    if not imp or imp.status != "preview":
        raise HTTPException(409, "Esa importación no está pendiente")
    f = get_settings().data_dir / "gym-imports" / f"{iid}.csv"
    if not f.exists():
        raise HTTPException(410, "La vista previa caducó: vuelve a subir el CSV")
    h = _hevy()
    texto = f.read_text(encoding="utf-8")
    if hashlib.sha256(texto.encode()).hexdigest() != imp.sha256:
        raise HTTPException(409, "El archivo cambió desde la vista previa")
    gpath = path()
    if not gpath.exists():
        raise HTTPException(404, "No encuentro Gym.md")
    ses = sesiones(correcciones(db))
    desde = date.fromisoformat(imp.summary["desde"]) if imp.summary.get("desde") else None
    r = h.leer(texto, desde)
    plan = h.planificar(r["entrenos"], {s.fecha for s in ses})
    vistos = {(w["fecha"], w["sesion"]) for w in plan["nuevos"]}
    previstos = {(w["fecha"], w["sesion"]) for w in imp.summary.get("nuevos", [])}
    if vistos != previstos:
        raise HTTPException(409, "Gym.md ha cambiado desde la vista previa: vuelve a previsualizar")
    from .modules import mirror, vault_sync
    n = len(plan["nuevos"])
    if n:  # la base manda: el registro nuevo va a la base y Gym.md se rehace
        vault_sync.write_workouts(db, mirror.workouts_text(db) + "\n\n" + "\n\n".join(h.bloque(w) for w in plan["nuevos"]))
    ses = sesiones(correcciones(db))
    trazas = 0
    for w in r["entrenos"]:
        cands = [s for s in ses if s.fecha == w["fecha"]]
        sid = (next((s.id for s in cands if gc.mismo_nombre(s.nombre, w["sesion"])), None) or (cands[0].id if len(cands) == 1 else None))
        hv = db.get(GymHevyWorkout, w["external_id"]) or GymHevyWorkout(external_id=w["external_id"])
        hv.date, hv.title, hv.start_time, hv.end_time = w["fecha"], w["titulo"], w["inicio"], w["fin"]
        hv.duration_min, hv.session_id, hv.in_gym_md, hv.rows, hv.import_id = w["duracion_min"], sid, sid is not None, w["filas"], iid
        db.merge(hv)
        trazas += 1
    imp.status = "applied"
    imp.summary = dict(imp.summary) | {"aplicadas": n, "trazas": trazas, "aplicada": utcnow().isoformat()}
    events.audit(db, p.name, "gym.import.apply", target=str(iid), sesiones=n, trazas=trazas)
    events.publish("gym.updated", {"what": "import", "id": iid, "sesiones": n}, db=db)
    return import_d(imp)


# ---------- Coach (conversación especializada) ----------

def coach_prompt() -> str:
    if not COACH_MD.exists():
        return ""
    import sys
    sys.path.insert(0, str(ROOT / "collectors"))
    import ajustes
    return ajustes.render(COACH_MD.read_text(encoding="utf-8"))


def coach_scope() -> dict:
    """Solo su apartado: de la vault ve Gym.md y su método, y sus acciones son las del gym."""
    from .core import orchestrator
    e = orchestrator.SPECIALISTS["entrenador"]
    return {"vault_paths": list(e.vault_paths), "pos": {"agent": "coach", "tools": ["memory.facts"], "capabilities": list(e.capabilities)}}


def coach_session(db: Session, p: Principal, crear: bool = True) -> ChatSession | None:
    pref = db.scalar(select(UserPreference).where(UserPreference.user_id == p.user.id, UserPreference.key == "gym.coach_session"))
    s = db.get(ChatSession, pref.value.get("id")) if pref else None
    if s and s.status != "archived":
        perms = {**(s.permissions or {}), "system_prompt": coach_prompt(), **coach_scope()}  # instrucciones y permisos al día
        if perms != s.permissions:
            s.permissions = perms
        return s
    if not crear:
        return None
    sid = str(uuid.uuid4())
    s = ChatSession(id=sid, kind="independent", name="Coach del gym", agent_id=None, model="sonnet",
                    description="Entrenador de Jarvis: consulta tus datos del gym con herramientas y propone cambios que tú apruebas",
                    workdir=f"data/sesiones/{sid}/trabajo",
                    permissions={"level": "read", "internet": False, "vault": True, "gym": True, "system_prompt": coach_prompt(), **coach_scope(),
                                 "minutes": 15, "vc": {"enabled": False, "profile": "terminal", "vc_id": None}, "subagents": False})
    db.add(s)
    if pref:
        pref.value = {"id": sid}
    else:
        db.add(UserPreference(user_id=p.user.id, key="gym.coach_session", value={"id": sid}))
    events.audit(db, p.name, "gym.coach.session", target=sid)
    db.flush()
    return s


@router.get("/coach")
def coach(p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    from .sessions import _sess
    s = coach_session(db, p, crear=p.user.role == "admin")
    return {"session": _sess(s) if s else None,
            "herramientas": [t["name"] for t in _mcp_tools()],
            "pendientes": db.query(GymCoachDecision).filter(GymCoachDecision.status == "propuesta").count()}


def _mcp_tools() -> list[dict]:
    sys.path.insert(0, str(ROOT / "control-center/gym"))
    try:
        import gym_mcp
        return gym_mcp.TOOLS
    except Exception:  # noqa: BLE001
        return []


class ChatIn(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)


@router.post("/coach/chat")
async def coach_chat(body: ChatIn, p: Principal = Depends(require_admin)):
    from . import sessions
    with session_scope() as db:
        sid = coach_session(db, p).id
    with session_scope() as db:
        return {"session_id": sid, **await sessions.send(sid, sessions.SendIn(text=body.text), p=p, db=db)}


def carpeta(sid: str) -> Path:
    return get_settings().sessions_dir / sid / "gym"


def preparar(sid: str) -> None:
    """Antes de cada turno del Coach: foto del estado del entrenador para su servidor MCP (solo lectura).
    Gym.md lo lee el propio MCP de la vault (montada en solo lectura)."""
    d = carpeta(sid)
    (d / "salida").mkdir(parents=True, exist_ok=True)
    for x in (d.parent, d, d / "salida"):
        x.chmod(0o700)
    with session_scope() as db:
        extra = correcciones(db)
        evaluar(db, sesiones(extra))
        estado = {"generado": utcnow().isoformat() + "Z", "hoy": hoy().isoformat(), "extra": extra,
                  "ajustes": ajustes_ej(db),
                  "rutina": rutina_activa(db),
                  "planificadas": planificadas(db, (hoy() - timedelta(days=90)).isoformat()),
                  "logs": [log_d(l) for l in db.scalars(select(GymRecoveryLog).where(
                      GymRecoveryLog.date >= (hoy() - timedelta(days=120)).isoformat()).order_by(GymRecoveryLog.date))],
                  "decisiones": [decision_d(x) for x in db.scalars(select(GymCoachDecision).order_by(GymCoachDecision.id.desc()).limit(60))],
                  "duraciones": duraciones_ses(db),
                  "pausas": gym.pausas(db),
                  "versiones_rutina": [{"rutina_id": v.routine_id, "version": v.version, "fecha": v.created_at.isoformat(),
                                        "motivo": v.reason, "cambios": v.changes} for v in db.scalars(select(GymRoutineVersion))]}
    tmp = d / "estado.json.tmp"
    tmp.write_text(json.dumps(estado, ensure_ascii=False, default=str), encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(d / "estado.json")


def ingerir(sid: str, run_id: str) -> int:
    """Después del turno: las propuestas que dejó el Coach (herramientas proponer_*) pasan a decisiones
    «propuesta» que el usuario acepta o rechaza. Lo que no valida se descarta y se audita."""
    d = carpeta(sid) / "salida"
    if not d.is_dir():
        return 0
    n = 0
    with session_scope() as db:
        for f in sorted(d.glob("*.json"))[:20]:
            try:
                if f.is_symlink() or f.stat().st_size > 200_000:
                    raise ValueError("archivo no válido")
                x = json.loads(f.read_text(encoding="utf-8"))
                body = DecisionIn.model_validate({k: x.get(k) for k in DecisionIn.model_fields if x.get(k) is not None})
                payload = {}
                if x.get("rutina"):
                    _spec(RoutineSpec.model_validate(x["rutina"]))  # valida antes de guardar
                    payload = {"rutina": x["rutina"], "nombre": str(x.get("nombre_rutina", ""))[:120]}
                db.add(GymCoachDecision(scope=body.alcance, target=body.objetivo_de, exercise_id=body.ejercicio_id,
                                        kind=body.tipo, situation=body.situacion, evidence=body.datos,
                                        recommendation=body.recomendacion, reason=body.motivo,
                                        expected=body.resultado_esperado,
                                        objective={"peso": body.peso, "reps": body.reps} if body.reps else {},
                                        apply_date=body.fecha_aplicacion if body.fecha_aplicacion and re.match(r"^\d{4}-\d{2}-\d{2}$", body.fecha_aplicacion) else None,
                                        payload=payload, status="propuesta", source="coach", run_id=run_id))
                n += 1
                events.audit(db, "agente:coach-gym", "gym.decision.propose", target=body.objetivo_de, tipo=body.tipo, run=run_id)
            except Exception as e:  # noqa: BLE001
                events.audit(db, "agente:coach-gym", "gym.decision.propose", outcome="error", target=f.name, error=str(e)[:300])
            finally:
                f.unlink(missing_ok=True)
        if n:
            events.publish("gym.updated", {"what": "decision", "nuevas": n}, db=db)
    return n
