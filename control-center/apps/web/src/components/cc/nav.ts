import {
  Activity, Bot, BookOpen, CalendarDays, Dumbbell, FolderGit2, GraduationCap, Heart, HomeIcon, Landmark, ListChecks,
  MessagesSquare, Monitor as MonitorIcon, Plane, Plug, Server, Settings, BriefcaseBusiness, Target, UserRound, Zap,
} from "lucide-react";

export type NavItem = { href: string; label: string; icon: typeof Activity; milestone?: string };

// Vida arriba, sistema abajo: lo técnico vive dentro de Agentes.
export const NAV: NavItem[] = [
  { href: "/", label: "Inicio", icon: HomeIcon },
  { href: "/agenda/", label: "Agenda", icon: CalendarDays },
  { href: "/tasks/", label: "Tareas", icon: ListChecks },
  { href: "/gym/", label: "Entrenamiento", icon: Dumbbell },
  { href: "/salud/", label: "Salud", icon: Heart },
  { href: "/finanzas/", label: "Finanzas", icon: Landmark },
  { href: "/carrera/", label: "Carrera", icon: BriefcaseBusiness },
  { href: "/educacion/", label: "Educación", icon: GraduationCap },
  { href: "/objetivos/", label: "Objetivos", icon: Target },
  { href: "/estilo-de-vida/", label: "Estilo de vida", icon: Plane },
  { href: "/memory/", label: "Conocimiento", icon: BookOpen },
  { href: "/memory/hechos/", label: "Qué sé de ti", icon: UserRound },
];

export const NAV_SYSTEM: NavItem[] = [
  { href: "/agents/", label: "Agentes", icon: Bot },
  { href: "/automatizaciones/", label: "Automatizaciones", icon: Zap },
  { href: "/integraciones/", label: "Integraciones", icon: Plug },
  { href: "/settings/", label: "Configuración", icon: Settings },
];

/** Subapartados de Agentes: lo que antes eran secciones técnicas sueltas. */
export const AGENTS_TABS: NavItem[] = [
  { href: "/agents/", label: "Agentes", icon: Bot },
  { href: "/chat/", label: "Conversaciones", icon: MessagesSquare },
  { href: "/sistema/", label: "Sistema", icon: Server },
  { href: "/monitor/", label: "Monitor", icon: Activity },
  { href: "/virtual-computers/", label: "Ordenadores", icon: MonitorIcon },
  { href: "/projects/", label: "Proyectos", icon: FolderGit2 },
];

/** Barra inferior del móvil. */
export const NAV_MOBILE: NavItem[] = [
  { href: "/", label: "Inicio", icon: HomeIcon },
  { href: "/agenda/", label: "Agenda", icon: CalendarDays },
  { href: "/chat/", label: "Asistente", icon: MessagesSquare },  // el texto real es el nombre del asistente (shell)
  { href: "/tasks/", label: "Tareas", icon: ListChecks },
];

export const isActive = (href: string, path: string) =>
  href === "/" ? path === "/" : href === "/memory/" ? path === "/memory/" || path === "/memory" : path.startsWith(href.replace(/\/$/, ""));
