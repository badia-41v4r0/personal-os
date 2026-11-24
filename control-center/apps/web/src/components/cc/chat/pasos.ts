// Los pasos de una respuesta, en palabras: «Leyendo PEC2.md», «Consultando tu agenda»…
// Cada paso llega como «herramienta etiqueta» (mensajes role=tool y eventos session.tool del backend).

const AREAS: [string, string][] = [
  ["memory", "tu memoria"], ["tasks", "tus tareas"], ["task", "tus tareas"], ["agenda", "tu agenda"], ["calendar", "tu calendario"],
  ["uni", "la uni"], ["gym", "el gimnasio"], ["mail", "tu correo"], ["finance", "tus finanzas"], ["career", "tus candidaturas"],
  ["health", "tu salud"], ["goals", "tus objetivos"], ["goal", "tus objetivos"], ["habits", "tus hábitos"], ["habit", "tus hábitos"],
  ["lifestyle", "tu estilo de vida"], ["ocio", "tu ocio"], ["note", "tus notas"], ["day", "tu día"],
];

const area = (nombre: string) => AREAS.find(([p]) => nombre === p || nombre.startsWith(`${p}.`))?.[1];
const base = (p: string) => p.replace(/^\/(vault|trabajo|archivos)\//, "").split("/").filter(Boolean).pop() ?? p;
const corto = (s: string, n = 48) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);

export type Paso = { herramienta: string; etiqueta: string };

export function separar(linea: string): Paso {
  const i = linea.indexOf(" ");
  return i < 0 ? { herramienta: linea, etiqueta: "" } : { herramienta: linea.slice(0, i), etiqueta: linea.slice(i + 1).trim() };
}

/** Frase en gerundio para la línea «está…» y para la lista de pasos. */
export function describir({ herramienta: h, etiqueta: e }: Paso): string {
  const sin = h.replace(/^mcp__plugin_\w+__/, "");
  switch (sin) {
    case "Read": return e ? `Leyendo ${corto(base(e))}` : "Leyendo un archivo";
    case "Grep": return e ? `Buscando «${corto(e, 36)}»` : "Buscando en sus archivos";
    case "Glob": return "Buscando archivos";
    case "Edit": case "Write": case "MultiEdit": return e ? `Escribiendo ${corto(base(e))}` : "Escribiendo un archivo";
    case "WebSearch": return e ? `Buscando en internet «${corto(e, 36)}»` : "Buscando en internet";
    case "WebFetch": {
      try { return `Leyendo ${new URL(e).hostname.replace(/^www\./, "")}`; } catch { return "Leyendo una web"; }
    }
    case "Task": case "Agent": return "Pidiendo ayuda a un subagente";
    case "TodoWrite": return "Ordenando los pasos";
    case "Bash": return "Ejecutando un comando";
    case "mcp__pos__pos_read": return `Consultando ${area(e) ?? (e ? corto(e) : "tus datos")}`;
    case "mcp__pos__pos_action": return `Preparando un cambio en ${area(e) ?? "tus datos"}`;
    case "mcp__pos__pos_tools": return "Mirando qué puede hacer";
  }
  if (sin.startsWith("mcp__gym__")) return "Consultando el gimnasio";
  if (sin.startsWith("mcp__vc__")) return "Usando su ordenador virtual";
  if (sin.startsWith("mcp__")) return `Usando ${sin.split("__").pop()}`;
  return e ? `${sin} · ${corto(e)}` : sin;
}

export const describirLinea = (linea: string) => describir(separar(linea));

export function duracion(ms: number): string {
  const s = Math.max(1, Math.round(ms / 1000));
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60);
  return `${m} min${s % 60 ? ` ${s % 60} s` : ""}`;
}
