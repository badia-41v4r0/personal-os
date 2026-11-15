"""Insights con reglas sobre datos reales: 0 tokens, y cada uno cita de dónde sale.

También reconoce lo que va bien: el objetivo no es encontrar siempre un problema.
"""
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import CheckIn, Fact, Habit, HabitLog, JournalEntry, LedgerAccount
from . import finance, personal
from ..marca import asistente

MAX = 3
PRIORITY = {"aviso": 0, "siguiente": 1, "bien": 2}


def item(tipo: str, titulo: str, texto: str, fuente: str, url: str) -> dict:
    return {"tipo": tipo, "titulo": titulo, "texto": texto, "fuente": fuente, "url": url}


MOTIVO = {"enfermedad": "Enfermedad", "lesion": "Lesión", "vacaciones": "Vacaciones", "otro": "Pausa"}


def _dm(s: str) -> str:
    return f"{s[8:10]}/{s[5:7]}"


def gym_insight(gym: dict, today: date) -> dict | None:
    p = gym.get("pausa")
    if p:
        motivo = MOTIVO.get(p.get("motivo"), "Pausa")
        rango = f"desde el {_dm(p['desde'])}" + (f" hasta el {_dm(p['hasta'])}" if p.get("hasta") else "")
        if p.get("en_curso"):
            return item("siguiente", "En pausa del gym", f"{motivo} {rango}: estos días no cuentan como entrenos perdidos. "
                        "Al volver, el Coach baja la carga la primera sesión.", "Pausas del gym", "/gym/")
        if gym["planificadas"] == 0:
            return item("siguiente", "Semana de pausa", f"{motivo} {rango}: no cuenta como semana perdida. "
                        "La vuelta va al ~90 % de la carga y sin llegar al fallo.", "Pausas del gym", "/gym/")
    previstas = min(today.weekday() + 1, gym["planificadas"])  # lunes a viernes; hoy puede no haber entrenado aún
    if gym["sesiones"] >= gym["planificadas"]:
        return item("bien", "Semana completa", f"Has hecho las {gym['sesiones']} sesiones de la semana. Toca descansar.", "Gym.md", "/gym/")
    if previstas >= 2 and gym["sesiones"] <= previstas - 2:
        return item("aviso", "Vas por detrás en el gym", f"Llevas {gym['sesiones']} de {previstas} sesiones previstas hasta hoy.", "Gym.md", "/gym/")
    if gym["sesiones"] >= previstas and previstas > 0:
        return item("bien", "Al día en el gym", f"{gym['sesiones']} sesiones esta semana, como estaba previsto.", "Gym.md", "/gym/")
    return None


SUENO_BAJO = 6.0
SUENO_SEGUIDAS = 3


def checkin_insights(db: Session, today: date) -> list[dict]:
    """Solo con datos reales de los check-ins: sin ninguno no se inventa nada."""
    out = []
    mañanas = list(db.scalars(select(CheckIn).where(CheckIn.slot == "manana", CheckIn.sleep_h.is_not(None), CheckIn.day <= today.isoformat())
                              .order_by(CheckIn.day.desc()).limit(SUENO_SEGUIDAS)))
    if len(mañanas) == SUENO_SEGUIDAS and all(c.sleep_h < SUENO_BAJO for c in mañanas):
        media = sum(c.sleep_h for c in mañanas) / SUENO_SEGUIDAS
        out.append(item("aviso", "Duermes poco", f"Las últimas {SUENO_SEGUIDAS} mañanas: {media:.1f} h de media.", "Check-ins", "/"))
    ayer = (today - timedelta(days=1)).isoformat()
    if db.scalar(select(func.count()).select_from(CheckIn).where(CheckIn.day < ayer)) and \
            not db.scalar(select(func.count()).select_from(CheckIn).where(CheckIn.day == ayer)):
        out.append(item("siguiente", "Ayer sin check-in", f"Un minuto al día basta para que {asistente()} vea cómo vas.", "Check-ins", "/"))
    return out


def build(db: Session, today: date, gym: dict, estudios: dict, carrera: dict, tareas: list[dict], objetivos: list[dict]) -> list[dict]:
    out: list[dict] = []
    if (g := gym_insight(gym, today)):
        out.append(g)
    prox = estudios.get("proxima")
    if prox:
        dias = (date.fromisoformat(prox["fecha"]) - today).days
        if dias <= 3:
            cuando = "hoy" if dias == 0 else "mañana" if dias == 1 else f"en {dias} días"
            out.append(item("aviso", "Entrega cerca", f"{prox['texto']}: {cuando}.", "Notas semanales de la uni", "/educacion/"))
    atrasadas = [t for t in tareas if t.get("atrasada")]
    if atrasadas:
        n = len(atrasadas)
        out.append(item("aviso", "Tareas atrasadas", f"{n} {'tarea' if n == 1 else 'tareas'}. La más antigua: {atrasadas[0]['texto']}.", "Tareas.md", "/tasks/?t=tasks"))
    if carrera["ofertas_nuevas"] and not carrera["candidaturas"]:
        out.append(item("siguiente", "Ofertas sin revisar", f"{carrera['ofertas_nuevas']} ofertas nuevas y ninguna en seguimiento.", "Radar de ofertas", "/carrera/"))
    if db.scalar(select(func.count()).select_from(LedgerAccount)):
        mes = today.strftime("%Y-%m")
        for b in finance.budget_status(db, mes):
            if b["excedido"]:
                out.append(item("aviso", "Presupuesto superado", f"{b['cuenta'].split(':')[-1]}: por encima de lo previsto este mes.", "Ledger", "/finanzas/"))
        pendientes = db.scalar(select(func.count()).select_from(JournalEntry).where(JournalEntry.status == "pending"))
        if pendientes:
            out.append(item("siguiente", "Movimientos por revisar", f"{pendientes} sin categorizar: no cuentan en los totales.", "Ledger", "/finanzas/"))
        if any(not c["cuadra"] for c in finance.reconcile(db)):
            out.append(item("aviso", "Descuadre con el banco", "El ledger no coincide con el saldo que declaraste.", "Conciliación", "/finanzas/"))
    sin_hitos = [g for g in objetivos if g["progreso"] is None]
    if sin_hitos:
        out.append(item("siguiente", "Objetivo sin hitos", f"«{sin_hitos[0]['titulo']}» aún no tiene pasos medibles.", "Objetivos", "/objetivos/"))
    for h in db.scalars(select(Habit).where(Habit.active.is_(True))):
        dias = set(db.scalars(select(HabitLog.day).where(HabitLog.habit_id == h.id, HabitLog.day >= (today - timedelta(days=60)).isoformat())))
        racha = personal.streak(dias, today)
        if racha >= 7:
            out.append(item("bien", "Buena racha", f"{h.name}: {racha} días seguidos.", "Hábitos", "/objetivos/"))
            break
    out.extend(checkin_insights(db, today))
    por_confirmar = db.scalar(select(func.count()).select_from(Fact).where(Fact.verification == "inferred", Fact.valid_to.is_(None)))
    if por_confirmar:
        out.append(item("siguiente", f"{asistente()} ha aprendido algo", f"{por_confirmar} por confirmar en «Qué sé de ti».", "Memoria", "/memory/hechos/"))
    # Lo importante primero, pero siempre con sitio para una buena noticia si la hay
    out.sort(key=lambda i: PRIORITY[i["tipo"]])
    bien = next((i for i in out if i["tipo"] == "bien"), None)
    top = out[:MAX]
    if bien and bien not in top:
        top[-1] = bien
    return top
