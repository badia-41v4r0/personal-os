"""Portada: responde a cómo estoy, qué hago hoy, qué persigo, si progreso y qué debería preocuparme.

Solo agrega datos reales. Lo que aún no tiene fuente va como None y la web lo enseña como pendiente: aquí nunca se
rellena un número.
"""
import asyncio
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import agenda as agenda_mod
from .. import gym as gym_mod
from ..config import TZ_NAME, ROOT, get_settings
from ..db import get_db
from ..models import Alert, LedgerAccount, Notification
from ..security import current_principal
from . import checkin, finance, insights, personal

sys.path.insert(0, str(ROOT / "collectors"))
import ajustes  # noqa: E402

router = APIRouter(prefix="/api/v1/home", dependencies=[Depends(current_principal)])
TZ = ZoneInfo(TZ_NAME)
DIAS = ("L", "M", "X", "J", "V", "S", "D")
FILA = re.compile(r"^\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|")
OFERTA_MIN_PUNTOS = 2


def saludo(hora: int) -> str:
    return "Buenos días" if 6 <= hora < 14 else "Buenas tardes" if 14 <= hora < 21 else "Buenas noches"


def pct_cambio(actual: float, anterior: float) -> float | None:
    return round(100 * (actual - anterior) / anterior, 1) if anterior else None


def gym_resumen(sesiones: list, hoy: date, planificadas: int, pausas: list[dict] | None = None) -> dict:
    import gym_coach as gc
    import gym_stats
    lunes = hoy - timedelta(days=hoy.weekday())
    # Los días laborables de esta semana en pausa (enfermedad, vacaciones…) no son sesiones perdidas
    en_pausa = gc.dias_laborables_en_pausa(pausas, lunes, lunes + timedelta(days=4))
    pausa = next((p for p in (pausas or []) if p["desde"] <= (lunes + timedelta(days=6)).isoformat()
                  and (p.get("hasta") or "9999-12-31") >= lunes.isoformat()), None)
    planificadas = max(0, planificadas - en_pausa)
    semana = gym_stats.en_periodo(sesiones, lunes, hoy)
    # Se compara con el mismo tramo de la semana pasada, no con la semana completa
    previa = gym_stats.en_periodo(sesiones, lunes - timedelta(days=7), hoy - timedelta(days=7))
    por_dia = [{"dia": d, "volumen": 0.0} for d in DIAS]
    for s in semana:
        por_dia[date.fromisoformat(s.fecha).weekday()]["volumen"] += s.volumen
    volumen, series = sum(s.volumen for s in semana), sum(s.series for s in semana)
    return {"sesiones": len(semana), "planificadas": planificadas, "volumen": round(volumen, 1), "series": series,
            "volumen_pct": pct_cambio(volumen, sum(s.volumen for s in previa)),
            "series_pct": pct_cambio(series, sum(s.series for s in previa)), "por_dia": por_dia,
            "pausa": ({"desde": pausa["desde"], "hasta": pausa.get("hasta"), "motivo": pausa.get("motivo"), "dias": en_pausa,
                       "en_curso": bool(gc.pausa_en([pausa], hoy))} if pausa else None)}


def carrera_resumen(hoy: date) -> dict:
    jarvis = get_settings().vault / "Jarvis"
    pipeline: dict[str, int] = {}
    try:
        txt = (jarvis / "Areas/Trabajo.md").read_text(encoding="utf-8")
        tabla = txt.split("## Pipeline de candidaturas", 1)[1].split("\n## ", 1)[0]
        for line in tabla.splitlines():
            m = FILA.match(line)
            if m and m[1] != "Empresa" and not set(m[1]) <= {"-", " "}:
                pipeline[m[3]] = pipeline.get(m[3], 0) + 1
    except (OSError, IndexError):
        pass
    nuevas = 0
    try:
        vistas = json.loads((jarvis / "Sistema/ofertas-vistas.json").read_text(encoding="utf-8"))
        limite = (hoy - timedelta(days=7)).isoformat()
        nuevas = sum(1 for o in vistas.values() if o.get("visto", "") >= limite and int(o.get("puntos") or 0) >= OFERTA_MIN_PUNTOS)
    except (OSError, ValueError):
        pass
    return {"pipeline": pipeline, "candidaturas": sum(pipeline.values()), "ofertas_nuevas": nuevas}


def estudios_resumen(uni: dict, hoy: date) -> dict:
    domingo = (hoy + timedelta(days=6 - hoy.weekday())).isoformat()
    pendientes = [e for e in uni.get("entregas", []) if not e.get("hecho")]
    return {"entregas_semana": sum(1 for e in pendientes if e["fecha"] <= domingo), "proxima": pendientes[0] if pendientes else None}


