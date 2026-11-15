"use client";

import Link from "next/link";
import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { cn } from "cn";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";

// ---------- tipos (los del backend: app/gym.py, app/gym_plan.py y collectors/gym_coach.py) ----------

export type Nivel = "registrado" | "calculado" | "estimacion" | "inferencia" | "recomendacion";
export type Serie = { peso: number | null; reps: number; calentamiento: boolean; fallo: boolean; drop: boolean; rpe: number | null; e1rm: number | null; rol?: string };
export type Target = { peso: number | null; reps: number | string; rir?: number | string };
export type Objetivo = {
  accion: string; motivo: string; evidencia: string[]; precaucion: string | null; top: Target | null; backoffs: Target[];
  series_objetivo?: Target[]; ultimo?: { fecha: string; top: Serie | null; series: string[] } | null; avisos?: string[];
  rango?: [number, number]; incremento_kg?: number; nivel?: Nivel;
};
export type PlanEx = {
  id: string; nombre: string; principales: string[]; secundarios: string[]; opcional?: boolean; categoria?: string; series: number;
  rango: [number, number]; descanso_s: number; metodo?: string; objetivo: Objetivo; ultimo?: Objetivo["ultimo"];
  mejor?: { fecha: string; top: Serie | null } | null; instrucciones?: string; por_que?: string[]; notas?: string; editado?: boolean;
};
export type Propuesta = {
  fecha: string; dia: string; nombre: string; origen: string; estado: string; ejercicios: PlanEx[]; duracion_estimada_min: number;
  duracion_criterio: string; objetivo: string; justificacion: string; molestias: { zona: string; fuente: string; detalle: string }[]; huella?: string;
};
export type Comparacion = {
  estado: string; sesion_id?: string; fecha?: string; cumplimiento: number | null; criterio?: string;
  ejercicios: { id: string; nombre: string; estado: string; series_previstas: number; series_hechas: number; objetivo: Partial<Target>; real: { peso: number | null; reps: number } | null; volumen?: number; diferencia_peso?: number | null; diferencia_reps?: number | null }[];
  anadidos: { id: string; nombre: string; series: number; volumen: number }[]; omitidos?: string[]; volumen_previsto?: number; volumen_real?: number;
};
export type Plan = {
  id: string; fecha: string; nombre: string; estado: string; version: number; workout_id: string | null; link_mode: string; origen_fecha: string | null;
  rutina_id: string | null; rutina_version: number | null; creada_por: string; creada: string; actualizada: string; ejercicios: PlanEx[];
  justificacion: string; motivo_version: string; comparacion?: Comparacion | null;
  versiones?: { version: number; autor: string; motivo: string; fecha: string; ejercicios: PlanEx[] }[];
  candidatas?: { id: string; fecha: string; nombre: string }[];
};
export type Obs = { id: string; tipo: string; nivel: Nivel; titulo: string; detalle: string; evidencia: string[]; propuestas?: string[]; ejercicio_id?: string };
export type Decision = {
  id: number; fecha: string; fecha_aplicacion: string | null; alcance: string; objetivo_de: string; ejercicio_id: string | null; tipo: string;
  situacion: string; datos: string[]; recomendacion: string; motivo: string; resultado_esperado: string; objetivo: { peso?: number | null; reps?: number };
  estado: string; fuente: string; evaluacion: { estado: string; texto: string } | null; decidida_por: string | null; payload: Record<string, unknown>;
};
export type Workout = { id: string; fecha: string; nombre: string; hevy: string; series: number; volumen: number; ejercicios: number; musculos: Record<string, number>; fuente: string; duracion_min: number | null; planificada?: string | null };
export type ExIndex = { id: string; nombre: string; nombres: string[]; sesiones: number; series: number; volumen: number; ultima: string; principales: string[]; secundarios: string[]; tipo: string; mejor_e1rm: number | null; categoria?: string; rango?: [number, number]; incremento_kg?: number };

// ---------- formato ----------

export const MUSCULO: Record<string, string> = {
  pecho: "Pecho", espalda: "Espalda", hombros: "Hombros", biceps: "Bíceps", triceps: "Tríceps", cuadriceps: "Cuádriceps",
  isquiotibiales: "Isquiotibiales", gluteos: "Glúteos", aductores: "Aductores", gemelos: "Gemelos", abdomen: "Abdomen", lumbar: "Lumbar",
};
export const DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"];
export const SESIONES = ["Leg day", "Push", "Pull", "Lower", "Upper"];
export const num = (n: number | null | undefined, d = 1) => (n == null ? "—" : n.toLocaleString("es-ES", { maximumFractionDigits: d }));
export const kg = (n: number | null | undefined) => (n == null ? "—" : `${num(n)} kg`);
export const day = (iso: string) => new Date(iso.slice(0, 10) + "T12:00:00").toLocaleDateString("es-ES", { weekday: "short", day: "2-digit", month: "short" });
export const peso = (p: number | null | undefined) => (p == null ? "PC" : num(p, 2));
export const serie = (s: { peso: number | null; reps: number | string }) => `${peso(s.peso)}×${s.reps}`;
export const today = () => new Date().toLocaleDateString("sv-SE");
export const musc = (l: string[]) => l.map((m) => MUSCULO[m] ?? m).join(", ");
export const selectCls = "h-8 rounded-lg border border-input bg-transparent px-2 text-sm dark:bg-input/30";
export const descanso = (s: number) => (s >= 120 ? `${Math.floor(s / 60)}${s % 60 ? `:${String(s % 60).padStart(2, "0")}` : ""} min` : `${s} s`);
export const errMsg = (e: unknown) => (e instanceof Error ? e.message : String(e));

