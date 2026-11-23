"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { AlertTriangle, ArrowDown, ArrowUp, CalendarClock, Check, MessageSquare, Pencil, Plus, Repeat, Trash2 } from "lucide-react";
import { cn } from "cn";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, post } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import {
  AccionBadge, descanso, errMsg, Evidencia, type ExIndex, kg, Msg, musc, type Plan, type PlanEx, type Propuesta, selectCls, SESIONES,
  serie, TargetView, today,
} from "./common";
import { asistente } from "@/lib/asistente";

/** Ejercicios de una sesión planificada o recomendada, con objetivo, último, mejor y por qué. */
export function SessionExercises({ ejercicios, compact = false }: { ejercicios: PlanEx[]; compact?: boolean }) {
  if (!ejercicios.length) return <p className="text-sm text-muted-foreground">Sin ejercicios.</p>;
  if (compact) {
    return (
      <ol className="divide-y divide-border">
        {ejercicios.map((e) => {
          const o = e.objetivo ?? ({} as PlanEx["objetivo"]);
          return (
            <li key={e.id} className="grid grid-cols-[1fr_auto] items-center gap-x-3 gap-y-0.5 py-1.5 text-sm">
              <span className="min-w-0 truncate">{e.nombre}{e.opcional && <span className="text-xs text-muted-foreground"> · opcional</span>}</span>
              <span className="font-mono text-xs tabular-nums">
                {e.series} × {e.rango?.[0]}–{e.rango?.[1]}{o.top ? ` · ${o.top.peso == null ? "PC" : kg(o.top.peso)}` : ""}
              </span>
              <span className="col-span-2 flex items-center gap-1.5 text-xs text-muted-foreground">
                {o.accion && <AccionBadge a={o.accion} />}
                {o.top && <span className="truncate">top {serie(o.top)}{o.backoffs?.[0]?.peso != null ? ` · back-offs ${kg(o.backoffs[0].peso)}` : ""} · {descanso(e.descanso_s)}</span>}
              </span>
            </li>
          );
        })}
      </ol>
    );
  }
  return (
    <ol className="space-y-3">
      {ejercicios.map((e, i) => {
        const o = e.objetivo ?? ({} as PlanEx["objetivo"]);
        return (
          <li key={e.id + i} className="rounded-lg border border-border p-3">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div className="min-w-0">
                <Link href={`/entrenamiento/?tab=progress&e=${e.id}`} className="-my-1 inline-block py-1 font-medium hover:text-primary">{i + 1}. {e.nombre}</Link>
                <div className="text-xs text-muted-foreground">
                  {musc(e.principales ?? []) || "sin clasificar"}{e.secundarios?.length ? ` · secundarios: ${musc(e.secundarios)}` : ""}
                  {e.categoria && ` · ${e.categoria.replace("_", " ")}`}{e.opcional && " · opcional"}{e.editado && " · editado a mano"}
                </div>
              </div>
              {o.accion && <AccionBadge a={o.accion} />}
            </div>
            <div className="mt-2 grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2 lg:grid-cols-4">
              <div><span className="text-xs text-muted-foreground">Series · rango</span><div className="font-mono tabular-nums">{e.series} × {e.rango?.[0]}–{e.rango?.[1]}</div></div>
              <div><span className="text-xs text-muted-foreground">Top set objetivo</span><div><TargetView t={o.top} /></div></div>
              <div><span className="text-xs text-muted-foreground">Back-offs</span><div className="font-mono text-xs tabular-nums">{o.backoffs?.length ? o.backoffs.map((b) => `${b.peso == null ? "—" : kg(b.peso)} × ${b.reps}`).join(" · ") : "—"}</div></div>
              <div><span className="text-xs text-muted-foreground">Descanso</span><div className="font-mono tabular-nums">{descanso(e.descanso_s)}</div></div>
              <div><span className="text-xs text-muted-foreground">Último</span><div className="font-mono text-xs tabular-nums">{e.ultimo ? `${e.ultimo.fecha.slice(5)}: ${e.ultimo.series.join(", ")}` : "—"}</div></div>
              <div><span className="text-xs text-muted-foreground">Mejor top set</span><div className="font-mono text-xs tabular-nums">{e.mejor?.top ? `${serie(e.mejor.top)} (${e.mejor.fecha.slice(5)})` : "—"}</div></div>
            </div>
            {o.precaucion && <p className="mt-2 flex items-start gap-1.5 text-xs text-warning"><AlertTriangle className="mt-0.5 size-3.5 shrink-0" />{o.precaucion}</p>}
            <p className="mt-2 text-sm"><span className="text-xs text-muted-foreground">Objetivo: </span>{o.motivo}</p>
            {e.instrucciones && <p className="mt-1 text-xs text-muted-foreground">{e.instrucciones}</p>}
            {(e.por_que?.length ?? 0) > 0 && <p className="mt-1 text-xs text-muted-foreground">Por qué este ejercicio: {e.por_que!.join(" · ")}</p>}
            {(o.avisos?.length ?? 0) > 0 && <p className="mt-1 text-xs text-warning">Última sesión: {o.avisos!.join("; ")}</p>}
            <div className="mt-1"><Evidencia items={o.evidencia ?? []} /></div>
          </li>
        );
      })}
    </ol>
  );
}

