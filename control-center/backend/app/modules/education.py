"""Educación: panorama por asignatura, plan, repaso espaciado, tiempo real, Canvas y archivos del tutor.

Lo que ya existía (casillas de la uni) sigue en `personal.py` y sigue marcándose igual. Aquí vive lo nuevo:
todo se calcula con datos reales (notas semanales, Notas-Uni, hechos, ledger, salud) y sin modelo. Lo que sí necesita
al tutor (generar tarjetas, revisar un borrador) se le pide por su chat, no se simula.
"""
import json
import mimetypes
import random
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import archivos, events
from ..config import get_settings
from ..core import memory
from ..db import get_db, utcnow
from ..models import (Assessment, EduCalendarBlock, EduCanvasChange, EduCanvasItem, EduCard, EduDeliveryState, EduReview, EduStudySession,
                      HealthLog, JournalEntry, StudyBlock, Subject, Workout)
from ..security import Principal, current_principal, require_admin

router = APIRouter(prefix="/api/v1/education", dependencies=[Depends(current_principal)])

ENTREGAS_ATRAS = 14  # como en personal.py: una entrega pasada sigue a la vista 14 días si no se ha marcado
CARPETA = "Uni"  # dentro de la carpeta común de archivos: Uni/<ASIG>/…
ESTADOS = ("sin_empezar", "en_curso", "revisando", "entregada")
BLOQUE_MIN = 120  # lo que asume el planificador por bloque
FECHA = r"^\d{4}-\d{2}-\d{2}$"
MAX_TEXTO = 200_000


# ---------- asignaturas ----------


def asignaturas() -> dict[str, str]:
    import planificador
    planificador.recargar()
    return dict(planificador.ASIG)


def codigo_de(texto: str) -> str:
    """Código de asignatura de un bloque («FP · PEC 1») o de una entrega («Fundamentos de programación: PR 1»)."""
    asig = asignaturas()
    t = texto.strip()
    primero = re.split(r"\s*[·:]\s*", t, maxsplit=1)[0].strip()
    if primero in asig:
        return primero
    for code, nombre in asig.items():
        if primero.lower() == nombre.lower() or t.lower().startswith(nombre.lower()):
            return code
    return ""


def _hechos() -> tuple[dict, dict]:
    import tareas
    from lib import load_json
    return load_json(tareas.HECHOS, {}), tareas.marcas_panel()


def _hecho(clave: str, hechos: dict, marcas: dict, base: bool = False) -> bool:
    return marcas.get(clave, base or clave in hechos)


def _fila_subject(db: Session, code: str) -> Subject | None:
    for s in db.scalars(select(Subject)):
        if s.code.split()[0] == code:
            return s
    return None


# ---------- panorama ----------


def _capacidad(desde: date, hasta: date) -> int:
    import planificador
    planificador.recargar()
    return sum(planificador.bloques_dia(d) for d in planificador.laborables(desde, hasta))


def plan_progress(db: Session, hoy: date) -> dict:
    """Bloques hechos frente a los que tocaban hasta hoy, y margen real hasta el final del plan."""
    import planificador
    planificador.recargar()
    hechos, marcas = _hechos()
    pasados = [b for b in db.scalars(select(StudyBlock).where(StudyBlock.day <= hoy.isoformat()))]
    hechos_pasados = sum(1 for b in pasados if _hecho(f"estudio|{b.day}|{b.text}", hechos, marcas))
    hp = planificador.hechos_por_paquete()
    restantes = sum(max(0, n - hp.get(planificador.etiqueta(a, t), 0)) for a, t, _i, _l, n in planificador.PAQUETES)
    capacidad = _capacidad(hoy, planificador.FIN)
    margen = capacidad - restantes
    _, avisos = planificador.planificar(hoy)  # los mismos avisos que el recálculo del domingo
    return {"avisos": len(avisos), "ejemplos_avisos": avisos[:3], "planificados_hasta_hoy": len(pasados), "hechos": hechos_pasados, "restantes": restantes, "capacidad": capacidad, "margen": margen,
            "fin": planificador.FIN.isoformat(),
            "estado": "ok" if margen >= 10 else "justo" if margen >= 0 else "no_cabe"}


def _reales(db: Session, desde: date, hasta: date) -> dict[str, int]:
    q = select(EduStudySession).where(EduStudySession.day >= desde.isoformat(), EduStudySession.day <= hasta.isoformat(), EduStudySession.ended_at.is_not(None))
    out: Counter = Counter()
    for s in db.scalars(q):
        out[s.day] += s.seconds
    return out


def week_load(db: Session, hoy: date, semanas: int = 10) -> list[dict]:
    """Horas planificadas frente a la capacidad, por semana; las pasadas llevan las horas reales cronometradas."""
    import planificador
    lunes = hoy - timedelta(days=hoy.weekday())
    bloques = list(db.scalars(select(StudyBlock).where(StudyBlock.day >= lunes.isoformat(), StudyBlock.day < (lunes + timedelta(weeks=semanas)).isoformat())))
    reales = _reales(db, lunes - timedelta(weeks=2), hoy)
    out = []
    for i in range(-2, semanas - 2):
        ini = lunes + timedelta(weeks=i)
        fin = ini + timedelta(days=6)
        plan = sum(1 for b in bloques if ini.isoformat() <= b.day <= fin.isoformat())
        cap = sum(planificador.bloques_dia(ini + timedelta(days=k)) for k in range(7))
        real = sum(v for d, v in reales.items() if ini.isoformat() <= d <= fin.isoformat())
        out.append({"semana": ini.isoformat(), "planificadas_h": plan * 2, "capacidad_h": cap * 2, "reales_h": round(real / 3600, 1) if real else None, "actual": i == 0})
    return out