export const ACCION: Record<string, string> = {
  subir_peso: "subir peso", mas_reps: "+1 rep", mantener: "consolidar", bajar_peso: "bajar peso", precaucion: "precaución",
  lastre: "añadir lastre", sin_datos: "sin datos", sin_objetivo: "sin objetivo", manual: "manual",
};
export const ESTADO_EJ: Record<string, string> = {
  progresa: "progresa", estable: "estable", estancado: "estancado", retroceso: "retroceso", pocos_datos: "pocos datos", sin_datos: "sin datos",
};

const NIVEL: Record<Nivel, { t: string; c: string; d: string }> = {
  registrado: { t: "registrado", c: "border-success/40 text-success", d: "Dato registrado en Hevy / Gym.md" },
  calculado: { t: "calculado", c: "border-border text-muted-foreground", d: "Cálculo exacto sobre datos registrados" },
  estimacion: { t: "estimación", c: "border-warning/50 text-warning", d: "Estimación con una fórmula (p. ej. e1RM de Epley): no es una marca levantada" },
  inferencia: { t: "inferencia", c: "border-chart-3/50 text-chart-3", d: "Deducción del motor a partir de patrones; puede fallar" },
  recomendacion: { t: "recomendación", c: "border-primary/40 text-primary", d: "Propuesta del entrenador; no es un dato" },
};

/** Etiqueta del tipo de dato: registrado, calculado, estimación, inferencia o recomendación. */
export function NivelBadge({ n, className }: { n?: Nivel | string | null; className?: string }) {
  const x = NIVEL[(n ?? "calculado") as Nivel] ?? NIVEL.calculado;
  return <Badge variant="outline" title={x.d} className={cn("h-5 px-1.5 text-[10px] font-normal", x.c, className)}>{x.t}</Badge>;
}

export function EstadoBadge({ e, conf }: { e: string; conf?: string | null }) {
  const c = e === "progresa" ? "border-success/40 text-success" : e === "retroceso" ? "border-destructive/40 text-destructive"
    : e === "estancado" ? "border-warning/50 text-warning" : "text-muted-foreground";
  return <Badge variant="outline" className={cn("h-5 px-1.5 text-[11px] font-normal", c)}>{ESTADO_EJ[e] ?? e}{conf ? ` · ${conf}` : ""}</Badge>;
}

export function AccionBadge({ a }: { a: string }) {
  const c = a === "subir_peso" || a === "lastre" ? "border-success/40 text-success" : a === "bajar_peso" || a === "precaucion" ? "border-warning/50 text-warning" : "";
  return <Badge variant="outline" className={cn("h-5 px-1.5 text-[11px] font-normal", c)}>{ACCION[a] ?? a}</Badge>;
}

export function Stat({ k, v, sub, nivel, href }: { k: string; v: React.ReactNode; sub?: React.ReactNode; nivel?: Nivel; href?: string }) {
  const body = (
    <CardContent>
      <div className="flex items-center justify-between gap-1 text-xs text-muted-foreground"><span className="truncate">{k}</span>{nivel && <NivelBadge n={nivel} />}</div>
      <div className="mt-1 truncate font-mono text-xl font-semibold tabular-nums">{v}</div>
      {sub && <div className="truncate text-xs text-muted-foreground">{sub}</div>}
    </CardContent>
  );
  return <Card size="sm" className={href ? "transition-colors hover:bg-muted/40" : undefined}>{href ? <Link href={href} className="block">{body}</Link> : body}</Card>;
}

export function SerieChips({ series }: { series: Serie[] }) {
  return (
    <div className="flex flex-wrap gap-1">
      {series.map((s, i) => {
        const r = s.rol;
        return (
          <span key={i}
            title={[r && r !== "calentamiento" ? `Papel inferido: ${r}` : "", s.e1rm ? `e1RM estimado ${s.e1rm} kg` : ""].filter(Boolean).join(" · ") || undefined}
            className={cn("rounded-md px-1.5 py-0.5 font-mono text-xs tabular-nums ring-1 ring-border",
              (s.calentamiento || r === "aproximacion") && "text-muted-foreground",
              s.calentamiento && "line-through decoration-muted-foreground/40",
              r === "top" && "ring-primary/60", s.fallo && "ring-primary/40")}>
            {serie(s)}{s.calentamiento ? " cal." : r === "aproximacion" ? " aprox." : r === "top" ? " top" : r === "intento" ? " intento" : ""}
            {s.fallo ? " F" : ""}{s.drop ? " D" : ""}{s.rpe ? ` @${s.rpe}` : ""}
          </span>
        );
      })}
    </div>
  );
}

/** Bloque plegable con los datos que justifican algo. */
export function Evidencia({ items, label = "Ver los datos" }: { items: string[]; label?: string }) {
  const [open, setOpen] = useState(false);
  if (!items?.length) return null;
  return (
    <div>
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}
        className="-mx-1 flex min-h-6 items-center gap-1 rounded px-1 text-xs text-muted-foreground hover:text-foreground">
        {open ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />} {label} ({items.length})
      </button>
      {open && <ul className="mt-1 space-y-0.5 border-l border-border pl-3 font-mono text-[11px] text-muted-foreground">{items.map((x, i) => <li key={i}>{x}</li>)}</ul>}
    </div>
  );
}

export function TargetView({ t }: { t: Target | null | undefined }) {
  if (!t) return <span className="text-muted-foreground">—</span>;
  return <span className="font-mono tabular-nums">{t.peso == null ? "PC" : `${num(t.peso, 2)} kg`} × {t.reps}{t.rir != null ? <span className="text-muted-foreground"> · RIR {t.rir}</span> : null}</span>;
}

export function Msg({ ok, text }: { ok: boolean; text: string }) {
  return <p role={ok ? "status" : "alert"} className={cn("text-xs", ok ? "text-success" : "text-destructive")}>{text}</p>;
}
