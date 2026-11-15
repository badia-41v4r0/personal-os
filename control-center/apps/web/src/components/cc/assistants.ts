import { BriefcaseBusiness, CalendarDays, CheckSquare, Dumbbell, Heart, Landmark, Lightbulb, Plane, Search, Target, TrendingUp, type LucideIcon } from "lucide-react";

export type Quick = { label: string; icon: LucideIcon; text: string };
export type Assistant = { key: string | null; name: string; hint: string; base: string; quick: Quick[] };

const main: Assistant = {
  key: null, name: "Jarvis", hint: "Asistente general", base: "/sessions/main",
  quick: [
    { label: "Planificar mi semana", icon: CalendarDays, text: "Ayúdame a planificar esta semana con mi agenda, entregas y tareas." },
    { label: "Analizar mi entrenamiento", icon: Dumbbell, text: "Analiza mi entrenamiento de esta semana y dime qué ajustar." },
    { label: "Revisar oportunidades laborales", icon: BriefcaseBusiness, text: "Revisa mis últimas ofertas y dime cuáles merecen la pena." },
  ],
};
const a = (key: string, name: string, hint: string, quick: Quick[]): Assistant => ({ key, name, hint, base: `/assistants/${key}`, quick });

const organizacion = a("agenda", "Organización", "Agenda y tareas", [
  { label: "Qué hago hoy", icon: CheckSquare, text: "Con mi agenda y mis tareas, dime qué debería hacer hoy y en qué orden." },
  { label: "Planificar mi semana", icon: CalendarDays, text: "Ayúdame a planificar esta semana." },
]);
const SECTIONS: [string, Assistant][] = [
  ["/agenda", organizacion], ["/tasks", organizacion],
  ["/gym", a("coach", "Coach", "Entrenador del gimnasio", [
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
  ["/memory/hechos", a("conocimiento", "Conocimiento", "Tu vault y tu memoria", [{ label: "Qué sabes de mí", icon: Lightbulb, text: "Resume lo que sabes de mí y lo que falta por confirmar." }])],
  ["/memory", a("conocimiento", "Conocimiento", "Tu vault y tu memoria", [{ label: "Qué tengo más trabajado", icon: Search, text: "¿Qué temas tengo más trabajados en mis notas? Cita de qué nota sale cada uno." }])],
];

export function assistantFor(path: string): Assistant {
  return SECTIONS.find(([p]) => path.startsWith(p))?.[1] ?? main;
}
