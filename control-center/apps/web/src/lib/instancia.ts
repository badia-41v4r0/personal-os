// Configuración de la instancia (GET /instancia): nombre, áreas, módulos activos y estado del onboarding.

export type Modulo = {
  id: string; nombre: string; descripcion: string; nucleo: boolean; activo: boolean;
  web: string[]; integraciones: string[]; config: string[]; requiere: string[];
};
export type Instancia = {
  nombre: string; idioma: string; areas: Record<string, string>; modulos: Modulo[];
  onboarding: { hecho: boolean; apartados: Record<string, "pendiente" | "hecho" | "saltado"> };
};

const norm = (h: string) => (h === "/" ? "/" : `/${h.replace(/^\/|\/$/g, "")}/`);

/** Módulo dueño de una ruta del panel (el prefijo más largo gana). */
export function moduloDe(inst: Instancia | null, href: string): Modulo | null {
  if (!inst) return null;
  const h = norm(href);
  let mejor: Modulo | null = null;
  let largo = -1;
  for (const m of inst.modulos) {
    for (const w of m.web) {
      const p = norm(w);
      const coincide = p === "/" ? h === "/" : h.startsWith(p);
      if (coincide && p.length > largo) { mejor = m; largo = p.length; }
    }
  }
  return mejor;
}

/** Una ruta se ve si su módulo está activo (o si no es de ningún módulo). Mientras carga, se ve todo. */
export function visible(inst: Instancia | null, href: string): boolean {
  const m = moduloDe(inst, href);
  return !m || m.activo;
}
