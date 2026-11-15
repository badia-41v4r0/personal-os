"""API del gym (lectura y análisis). Reutiliza collectors/gym_stats.py y collectors/gym_coach.py: el mismo cálculo
que usan Jarvis y el Coach. Gym.md es la fuente de los entrenos; aquí hay una caché en memoria que se invalida
cuando cambia el archivo o las correcciones de ejercicios. Lo que es del entrenador (planificación, rutinas,
sensaciones, decisiones, informes, importación) está en gym_plan.py."""
import hashlib
import json
import sys
from dataclasses import asdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import events
from .config import ROOT, get_settings
from .db import get_db, session_scope
from .models import (GymCoachDecision, GymPause, GymExerciseAlias, GymExerciseSetting, GymHevyWorkout, GymPlannedSession,
                     GymPlannedVersion, GymRecoveryLog, GymRoutine, GymRoutineVersion)
from .security import Principal, current_principal, require_admin

sys.path.insert(0, str(ROOT / "collectors"))
import gym_coach as gc  # noqa: E402
import gym_stats  # noqa: E402

router = APIRouter(prefix="/api/v1/gym", dependencies=[Depends(current_principal)])
_cache: dict = {"key": None, "data": None}


def path():
    return get_settings().vault / "Jarvis/Areas/Gym.md"


def hoy() -> date:
    return date.today()


# ---------- estado del entrenador (SQLite) en el formato del motor ----------

def correcciones(db: Session) -> dict:
    extra = {"alias_id": {a.alias: a.exercise_id for a in db.scalars(select(GymExerciseAlias))}, "musculos_id": {}}
    for s in db.scalars(select(GymExerciseSetting)):
        st = s.settings or {}
        if st.get("principales") is not None or st.get("secundarios") is not None:
            extra["musculos_id"][s.exercise_id] = {"principales": st.get("principales") or [],
                                                   "secundarios": st.get("secundarios") or []}
    return extra


def ajustes(db: Session) -> dict:
    return {s.exercise_id: {k: v for k, v in (s.settings or {}).items() if k not in ("principales", "secundarios")}
            for s in db.scalars(select(GymExerciseSetting))}


def rutina_activa(db: Session) -> dict | None:
    r = db.scalar(select(GymRoutine).where(GymRoutine.status == "active"))
    if not r:
        return None
    v = db.scalar(select(GymRoutineVersion).where(GymRoutineVersion.routine_id == r.id,
                                                   GymRoutineVersion.version == r.current_version))
    return {"id": r.id, "nombre": r.name, "version": r.current_version, **(v.spec if v else {})}


def plan_d(p: GymPlannedSession, v: GymPlannedVersion | None) -> dict:
    return {"id": p.id, "fecha": p.date, "nombre": p.name, "estado": p.status, "version": p.current_version,
            "workout_id": p.workout_id, "link_mode": p.link_mode, "origen_fecha": p.origin_date,
            "rutina_id": p.routine_id, "rutina_version": p.routine_version, "creada_por": p.created_by,
            "creada": p.created_at.isoformat() + "Z", "actualizada": p.updated_at.isoformat() + "Z",
            "ejercicios": v.exercises if v else [], "justificacion": v.rationale if v else "",
            "motivo_version": v.reason if v else ""}


def planificadas(db: Session, desde: str | None = None, hasta: str | None = None) -> list[dict]:
    q = select(GymPlannedSession)
    if desde:
        q = q.where(GymPlannedSession.date >= desde)
    if hasta:
        q = q.where(GymPlannedSession.date <= hasta)
    out = []
    for p in db.scalars(q.order_by(GymPlannedSession.date)):
        v = db.scalar(select(GymPlannedVersion).where(GymPlannedVersion.planned_id == p.id,
                                                      GymPlannedVersion.version == p.current_version))
        out.append(plan_d(p, v))
    return out


