import {
  Activity, Bot, BookOpen, CalendarDays, Cpu, Dumbbell, FolderGit2, GraduationCap, Heart, HomeIcon, Inbox, Landmark,
  LayersIcon, ListChecks, ListTree, MessagesSquare, Monitor as MonitorIcon, Plane, Plug, Popcorn, ScrollText, Server, Settings, ShieldCheck,
  BriefcaseBusiness, Target, UserRound, Zap,
} from "lucide-react";

export type NavItem = { href: string; label: string; icon: typeof Activity; hint?: string };
export type NavGroup = { label: string; items: NavItem[] };

// Menú lateral: lo del día, tus áreas (solo los módulos activos) y tu conocimiento. Ajustes va aparte, abajo.
export const NAV_GROUPS: NavGroup[] = [
  {
    label: "Hoy",
    items: [
      { href: "/", label: "Inicio", icon: HomeIcon },
      { href: "/bandeja/", label: "Bandeja", icon: Inbox, hint: "Avisos y lo que espera tu aprobación" },
      { href: "/agenda/", label: "Agenda", icon: CalendarDays },
      { href: "/tareas/", label: "Tareas", icon: ListChecks },
    ],
  },
  {
    label: "Tus áreas",
    items: [
      { href: "/educacion/", label: "Educación", icon: GraduationCap },
      { href: "/entrenamiento/", label: "Entrenamiento", icon: Dumbbell },
      { href: "/salud/", label: "Salud", icon: Heart },
      { href: "/finanzas/", label: "Finanzas", icon: Landmark },
      { href: "/carrera/", label: "Carrera", icon: BriefcaseBusiness },
      { href: "/objetivos/", label: "Objetivos", icon: Target },
      { href: "/estilo-de-vida/", label: "Estilo de vida", icon: Plane },
      { href: "/ocio/", label: "Ocio", icon: Popcorn },
      { href: "/proyectos/", label: "Proyectos", icon: FolderGit2 },
    ],
  },
  {
    label: "Conocimiento",
    items: [{ href: "/conocimiento/", label: "Conocimiento", icon: BookOpen, hint: "Tu vault y lo que sé de ti" }],
  },
];

export const NAV: NavItem[] = NAV_GROUPS.flatMap((g) => g.items);
export const NAV_AJUSTES: NavItem = { href: "/ajustes/", label: "Ajustes", icon: Settings };

/** Pestañas de Conocimiento. */
export const CONOCIMIENTO_TABS: NavItem[] = [
  { href: "/conocimiento/", label: "Tu vault", icon: BookOpen },
  { href: "/conocimiento/sobre-ti/", label: "Qué sé de ti", icon: UserRound },
];

/** Menú de Ajustes: todo lo que se configura o se conecta, en un solo sitio. */
export const AJUSTES_GROUPS: NavGroup[] = [
  {
    label: "General",
    items: [
      { href: "/ajustes/", label: "Tú y tu cuenta", icon: UserRound, hint: "Usuario, contraseña, tu nombre y el de tu asistente" },
      { href: "/ajustes/motor/", label: "Motor de IA", icon: Cpu, hint: "Claude, Codex, OpenRouter o Antigravity, y sus credenciales" },
      { href: "/ajustes/modulos/", label: "Módulos", icon: LayersIcon, hint: "Activar apartados y configurarlos con su asistente" },
      { href: "/ajustes/conexiones/", label: "Conexiones", icon: Plug, hint: "Google, GitHub, campus, Telegram y avisos en el móvil" },
      { href: "/ajustes/automatizaciones/", label: "Automatizaciones", icon: Zap, hint: "Horario de las rutinas" },
      { href: "/ajustes/permisos/", label: "Autonomía", icon: ShieldCheck, hint: "Qué pueden hacer los agentes sin preguntarte" },
    ],
  },
  {
    label: "Avanzado",
    items: [
      { href: "/ajustes/agentes/", label: "Agentes", icon: Bot },
      { href: "/conversaciones/", label: "Conversaciones", icon: MessagesSquare },
      { href: "/ajustes/ordenadores/", label: "Ordenadores", icon: MonitorIcon, hint: "Ordenadores virtuales de los agentes (campus, navegador, terminal)" },
      { href: "/ajustes/sistema/", label: "Sistema", icon: Server },
      { href: "/ajustes/monitor/", label: "Monitor", icon: Activity },
      { href: "/ajustes/colas/", label: "Colas y temporizadores", icon: ListTree },
      { href: "/ajustes/auditoria/", label: "Auditoría", icon: ScrollText },
    ],
  },
];
export const AJUSTES: NavItem[] = AJUSTES_GROUPS.flatMap((g) => g.items);

/** Barra inferior del móvil. */
export const NAV_MOBILE: NavItem[] = [
  { href: "/", label: "Inicio", icon: HomeIcon },
  { href: "/agenda/", label: "Agenda", icon: CalendarDays },
  { href: "/conversaciones/", label: "Asistente", icon: MessagesSquare },  // abre el asistente del apartado (shell)
  { href: "/bandeja/", label: "Bandeja", icon: Inbox },
];

const sinBarra = (h: string) => h.replace(/\/$/, "");

/** ¿Está activo este enlace? «/» y las raíces con subpáginas propias en el menú solo coinciden exactas. */
export function isActive(href: string, path: string): boolean {
  const p = sinBarra(path) || "/";
  const h = sinBarra(href) || "/";
  if (h === "/" || h === "/ajustes" || h === "/conocimiento") return p === h;
  return p === h || p.startsWith(`${h}/`);
}

/** Para el menú lateral: Ajustes y Conocimiento cubren todas sus subpáginas. */
export function enSeccion(href: string, path: string): boolean {
  const h = sinBarra(href);
  if (h === "/ajustes") return path.startsWith("/ajustes") || path.startsWith("/conversaciones");
  if (h === "/conocimiento") return path.startsWith("/conocimiento");
  return isActive(href, path);
}

/** Título de la sección para la cabecera del móvil (Inicio usa la fecha). */
export function tituloDe(path: string): string | null {
  if (sinBarra(path) === "/mas") return "Más";
  if (sinBarra(path) === "" || path.startsWith("/bienvenida")) return null;
  const candidatos = [...NAV.filter((i) => i.href !== "/"), ...AJUSTES];
  let mejor: NavItem | null = null;
  for (const i of candidatos) {
    if (isActive(i.href, path) && (!mejor || i.href.length > mejor.href.length)) mejor = i;
  }
  return mejor?.label ?? null;
}
