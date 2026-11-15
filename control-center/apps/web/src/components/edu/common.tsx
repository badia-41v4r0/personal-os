"use client";

import type { ReactNode } from "react";
import { cn } from "cn";
import { post } from "@/lib/api";

export type Siguiente = { texto: string; fecha: string; hora: string; dias: number };
export type Asig = {
  codigo: string; nombre: string; creditos: number | null; nota_actual: string; estado: string; formula: string; minimos: string;
  semaforo: "verde" | "ambar" | "rojo"; siguiente: Siguiente | null; pendientes: number; atrasadas: number;
  bloques_hechos: number; bloques_pasados: number; bloques_futuros: number; tarjetas_hoy: number;
};
export type Progreso = { avisos: number; ejemplos_avisos: string[]; planificados_hasta_hoy: number; hechos: number; restantes: number; capacidad: number; margen: number; fin: string; estado: "ok" | "justo" | "no_cabe" };
export type Semana = { semana: string; planificadas_h: number; capacidad_h: number; reales_h: number | null; actual: boolean };
export type Tiempo = { sesiones: number; horas: number; media_min: number | null; plan_min: number; por_asignatura: { asig: string; horas: number; sesiones: number; media_min: number }[] };
export type Overview = { hoy: string; asignaturas: Asig[]; progreso: Progreso; carga: Semana[]; tiempo: Tiempo; canvas_nuevos: number };
export type Entrega = { clave: string; texto: string; hora: string; asig: string; hecha: boolean; estado: Estado; dias: number };
export type Bloque = { clave: string; slot: number; hora: string; texto: string; asig: string; hecho: boolean };
export type Dia = { dia: string; bloques: Bloque[]; entregas: Entrega[] };
export type Estado = "sin_empezar" | "en_curso" | "revisando" | "entregada";

export const ESTADOS: [Estado, string][] = [["sin_empezar", "Sin empezar"], ["en_curso", "En curso"], ["revisando", "Revisando"], ["entregada", "Entregada"]];
export const DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"];

export const fecha = (f: string) => `${f.slice(8, 10)}/${f.slice(5, 7)}`;
export const diaSemana = (f: string) => DIAS[(new Date(f + "T12:00:00").getDay() + 6) % 7];
export const cuentaAtras = (d: number) => (d < 0 ? `hace ${-d} d` : d === 0 ? "hoy" : d === 1 ? "mañana" : `en ${d} d`);

/** Color por asignatura: siempre el mismo en todo Educación, sin depender solo del color (lleva el código al lado). */
const COLORES: Record<string, string> = {
  FP: "bg-chart-1/15 text-chart-1", FC: "bg-chart-2/15 text-chart-2", SC: "bg-chart-3/15 text-chart-3",
  SD: "bg-chart-4/15 text-chart-4", ARD: "bg-chart-5/15 text-chart-5", CI: "bg-muted text-foreground",
};
export function Chip({ code, className }: { code: string; className?: string }) {
  if (!code) return null;
  return <span className={cn("inline-flex shrink-0 items-center rounded-md px-1.5 py-0.5 text-[11px] font-semibold leading-none", COLORES[code] ?? "bg-muted", className)}>{code}</span>;
}

export const SEMAFORO = { verde: ["bg-emerald-500", "Al día"], ambar: ["bg-amber-500", "Atención"], rojo: ["bg-red-500", "En riesgo"] } as const;
export function Semaforo({ valor }: { valor: Asig["semaforo"] }) {
  const [c, t] = SEMAFORO[valor];
  return <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground"><span aria-hidden className={cn("size-2 rounded-full", c)} />{t}</span>;
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-0.5 text-xl font-semibold tabular-nums leading-tight">{value}</div>
      {hint && <div className="mt-0.5 text-xs text-muted-foreground">{hint}</div>}
    </div>
  );
}

export function Bar({ value, max, tone = "primary", label }: { value: number; max: number; tone?: "primary" | "warn" | "bad"; label: string }) {
  const pct = max > 0 ? Math.max(0, Math.min(100, (100 * value) / max)) : 0;
  const color = tone === "bad" ? "bg-red-500" : tone === "warn" ? "bg-amber-500" : "bg-primary";
  return (
    <div role="progressbar" aria-label={label} aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100} className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
      <div className={cn("h-full rounded-full", color)} style={{ width: `${pct}%` }} />
    </div>
  );
}

/** Le manda un mensaje al tutor y abre su chat. El mensaje lo contesta de verdad: nada se simula aquí. */
export async function preguntarTutor(texto: string): Promise<void> {
  await post("/assistants/tutor/messages", { text: texto });
  window.dispatchEvent(new Event("cc:open-dock"));
}