def subject_cards(db: Session, hoy: date) -> list[dict]:
    asig = asignaturas()
    hechos, marcas = _hechos()
    entregas = list(db.scalars(select(Assessment).where(Assessment.removed_at.is_(None)).order_by(Assessment.due)))
    # «Hecha» es lo marcado en el Panel o en el panel web (hechos.json), no solo la casilla de la nota semanal
    por_asig: dict[str, list[Assessment]] = defaultdict(list)
    for e in entregas:
        por_asig[codigo_de(e.title)].append(e)
    hecha = {e.id: _hecho(f"entrega|{e.due}|{e.title}", hechos, marcas, e.done) for e in entregas}  # sin tocar la fila: es un GET
    bloques: dict[str, list[StudyBlock]] = defaultdict(list)
    for b in db.scalars(select(StudyBlock)):
        bloques[codigo_de(b.text)].append(b)
    tarjetas = Counter(c.subject for c in db.scalars(select(EduCard).where(EduCard.due <= hoy.isoformat(), EduCard.suspended.is_(False))))
    cards = []
    for code, nombre in asig.items():
        s = _fila_subject(db, code)
        pend = [e for e in por_asig[code] if not hecha[e.id] and e.due >= hoy.isoformat()]
        atras = [e for e in por_asig[code] if not hecha[e.id] and e.due < hoy.isoformat() and e.due >= (hoy - timedelta(days=ENTREGAS_ATRAS)).isoformat()]
        bl = bloques[code]
        pasados = [b for b in bl if b.day <= hoy.isoformat()]
        sig = pend[0] if pend else None
        estado = s.status if s else ""
        semaforo = "rojo" if atras or "incumpl" in estado.lower() or "no llegas" in estado.lower() else "ambar" if (sig and (date.fromisoformat(sig.due) - hoy).days <= 3) else "verde"
        cards.append({
            "codigo": code, "nombre": nombre, "creditos": s.credits if s else None, "nota_actual": s.current_grade if s else "", "estado": estado,
            "formula": s.formula if s else "", "minimos": s.minimums if s else "", "semaforo": semaforo,
            "siguiente": {"texto": sig.title, "fecha": sig.due, "hora": sig.due_time, "dias": (date.fromisoformat(sig.due) - hoy).days} if sig else None,
            "pendientes": len(pend), "atrasadas": len(atras),
            "bloques_hechos": sum(1 for b in pasados if _hecho(f"estudio|{b.day}|{b.text}", hechos, marcas)), "bloques_pasados": len(pasados),
            "bloques_futuros": len(bl) - len(pasados), "tarjetas_hoy": tarjetas.get(code, 0),
        })
    return cards


@router.get("/overview")
def overview(db: Session = Depends(get_db)):
    hoy = date.today()
    return {"hoy": hoy.isoformat(), "asignaturas": subject_cards(db, hoy), "progreso": plan_progress(db, hoy), "carga": week_load(db, hoy),
            "tiempo": time_stats(db, hoy), "canvas_nuevos": db.scalar(select(func.count()).select_from(EduCanvasChange).where(EduCanvasChange.seen.is_(False))) or 0}


# ---------- plan (semana y mes) ----------


def _horas(slot: int, dia: date) -> str:
    import planificador
    horas = planificador.horas(dia)
    return horas[slot] if slot < len(horas) else ""


@router.get("/plan")
def plan(desde: str | None = None, dias: int = 7, db: Session = Depends(get_db)):
    if not 1 <= dias <= 62:
        raise HTTPException(422, "Entre 1 y 62 días")
    ini = date.fromisoformat(desde) if desde else date.today()
    fin = ini + timedelta(days=dias - 1)
    hechos, marcas = _hechos()
    estados = {s.key: s.state for s in db.scalars(select(EduDeliveryState))}
    bl = defaultdict(list)
    for b in db.scalars(select(StudyBlock).where(StudyBlock.day >= ini.isoformat(), StudyBlock.day <= fin.isoformat()).order_by(StudyBlock.day, StudyBlock.slot)):
        d = date.fromisoformat(b.day)
        clave = f"estudio|{b.day}|{b.text}"
        bl[b.day].append({"clave": clave, "slot": b.slot, "hora": _horas(b.slot, d), "texto": b.text, "asig": codigo_de(b.text), "hecho": _hecho(clave, hechos, marcas)})
    en = defaultdict(list)
    for e in db.scalars(select(Assessment).where(Assessment.removed_at.is_(None), Assessment.due >= ini.isoformat(), Assessment.due <= fin.isoformat()).order_by(Assessment.due, Assessment.due_time)):
        clave = f"entrega|{e.due}|{e.title}"
        hecha = _hecho(clave, hechos, marcas, e.done)
        en[e.due].append({"clave": clave, "texto": e.title, "hora": e.due_time, "asig": codigo_de(e.title), "hecha": hecha,
                          "estado": "entregada" if hecha else estados.get(clave, "sin_empezar"),
                          "dias": (date.fromisoformat(e.due) - date.today()).days})
    dias_out = []
    for k in range(dias):
        d = ini + timedelta(days=k)
        dias_out.append({"dia": d.isoformat(), "bloques": bl.get(d.isoformat(), []), "entregas": en.get(d.isoformat(), [])})
    return {"desde": ini.isoformat(), "dias": dias_out}


