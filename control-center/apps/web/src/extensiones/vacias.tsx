// Extensiones locales de la web: piezas propias de una instalación que no forman parte del proyecto público.
// Si existe src/privado/index.tsx (excluida al publicar), next.config.ts y tsconfig.json usan esa en vez de esta.
// Esta versión vacía es la del proyecto público: cada enganche no añade nada.
import type { ReactNode } from "react";

/** Proyectos: bloque extra encima de un repo (recibe su área). */
export function ProyectoCabecera(_: { area: string; repo: string }): ReactNode {
  return null;
}

/** Proyectos: página de detalle propia para `?r=<repo>&t=<id>`. null = no hay. */
export const ProyectoDetalle: ((p: { repo: string; id: string }) => ReactNode) | null = null;

/** Etiquetas de issues que van primero y destacadas (además de «decision»). */
export const ETIQUETAS_DESTACADAS: string[] = [];