type Row = { id: string | null; nombre: string; series: number; rep_min: number; rep_max: number; peso: number | null; reps: number | null; backoff_peso: number | null; descanso_s: number; notas: string };

const toRow = (e: PlanEx): Row => ({
  id: e.id, nombre: e.nombre, series: e.series || 3, rep_min: e.rango?.[0] ?? 6, rep_max: e.rango?.[1] ?? 10,
  peso: e.objetivo?.top?.peso ?? null, reps: typeof e.objetivo?.top?.reps === "number" ? e.objetivo.top.reps : null,
  backoff_peso: e.objetivo?.backoffs?.[0]?.peso ?? null, descanso_s: e.descanso_s ?? 120, notas: e.notas ?? "",
});

/** Editor de una sesión: añadir, quitar, cambiar, reordenar, series, reps y pesos. Guarda una versión nueva. */
export function PlanEditor({ plan, propuesta, fecha, nombre, onSaved, onCancel }: {
  plan?: Plan; propuesta?: Propuesta; fecha: string; nombre: string; onSaved: (p: Plan) => void; onCancel: () => void;
}) {
  const ejercicios = useApi<ExIndex[]>("/gym/exercises").data ?? [];
  const [rows, setRows] = useState<Row[]>(() => (plan?.ejercicios ?? propuesta?.ejercicios ?? []).map(toRow));
  const [motivo, setMotivo] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (i: number, patch: Partial<Row>) => setRows((r) => r.map((x, j) => (j === i ? { ...x, ...patch } : x)));
  const move = (i: number, d: number) => setRows((r) => {
    const n = [...r];
    const [x] = n.splice(i, 1);
    n.splice(i + d, 0, x);
    return n;
  });
  const nb = (v: string) => (v === "" ? null : Number(v.replace(",", ".")));

  async function save() {
    setBusy(true);
    setMsg(null);
    try {
      const body = rows.map((r) => ({ ...r, id: r.id || undefined, reps: r.reps || undefined }));
      const out = plan
        ? await api<Plan>(`/gym/plans/${plan.id}`, { method: "PATCH", body: JSON.stringify({ ejercicios: body, motivo: motivo || "Modificada en el panel", version_base: plan.version }) })
        : await post<Plan>("/gym/plans", { fecha, nombre, ejercicios: body, motivo: motivo || "Recomendación modificada en el panel" });
      onSaved(out);
    } catch (e) {
      setMsg({ ok: false, text: errMsg(e) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">
        {plan ? `Guardar crea la versión ${plan.version + 1}; la ${plan.version} se conserva.` : "Guardar planifica esta sesión con tus cambios (la recomendación original queda en el historial del motor)."}
      </p>
      <datalist id="gym-ejercicios">{ejercicios.map((x) => <option key={x.id} value={x.nombre} />)}</datalist>
      <ol className="space-y-2">
        {rows.map((r, i) => (
          <li key={i} className="rounded-lg border border-border p-2">
            <div className="flex items-center gap-1">
              <Input aria-label={`Ejercicio ${i + 1}`} list="gym-ejercicios" value={r.nombre} className="min-w-0 flex-1"
                onChange={(e) => {
                  const m = ejercicios.find((x) => x.nombre === e.target.value);
                  set(i, { nombre: e.target.value, id: m?.id ?? null });
                }} />
              <Button variant="ghost" size="icon-sm" aria-label="Subir" disabled={i === 0} onClick={() => move(i, -1)}><ArrowUp /></Button>
              <Button variant="ghost" size="icon-sm" aria-label="Bajar" disabled={i === rows.length - 1} onClick={() => move(i, 1)}><ArrowDown /></Button>
              <Button variant="ghost" size="icon-sm" aria-label="Quitar" onClick={() => setRows(rows.filter((_, j) => j !== i))}><Trash2 /></Button>
            </div>
            <div className="mt-2 grid grid-cols-3 gap-2 sm:grid-cols-7">
              {([["series", "Series"], ["rep_min", "Reps mín."], ["rep_max", "Reps máx."], ["peso", "Peso top (kg)"], ["reps", "Reps top"], ["backoff_peso", "Back-off (kg)"], ["descanso_s", "Descanso (s)"]] as const).map(([k, l]) => (
                <label key={k} className="text-[11px] text-muted-foreground">{l}
                  <Input inputMode="decimal" value={r[k] ?? ""} onChange={(e) => set(i, { [k]: k === "peso" || k === "backoff_peso" || k === "reps" ? nb(e.target.value) : Number(e.target.value) || 0 } as Partial<Row>)} />
                </label>
              ))}
            </div>
            <Input className="mt-2" placeholder="Nota (opcional)" aria-label="Nota" value={r.notas} onChange={(e) => set(i, { notas: e.target.value })} />
          </li>
        ))}
      </ol>
      <Button variant="outline" size="sm" onClick={() => setRows([...rows, { id: null, nombre: "", series: 3, rep_min: 8, rep_max: 12, peso: null, reps: null, backoff_peso: null, descanso_s: 90, notas: "" }])}>
        <Plus /> Añadir ejercicio
      </Button>
      <Input placeholder="Motivo del cambio" aria-label="Motivo del cambio" value={motivo} onChange={(e) => setMotivo(e.target.value)} />
      <div className="flex flex-wrap gap-2">
        <Button size="sm" disabled={busy || rows.some((r) => !r.nombre.trim())} onClick={save}><Check /> Guardar</Button>
        <Button size="sm" variant="ghost" onClick={onCancel}>Cancelar</Button>
      </div>
      {msg && <Msg {...msg} />}
    </div>
  );
}

/** Acciones sobre la sesión recomendada o planificada. */
export function SessionActions({ propuesta, plan, onChanged, verHref }: { propuesta: Propuesta | null; plan: Plan | null; onChanged: () => void; verHref?: string }) {
  const router = useRouter();
  const [modo, setModo] = useState<"" | "posponer" | "sustituir">("");
  const [fecha, setFecha] = useState("");
  const [nombre, setNombre] = useState(SESIONES[0]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const objetivo = plan ?? propuesta;
  if (!objetivo) return null;

  async function run(f: () => Promise<unknown>, ok: string) {
    setBusy(true);
    setMsg(null);
    try {
      await f();
      setMsg({ ok: true, text: ok });
      setModo("");
      onChanged();
    } catch (e) {
      setMsg({ ok: false, text: errMsg(e) });
    } finally {
      setBusy(false);
    }
  }
  const aceptar = () => run(() => post("/gym/recommendations/siguiente/accept", { huella: propuesta?.huella }), "Planificada.");
  const posponer = () => run(
    () => (plan ? api(`/gym/plans/${plan.id}`, { method: "PATCH", body: JSON.stringify({ fecha, estado: "aceptada", motivo: "Pospuesta desde el panel", version_base: plan.version }) })
      : post("/gym/recommendations/siguiente/accept", { huella: propuesta?.huella, fecha })), `Movida al ${fecha}.`);
  const sustituir = () => run(() => post("/gym/plans", { fecha: fecha || objetivo.fecha, nombre, motivo: `Sustituye a ${objetivo.nombre}` }), `Planificada ${nombre}.`);
  const preguntar = () => run(async () => {
    await post("/gym/coach/chat", { text: `Explícame el entrenamiento ${plan ? "planificado" : "recomendado"} para el ${objetivo.fecha} (${objetivo.nombre}): por qué esos ejercicios y esas cargas, y qué debo vigilar.` });
    router.push("/entrenamiento/?tab=coach");
  }, "Pregunta enviada al Coach.");

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        {verHref && <Link href={verHref} className={buttonVariants({ size: "sm", variant: "outline" })}>Ver entrenamiento</Link>}
        {!plan && propuesta && <Button size="sm" disabled={busy} onClick={aceptar}><Check /> Aceptar planificación</Button>}
        <Link href="/entrenamiento/?tab=training&editar=1" className={buttonVariants({ size: "sm", variant: "outline" })}><Pencil /> Modificar</Link>
        <Button size="sm" variant="outline" aria-expanded={modo === "sustituir"} onClick={() => setModo(modo === "sustituir" ? "" : "sustituir")}><Repeat /> Sustituir</Button>
        <Button size="sm" variant="outline" aria-expanded={modo === "posponer"} onClick={() => setModo(modo === "posponer" ? "" : "posponer")}><CalendarClock /> Posponer</Button>
        <Button size="sm" variant="ghost" disabled={busy} onClick={preguntar}><MessageSquare /> Preguntar a {asistente()}</Button>
      </div>
      {modo === "posponer" && (
        <div className="flex flex-wrap items-center gap-2">
          <Input type="date" aria-label="Nueva fecha" min={today()} value={fecha} onChange={(e) => setFecha(e.target.value)} className="w-auto" />
          <Button size="sm" disabled={!fecha || busy} onClick={posponer}>Mover</Button>
        </div>
      )}
      {modo === "sustituir" && (
        <div className="flex flex-wrap items-center gap-2">
          <select aria-label="Sesión" value={nombre} onChange={(e) => setNombre(e.target.value)} className={selectCls}>
            {SESIONES.map((s) => <option key={s}>{s}</option>)}
          </select>
          <Input type="date" aria-label="Fecha" min={today()} value={fecha || objetivo.fecha} onChange={(e) => setFecha(e.target.value)} className="w-auto" />
          <Button size="sm" disabled={busy} onClick={sustituir}>Planificar en su lugar</Button>
          <span className="text-xs text-muted-foreground">El motor prepara esa sesión con tus datos; la anterior queda como «sustituida».</span>
        </div>
      )}
      {msg && <Msg {...msg} />}
    </div>
  );
}

export function PlanStateBadge({ estado }: { estado: string }) {
  const c = estado === "hecha" ? "text-success border-success/40" : estado === "aceptada" ? "text-primary border-primary/40" : "text-muted-foreground";
  return <span className={cn("rounded-md border px-1.5 py-0.5 text-[11px]", c)}>{estado}</span>;
}
