"""Orquestador: decide quién atiende cada petición. Código primero: el modelo solo si hace falta.

Los especialistas no están siempre encendidos: se activan bajo demanda y comparten memoria por el Core. Solo se ofrece
uno cuando su módulo tiene datos: un agente sin datos solo puede inventar.
"""
import re
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Specialist:
    name: str
    profile: str
    tools: tuple[str, ...]
    capabilities: tuple[str, ...]
    keywords: tuple[str, ...]
    # Necesita sus herramientas o datos privados: nunca pasa al relevo de solo texto
    sensitive: bool = False
    vault: bool = False
    panel_agent: str = ""  # definición del panel de la que hereda permisos y ordenador
    # Chat de un apartado: conversación propia y contexto limitado a su contenido
    section: bool = False
    vault_paths: tuple[str, ...] = ()  # solo esto de la vault existe en su contenedor; vacío con vault=True es la vault entera
    vault_write: bool = False  # solo las rutinas programadas
    gym: bool = False  # herramientas del motor del gym
    subagents: bool = False
    deliverables: bool = False  # puede dejar archivos en archivos/Uni (se ven en el explorador de Educación)
    guia: str = ""  # instrucciones extra que se añaden a las suyas (los asistentes de onboarding)


COMMON_TOOLS = ("memory.search", "memory.facts", "memory.context", "tasks.list", "agenda.days", "uni.deadlines", "gym.summary")
JARVIS_TOOLS = COMMON_TOOLS + ("mail.recent", "mail.read", "ocio.list", "ocio.search")
JARVIS_CAPS = ("memory.fact.propose", "task.create", "task.done", "task.reschedule", "task.edit", "task.delete", "uni.check", "note.add", "gym.register", "gym.pause.log", "health.log", "career.application.create",
               "calendar.create", "calendar.move", "calendar.delete", "mail.draft", "ocio.add", "ocio.update",
               "day.close", "encargo.create", "ayudante.create", "repo.create", "video.analyze")
