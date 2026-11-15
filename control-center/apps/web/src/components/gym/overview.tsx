"use client";

import Link from "next/link";
import { AlertTriangle, Inbox, Trophy } from "lucide-react";
import { cn } from "cn";
import { Bars, HBars } from "@/components/cc/charts";
import { Empty, ErrorState, Loading } from "@/components/cc/states";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useApi } from "@/lib/hooks";
import {
  day, EstadoBadge, Evidencia, kg, MUSCULO, NivelBadge, num, type Obs, type Plan, type Propuesta, Stat,
} from "./common";
import { PlanStateBadge, SessionActions, SessionExercises } from "./session";

type Overview = {
  hoy: string;
  ultima: { id: string; fecha: string; nombre: string; series: number; volumen: number; duracion_min: number | null } | null;
  semana: { sesiones: number; previstas: number; series: number; volumen: number; desde: string };
  mes: { sesiones: number; series: number; volumen: number; desde: string };
  mes_anterior: { sesiones: number; series: number; volumen: number; desde: string };
  records_recientes: { fecha: string; sesion_id: string; ejercicio_id: string; nombre: string; tipo: string; valor: number; detalle: string; nivel: string }[];
  progresan: { id: string; nombre: string }[];
  estancados: { id: string; nombre: string; estado: string; confianza: string | null }[];
  consistencia: { semanas: { semana: string; hechas: number; previstas: number }[]; porcentaje: number | null; media_semanal: number; criterio: string };
  analisis: Obs[];
  semanas: { semana: string; sesiones: number; series: number; volumen: number }[];
  musculos_7d: Record<string, number>;
  rutina: { id: string; nombre: string; version: number } | null;
  planificada: Plan | null;
  decisiones_pendientes: number;
  importaciones_pendientes: number;
};
type Recs = { siguiente: Propuesta | null; planificada: Plan | null };

const REC: Record<string, string> = { peso_max: "peso máximo", reps_con_peso: "más reps con ese peso", volumen_serie: "volumen en una serie", volumen_sesion: "volumen en la sesión", e1rm: "e1RM" };
const mesNombre = (iso: string) => new Date(iso + "T12:00:00").toLocaleDateString("es-ES", { month: "long" });

export function RecommendedCard({ compact = true, onChanged }: { compact?: boolean; onChanged?: () => void }) {
  const r = useApi<Recs>("/gym/recommendations");
  if (r.error) return <ErrorState message={r.error} />;
  if (!r.data) return <Loading rows={5} />;
  const plan = r.data.planificada;
  const prop = r.data.siguiente;
  const s = plan ?? prop;
  if (!s) return <Empty message="No hay una próxima sesión en la rutina (ni planificada ni recomendable con tus datos)." />;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <div className="text-lg font-semibold">{s.nombre}</div>
          <div className="text-xs text-muted-foreground">{day(s.fecha)}{prop && !plan ? ` · ~${prop.duracion_estimada_min} min (estimación)` : ""}</div>
        </div>
        {plan ? <span className="flex items-center gap-1.5 text-xs text-muted-foreground">Planificada v{plan.version} <PlanStateBadge estado={plan.estado} /></span>
          : <span className="flex items-center gap-1.5 text-xs text-muted-foreground">Sin planificar <NivelBadge n="recomendacion" /></span>}
      </div>
      {prop && !plan && <p className="text-sm"><span className="text-muted-foreground">Objetivo: </span>{prop.objetivo}</p>}
      {prop && !plan && prop.molestias.length > 0 && (
        <p className="flex items-start gap-1.5 text-xs text-warning"><AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
          Molestias: {prop.molestias.map((m) => `${m.zona} (${m.fuente})`).join(", ")}. Esos ejercicios van sin fallo y sin subir carga.</p>
      )}
      <SessionExercises ejercicios={s.ejercicios} compact={compact} />
      <p className="text-xs text-muted-foreground"><span className="font-medium text-foreground">Jarvis: </span>{plan ? plan.justificacion : prop?.justificacion}</p>
      {prop && !plan && <p className="text-[11px] text-muted-foreground">Duración: {prop.duracion_criterio}.</p>}
      <SessionActions propuesta={prop} plan={plan} onChanged={() => { r.reload(); onChanged?.(); }} verHref={compact ? "/gym/?tab=training" : undefined} />
    </div>
  );
}

