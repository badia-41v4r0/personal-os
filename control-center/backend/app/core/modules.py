"""Registro de módulos: qué partes del Personal OS están activas en esta instalación.

Cada módulo declara lo que es suyo (apartados de la web, rutas de la API, lecturas y acciones de los agentes,
asistentes, temporizadores y configuración). Un módulo apagado desaparece de todo eso a la vez:
- la web no lo enseña (lee /api/v1/instancia);
- su API responde 404 (middleware en main.py);
- ningún agente recibe sus lecturas ni sus acciones, y el gateway y core/actions las rechazan aunque alguien las pida;
- sus temporizadores no se instalan ni se ofrecen en Automatizaciones.
El núcleo (Inicio, memoria, tareas, avisos, agentes, sistema) no se puede apagar.

Lo activo vive en data/config/modulos.json (collectors/ajustes.py): {"activos": [...]}. Sin ese archivo valen los
módulos marcados por defecto, que son los que no necesitan ninguna cuenta externa.
"""
from dataclasses import dataclass, field

from fastapi import HTTPException

from ..config import ROOT
import sys

sys.path.insert(0, str(ROOT / "collectors"))
import ajustes  # noqa: E402


@dataclass(frozen=True)
class Module:
    id: str
    nombre: str
    descripcion: str
    nucleo: bool = False
    por_defecto: bool = False
    web: tuple[str, ...] = ()            # rutas del panel (como en nav.ts)
    api: tuple[str, ...] = ()            # prefijos de /api/v1 que son solo suyos
    prefijos: tuple[str, ...] = ()       # lecturas y acciones de agentes («gym.» vale para gym.register, gym.summary…)
    nombres: tuple[str, ...] = ()        # lecturas o acciones sueltas
    asistentes: tuple[str, ...] = ()     # especialistas y apartados del orquestador
    timers: tuple[str, ...] = ()
    config: tuple[str, ...] = ()         # archivos de configuración que usa (data/config/<nombre>.json)
    integraciones: tuple[str, ...] = ()  # lo que el usuario tiene que conectar (informativo para el onboarding)
    requiere: tuple[str, ...] = ()       # otros módulos que necesita activos
    extra: dict = field(default_factory=dict)


MODULES: dict[str, Module] = {m.id: m for m in (
    Module("inicio", "Inicio", "Jarvis, memoria, tareas, avisos y check-ins: lo mínimo para usar el sistema.", nucleo=True,
           web=("/", "/tasks/", "/memory/hechos/", "/avisos/"),
           prefijos=("memory.", "task.", "note.", "journal."), nombres=("tasks.list", "day.close"),
           asistentes=("jarvis", "memoria", "rutina"), config=("perfil",)),
    Module("sistema", "Sistema", "Agentes, conversaciones, monitor, automatizaciones e integraciones.", nucleo=True,
           web=("/agents/", "/chat/", "/sistema/", "/monitor/", "/automatizaciones/", "/integraciones/", "/settings/"),
           timers=("cc-backup",)),
    Module("agenda", "Agenda", "Calendario unificado con Google Calendar.", por_defecto=True,
           web=("/agenda/",), api=("/api/v1/calendar",), prefijos=("calendar.",), nombres=("agenda.days",),
           asistentes=("agenda",), timers=("collect", "google"), integraciones=("google",)),
    Module("correo", "Correo", "Leer correo y preparar borradores (Gmail y Zoho). Nunca envía.",
           prefijos=("mail.",), config=("correo",), integraciones=("google", "zoho")),
    Module("rutinas", "Rutinas", "Briefing de la mañana, recordatorio de la noche y revisión semanal.", por_defecto=True,
           timers=("briefing", "noche", "semanal")),
    Module("educacion", "Educación", "Asignaturas, entregas, plan de estudio, repaso espaciado y tutor con acceso a tu campus.",
           web=("/educacion/",), api=("/api/v1/education", "/api/v1/me/education"), prefijos=("uni.",),
           asistentes=("tutor",), timers=("replan",), config=("estudios",), integraciones=("campus",)),
    Module("gym", "Entrenamiento", "Registro de entrenos, progresión, rutinas y Coach. Importa de Hevy.", por_defecto=True,
           web=("/gym/",), api=("/api/v1/gym",), prefijos=("gym.",), asistentes=("entrenador", "coach")),
    Module("salud", "Salud", "Peso, medidas y bienestar.", por_defecto=True,
           web=("/salud/",), api=("/api/v1/me/health",), prefijos=("health.",), asistentes=("salud",)),
    Module("finanzas", "Finanzas", "Contabilidad de partida doble, presupuestos e importación de extractos.",
           web=("/finanzas/",), api=("/api/v1/finance",), prefijos=("finance.",), asistentes=("finanzas",)),
    Module("carrera", "Carrera", "Búsqueda de empleo: candidaturas, ofertas y solicitudes con agente.",
           web=("/carrera/",), api=("/api/v1/me/career",), prefijos=("career.", "candidatura."), asistentes=("carrera",),
           config=("ofertas",)),
    Module("objetivos", "Objetivos", "Objetivos con hitos y hábitos.", por_defecto=True,
           web=("/objetivos/",), api=("/api/v1/me/goals", "/api/v1/me/habits", "/api/v1/me/milestones"),
           prefijos=("goal.", "habit."), nombres=("goals.list", "habits.list"), asistentes=("objetivos",)),
    Module("estilo", "Estilo de vida", "Viajes, compras, suscripciones, garantías e intereses.", por_defecto=True,
           web=("/estilo-de-vida/",), api=("/api/v1/me/lifestyle",), prefijos=("lifestyle.",), asistentes=("estilo",)),
    Module("conocimiento", "Conocimiento", "Explorar, buscar y editar tu vault de Obsidian.", por_defecto=True,
           web=("/memory/",), api=("/api/v1/memory/tree", "/api/v1/memory/file", "/api/v1/memory/raw", "/api/v1/memory/backlinks",
                                   "/api/v1/memory/resolve", "/api/v1/memory/rules", "/api/v1/memory/recent"),
           asistentes=("conocimiento",)),
    Module("proyectos", "Proyectos", "Tus repos de GitHub y un programador que trabaja en la rama staging.",
           web=("/projects/",), api=("/api/v1/projects",), nombres=("encargo.create", "repo.create"),
           timers=(), config=("github",), integraciones=("github",)),
    Module("ayudante", "Ayudante", "Tareas largas con búsqueda web en un contenedor aparte.", nombres=("ayudante.create",)),
    Module("videos", "Vídeos", "Analiza vídeos cortos (Instagram, TikTok, Shorts) con transcripción local.", nombres=("video.analyze",)),
    Module("ordenadores", "Ordenadores virtuales", "Contenedores con terminal, navegador o escritorio para los agentes.",
           web=("/virtual-computers/",), api=("/api/v1/virtual-computers",)),
    Module("voz", "Voz en el PC", "«Hey Jarvis» con el micrófono del PC y respuesta hablada (local).", timers=()),
    Module("telegram", "Avisos por Telegram", "Copia de las alertas críticas a un bot de Telegram (solo salida).",
           integraciones=("telegram",)),
)}
ORDEN = list(MODULES)


