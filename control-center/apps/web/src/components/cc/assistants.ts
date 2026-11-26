import { Brain, BriefcaseBusiness, Hammer, LayoutDashboard, Palette, CalendarCheck, CalendarDays, CheckSquare, Clapperboard, Compass, Dumbbell, GraduationCap, Heart, HeartPulse, Landmark, Lightbulb, Plane, Popcorn, Search, Target, TrendingUp, Wallet, type LucideIcon } from "lucide-react";
import { asistente } from "@/lib/asistente";

export type Quick = { label: string; icon: LucideIcon; text: string };
/** `icon`/`tono`: su avatar en el chat (el general usa el logo). `tono` son clases de Tailwind completas (fondo + texto). */
export type Assistant = { key: string | null; name: string; hint: string; base: string; quick: Quick[]; icon?: LucideIcon; tono?: string };

const main: Assistant = {
  key: null, get name() { return asistente(); }, hint: "Asistente general", base: "/sessions/main",
  quick: [
    { label: "Planificar mi semana", icon: CalendarDays, text: "Ayúdame a planificar esta semana con mi agenda, entregas y tareas." },
    { label: "Analizar mi entrenamiento", icon: Dumbbell, text: "Analiza mi entrenamiento de esta semana y dime qué ajustar." },
    { label: "Revisar oportunidades laborales", icon: BriefcaseBusiness, text: "Revisa mis últimas ofertas y dime cuáles merecen la pena." },
  ],
};
const a = (key: string, name: string, hint: string, quick: Quick[]): Assistant => ({ key, name, hint, base: `/assistants/${key}`, quick, ...AVATAR[key] });