def log_d(l: GymRecoveryLog) -> dict:
    return {"fecha": l.date, "energia": l.energia, "sueno": l.sueno, "sueno_horas": l.sueno_horas,
            "agujetas": l.agujetas, "motivacion": l.motivacion, "estres": l.estres, "molestia_zona": l.molestia_zona,
            "molestia_intensidad": l.molestia_intensidad, "notas": l.notas}


def pausa_d(x: GymPause) -> dict:
    return {"id": x.id, "desde": x.start, "hasta": x.end, "motivo": x.reason, "nota": x.note, "por": x.created_by}


def pausas(db: Session) -> list[dict]:
    return [pausa_d(x) for x in db.scalars(select(GymPause).order_by(GymPause.start))]


def logs(db: Session) -> list[dict]:
    return [log_d(l) for l in db.scalars(select(GymRecoveryLog).order_by(GymRecoveryLog.date))]


def duraciones(db: Session) -> dict:
    return {h.session_id: h.duration_min for h in db.scalars(select(GymHevyWorkout).where(GymHevyWorkout.session_id.is_not(None)))
            if h.duration_min}


def sesiones(extra: dict | None = None):
    p = path()
    if extra is None:
        with session_scope() as db:
            extra = correcciones(db)
    ek = hashlib.sha1(json.dumps(extra, sort_keys=True).encode()).hexdigest()
    key = (p.stat().st_mtime_ns, p.stat().st_size, ek) if p.exists() else (None, ek)
    if key != _cache["key"]:
        _cache["key"], _cache["data"] = key, gym_stats.cargar(p, extra)
    return _cache["data"]


def perfil() -> dict:
    return gc.perfil(path())


def contexto(db: Session) -> dict:
    """Todo lo que el motor necesita, en una lectura."""
    ses = sesiones(correcciones(db))
    sync_planes(db, ses)
    return {"sesiones": ses, "rutina": rutina_activa(db), "ajustes": ajustes(db), "logs": logs(db), "perfil": perfil(),
            "planificadas": planificadas(db), "duraciones": duraciones(db), "pausas": pausas(db)}


def sync_planes(db: Session, ses) -> None:
    """Asocia automáticamente una sesión planificada aceptada con el entreno de Gym.md solo si coinciden fecha y
    nombre de la sesión (y no hay ambigüedad). Las asociaciones manuales no se tocan."""
    for p in db.scalars(select(GymPlannedSession).where(GymPlannedSession.link_mode != "manual",
                                                        GymPlannedSession.status.in_(("aceptada", "hecha")))):
        s = gc.buscar_sesion(ses, p.date, p.name)
        nuevo = s.id if s else None
        if nuevo != p.workout_id:
            p.workout_id, p.link_mode = nuevo, "auto" if nuevo else "none"
            p.status = "hecha" if nuevo else "aceptada"


# ---------- serialización ----------

def _ses(s, dur: dict | None = None) -> dict:
    musc = gym_stats.series_por_musculo([s])
    return {"id": s.id, "fecha": s.fecha, "nombre": s.nombre, "hevy": s.hevy, "series": s.series,
            "volumen": s.volumen, "ejercicios": len(s.ejercicios), "musculos": musc, "fuente": f"{s.fuente}:{s.linea}",
            "duracion_min": (dur or {}).get(s.id)}


@router.get("/workouts")
def workouts(desde: str | None = None, hasta: str | None = None, ejercicio: str | None = None,
             musculo: str | None = None, tipo: str | None = None, db: Session = Depends(get_db)):
    dur = duraciones(db)
    ses = sesiones(correcciones(db))
    planes = {p["workout_id"]: p for p in planificadas(db) if p["workout_id"]}
    out = []
    for s in reversed(ses):
        if desde and s.fecha < desde or hasta and s.fecha > hasta:
            continue
        if tipo and not gc.mismo_nombre(s.nombre, tipo):
            continue
        if ejercicio and not any(e.id == ejercicio for e in s.ejercicios):
            continue
        if musculo and not any(musculo in e.principales for e in s.ejercicios):
            continue
        d = _ses(s, dur)
        d["planificada"] = planes[s.id]["id"] if s.id in planes else None
        out.append(d)
    return out