# Lo básico sobre el usuario vale en todos los apartados. Lo demás de cada apartado es solo suyo: lo que no está aquí, no lo puede ni leer.
_PERFIL = ("memory.facts",)
_RECUERDO = ("memory.fact.propose",)
GYM_VAULT = ("Jarvis/Areas/Gym.md", "Jarvis/Sistema/gym.md")
GYM_CAPS = _RECUERDO + ("gym.register", "gym.workout.replace", "gym.recovery.log", "gym.pause.log", "gym.plan.create", "gym.plan.update", "gym.exercise.settings")
FINANCE_TOOLS = _PERFIL + ("finance.summary", "finance.entries", "finance.overview", "finance.budgets", "finance.accounts", "finance.rules", "finance.savings")
FINANCE_CAPS = ("finance.rule.create", "finance.entry.create", "finance.entry.categorize", "finance.analysis.save", "finance.budget.set", "finance.value.set")
UNI_TOOLS = _PERFIL + ("uni.overview", "uni.deadlines", "uni.tasks", "uni.snapshot", "uni.cards.due")
UNI_CAPS = _RECUERDO + ("uni.task.create", "uni.task.done", "uni.check", "uni.grade.set", "uni.card.add")
UNI_VAULT = ("Uni", "Jarvis/Areas/Uni.md", "Jarvis/Areas/Notas-Uni.md", "Jarvis/Sistema/estudio.md", "Jarvis/Sistema/semana.md")
CAREER_TOOLS = _PERFIL + ("career.list", "career.tasks")
CAREER_CAPS = _RECUERDO + ("career.application.create", "career.application.update", "career.task.create")
CAREER_VAULT = ("Jarvis/Areas/Trabajo.md", "Jarvis/Areas/Ofertas.md", "Jarvis/Sistema/ofertas.md")
SPECIALISTS: dict[str, Specialist] = {
    "finanzas": Specialist("finanzas", "standard", FINANCE_TOOLS, FINANCE_CAPS,
                           ("gast", "diner", "presupuest", "ahorr", "banco", "patrimonio", "factura", "nómina", "suscripci", "finanza"),
                           sensitive=True),
    "entrenador": Specialist("entrenador", "standard", _PERFIL + ("gym.summary",), GYM_CAPS,
                             ("entren", "gym", "gimnasio", "rutina", "series", "press", "sentadilla", "hevy", "volumen"),
                             sensitive=True, vault=True, vault_paths=GYM_VAULT),
    # El tutor, con su ordenador del campus
    "tutor": Specialist("tutor", "deep", UNI_TOOLS, UNI_CAPS,
                            ("uni", "universidad", "asignatura", "examen", "exámenes", "pec", "entrega", "estudi", "canvas"),
                            sensitive=True, vault=True, panel_agent="tutor", vault_paths=UNI_VAULT, deliverables=True),
    "carrera": Specialist("carrera", "standard", CAREER_TOOLS, CAREER_CAPS,
                          ("empleo", "trabajo", "oferta", "entrevista", "candidatura", "cv", "linkedin"), sensitive=True, vault=True, vault_paths=CAREER_VAULT),
}
DEFAULT = Specialist("jarvis", "standard", JARVIS_TOOLS, JARVIS_CAPS, ())
# Asistente de cada apartado del panel: aquí manda dónde está el usuario, no sus palabras
SECTIONS: dict[str, Specialist] = {
    "agenda": Specialist("agenda", "standard", _PERFIL + ("tasks.list", "agenda.days", "uni.deadlines"),
                         _RECUERDO + ("task.create", "task.done", "task.reschedule", "task.edit", "task.delete", "calendar.create", "calendar.move", "calendar.delete"), (),
                         sensitive=True, vault=True, vault_paths=("Jarvis/Tareas.md",), section=True),
    "salud": Specialist("salud", "standard", _PERFIL + ("health.list",), _RECUERDO + ("health.log",), (), sensitive=True, section=True),
    "finanzas": replace(SPECIALISTS["finanzas"], section=True),
    "carrera": replace(SPECIALISTS["carrera"], section=True),
    "tutor": replace(SPECIALISTS["tutor"], section=True),
    "objetivos": Specialist("objetivos", "standard", _PERFIL + ("goals.list", "habits.list"),
                            _RECUERDO + ("goal.create", "goal.milestone", "goal.milestone.toggle", "goal.status", "habit.create", "habit.toggle"), (), sensitive=True, section=True),
    "estilo": Specialist("estilo", "standard", _PERFIL + ("lifestyle.list",), _RECUERDO + ("lifestyle.add", "lifestyle.remove"), (), sensitive=True, section=True),
    "ocio": Specialist("ocio", "standard", _PERFIL + ("ocio.list", "ocio.search"), _RECUERDO + ("ocio.add", "ocio.update"), (), sensitive=True, section=True),
    # Su contenido es justo la vault y la memoria: es el único apartado que las ve enteras
    "conocimiento": Specialist("conocimiento", "standard", ("memory.search", "memory.facts", "memory.context"), _RECUERDO + ("note.add",), (),
                               sensitive=True, vault=True, section=True),
}
# Briefing, cierre y revisión: sin chat ni correo. Lo único que puede escribir en la vault, y solo en Jarvis/ fuera de Sistema/.
# Lo que el cierre cambia en tareas, candidaturas y entrenos va por acciones (la base manda), no escribiendo esas notas a mano.
RUTINA_TOOLS = ("tasks.list", "career.list")
RUTINA_CAPS = ("task.create", "task.done", "task.reschedule", "career.application.create", "career.application.update", "gym.register", "gym.workout.replace", "gym.pause.log", "journal.write")
RUTINA = Specialist("rutina", "standard", RUTINA_TOOLS, RUTINA_CAPS, (), sensitive=True, vault=True, vault_write=True, gym=True, subagents=True)
WORD = re.compile(r"[a-záéíóúüñ]+")
# Lecturas de cada apartado que también puede consultar su asistente de onboarding (para ver qué hay ya)
_LECTURAS = {"educacion": UNI_TOOLS, "gym": ("gym.summary",), "carrera": CAREER_TOOLS, "finanzas": FINANCE_TOOLS, "agenda": ("agenda.days", "tasks.list")}


def onboarding(mod: str) -> Specialist | None:
    """Asistente que configura un apartado la primera vez. En Educación es el propio tutor (con su ordenador del
    campus, que después seguirá usando) más la guía de onboarding."""
    from . import modules
    from ..modules import onboarding as ob
    if mod not in modules.MODULES:
        return None
    caps = _RECUERDO + tuple(f"config.{c}.set" for c in ob.configs_de(mod)) + ("onboarding.hecho",)
    tools = _PERFIL + ("config.get",) + _LECTURAS.get(mod, ())
    if mod == "educacion":
        return replace(SPECIALISTS["tutor"], name="onboarding-educacion", tools=tools, capabilities=caps, section=True, guia=ob.guia(mod),
                       deliverables=False)
    return Specialist(f"onboarding-{mod}", "standard", tools, caps, (), sensitive=True, section=True, guia=ob.guia(mod))


def pick(text: str) -> Specialist:
    """Por raíces de palabra («ahorr» vale para ahorro y ahorrado): gratis y predecible. Ante un empate, Jarvis."""
    words = set(WORD.findall(text.lower()))

    def hits(s: Specialist) -> int:
        # Las raíces cortas deben ser la palabra entera: «uni» no vale para «unidad», «pec» no vale para «pecho»
        return sum(1 for k in s.keywords if any(w == k or (len(k) >= 4 and w.startswith(k)) for w in words))
    from . import modules
    act = modules.activos()
    scored = sorted(((hits(s), s.name) for s in SPECIALISTS.values() if modules.asistente_activo(s.name, act)), reverse=True)
    if not scored:
        return DEFAULT
    if not scored[0][0] or (len(scored) > 1 and scored[0][0] == scored[1][0]):
        return DEFAULT
    return SPECIALISTS[scored[0][1]]