class EstadoIn(BaseModel):
    clave: str = Field(min_length=3, max_length=800)
    estado: str = Field(pattern="^(sin_empezar|en_curso|revisando|entregada)$")


@router.post("/entrega-estado")
def entrega_estado(body: EstadoIn, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    """Estado fino de una entrega. «Entregada» es lo mismo que marcarla (uni.check): una sola fuente de verdad."""
    from . import personal
    tipo, _, resto = body.clave.partition("|")
    fecha, _, titulo = resto.partition("|")
    e = db.scalar(select(Assessment).where(Assessment.due == fecha, Assessment.title == titulo, Assessment.removed_at.is_(None))) if tipo == "entrega" else None
    if e is None:
        raise HTTPException(404, "Esa entrega ya no está en tu lista")
    hechos, marcas = _hechos()
    estaba = _hecho(body.clave, hechos, marcas, e.done)
    if body.estado == "entregada" and not estaba:
        personal.uni_check(body.clave, True, p.name, db)
    elif body.estado != "entregada" and estaba:
        personal.uni_check(body.clave, False, p.name, db)
    row = db.get(EduDeliveryState, body.clave) or EduDeliveryState(key=body.clave)
    row.state, row.updated_at = body.estado, utcnow()
    db.add(row)
    events.audit(db, p.name, "edu.delivery.state", body.clave[:255], estado=body.estado)
    return {"clave": body.clave, "estado": body.estado}


# ---------- reprogramar ----------


@router.post("/reschedule")
def reschedule(p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    """Recalcula el plan desde hoy sin esperar al domingo: lo mismo que `jarvis-replan`, descontando lo marcado."""
    import planificador
    hoy = date.today()
    plan_nuevo, avisos = planificador.planificar(hoy)
    planificador.escribir(plan_nuevo, hoy)
    from . import vault_sync
    with db.begin_nested():
        vault_sync.sync_uni(db)
    events.audit(db, p.name, "edu.reschedule", hoy.isoformat(), avisos=len(avisos))
    events.publish("uni.updated", {"replan": True}, db=db)
    return {"desde": hoy.isoformat(), "avisos": avisos[:20], "progreso": plan_progress(db, hoy)}


# ---------- tiempo real ----------


class TimerIn(BaseModel):
    label: str = Field(default="", max_length=300)
    subject: str = Field(default="", max_length=32)


def _abierta(db: Session) -> EduStudySession | None:
    return db.scalar(select(EduStudySession).where(EduStudySession.ended_at.is_(None)).order_by(EduStudySession.id.desc()))


def _cerrar(s: EduStudySession) -> None:
    s.ended_at = utcnow()
    s.seconds = max(0, int((s.ended_at - s.started_at).total_seconds()))


@router.get("/timer")
def timer(db: Session = Depends(get_db)):
    s = _abierta(db)
    if s is None:
        return {"activo": False}
    return {"activo": True, "id": s.id, "label": s.label, "asignatura": s.subject, "desde": s.started_at.isoformat(), "segundos": int((utcnow() - s.started_at).total_seconds())}


@router.post("/timer/start")
def timer_start(body: TimerIn, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    if (prev := _abierta(db)) is not None:
        _cerrar(prev)
    code = body.subject or codigo_de(body.label)
    s = EduStudySession(day=date.today().isoformat(), subject=code, label=body.label.strip())
    db.add(s)
    db.flush()
    return {"id": s.id, "asignatura": code}


@router.post("/timer/stop")
def timer_stop(p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    s = _abierta(db)
    if s is None:
        raise HTTPException(409, "No hay ningún cronómetro en marcha")
    _cerrar(s)
    return {"id": s.id, "segundos": s.seconds}


def time_stats(db: Session, hoy: date) -> dict:
    """Minutos reales por asignatura (30 días) y media por sesión frente a los 120 min que supone el plan."""
    ini = (hoy - timedelta(days=30)).isoformat()
    q = select(EduStudySession).where(EduStudySession.day >= ini, EduStudySession.ended_at.is_not(None), EduStudySession.seconds >= 300)
    filas = list(db.scalars(q))
    por: dict[str, list[int]] = defaultdict(list)
    for s in filas:
        por[s.subject or "—"].append(s.seconds)
    total = sum(s.seconds for s in filas)
    media = round(total / len(filas) / 60) if filas else None
    return {"sesiones": len(filas), "horas": round(total / 3600, 1), "media_min": media, "plan_min": BLOQUE_MIN,
            "por_asignatura": [{"asig": a, "horas": round(sum(v) / 3600, 1), "sesiones": len(v), "media_min": round(sum(v) / len(v) / 60)} for a, v in sorted(por.items())]}


# ---------- repaso espaciado ----------


def sm2(card: EduCard, grade: int, hoy: date) -> None:
    """SM-2 con cuatro respuestas: 0 otra vez · 3 difícil · 4 bien · 5 fácil."""
    if grade < 3:
        card.reps, card.interval = 0, 1
        card.lapses += 1
        card.ease = max(1.3, card.ease - 0.2)
    else:
        card.reps += 1
        card.interval = 1 if card.reps == 1 else 3 if card.reps == 2 else max(card.interval + 1, round(card.interval * card.ease))
        card.ease = max(1.3, card.ease + 0.1 - (5 - grade) * (0.08 + (5 - grade) * 0.02))
    card.last_review = hoy.isoformat()
    card.due = (hoy + timedelta(days=card.interval)).isoformat()


class CardIn(BaseModel):
    asignatura: str = Field(min_length=1, max_length=32)
    frente: str = Field(min_length=1, max_length=2000)
    dorso: str = Field(min_length=1, max_length=4000)
    tipo: str = Field(default="concepto", pattern="^(concepto|examen)$")
    fuente: str = Field(default="", max_length=300)


def add_cards(db: Session, cards: list[dict], author: str) -> list[int]:
    """Alta común (panel y tutor): valida la asignatura y no repite una tarjeta con el mismo frente."""
    asig = asignaturas()
    ids = []
    for c in cards[:50]:
        code = str(c.get("asignatura", "")).strip().split(" ·")[0].strip()
        if code not in asig:
            raise ValueError(f"Asignatura desconocida: {code or '—'} (usa {', '.join(asig)})")
        frente, dorso = " ".join(str(c.get("frente", "")).split())[:2000], str(c.get("dorso", "")).strip()[:4000]
        if not frente or not dorso:
            raise ValueError("La tarjeta necesita frente y dorso")
        if db.scalar(select(EduCard.id).where(EduCard.subject == code, EduCard.front == frente)):
            continue
        tipo = c.get("tipo") if c.get("tipo") in ("concepto", "examen") else "concepto"
        row = EduCard(subject=code, kind=tipo, front=frente, back=dorso, source=str(c.get("fuente", ""))[:300], author=author[:40], due=date.today().isoformat())
        db.add(row)
        db.flush()
        ids.append(row.id)
    return ids


def card_view(c: EduCard) -> dict:
    return {"id": c.id, "asignatura": c.subject, "tipo": c.kind, "frente": c.front, "dorso": c.back, "fuente": c.source, "autor": c.author, "vence": c.due,
            "intervalo": c.interval, "repeticiones": c.reps, "fallos": c.lapses, "facilidad": round(c.ease, 2), "suspendida": c.suspended}


@router.post("/cards")
def cards_add(body: list[CardIn], p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    if not 1 <= len(body) <= 50:
        raise HTTPException(422, "Entre 1 y 50 tarjetas")
    try:
        ids = add_cards(db, [{"asignatura": c.asignatura, "frente": c.frente, "dorso": c.dorso, "tipo": c.tipo, "fuente": c.fuente} for c in body], "manual")
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    events.audit(db, p.name, "edu.cards.add", f"{len(ids)} tarjetas")
    return {"creadas": len(ids), "repetidas": len(body) - len(ids), "ids": ids}


@router.get("/cards")
def cards_list(asignatura: str | None = None, estado: str = "todas", limit: int = 200, db: Session = Depends(get_db)):
    q = select(EduCard).order_by(EduCard.due, EduCard.id).limit(max(1, min(limit, 500)))
    if asignatura:
        q = q.where(EduCard.subject == asignatura)
    if estado == "pendientes":
        q = q.where(EduCard.due <= date.today().isoformat(), EduCard.suspended.is_(False))
    return [card_view(c) for c in db.scalars(q)]


@router.get("/cards/due")
def cards_due(asignatura: str | None = None, limit: int = 20, db: Session = Depends(get_db)):
    """Las que tocan hoy, las más atrasadas primero, y como mucho `limit` para que la sesión sea corta."""
    q = select(EduCard).where(EduCard.due <= date.today().isoformat(), EduCard.suspended.is_(False)).order_by(EduCard.due, EduCard.id).limit(max(1, min(limit, 100)))
    if asignatura:
        q = q.where(EduCard.subject == asignatura)
    return [card_view(c) for c in db.scalars(q)]


class ReviewIn(BaseModel):
    nota: int = Field(ge=0, le=5)
    modo: str = Field(default="repaso", pattern="^(repaso|simulacro)$")


@router.post("/cards/{cid}/review")
def cards_review(cid: int, body: ReviewIn, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    c = db.get(EduCard, cid)
    if c is None:
        raise HTTPException(404, "Tarjeta no encontrada")
    grade = 0 if body.nota < 3 else body.nota
    sm2(c, grade, date.today())
    db.add(EduReview(card_id=c.id, grade=grade, mode=body.modo))
    return card_view(c)


class CardPatch(BaseModel):
    suspendida: bool | None = None
    frente: str | None = Field(default=None, min_length=1, max_length=2000)
    dorso: str | None = Field(default=None, min_length=1, max_length=4000)


@router.patch("/cards/{cid}")
def cards_patch(cid: int, body: CardPatch, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    c = db.get(EduCard, cid)
    if c is None:
        raise HTTPException(404, "Tarjeta no encontrada")
    if body.suspendida is not None:
        c.suspended = body.suspendida
    if body.frente:
        c.front = body.frente.strip()
    if body.dorso:
        c.back = body.dorso.strip()
    return card_view(c)


@router.delete("/cards/{cid}")
def cards_delete(cid: int, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    c = db.get(EduCard, cid)
    if c is None:
        raise HTTPException(404, "Tarjeta no encontrada")
    events.audit(db, p.name, "edu.cards.delete", c.front[:200])
    db.query(EduReview).filter(EduReview.card_id == cid).delete()
    db.delete(c)
    return {"ok": True}


def card_stats(db: Session, hoy: date) -> dict:
    ahora = hoy.isoformat()
    total = db.scalar(select(func.count()).select_from(EduCard).where(EduCard.suspended.is_(False))) or 0
    hoy_n = db.scalar(select(func.count()).select_from(EduCard).where(EduCard.suspended.is_(False), EduCard.due <= ahora)) or 0
    hace = datetime.combine(hoy - timedelta(days=30), datetime.min.time())
    por: dict[str, list[int]] = defaultdict(list)
    dias: set[str] = set()
    for r, sub in db.execute(select(EduReview, EduCard.subject).join(EduCard, EduCard.id == EduReview.card_id).where(EduReview.at >= hace)):
        por[sub].append(1 if r.grade >= 3 else 0)
        dias.add(r.at.date().isoformat())
    racha, d = 0, hoy
    while d.isoformat() in dias or (d == hoy and racha == 0 and (hoy - timedelta(days=1)).isoformat() in dias):
        if d.isoformat() in dias:
            racha += 1
        d -= timedelta(days=1)
    nuevas = db.scalar(select(func.count()).select_from(EduCard).where(EduCard.reps == 0, EduCard.suspended.is_(False))) or 0
    return {"total": total, "hoy": hoy_n, "nuevas": nuevas, "racha_dias": racha,
            "retencion": [{"asig": a, "acierto": round(100 * sum(v) / len(v)), "revisiones": len(v)} for a, v in sorted(por.items())],
            "por_asignatura": [{"asig": a, "tarjetas": n} for a, n in db.execute(select(EduCard.subject, func.count()).group_by(EduCard.subject).order_by(EduCard.subject))]}


@router.get("/cards/stats")
def cards_stats(db: Session = Depends(get_db)):
    return card_stats(db, date.today())


class SimulacroIn(BaseModel):
    asignatura: str = Field(min_length=1, max_length=32)
    n: int = Field(default=10, ge=3, le=40)
    minutos: int = Field(default=0, ge=0, le=180)


@router.post("/simulacro")
def simulacro(body: SimulacroIn, db: Session = Depends(get_db)):
    """Preguntas para una pasada cronometrada: primero las de tipo examen y las que más has fallado, mezcladas."""
    cs = list(db.scalars(select(EduCard).where(EduCard.subject == body.asignatura, EduCard.suspended.is_(False))))
    if not cs:
        raise HTTPException(404, "Aún no hay tarjetas de esa asignatura: pídele al tutor que las genere")
    cs.sort(key=lambda c: (c.kind != "examen", -c.lapses, c.ease))
    elegidas = cs[: body.n]
    random.shuffle(elegidas)
    return {"asignatura": body.asignatura, "minutos": body.minutos, "preguntas": [card_view(c) for c in elegidas]}


# ---------- Canvas: cambios de fechas ----------


def check_canvas(db: Session, dias: int = 90) -> dict:
    """Compara el calendario de Canvas (por Google Calendar) con la foto anterior. 0 tokens."""
    import gcal
    ev = [e for e in gcal.agenda(dias) if "canvas" in (e.get("calendario") or "").lower()]
    vistos = {i.uid: i for i in db.scalars(select(EduCanvasItem))}
    primera = not vistos  # la primera lectura no avisa de nada: es la línea base
    ahora, cambios, actuales = utcnow(), [], set()
    for e in ev:
        uid, titulo, dia = str(e["id"])[:200], str(e["titulo"])[:400], f"{e['dia']} {e.get('inicio') or ''}".strip()[:40]
        actuales.add(uid)
        it = vistos.get(uid)
        if it is None:
            db.add(EduCanvasItem(uid=uid, title=titulo, start=dia))
            if not primera:
                cambios.append(EduCanvasChange(kind="nuevo", title=titulo, new=dia))
        else:
            if it.start != dia:
                cambios.append(EduCanvasChange(kind="movido", title=titulo, old=it.start, new=dia))
                it.start = dia
            it.title, it.removed_at = titulo, None
    limite = (date.today() + timedelta(days=dias)).isoformat()
    for uid, it in vistos.items():
        if uid not in actuales and it.removed_at is None and it.start[:10] >= date.today().isoformat() and it.start[:10] <= limite:
            it.removed_at = ahora
            cambios.append(EduCanvasChange(kind="retirado", title=it.title, old=it.start))
    for c in cambios:
        db.add(c)
    db.flush()
    return {"eventos": len(ev), "cambios": len(cambios), "linea_base": primera}


def canvas_view(c: EduCanvasChange) -> dict:
    return {"id": c.id, "cuando": c.at.isoformat(), "tipo": c.kind, "titulo": c.title, "antes": c.old, "ahora": c.new, "visto": c.seen}


@router.get("/canvas")
def canvas_changes(db: Session = Depends(get_db)):
    q = select(EduCanvasChange).order_by(EduCanvasChange.id.desc()).limit(40)
    return [canvas_view(c) for c in db.scalars(q)]


@router.post("/canvas/check")
def canvas_check(p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        return check_canvas(db)
    except Exception as e:  # noqa: BLE001
        caducado = e.__class__.__name__ == "Caducado" or "invalid_grant" in str(e)
        raise HTTPException(502, "El permiso de Google ha caducado: renuévalo en Configuración" if caducado else f"Calendario no disponible: {str(e)[:120]}") from e


@router.post("/canvas/seen")
def canvas_seen(p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    db.query(EduCanvasChange).filter(EduCanvasChange.seen.is_(False)).update({"seen": True})
    return {"ok": True}


# ---------- calendario ----------


@router.post("/calendar-sync")
def calendar_sync(dias: int = 7, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    """Pasa los bloques de los próximos días a Google Calendar (marca jarvis=1). Es un clic tuyo: una vez por bloque."""
    from .agent_caps import cli
    if not 1 <= dias <= 14:
        raise HTTPException(422, "Entre 1 y 14 días")
    hoy = date.today()
    hechos, marcas = _hechos()
    creados, fallos = 0, []
    bl = db.scalars(select(StudyBlock).where(StudyBlock.day >= hoy.isoformat(), StudyBlock.day <= (hoy + timedelta(days=dias)).isoformat()).order_by(StudyBlock.day, StudyBlock.slot))
    ya = {(c.day, c.slot) for c in db.scalars(select(EduCalendarBlock))}
    for b in bl:
        d = date.fromisoformat(b.day)
        if (b.day, b.slot) in ya or _hecho(f"estudio|{b.day}|{b.text}", hechos, marcas):
            continue
        h = _horas(b.slot, d)
        m = re.match(r"(\d{1,2}:\d{2})\D+(\d{1,2}:\d{2})", h)
        if not m:
            continue
        try:
            r = json.loads(cli("gcal.py", "crear", f"--titulo=📚 {' '.join(b.text.split())[:120]}", f"--inicio={b.day}T{m[1].zfill(5)}", f"--fin={b.day}T{m[2].zfill(5)}"))
        except Exception as e:  # noqa: BLE001
            fallos.append(str(e)[:120])
            break  # si Google falla, no se insiste con el resto
        db.add(EduCalendarBlock(day=b.day, slot=b.slot, event_id=str(r["id"])[:200]))
        creados += 1
    events.audit(db, p.name, "edu.calendar.sync", f"{creados} bloques")
    return {"creados": creados, "errores": fallos}


# ---------- cruces con el resto del LifeOS ----------

# Palabras de las ofertas que cada asignatura cubre: config estudios.json → asignaturas[].habilidades. Es un criterio, no un dato.
def _habilidades() -> dict[str, tuple[str, ...]]:
    import ajustes
    return {str(a.get("codigo")): tuple(str(w).lower() for w in a.get("habilidades") or [])
            for a in ajustes.leer("estudios").get("asignaturas") or [] if a.get("codigo") and a.get("habilidades")}


def job_skills(db: Session) -> list[dict]:
    from ..models import JobLead
    leads = list(db.scalars(select(JobLead).order_by(JobLead.seen_on.desc()).limit(200)))
    out = []
    for code, palabras in _habilidades().items():
        hits = [l for l in leads if any(w in f"{l.title} {l.company}".lower() for w in palabras)]
        out.append({"asig": code, "ofertas": len(hits), "ejemplos": [f"{l.title} · {l.company}" for l in hits[:3]]})
    return {"analizadas": len(leads), "asignaturas": sorted(out, key=lambda x: -x["ofertas"])}


def energy(db: Session, hoy: date) -> dict:
    """Bloques hechos por día frente a sueño/energía registrados y entreno ese día. Solo se muestra con datos suficientes."""
    ini = (hoy - timedelta(days=60)).isoformat()
    hechos, marcas = _hechos()
    por_dia: Counter = Counter()
    for b in db.scalars(select(StudyBlock).where(StudyBlock.day >= ini, StudyBlock.day <= hoy.isoformat())):
        if _hecho(f"estudio|{b.day}|{b.text}", hechos, marcas):
            por_dia[b.day] += 1
    sueno = {h.day: h.value for h in db.scalars(select(HealthLog).where(HealthLog.metric == "sueno", HealthLog.day >= ini))}
    entreno = {w.day for w in db.scalars(select(Workout).where(Workout.day >= ini, Workout.removed_at.is_(None)))}
    pares = [(sueno[d], por_dia.get(d, 0)) for d in sueno]
    con_entreno = [por_dia.get(d, 0) for d in por_dia if d in entreno]
    sin_entreno = [por_dia.get(d, 0) for d in por_dia if d not in entreno]
    media = lambda xs: round(sum(xs) / len(xs), 2) if xs else None  # noqa: E731
    buen, mal = [b for s, b in pares if s >= 7], [b for s, b in pares if s < 7]
    suficiente = len(pares) >= 10 or (len(con_entreno) >= 5 and len(sin_entreno) >= 5)
    return {"suficiente": suficiente, "dias_con_sueno": len(sueno), "bloques_con_sueno_7h": media(buen), "bloques_con_menos_de_7h": media(mal),
            "bloques_dia_con_entreno": media(con_entreno), "bloques_dia_sin_entreno": media(sin_entreno),
            "nota": "Correlación sobre pocos días: orienta, no demuestra nada." if suficiente else "Aún no hay datos suficientes de sueño o entreno para comparar."}


def cost(db: Session) -> dict:
    """Lo pagado al centro según el ledger y, si hay créditos anotados, el coste por crédito. Sin importes inventados.
    El texto que identifica los pagos es config estudios.json → plataforma.pago (o, si no, plataforma.centro)."""
    import ajustes
    from ..models import LedgerAccount, Posting
    plat = ajustes.leer("estudios").get("plataforma") or {}
    marca = str(plat.get("pago") or plat.get("centro") or "").strip()
    if not marca:
        return {"asientos": 0, "pagado": None, "creditos": None, "por_credito": None,
                "nota": "Indica en Configuración → Educación cómo aparece tu universidad en el banco para calcular el coste."}
    q = (select(func.count(func.distinct(JournalEntry.id)), func.coalesce(func.sum(Posting.amount), 0))
         .join(Posting, Posting.entry_id == JournalEntry.id).join(LedgerAccount, LedgerAccount.id == Posting.account_id)
         .where(JournalEntry.status == "posted", LedgerAccount.kind == "expense", Posting.amount > 0,
                (JournalEntry.description.ilike(f"%{marca}%")) | (JournalEntry.counterparty.ilike(f"%{marca}%"))))
    n, total = db.execute(q).one()
    total = float(total)
    creditos = sum(s.credits or 0 for s in db.scalars(select(Subject)))
    return {"asientos": n, "pagado": round(total, 2) if n else None, "creditos": creditos or None,
            "por_credito": round(total / creditos, 2) if n and creditos else None,
            "nota": f"Sale de los gastos del ledger cuya descripción o contraparte contiene «{marca}»." if n else f"No hay gastos con «{marca}» en el ledger."}


@router.get("/cruces")
def cruces(db: Session = Depends(get_db)):
    return {"ofertas": job_skills(db), "energia": energy(db, date.today()), "coste": cost(db)}


class CreditsIn(BaseModel):
    asignatura: str = Field(min_length=1, max_length=32)
    creditos: int = Field(ge=0, le=60)


@router.put("/credits")
def set_credits(body: CreditsIn, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    s = _fila_subject(db, body.asignatura)
    if s is None:
        raise HTTPException(404, "Asignatura sin fila de notas todavía")
    s.credits = body.creditos or None
    return {"asignatura": body.asignatura, "creditos": s.credits}


# ---------- estudiar ahora ----------


@router.get("/study-context")
def study_context(db: Session = Depends(get_db)):
    """El bloque que toca ahora (o el siguiente de hoy) y el mensaje listo para el tutor, con todo lo relevante."""
    hoy, ahora = date.today(), datetime.now().strftime("%H:%M")
    hechos, marcas = _hechos()
    bl = [b for b in db.scalars(select(StudyBlock).where(StudyBlock.day == hoy.isoformat()).order_by(StudyBlock.slot))]
    pend = [b for b in bl if not _hecho(f"estudio|{b.day}|{b.text}", hechos, marcas)]
    actual = next((b for b in pend if (m := re.match(r"\d{1,2}:\d{2}\D+(\d{1,2}:\d{2})", _horas(b.slot, hoy))) and ahora < m[1].zfill(5)), pend[0] if pend else None)
    if actual is None:
        return {"bloque": None, "mensaje": "Hoy no tengo bloques pendientes. ¿Qué me recomiendas adelantar o repasar según mi plan y mis entregas?"}
    code = codigo_de(actual.text)
    entregas = [e for e in db.scalars(select(Assessment).where(Assessment.removed_at.is_(None), Assessment.done.is_(False), Assessment.due >= hoy.isoformat()).order_by(Assessment.due)) if codigo_de(e.title) == code][:2]
    tarjetas = db.scalar(select(func.count()).select_from(EduCard).where(EduCard.subject == code, EduCard.due <= hoy.isoformat(), EduCard.suspended.is_(False))) or 0
    lineas = [f"Voy a empezar el bloque de estudio: «{actual.text}» ({_horas(actual.slot, hoy)})."]
    if entregas:
        lineas.append("Entregas próximas de esta asignatura: " + "; ".join(f"{e.title} ({e.due})" for e in entregas) + ".")
    if tarjetas:
        lineas.append(f"Tengo {tarjetas} tarjetas de repaso pendientes de {code}.")
    lineas.append("Léete mis notas de la semana y los materiales de la asignatura y dime: 1) por dónde empezar, 2) los ejercicios que debo hacer primero (mi método), 3) cómo sabré que el bloque ha servido. Sé breve.")
    return {"bloque": {"clave": f"estudio|{actual.day}|{actual.text}", "texto": actual.text, "asig": code, "hora": _horas(actual.slot, hoy)}, "mensaje": "\n".join(lineas)}


# ---------- archivos del tutor ----------


def uni_root() -> "Path":  # noqa: F821
    base = archivos.root()
    d = base / CARPETA
    d.mkdir(exist_ok=True, mode=0o700)
    for code in asignaturas():
        (d / code).mkdir(exist_ok=True, mode=0o700)
    return d


def _safe(rel: str, must_exist: bool = True):
    """Ruta dentro de Uni/: sin `..`, sin ocultos, sin enlaces simbólicos en ningún tramo."""
    root = uni_root()
    parts = [x for x in rel.replace("\\", "/").split("/") if x not in ("", ".")]
    if any(x == ".." or x.startswith(".") or "\x00" in x for x in parts):
        raise HTTPException(403, "Ruta no válida")
    cur = root
    for x in parts:
        cur = cur / x
        if cur.is_symlink():
            raise HTTPException(403, "Ruta no válida")
    if root.resolve() not in (cur.resolve(), *cur.resolve().parents):
        raise HTTPException(403, "Ruta no válida")
    if must_exist and not cur.exists():
        raise HTTPException(404, "No existe")
    return cur


def _item(p, root) -> dict:
    st = p.stat()
    return {"nombre": p.name, "ruta": p.relative_to(root).as_posix(), "carpeta": p.is_dir(), "bytes": 0 if p.is_dir() else st.st_size,
            "modificado": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
            "tipo": "dir" if p.is_dir() else (mimetypes.guess_type(p.name)[0] or "application/octet-stream")}


@router.get("/archivos")
def files_list(path: str = ""):
    root = uni_root()
    d = _safe(path)
    if not d.is_dir():
        raise HTTPException(422, "No es una carpeta")
    items = [_item(x, root) for x in sorted(d.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())) if not x.name.startswith(".") and not x.is_symlink()]
    rel = d.relative_to(root).as_posix()
    return {"ruta": "" if rel == "." else rel, "nombres": asignaturas(), "items": items}


TEXTO = {".md", ".txt", ".c", ".h", ".py", ".json", ".csv", ".sh", ".v", ".sv", ".yaml", ".yml", ".java", ".js", ".ts", ".tex", ".log", ".xml", ".sql"}
EN_LINEA = {"application/pdf", "image/png", "image/jpeg", "image/gif", "image/webp", "text/plain"}


@router.get("/archivos/texto")
def files_text(path: str):
    f = _safe(path)
    if not f.is_file() or f.suffix.lower() not in TEXTO:
        raise HTTPException(422, "No se puede previsualizar")
    data = f.read_bytes()[:MAX_TEXTO]
    return {"ruta": path, "texto": data.decode("utf-8", errors="replace"), "recortado": f.stat().st_size > MAX_TEXTO, "md": f.suffix.lower() == ".md"}


@router.get("/archivos/raw")
def files_raw(path: str, descargar: bool = False):
    f = _safe(path)
    if not f.is_file():
        raise HTTPException(422, "No es un archivo")
    tipo = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
    en_linea = tipo in EN_LINEA and not descargar
    # Nada activo (HTML, SVG, JS) se sirve en línea desde nuestro origen: solo PDF, imágenes y texto plano, con nosniff.
    # Se pueden incrustar en esta misma página (la vista previa); el visor de PDF de Chrome no admite sandbox ni object-src.
    headers = {"X-Content-Type-Options": "nosniff", "X-Frame-Options": "SAMEORIGIN", "Content-Security-Policy": "frame-ancestors 'self'"}
    return FileResponse(f, media_type=tipo if en_linea else "application/octet-stream", filename=None if en_linea else f.name, headers=headers,
                        content_disposition_type="inline" if en_linea else "attachment")


@router.post("/archivos")
async def files_upload(request: Request, path: str, name: str, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    """Sube un archivo a una carpeta de Uni/ (por ejemplo un borrador para que el tutor lo revise). Nunca sobrescribe."""
    d = _safe(path)
    if not d.is_dir():
        raise HTTPException(422, "No es una carpeta")
    final, size = await archivos.receive(request, d, name)
    events.audit(db, p.name, "edu.files.upload", final.relative_to(uni_root()).as_posix(), bytes=size)
    return {"ruta": final.relative_to(uni_root()).as_posix(), "bytes": size}


class MkdirIn(BaseModel):
    ruta: str = Field(default="", max_length=400)
    nombre: str = Field(min_length=1, max_length=80)


@router.post("/archivos/carpeta")
def files_mkdir(body: MkdirIn, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    d = _safe(body.ruta)
    nombre = archivos.safe_name(body.nombre).lstrip(".")
    if not nombre or not d.is_dir():
        raise HTTPException(422, "Nombre no válido")
    (d / nombre).mkdir(exist_ok=True, mode=0o700)
    events.audit(db, p.name, "edu.files.mkdir", (d / nombre).relative_to(uni_root()).as_posix())
    return {"ruta": (d / nombre).relative_to(uni_root()).as_posix()}


@router.get("/archivos/recientes")
def files_recent(limit: int = 12):
    root = uni_root()
    todos = [x for x in root.rglob("*") if x.is_file() and not x.is_symlink() and not any(part.startswith(".") for part in x.relative_to(root).parts)]
    todos.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    return [_item(x, root) for x in todos[: max(1, min(limit, 50))]]


# ---------- para los agentes ----------


def tutor_snapshot(db: Session) -> dict:
    """Lo que ve el tutor: asignaturas, margen, tarjetas y cambios de Canvas sin revisar. Solo datos calculados."""
    hoy = date.today()
    return {"progreso": plan_progress(db, hoy),
            "asignaturas": [{k: c[k] for k in ("codigo", "nota_actual", "estado", "semaforo", "siguiente", "atrasadas", "tarjetas_hoy")} for c in subject_cards(db, hoy)],
            "repaso": card_stats(db, hoy), "canvas_sin_ver": [canvas_view(c) for c in db.scalars(select(EduCanvasChange).where(EduCanvasChange.seen.is_(False)).limit(20))]}
