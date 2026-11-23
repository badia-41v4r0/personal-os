// Direcciones antiguas del panel → las nuevas. Mismo mapa que backend/app/rutas_viejas.py (que redirige en el
// servidor). Aquí sirve para los enlaces que vienen guardados en la base (avisos antiguos) y para `next dev`.

const TAREAS: Record<string, string> = {
  approvals: "/bandeja/", requests: "/bandeja/?t=solicitudes", queues: "/ajustes/colas/", timers: "/ajustes/colas/", tasks: "/tareas/",
};

export const PREFIJOS: [string, string][] = [
  ["/memory/hechos/", "/conocimiento/sobre-ti/"],
  ["/settings/modulos/", "/ajustes/modulos/"],
  ["/gym/", "/entrenamiento/"],
  ["/memory/", "/conocimiento/"],
  ["/projects/", "/proyectos/"],
  ["/tasks/", "/tareas/"],
  ["/chat/", "/conversaciones/"],
  ["/settings/", "/ajustes/"],
  ["/agents/", "/ajustes/agentes/"],
  ["/sistema/", "/ajustes/sistema/"],
  ["/monitor/", "/ajustes/monitor/"],
  ["/virtual-computers/", "/ajustes/ordenadores/"],
  ["/integraciones/", "/ajustes/conexiones/"],
  ["/automatizaciones/", "/ajustes/automatizaciones/"],
  ["/avisos/", "/bandeja/"],
];

/** Enlace actual para una dirección del panel, antigua o no. */
export function rutaActual(url: string): string {
  if (!url.startsWith("/") || url.startsWith("/api/")) return url;
  const [path0, query = ""] = url.split("?", 2);
  const path = path0.endsWith("/") ? path0 : `${path0}/`;
  const params = new URLSearchParams(query);
  if (path === "/tasks/" && params.get("t") && TAREAS[params.get("t")!]) return TAREAS[params.get("t")!];
  for (const [viejo, nuevo] of PREFIJOS) {
    if (path.startsWith(viejo)) {
      if (viejo === "/tasks/") params.delete("t");
      const q = params.toString();
      return nuevo + path.slice(viejo.length) + (q ? `?${q}` : "");
    }
  }
  return url;
}