def agenda_hoy(eventos: list[dict], uni: dict, hoy: date) -> list[dict]:
    dia = hoy.isoformat()
    items = [{"hora": e.get("inicio"), "fin": e.get("fin"), "titulo": e["titulo"], "tipo": "evento"}
             for e in eventos if e.get("dia") == dia and "Canvas" not in (e.get("calendario") or "")]
    items += [{"hora": None, "fin": None, "titulo": b, "tipo": "estudio"} for b in uni.get("bloques", [])]
    return sorted(items, key=lambda i: (i["hora"] is None, i["hora"] or ""))


def foco(uni: dict, tareas: list[dict], hoy: date) -> list[str]:
    """Hasta 3 cosas del día, de lo ya planificado. Es una selección, no una invención."""
    dia = hoy.isoformat()
    urgentes = [t["texto"] for t in tareas if t.get("fecha") and t["fecha"] <= dia]
    return (urgentes + list(uni.get("bloques", [])))[:3]


def finanzas_resumen(db: Session, hoy: date) -> dict | None:
    if not db.scalar(select(func.count()).select_from(LedgerAccount)):
        return None
    r = finance.month_summary(db, hoy.strftime("%Y-%m"))
    return {"ahorro": r["ahorro"], "gastos": r["gastos"], "ingresos": r["ingresos"]}


@router.get("")
async def home(db: Session = Depends(get_db)):
    ahora = datetime.now(timezone.utc).astimezone(TZ)
    hoy = ahora.date()
    import gym_stats
    import tareas as tareas_mod
    loop = asyncio.get_running_loop()
    cal = await loop.run_in_executor(None, agenda_mod._cached, "cal0", lambda: agenda_mod.calendario(0))
    uni = agenda_mod.uni_semana()
    tareas_data = agenda_mod.tasks()
    ctx = gym_mod.contexto(db)
    alertas = db.scalar(select(func.count()).select_from(Alert).where(Alert.status == "open"))
    sin_leer = db.scalar(select(func.count()).select_from(Notification).where(Notification.read_at.is_(None)))
    goles, gym_r, est, car = personal.active_goals(db), gym_resumen(ctx["sesiones"], hoy, len(gym_stats.RUTINA), ctx.get("pausas")), estudios_resumen(uni, hoy), carrera_resumen(hoy)
    return {
        "saludo": saludo(ahora.hour), "nombre": ajustes.nombre_usuario(), "fecha": hoy.isoformat(),
        "foco": foco(uni, tareas_data["pendientes"], hoy),
        "agenda": agenda_hoy(cal["eventos"], uni, hoy), "agenda_error": cal["error"],
        "gym": gym_r, "estudios": est, "carrera": car,
        "tareas": {"pendientes": len(tareas_data["pendientes"]),
                   "atrasadas": sum(1 for t in tareas_data["pendientes"] if t["atrasada"])},
        "preocupa": {"alertas": alertas, "avisos": sin_leer},
        "objetivos": goles or None,
        "finanzas": finanzas_resumen(db, hoy),
        "checkin": checkin.view(db, hoy, ahora.hour),
        # Medias de la última semana de check-ins; sin ninguno no hay estado que enseñar
        "estado_general": checkin.summary(db, hoy),
        "insights": insights.build(db, hoy, gym_r, est, car, tareas_data["pendientes"], goles),
    }


INTEGRACIONES = (
    ("Google Calendar", "Agenda", "secrets:token"),
    ("Gmail", "Correo: leer y borradores", "secrets:token"),
    ("Zoho Mail", "Correo: leer y borradores", "secrets:zoho.json"),
    ("GitHub", "Repos, PRs e issues", "manual:Con el gh del PC"),
    ("Campus de estudios", "Lectura desde su ordenador virtual", "manual:Sesión en el ordenador del campus"),
    ("Hevy", "Entrenos", "manual:Por importación: sin API, requiere Pro"),
    ("Telegram", "Solo alertas de emergencia", "manual:Mientras dure la transición, también chat"),
    ("Obsidian", "Conocimiento, sincronizado con Syncthing", "manual:Vault local"),
)


@router.get("/integraciones")
def integraciones(db: Session = Depends(get_db)):
    from ..models import PushSubscription
    secretos = get_settings().root / "secrets"
    nombres = {p.name for p in secretos.iterdir()} if secretos.is_dir() else set()
    out = []
    for nombre, uso, regla in INTEGRACIONES:
        tipo, valor = regla.split(":", 1)
        if tipo == "secrets":
            ok = any(valor in n for n in nombres)  # solo el nombre del archivo: nunca se lee su contenido
            out.append({"nombre": nombre, "uso": uso, "estado": "conectada" if ok else "sin_conectar", "detalle": ""})
        else:
            out.append({"nombre": nombre, "uso": uso, "estado": "manual", "detalle": valor})
    subs = db.scalar(select(func.count()).select_from(PushSubscription))
    out.append({"nombre": "Avisos push", "uso": "Notificaciones en tus dispositivos", "estado": "conectada" if subs else "sin_conectar",
                "detalle": f"{subs} {'dispositivo' if subs == 1 else 'dispositivos'}"})
    return out
