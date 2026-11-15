"use client";

import { useState } from "react";
import { Check, Send, X } from "lucide-react";
import { cn } from "cn";
import { IndependentChat } from "@/components/cc/independent-chat";
import type { SessionSummary } from "@/components/cc/new-session";
import { Empty, ErrorState, Loading } from "@/components/cc/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ApiError, post } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { type Decision, errMsg, Evidencia, kg, Msg, MUSCULO, NivelBadge, num, type Obs } from "./common";
import { asistente } from "@/lib/asistente";

type Coach = { session: SessionSummary | null; herramientas: string[]; pendientes: number };
type ReportRow = { id: number; tipo: string; desde: string; hasta: string; creado: string; enviado: string | null; resumen: { sesiones_hechas: number; sesiones_previstas: number; cumplimiento: number | null; volumen_kg: number; series: number } };
type Fila = { nombre: string; antes: string; ahora: string; cambio_pct: number };
type ReportData = {
  tipo: string; desde: string; hasta: string; sesiones_hechas: number; sesiones_previstas: number; cumplimiento: number | null; volumen_kg: number; series: number;
  series_por_musculo: Record<string, number>; progresos: Fila[]; retrocesos: Fila[]; records: { fecha: string; nombre: string; detalle: string; nivel: string }[];
  estancados: { nombre: string; estado: string; confianza: string | null }[]; analisis: Obs[]; recomendaciones: string[]; texto: string;
  semanas?: { semana: string; sesiones: number; series: number; volumen: number }[]; evolucion_muscular?: Record<string, { mes: number; mes_anterior: number }>;
  volumen_mes_anterior?: number; cambios_rutina?: { version: number; motivo: string; cambios: string[] }[]; decisiones?: (Decision & { evaluacion: { estado: string; texto: string } | null })[];
  objetivos_proximo_mes?: string[];
};

const TIPO: Record<string, string> = {
  subir_peso: "Subir peso", mantener: "Mantener", bajar_peso: "Bajar peso", mas_reps: "Más reps", reducir_volumen: "Reducir volumen",
  cambiar_ejercicio: "Cambiar ejercicio", frecuencia: "Frecuencia", reorganizar: "Reorganizar rutina", descarga: "Descarga", otro: "Otro", precaucion: "Precaución",
};
const EVAL: Record<string, string> = { cumplido: "text-success", parcial: "text-warning", no_cumplido: "text-destructive", pendiente: "text-muted-foreground" };

function DecisionItem({ d, onChanged }: { d: Decision; onChanged: () => void }) {
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [needsConfirm, setNeedsConfirm] = useState(false);
  const act = async (a: "accept" | "reject", confirmar = false) => {
    try {
      await post(`/gym/coach/decisions/${d.id}/${a}`, a === "accept" ? { confirmar } : undefined);
      onChanged();
    } catch (e) {
      if (e instanceof ApiError && e.status === 428) setNeedsConfirm(true);
      setMsg({ ok: false, text: errMsg(e) });
    }
  };
  const rutina = (d.payload?.rutina as { dias?: Record<string, { nombre: string; ejercicios: { nombre: string; series: number; rep_min: number; rep_max: number }[] }> } | undefined)?.dias;
  return (
    <li className="space-y-1 py-2 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <b>{TIPO[d.tipo] ?? d.tipo}</b>{d.objetivo_de && <span>· {d.objetivo_de}</span>}
        <span className="text-xs text-muted-foreground">{d.fecha.slice(0, 10)} · {d.fuente === "motor" ? "motor (al aceptar un plan)" : d.fuente === "coach" ? "Coach" : "tú"}</span>
        <span className={cn("rounded-md border px-1.5 text-[11px]", d.estado === "propuesta" ? "border-primary/40 text-primary" : "text-muted-foreground")}>{d.estado}</span>
      </div>
      {d.situacion && <p className="text-xs text-muted-foreground">Situación: {d.situacion}</p>}
      <p>{d.recomendacion}</p>
      {d.motivo && d.motivo !== d.recomendacion && <p className="text-xs text-muted-foreground">Por qué: {d.motivo}</p>}
      {d.resultado_esperado && <p className="text-xs text-muted-foreground">Esperado: {d.resultado_esperado}</p>}
      {rutina && (
        <div className="rounded-md border border-border p-2 text-xs">
          {Object.entries(rutina).map(([k, v]) => <div key={k}><b>{["L", "M", "X", "J", "V", "S", "D"][Number(k)]} {v.nombre}:</b> {v.ejercicios.map((e) => `${e.nombre} ${e.series}×${e.rep_min}–${e.rep_max}`).join(", ")}</div>)}
        </div>
      )}
      <Evidencia items={d.datos} label="Datos usados" />
      {d.evaluacion && <p className={cn("text-xs", EVAL[d.evaluacion.estado])}>Resultado: {d.evaluacion.estado.replace("_", " ")} · {d.evaluacion.texto}</p>}
      {d.estado === "propuesta" && (
        <div className="flex gap-2 pt-1">
          <Button size="sm" onClick={() => act("accept", needsConfirm)}><Check /> {needsConfirm ? "Confirmar cambio de la rutina activa" : d.tipo === "reorganizar" ? "Aceptar (crea una versión de la rutina)" : "Aceptar"}</Button>
          <Button size="sm" variant="ghost" onClick={() => act("reject")}><X /> Rechazar</Button>
        </div>
      )}
      {msg && <Msg {...msg} />}
    </li>
  );
}