@router.get("/workouts/{wid}")
def workout(wid: str, db: Session = Depends(get_db)):
    ses = sesiones(correcciones(db))
    for i, s in enumerate(ses):
        if s.id != wid:
            continue
        d = _ses(s, duraciones(db))
        ejs = []
        for e in s.ejercicios:
            rs = gc.roles(e.series)
            ejs.append({"id": e.id, "nombre": e.nombre,
                        "series": [asdict(x) | {"e1rm": x.e1rm, "rol": r} for x, r in zip(e.series, rs)],
                        "volumen": e.volumen, "efectivas": len(e.efectivas), "notas": e.notas, "tipo": e.tipo,
                        "principales": e.principales, "secundarios": e.secundarios, "raw": e.raw})
        d["ejercicios"] = ejs
        hv = db.scalar(select(GymHevyWorkout).where(GymHevyWorkout.session_id == wid))
        d["hevy_traza"] = {"external_id": hv.external_id, "titulo": hv.title, "inicio": hv.start_time, "fin": hv.end_time,
                           "duracion_min": hv.duration_min, "filas": len(hv.rows)} if hv else None
        plan = next((p for p in planificadas(db) if p["workout_id"] == wid), None)
        d["plan"] = plan
        d["comparacion"] = gc.comparar(plan, s) if plan else None
        # sesión anterior del mismo nombre, para comparar
        prev = next((x for x in reversed(ses[:i]) if gc.mismo_nombre(x.nombre, s.nombre)), None)
        d["anterior"] = _ses(prev) if prev else None
        d["records"] = [e for e in gc.records(ses[: i + 1])["eventos"] if e["sesion_id"] == wid]
        return d
    raise HTTPException(404, "Sesión no encontrada")


@router.get("/workouts/{a}/compare/{b}")
def compare_workouts(a: str, b: str, db: Session = Depends(get_db)):
    """Comparación de dos sesiones: ejercicio a ejercicio (top set, series y volumen)."""
    ses = {s.id: s for s in sesiones(correcciones(db))}
    if a not in ses or b not in ses:
        raise HTTPException(404, "Sesión no encontrada")
    sa, sb = ses[a], ses[b]

    def top(e):
        rs = gc.roles(e.series)
        t = next((x for x, r in zip(e.series, rs) if r == "top"), None)
        return {"peso": t.peso, "reps": t.reps, "e1rm": t.e1rm} if t else None
    ea = {e.id: e for e in sa.ejercicios if e.series}
    eb = {e.id: e for e in sb.ejercicios if e.series}
    filas = []
    for eid in list(ea) + [k for k in eb if k not in ea]:
        x, y = ea.get(eid), eb.get(eid)
        filas.append({"id": eid, "nombre": (x or y).nombre, "a": {"top": top(x), "series": len(x.efectivas), "volumen": x.volumen} if x else None,
                      "b": {"top": top(y), "series": len(y.efectivas), "volumen": y.volumen} if y else None})
    return {"a": _ses(sa), "b": _ses(sb), "ejercicios": filas}


@router.get("/exercises")
def exercises(db: Session = Depends(get_db)):
    ses = sesiones(correcciones(db))
    aj = ajustes(db)
    out = gym_stats.ejercicios_indice(ses)
    for d in out:
        cfg = gc.config(d["id"], d["nombre"], gc.apariciones(ses, d["id"]), aj.get(d["id"]))
        d["categoria"], d["rango"], d["incremento_kg"] = cfg["categoria"], [cfg["rep_min"], cfg["rep_max"]], cfg["incremento_kg"]
    return out


@router.get("/exercises/aliases")
def aliases(db: Session = Depends(get_db)):
    return [{"alias": a.alias, "exercise_id": a.exercise_id, "creado_por": a.created_by,
             "creado": a.created_at.isoformat() + "Z"} for a in db.scalars(select(GymExerciseAlias).order_by(GymExerciseAlias.alias))]