const AVATAR: Record<string, { icon: LucideIcon; tono: string }> = {
  agenda: { icon: CalendarCheck, tono: "bg-sky-500/15 text-sky-600 dark:text-sky-300" },
  coach: { icon: Dumbbell, tono: "bg-orange-500/15 text-orange-600 dark:text-orange-300" },
  salud: { icon: HeartPulse, tono: "bg-rose-500/15 text-rose-600 dark:text-rose-300" },
  finanzas: { icon: Wallet, tono: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-300" },
  carrera: { icon: BriefcaseBusiness, tono: "bg-amber-500/15 text-amber-600 dark:text-amber-300" },
  tutor: { icon: GraduationCap, tono: "bg-violet-500/15 text-violet-600 dark:text-violet-300" },
  objetivos: { icon: Target, tono: "bg-red-500/15 text-red-600 dark:text-red-300" },
  estilo: { icon: Compass, tono: "bg-teal-500/15 text-teal-600 dark:text-teal-300" },
  ocio: { icon: Clapperboard, tono: "bg-fuchsia-500/15 text-fuchsia-600 dark:text-fuchsia-300" },
  conocimiento: { icon: Brain, tono: "bg-indigo-500/15 text-indigo-600 dark:text-indigo-300" },
  constructor: { icon: Hammer, tono: "bg-slate-500/15 text-slate-700 dark:text-slate-200" },
};

const organizacion = a("agenda", "Organización", "Agenda y tareas", [
  { label: "Qué hago hoy", icon: CheckSquare, text: "Con mi agenda y mis tareas, dime qué debería hacer hoy y en qué orden." },
  { label: "Planificar mi semana", icon: CalendarDays, text: "Ayúdame a planificar esta semana." },
]);
const SECTIONS: [string, Assistant][] = [
  ["/agenda", organizacion], ["/tareas", organizacion],
  ["/entrenamiento", a("coach", "Coach", "Entrenador del gimnasio", [
    { label: "Qué toca hoy", icon: Dumbbell, text: "¿Qué entrenamiento me toca hoy y con qué pesos?" },
    { label: "Analizar mi progreso", icon: TrendingUp, text: "Analiza mi progreso de las últimas semanas." },
  ])],
  ["/salud", a("salud", "Salud", "Peso, medidas y bienestar", [{ label: "Ver mi evolución", icon: Heart, text: "¿Cómo va mi evolución según lo que tengo registrado?" }])],
  ["/finanzas", a("finanzas", "Finanzas", "Tu dinero, con el ledger", [
    { label: "En qué se me va el dinero", icon: Landmark, text: "¿En qué se me va el dinero este año? Cita las cifras." },
    { label: "Resumen del mes", icon: TrendingUp, text: "Hazme el resumen de este mes." },
  ])],
  ["/carrera", a("carrera", "Carrera", "Empleo y candidaturas", [{ label: "Revisar ofertas", icon: BriefcaseBusiness, text: "Revisa mis ofertas recientes y dime cuáles merecen la pena." }])],
  ["/educacion", a("tutor", "Tutor", "Tu tutor, con acceso a tu campus", [
    { label: "Qué priorizo", icon: Target, text: "¿Qué debería priorizar esta semana en la uni?" },
    { label: "Próximas entregas", icon: CalendarDays, text: "¿Cuáles son mis próximas entregas y voy a tiempo?" },
  ])],
  ["/objetivos", a("objetivos", "Objetivos", "Objetivos y hábitos", [{ label: "Definir un objetivo", icon: Target, text: "Ayúdame a definir un objetivo con hitos medibles." }])],
  ["/estilo-de-vida", a("estilo", "Estilo de vida", "Viajes, compras e intereses", [{ label: "Planificar un viaje", icon: Plane, text: "Ayúdame a planificar un viaje." }])],
  ["/ocio", a("ocio", "Ocio", "Pelis y series", [
    { label: "Qué veo esta noche", icon: Popcorn, text: "Con lo que tengo pendiente y lo que me ha gustado, ¿qué veo esta noche? Dime por qué." },
  ])],
  ["/conocimiento/sobre-ti", a("conocimiento", "Conocimiento", "Tu vault y tu memoria", [{ label: "Qué sabes de mí", icon: Lightbulb, text: "Resume lo que sabes de mí y lo que falta por confirmar." }])],
  ["/conocimiento", a("conocimiento", "Conocimiento", "Tu vault y tu memoria", [{ label: "Qué tengo más trabajado", icon: Search, text: "¿Qué temas tengo más trabajados en mis notas? Cita de qué nota sale cada uno." }])],
];

export function assistantFor(path: string): Assistant {
  return SECTIONS.find(([p]) => path.startsWith(p))?.[1] ?? main;
}

/** Clave del asistente en las conversaciones del chat (el general es «jarvis»). */
export const claveChat = (a: Assistant) => a.key ?? "jarvis";

/** Personaliza el propio panel (módulo «constructor»), con vista previa antes de aplicar. */
export const CONSTRUCTOR = a("constructor", "Constructor", "Personaliza tu panel", [
  { label: "Ideas de apartados", icon: LayoutDashboard, text: "Según lo que uso del panel, ¿qué apartado nuevo me recomiendas añadir? Dame tres ideas y pregúntame cuál hacemos." },
  { label: "Cambiar el aspecto", icon: Palette, text: "Quiero cambiar el aspecto del panel. Pregúntame qué me gustaría y enséñame opciones." },
  { label: "Qué puedo personalizar", icon: Lightbulb, text: "¿Qué cosas del panel me puedes cambiar o añadir? Dame ideas según lo que uso." },
]);

/** Todos los asistentes del chat, sin repetir, con la ruta de su apartado (para saber si su módulo está activo) o su módulo. */
export const ASISTENTES: { asistente: Assistant; ruta: string; modulo?: string }[] = [
  { asistente: main, ruta: "/" },
  ...SECTIONS.filter(([, a], i) => SECTIONS.findIndex(([, b]) => b.key === a.key) === i).map(([ruta, asistente]) => ({ asistente, ruta: `${ruta}/` })),
  { asistente: CONSTRUCTOR, ruta: "/", modulo: "constructor" },
];

export const asistentePorClave = (k: string): Assistant => ASISTENTES.find((x) => claveChat(x.asistente) === k)?.asistente ?? main;