function Decisions() {
  const [estado, setEstado] = useState("");
  const d = useApi<Decision[]>(`/gym/coach/decisions${estado ? `?estado=${estado}` : ""}`);
  const pend = useApi<Decision[]>("/gym/coach/decisions?estado=propuesta");
  const reload = () => { d.reload(); pend.reload(); };
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader><CardTitle>Propuestas por revisar</CardTitle></CardHeader>
        <CardContent>
          {pend.data?.length === 0 && <p className="text-sm text-muted-foreground">Nada pendiente. Cuando el Coach proponga un cambio, lo aceptas o rechazas aquí: nada se aplica solo.</p>}
          <ul className="divide-y divide-border">{pend.data?.map((x) => <DecisionItem key={x.id} d={x} onChanged={reload} />)}</ul>
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Historial de decisiones</CardTitle></CardHeader>
        <CardContent>
          <div role="group" aria-label="Estado" className="mb-2 flex flex-wrap gap-1">
            {[["", "Todas"], ["aceptada", "Aceptadas"], ["aplicada", "Aplicadas"], ["rechazada", "Rechazadas"]].map(([k, l]) => (
              <button key={k} type="button" aria-pressed={estado === k} onClick={() => setEstado(k)} className={cn("min-h-7 rounded-md px-2.5 text-xs", estado === k ? "bg-muted" : "text-muted-foreground")}>{l}</button>
            ))}
          </div>
          {d.error && <ErrorState message={d.error} />}
          {d.data?.filter((x) => x.estado !== "propuesta").length === 0 && <Empty message="Sin decisiones aún. Se registran al aceptar un plan (subidas, bajadas, consolidar) y al aceptar propuestas del Coach." />}
          <ul className="max-h-[36rem] divide-y divide-border overflow-y-auto pr-1">{d.data?.filter((x) => x.estado !== "propuesta").map((x) => <DecisionItem key={x.id} d={x} onChanged={reload} />)}</ul>
        </CardContent>
      </Card>
    </div>
  );
}

function ReportView({ id }: { id: number }) {
  const r = useApi<{ datos: ReportData; enviado: string | null }>(`/gym/reports/${id}`);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  if (r.error) return <ErrorState message={r.error} />;
  if (!r.data) return <Loading rows={6} />;
  const d = r.data.datos;
  const lista = (t: string, l: Fila[]) => l.length > 0 && <div><b>{t}:</b> {l.map((p) => `${p.nombre} ${p.antes} → ${p.ahora} (${p.cambio_pct > 0 ? "+" : ""}${p.cambio_pct} %)`).join(" · ")}</div>;
  return (
    <div className="space-y-2 text-sm">
      <div className="flex flex-wrap gap-x-6 gap-y-1">
        <span>Sesiones {d.sesiones_hechas}{d.sesiones_previstas ? `/${d.sesiones_previstas}` : ""}{d.cumplimiento != null ? ` (${d.cumplimiento} %)` : ""}</span>
        <span>{d.series} series efectivas</span><span>Volumen {kg(d.volumen_kg)}{d.volumen_mes_anterior != null ? ` (mes anterior ${kg(d.volumen_mes_anterior)})` : ""}</span>
      </div>
      <div className="text-xs text-muted-foreground">Series por músculo: {Object.entries(d.series_por_musculo).map(([k, v]) => `${MUSCULO[k] ?? k} ${num(v)}`).join(", ") || "—"}</div>
      {lista("Progresos", d.progresos)}
      {lista("Retrocesos", d.retrocesos)}
      {d.records.length > 0 && <div><b>Récords:</b> {d.records.slice(0, 8).map((x) => `${x.nombre} ${x.detalle}${x.nivel === "estimacion" ? " (est.)" : ""}`).join(" · ")}{d.records.length > 8 ? ` y ${d.records.length - 8} más` : ""}</div>}
      {d.estancados.length > 0 && <div><b>Estancados:</b> {d.estancados.map((e) => `${e.nombre} (${e.estado}, ${e.confianza})`).join(", ")}</div>}
      {d.evolucion_muscular && <div className="text-xs text-muted-foreground"><b className="text-foreground">Evolución muscular (series del mes frente al anterior):</b> {Object.entries(d.evolucion_muscular).filter(([, v]) => v.mes || v.mes_anterior).map(([k, v]) => `${MUSCULO[k] ?? k} ${num(v.mes_anterior)}→${num(v.mes)}`).join(" · ")}</div>}
      {d.cambios_rutina && d.cambios_rutina.length > 0 && <div><b>Cambios de rutina:</b> {d.cambios_rutina.map((c) => `v${c.version}: ${c.motivo}`).join("; ")}</div>}
      {d.decisiones && d.decisiones.length > 0 && <div><b>Recomendaciones del mes y resultado:</b><ul className="list-disc pl-5 text-xs">{d.decisiones.map((x) => <li key={x.id}>{TIPO[x.tipo] ?? x.tipo} · {x.objetivo_de}: {x.evaluacion ? `${x.evaluacion.estado.replace("_", " ")} (${x.evaluacion.texto})` : "sin evaluar"}</li>)}</ul></div>}
      <div><b>Análisis de {asistente()}</b> <NivelBadge n="inferencia" /><ul className="list-disc pl-5 text-xs">{d.analisis.map((a) => <li key={a.id}>{a.titulo}{a.detalle ? `: ${a.detalle}` : ""}</li>)}</ul></div>
      {d.recomendaciones.length > 0 && <div><b>Para el siguiente periodo</b> <NivelBadge n="recomendacion" /><ul className="list-disc pl-5 text-xs">{d.recomendaciones.map((x) => <li key={x}>{x}</li>)}</ul></div>}
      {d.objetivos_proximo_mes && <div><b>Objetivos del próximo mes</b><ul className="list-disc pl-5 text-xs">{d.objetivos_proximo_mes.map((x) => <li key={x}>{x}</li>)}</ul></div>}
      <div className="flex flex-wrap items-center gap-2 pt-1">
        <Button size="sm" variant="outline" onClick={async () => {
          try { await post(`/gym/reports/${id}/send`); setMsg({ ok: true, text: "Enviado por Telegram." }); r.reload(); } catch (e) { setMsg({ ok: false, text: errMsg(e) }); }
        }}><Send /> Enviar resumen por Telegram</Button>
        {r.data.enviado && <span className="text-xs text-muted-foreground">Enviado el {r.data.enviado.slice(0, 16).replace("T", " ")}</span>}
      </div>
      {msg && <Msg {...msg} />}
    </div>
  );
}