def activos() -> set[str]:
    guardado = ajustes.leer("modulos").get("activos")
    if isinstance(guardado, list):
        ids = {m for m in guardado if m in MODULES}
    else:
        ids = {m.id for m in MODULES.values() if m.por_defecto}
    return ids | {m.id for m in MODULES.values() if m.nucleo}


def activo(mid: str) -> bool:
    return mid in activos()


def dueno_de(nombre: str) -> str | None:
    """Módulo dueño de una lectura o acción de agente. None = de nadie en concreto (siempre disponible)."""
    for m in MODULES.values():
        if nombre in m.nombres or any(nombre.startswith(p) for p in m.prefijos):
            return m.id
    return None


def permitido(nombre: str, act: set[str] | None = None) -> bool:
    d = dueno_de(nombre)
    return d is None or d in (act if act is not None else activos())


def filtrar(nombres, act: set[str] | None = None) -> list[str]:
    act = act if act is not None else activos()
    return [n for n in nombres if permitido(n, act)]


def asistente_activo(nombre: str, act: set[str] | None = None) -> bool:
    act = act if act is not None else activos()
    for m in MODULES.values():
        if nombre in m.asistentes:
            return m.id in act
    return True


def modulo_de_ruta(path: str) -> str | None:
    """Prefijo de API más largo que coincide: así /api/v1/me/career no se confunde con /api/v1/me."""
    mejor, largo = None, 0
    for m in MODULES.values():
        for p in m.api:
            if (path == p or path.startswith(p + "/")) and len(p) > largo:
                mejor, largo = m.id, len(p)
    return mejor


def timers_activos(act: set[str] | None = None) -> set[str]:
    act = act if act is not None else activos()
    return {t for m in MODULES.values() if m.id in act for t in m.timers}


def todos_los_timers() -> set[str]:
    return {t for m in MODULES.values() for t in m.timers}


def guardar(ids: list[str]) -> set[str]:
    desconocidos = [i for i in ids if i not in MODULES]
    if desconocidos:
        raise ValueError(f"Módulos desconocidos: {', '.join(desconocidos)}")
    act = set(ids) | {m.id for m in MODULES.values() if m.nucleo}
    faltan = [f"{MODULES[i].nombre} necesita {MODULES[r].nombre}" for i in act for r in MODULES[i].requiere if r not in act]
    if faltan:
        raise ValueError("; ".join(faltan))
    ajustes.guardar("modulos", ajustes.propia("modulos") | {"activos": [i for i in ORDEN if i in act]})
    return act


def requiere(mid: str):
    """Dependencia de FastAPI para rutas sueltas de un módulo."""
    def dep():
        if not activo(mid):
            raise HTTPException(404, f"El módulo {MODULES[mid].nombre} está desactivado")
    return dep


def vista(act: set[str] | None = None) -> list[dict]:
    act = act if act is not None else activos()
    return [{"id": m.id, "nombre": m.nombre, "descripcion": m.descripcion, "nucleo": m.nucleo, "activo": m.id in act,
             "web": list(m.web), "integraciones": list(m.integraciones), "config": list(m.config), "requiere": list(m.requiere)}
            for m in MODULES.values()]