def _ejercicio(db: Session, eid: str) -> tuple:
    ctx = contexto(db)
    ses = ctx["sesiones"]
    idx = {d["id"]: d for d in gym_stats.ejercicios_indice(ses)}
    if eid not in idx:
        raise HTTPException(404, "Ejercicio no encontrado")
    return ctx, ses, idx[eid]


@router.get("/exercises/{eid}")
def exercise(eid: str, db: Session = Depends(get_db)):
    ctx, ses, ix = _ejercicio(db, eid)
    h = gym_stats.historial_ejercicio(ses, eid)
    hist = gc.historial(ses, eid)
    cfg = gc.config(eid, ix["nombre"], gc.apariciones(ses, eid), ctx["ajustes"].get(eid))
    zona = gc.afectado(ix["principales"], ix["secundarios"], gc.molestias(ctx["perfil"], ctx["logs"], hoy()))
    rec = gc.records(ses, eid)
    return {"ejercicio": ix, "historial": h, "tendencia": gym_stats.tendencia(h),
            "volumen_acumulado": round(sum(x["volumen"] for x in h), 1),
            "historial_roles": hist, "config": cfg, "ajustes": ctx["ajustes"].get(eid, {}),
            "objetivo": gc.objetivo(hist, cfg, zona), "estancamiento": gc.estancamiento(hist[-8:], hoy()),
            "records": rec["ejercicios"].get(eid), "eventos_record": rec["eventos"][::-1][:20],
            "alias": [a.alias for a in db.scalars(select(GymExerciseAlias).where(GymExerciseAlias.exercise_id == eid))]}


PERIODOS = {"7d": 7, "28d": 28, "3m": 91, "6m": 182, "1a": 365}


@router.get("/exercises/{eid}/progress")
def exercise_progress(eid: str, periodo: str = Query("todo", pattern="^(7d|28d|3m|6m|1a|todo|custom)$"),
                      desde: str | None = None, hasta: str | None = None, db: Session = Depends(get_db)):
    ctx, ses, ix = _ejercicio(db, eid)
    if periodo in PERIODOS:
        desde, hasta = (hoy() - timedelta(days=PERIODOS[periodo] - 1)).isoformat(), hoy().isoformat()
    elif periodo == "todo":
        desde, hasta = None, None
    hist = [h for h in gc.historial(ses, eid) if (not desde or h["fecha"] >= desde) and (not hasta or h["fecha"] <= hasta)]
    puntos = []
    for h in hist:
        ef = [s for s in h["series"] if s["rol"] in ("top", "backoff", "intento")]
        mejor = max((s for s in ef if s["e1rm"]), key=lambda s: s["e1rm"], default=None)
        puntos.append({"fecha": h["fecha"], "sesion_id": h["sesion_id"], "peso_max": h["peso_max"],
                       "top_peso": h["top"]["peso"] if h["top"] else None, "top_reps": h["top"]["reps"] if h["top"] else None,
                       "mejor_serie": f"{mejor['peso']:g}×{mejor['reps']}" if mejor else None,
                       "e1rm": mejor["e1rm"] if mejor else None, "reps_total": h["reps_total"],
                       "series": h["series_efectivas"], "volumen": h["volumen"]})
    ev = None
    con = [p for p in puntos if p["e1rm"]]
    if len(con) >= 2:
        a, b = con[0]["e1rm"], con[-1]["e1rm"]
        ev = round(100 * (b - a) / a, 1)
    return {"ejercicio": ix, "periodo": periodo, "desde": desde, "hasta": hasta, "puntos": puntos,
            "evolucion_pct": ev, "tendencia": gc.estancamiento(hist, hoy()),
            "nota": "Evolución = e1RM estimado (Epley) de la primera y la última sesión del periodo. "
                    "Peso máximo y reps son datos registrados."}