export function OverviewTab() {
  const { data: o, error } = useApi<Overview>("/gym/overview");
  if (error) return <ErrorState message={error} />;
  if (!o) return <Loading rows={8} />;
  const m = o.mes.sesiones ? o.mes : o.mes_anterior;
  const mus = Object.entries(o.musculos_7d).map(([k, v]) => ({ name: MUSCULO[k] ?? k, value: v })).sort((a, b) => b.value - a.value);
  const alertas = o.analisis.filter((a) => ["estancado", "retroceso", "recuperacion"].includes(a.tipo));
  const resto = o.analisis.filter((a) => !alertas.includes(a));

  return (
    <div className="space-y-4">
      {(o.decisiones_pendientes > 0 || o.importaciones_pendientes > 0) && (
        <div className="flex flex-wrap gap-2 text-sm">
          {o.decisiones_pendientes > 0 && <Link href="/gym/?tab=coach" className="flex items-center gap-1.5 rounded-lg border border-primary/40 px-3 py-1.5 text-primary hover:bg-primary/10"><Inbox className="size-4" /> {o.decisiones_pendientes} propuesta{o.decisiones_pendientes > 1 ? "s" : ""} del Coach por revisar</Link>}
          {o.importaciones_pendientes > 0 && <Link href="/gym/?tab=history&importar=1" className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 hover:bg-muted"><Inbox className="size-4" /> {o.importaciones_pendientes} CSV de Hevy en Telegram sin importar</Link>}
        </div>
      )}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Stat k="Último entreno" v={o.ultima?.nombre ?? "—"} sub={o.ultima ? `${day(o.ultima.fecha)} · ${o.ultima.series} series` : "sin datos"} nivel="registrado" href={o.ultima ? `/gym/?tab=history&w=${o.ultima.id}` : undefined} />
        <Stat k="Esta semana" v={`${o.semana.sesiones}/${o.semana.previstas}`} sub={`${o.semana.series} series efectivas`} nivel="registrado" />
        <Stat k={o.mes.sesiones ? "Este mes" : mesNombre(m.desde)} v={String(m.sesiones)} sub={`${m.series} series efectivas`} nivel="registrado" />
        <Stat k="Vol. semana" v={kg(o.semana.volumen)} sub="peso × reps efectivas" nivel="calculado" />
        <Stat k={o.mes.sesiones ? "Vol. mes" : `Vol. ${mesNombre(m.desde)}`} v={kg(m.volumen)} sub="peso × reps efectivas" nivel="calculado" />
        <Stat k="Constancia" v={o.consistencia.porcentaje == null ? "—" : `${o.consistencia.porcentaje} %`} sub={`${num(o.consistencia.media_semanal)} sesiones/sem · 4 sem.`} nivel="calculado" />
      </div>

      <div className="grid gap-4 xl:grid-cols-5">
        <Card className="xl:col-span-3">
          <CardHeader><CardTitle>Próximo entrenamiento</CardTitle></CardHeader>
          <CardContent><RecommendedCard /></CardContent>
        </Card>
        <Card className="xl:col-span-2">
          <CardHeader><CardTitle>Análisis de Jarvis</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            {o.analisis.length === 0 && <Empty message="Aún no hay observaciones: hacen falta más sesiones." />}
            {[...alertas, ...resto].map((a) => (
              <div key={a.id} className="space-y-1 border-b border-border pb-2 last:border-0">
                <div className="flex items-start justify-between gap-2">
                  <span className={cn("text-sm font-medium", (a.tipo === "estancado" || a.tipo === "retroceso" || a.tipo === "recuperacion") && "text-warning")}>{a.titulo}</span>
                  <NivelBadge n={a.nivel} />
                </div>
                {a.detalle && <p className="text-xs text-muted-foreground">{a.detalle}</p>}
                {a.ejercicio_id && <Link href={`/gym/?tab=progress&e=${a.ejercicio_id}`} className="inline-block py-1 text-xs text-primary hover:underline">Ver el ejercicio</Link>}
                <Evidencia items={a.evidencia} />
              </div>
            ))}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader><CardTitle>Volumen por semana (kg)</CardTitle></CardHeader>
          <CardContent><Bars data={o.semanas.map((w) => ({ ...w, label: w.semana.slice(5) }))} x="label" y="volumen" unit=" kg" label="Volumen por semana" /></CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Series por músculo (7 días)</CardTitle></CardHeader>
          <CardContent>
            {mus.length ? <HBars data={mus} label="Series por músculo" /> : <Empty message="Sin series en 7 días" />}
            <p className="mt-1 text-[11px] text-muted-foreground">Principal 1, secundario 0,5: aproximación analítica.</p>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader><CardTitle className="flex items-center gap-2"><Trophy className="size-4" /> Récords (30 días)</CardTitle></CardHeader>
          <CardContent>
            {o.records_recientes.length === 0 && <Empty message="Sin récords en 30 días" />}
            <ul className="divide-y divide-border">
              {o.records_recientes.map((r, i) => (
                <li key={i} className="flex items-center justify-between gap-2 py-1.5 text-sm">
                  <Link href={`/gym/?tab=progress&e=${r.ejercicio_id}`} className="min-w-0 truncate hover:text-primary">{r.nombre}<span className="block truncate text-xs text-muted-foreground">{REC[r.tipo] ?? r.tipo}: {r.detalle}</span></Link>
                  <span className="flex shrink-0 flex-col items-end gap-0.5 text-xs text-muted-foreground">{r.fecha.slice(5)}<NivelBadge n={r.nivel} /></span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Progresan</CardTitle></CardHeader>
          <CardContent>
            {o.progresan.length === 0 && <Empty message="Ningún ejercicio con progresión clara" />}
            <ul className="space-y-1 text-sm">{o.progresan.map((p) => <li key={p.id} className="flex items-center justify-between gap-2"><Link href={`/gym/?tab=progress&e=${p.id}`} className="truncate py-0.5 hover:text-primary">{p.nombre}</Link><EstadoBadge e="progresa" /></li>)}</ul>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Estancados o en retroceso</CardTitle></CardHeader>
          <CardContent>
            {o.estancados.length === 0 && <Empty message="Ninguno" />}
            <ul className="space-y-1 text-sm">{o.estancados.map((p) => <li key={p.id} className="flex items-center justify-between gap-2"><Link href={`/gym/?tab=progress&e=${p.id}`} className="truncate py-0.5 hover:text-primary">{p.nombre}</Link><EstadoBadge e={p.estado} conf={p.confianza} /></li>)}</ul>
            <p className="mt-2 text-[11px] text-muted-foreground">Inferencia: 3+ sesiones sin superar la mejor marca previa, nunca por una sola sesión.</p>
          </CardContent>
        </Card>
      </div>
      <p className="text-[11px] text-muted-foreground">{o.consistencia.criterio} {o.rutina ? `Rutina activa: ${o.rutina.nombre} v${o.rutina.version}.` : "Sin rutina activa en el panel: se usa la de Gym.md (L Leg day, M Push, X Pull, J Lower, V Upper)."}</p>
    </div>
  );
}