function Reports() {
  const [tipo, setTipo] = useState("semanal");
  const l = useApi<ReportRow[]>(`/gym/reports?tipo=${tipo}`);
  const [sel, setSel] = useState<number | null>(null);
  const actual = sel ?? l.data?.[0]?.id ?? null;
  return (
    <Card>
      <CardHeader><CardTitle>Informes</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        <div role="group" aria-label="Tipo de informe" className="flex gap-1">
          {["semanal", "mensual"].map((t) => <button key={t} type="button" aria-pressed={tipo === t} onClick={() => { setTipo(t); setSel(null); }} className={cn("min-h-7 rounded-md px-2.5 text-xs capitalize", tipo === t ? "bg-muted" : "text-muted-foreground")}>{t}</button>)}
        </div>
        {l.error && <ErrorState message={l.error} />}
        {l.data?.length === 0 && <Empty message="Sin periodos cerrados todavía" />}
        <div className="flex flex-wrap gap-1">
          {l.data?.map((r) => (
            <button key={r.id} type="button" aria-pressed={actual === r.id} onClick={() => setSel(r.id)}
              className={cn("min-h-7 rounded-md border px-2 text-xs", actual === r.id ? "border-primary text-primary" : "border-border text-muted-foreground hover:text-foreground")}>
              {tipo === "semanal" ? `${r.desde.slice(5)}–${r.hasta.slice(5)}` : new Date(r.desde + "T12:00").toLocaleDateString("es-ES", { month: "short", year: "2-digit" })}
            </button>
          ))}
        </div>
        {actual != null && <ReportView key={actual} id={actual} />}
        <p className="text-[11px] text-muted-foreground">Se generan solos al abrir esta lista para cada semana y mes ya cerrados (uno por periodo, sin duplicados) con los mismos cálculos que el resto del panel.</p>
      </CardContent>
    </Card>
  );
}

export function CoachTab() {
  const c = useApi<Coach>("/gym/coach");
  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
      <div className="space-y-4">
        <Card>
          <CardHeader><CardTitle>Coach</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            <p className="text-xs text-muted-foreground">Entrenador de {asistente()} con acceso de solo lectura a tus datos del gym ({c.data?.herramientas.length ?? "…"} herramientas: historial, ejercicios, progresión, récords, músculos, planificación, recuperación y decisiones). Puede proponer cambios, pero no aplicarlos. Prueba: «¿Qué entreno hoy?», «¿Estoy progresando en press banca?», «Analiza mis últimos 30 días».</p>
            {c.error && <ErrorState message={c.error} />}
            {!c.data && !c.error && <Loading rows={4} />}
            {c.data && !c.data.session && <p className="text-sm text-muted-foreground">Solo el administrador puede abrir el Coach.</p>}
            {c.data?.session && (
              <div className="grid h-[36rem] grid-cols-1 overflow-hidden rounded-lg border border-border [&>aside]:hidden">
                <IndependentChat session={c.data.session} onChanged={c.reload} />
              </div>
            )}
          </CardContent>
        </Card>
        <Reports />
      </div>
      <Decisions />
    </div>
  );
}