@router.get("/statistics")
def statistics(dias: int = 7, db: Session = Depends(get_db)):
    ses, h = sesiones(correcciones(db)), hoy()
    dias = max(1, min(dias, 365))
    semanas = []
    for i in range(7, -1, -1):  # 8 semanas (lunes a domingo)
        ini = h - timedelta(days=h.weekday()) - timedelta(weeks=i)
        per = gym_stats.en_periodo(ses, ini, ini + timedelta(days=6))
        semanas.append({"semana": ini.isoformat(), "sesiones": len(per), "series": sum(s.series for s in per),
                        "volumen": round(sum(s.volumen for s in per), 1)})
    top = gym_stats.ejercicios_indice(ses)[:8]
    return {"periodo": gym_stats.resumen(ses, dias, h), "semanas": semanas,
            "ultima": _ses(ses[-1], duraciones(db)) if ses else None, "frecuentes": top,
            "progreso": gym_stats.progreso(ses, 28, h), "hoy": gym_stats.sugerencia_hoy(ses, h),
            "criterio": "Serie efectiva = no calentamiento. Músculos: principal 1, secundario 0,5. e1RM = Epley (estimación).",
            "faltan": ["duración de la sesión", "descansos"]}


class RegistroIn(BaseModel):
    texto: str = Field(min_length=3, max_length=20000)
    fecha: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    sesion: str | None = Field(default=None, max_length=60)


def _registro(body: RegistroIn) -> tuple[str, list, list[str]]:
    import gym_texto
    sesion = body.sesion or gym_stats.RUTINA.get(date.fromisoformat(body.fecha).weekday(), "Extra")
    ejercicios, avisos = gym_texto.parsear(body.texto)
    return sesion, ejercicios, avisos


@router.post("/register/preview")
def register_preview(body: RegistroIn, _: Principal = Depends(require_admin)):
    """Sin modelo: lee el texto pegado y enseña qué se apuntaría."""
    sesion, ejercicios, avisos = _registro(body)
    return {"sesion": sesion, "ejercicios": [{"nombre": e, "series": s} for e, s in ejercicios], "avisos": avisos}


@router.post("/register")
def register(body: RegistroIn, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    import gym_texto
    sesion, ejercicios, _ = _registro(body)
    if not ejercicios:
        raise HTTPException(422, "No he encontrado ningún ejercicio con series")
    from .modules import mirror, vault_sync
    vault_sync._sembrar_gym(db)
    registro = mirror.workouts_text(db)
    for s in _sesiones_de(registro):
        if s.fecha == body.fecha and s.nombre == sesion:
            raise HTTPException(409, f"Ya hay una sesión {sesion} el {body.fecha}")
    vault_sync.write_workouts(db, registro + "\n\n" + gym_texto.bloque(body.fecha, sesion, ejercicios))
    events.audit(db, p.name, "gym.register", f"{body.fecha} {sesion}", ejercicios=len(ejercicios))
    events.publish("gym.updated", {"what": "workout"}, db=db)
    return {"ok": True, "sesion": sesion, "ejercicios": len(ejercicios)}


def _sesiones_de(registro: str) -> list:
    """Las sesiones de un texto de registro (el de la base), con el parser de siempre."""
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "Gym.md"
        f.write_text("## Registro\n\n" + registro + "\n", encoding="utf-8")
        return gym_stats.cargar(f)


def _bloque_entreno(lines: list[str], fecha: str, sesion: str) -> tuple[int, int]:
    """Dónde empieza y acaba ese entreno en Gym.md."""
    cabecera = f"### {fecha} · {sesion}"
    ini = next((i for i, x in enumerate(lines) if x.strip() == cabecera), None)
    if ini is None:
        raise HTTPException(404, f"No hay ninguna sesión {sesion} el {fecha}")
    fin = next((i for i in range(ini + 1, len(lines)) if lines[i].startswith(("### ", "## "))), len(lines))
    while fin > ini + 1 and not lines[fin - 1].strip():
        fin -= 1
    return ini, fin


def replace_workout(fecha: str, sesion: str, bloque: str, actor: str, db: Session) -> str:
    """Sustituye un entreno ya registrado (en la base; la nota se rehace) y devuelve el texto anterior, para deshacerlo."""
    from .modules import mirror, vault_sync
    vault_sync._sembrar_gym(db)
    lines = mirror.workouts_text(db).split("\n")
    ini, fin = _bloque_entreno(lines, fecha, sesion)
    anterior = "\n".join(lines[ini:fin])
    vault_sync.write_workouts(db, "\n".join([*lines[:ini], *bloque.split("\n"), *lines[fin:]]))
    events.audit(db, actor, "gym.workout.replace", f"{fecha} {sesion}")
    events.publish("gym.updated", {"what": "workout"}, db=db)
    return anterior


@router.get("/overview")
def overview(db: Session = Depends(get_db)):
    c = contexto(db)
    o = gc.overview(c["sesiones"], hoy(), c["rutina"], c["ajustes"], c["logs"], c["perfil"], c["planificadas"],
                    c["duraciones"])
    sem = []
    for i in range(7, -1, -1):
        ini = hoy() - timedelta(days=hoy().weekday()) - timedelta(weeks=i)
        per = gym_stats.en_periodo(c["sesiones"], ini, ini + timedelta(days=6))
        sem.append({"semana": ini.isoformat(), "sesiones": len(per), "series": sum(s.series for s in per),
                    "volumen": round(sum(s.volumen for s in per), 1)})
    o["semanas"] = sem
    o["musculos_7d"] = {k: round(v, 1) for k, v in gym_stats.series_por_musculo(
        gym_stats.en_periodo(c["sesiones"], hoy() - timedelta(days=6), hoy())).items()}
    o["rutina"] = {"id": c["rutina"]["id"], "nombre": c["rutina"]["nombre"], "version": c["rutina"]["version"]} if c["rutina"] else None
    hoy_s = hoy().isoformat()
    o["planificada"] = next((p for p in c["planificadas"] if p["fecha"] >= hoy_s and p["estado"] in ("aceptada", "pospuesta")), None)
    o["decisiones_pendientes"] = db.query(GymCoachDecision).filter(GymCoachDecision.status == "propuesta").count()
    from .gym_plan import csv_telegram_pendientes
    o["importaciones_pendientes"] = csv_telegram_pendientes(db)
    return o


@router.get("/muscles")
def muscles(semanas: int = Query(4, ge=1, le=26), peso_secundario: float = Query(0.5, ge=0, le=1), db: Session = Depends(get_db)):
    return gc.musculos(sesiones(correcciones(db)), hoy(), semanas, peso_secundario)


@router.get("/records")
def records(ejercicio: str | None = None, dias: int = Query(3650, ge=1, le=3650), db: Session = Depends(get_db)):
    r = gc.records(sesiones(correcciones(db)), ejercicio)
    desde = (hoy() - timedelta(days=dias)).isoformat()
    return {"ejercicios": sorted(r["ejercicios"].values(), key=lambda x: x["nombre"]),
            "eventos": [e for e in r["eventos"] if e["fecha"] >= desde][::-1],
            "criterio": "Reales: peso máximo, más reps con el peso del top set, mayor volumen en una serie y en una sesión. "
                        "Estimado: e1RM (Epley, 1–12 reps). La primera sesión de un ejercicio fija la marca sin contar como récord."}


@router.get("/stagnation")
def stagnation(db: Session = Depends(get_db)):
    return {"ejercicios": gc.estancamientos(sesiones(correcciones(db)), hoy()), "nivel": "inferencia",
            "criterio": "Estancado: 3+ sesiones seguidas sin superar el mejor rendimiento previo (+1 %) en ≥10 días. "
                        "Retroceso: 2 bajadas seguidas ≥3 %. Rendimiento = e1RM del top set (o reps si es peso corporal)."}


@router.get("/analysis")
def analysis(db: Session = Depends(get_db)):
    c = contexto(db)
    return gc.observaciones(c["sesiones"], hoy(), c["logs"], c["perfil"])
