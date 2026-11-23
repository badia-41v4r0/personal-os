"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { X } from "lucide-react";
import { cn } from "cn";
import { Bars, Lines } from "@/components/cc/charts";
import { Empty, ErrorState, Loading } from "@/components/cc/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api, post } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import {
  AccionBadge, day, EstadoBadge, Evidencia, type ExIndex, kg, Msg, MUSCULO, musc, NivelBadge, num, type Objetivo, selectCls, type Serie,
  SerieChips, serie, Stat, TargetView, errMsg,
} from "./common";

type Estanc = { estado: string; confianza: string | null; sesiones: number; evidencia: string[]; propuestas: string[]; ventana?: number; dias?: number };
type RecEj = {
  ejercicio_id: string; nombre: string; peso_max: { peso: number; reps: number; fecha: string } | null;
  reps_por_peso: Record<string, { reps: number; fecha: string }>; volumen_serie: { valor: number; peso: number; reps: number; fecha: string } | null;
  volumen_sesion: { valor: number; fecha: string } | null; e1rm: { valor: number; peso: number; reps: number; fecha: string; formula: string } | null;
};
type Evento = { fecha: string; sesion_id: string; ejercicio_id: string; nombre: string; tipo: string; valor: number; detalle: string; nivel: string };
type Cfg = { categoria: string; equipo: string; metodo: string; incremento_kg: number; incremento_origen: string; rep_min: number; rep_max: number; series: number; descanso_s: number; rir_top: number; origen: string; notas?: string };
type ExDetail = {
  ejercicio: ExIndex; volumen_acumulado: number; config: Cfg; ajustes: Record<string, unknown>; objetivo: Objetivo; estancamiento: Estanc;
  records: RecEj | null; eventos_record: Evento[]; alias: string[];
  historial_roles: { fecha: string; sesion: string; sesion_id: string; series: Serie[]; volumen: number; notas: string; avisos: string[] }[];
};
type Prog = {
  puntos: { fecha: string; sesion_id: string; peso_max: number | null; top_peso: number | null; top_reps: number | null; mejor_serie: string | null; e1rm: number | null; reps_total: number; series: number; volumen: number }[];
  evolucion_pct: number | null; tendencia: Estanc; nota: string;
};
type Musculos = { musculos: { musculo: string; semanas: { semana: string; directas: number; indirectas: number; ponderadas: number; frecuencia: number }[]; actual: number; media_semanal: number; tendencia: string | null; frecuencia_media: number; ultima: string | null; ejercicios: string[] }[]; criterio: string; peso_secundario: number };

const REC: Record<string, string> = { peso_max: "Peso máximo", reps_con_peso: "Más reps con ese peso", volumen_serie: "Volumen en una serie", volumen_sesion: "Volumen en la sesión", e1rm: "e1RM (estimado)" };
const PERIODOS: [string, string][] = [["7d", "7 días"], ["28d", "28 días"], ["3m", "3 meses"], ["6m", "6 meses"], ["1a", "1 año"], ["todo", "Todo"], ["custom", "Personalizado"]];

function Settings({ id, cfg, ajustes, principales, secundarios, onSaved }: { id: string; cfg: Cfg; ajustes: Record<string, unknown>; principales: string[]; secundarios: string[]; onSaved: () => void }) {
  const [f, setF] = useState({
    rep_min: cfg.rep_min, rep_max: cfg.rep_max, series: cfg.series, incremento_kg: cfg.incremento_kg, metodo: cfg.metodo,
    descanso_s: cfg.descanso_s, categoria: cfg.categoria, principales, secundarios,
  });
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const grupos = Object.keys(MUSCULO);
  const toggle = (k: "principales" | "secundarios", m: string) => setF({ ...f, [k]: f[k].includes(m) ? f[k].filter((x) => x !== m) : [...f[k], m] });
  async function save(reset = false) {
    try {
      await api(`/gym/exercises/${id}/settings`, { method: "PUT", body: JSON.stringify(reset ? {} : f) });
      setMsg({ ok: true, text: reset ? "Vuelve a los valores por categoría." : "Guardado: el objetivo se recalcula con estos ajustes." });
      onSaved();
    } catch (e) {
      setMsg({ ok: false, text: errMsg(e) });
    }
  }
  return (
    <div className="space-y-3 text-sm">
      <p className="text-xs text-muted-foreground">Ahora: {cfg.origen === "ajuste" ? "ajustes tuyos" : `valores por categoría (${cfg.categoria})`}; incremento {cfg.incremento_origen === "observado" ? "observado en tus pesos" : cfg.incremento_origen === "ajuste" ? "ajustado" : "por equipo"}.</p>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {([["rep_min", "Reps mín."], ["rep_max", "Reps máx."], ["series", "Series"], ["incremento_kg", "Incremento (kg)"], ["descanso_s", "Descanso (s)"]] as const).map(([k, l]) => (
          <label key={k} className="text-[11px] text-muted-foreground">{l}<Input inputMode="decimal" value={f[k]} onChange={(e) => setF({ ...f, [k]: Number(e.target.value.replace(",", ".")) || 0 })} /></label>
        ))}
        <label className="text-[11px] text-muted-foreground">Método
          <select value={f.metodo} onChange={(e) => setF({ ...f, metodo: e.target.value })} className={cn(selectCls, "w-full")}>
            <option value="top_set">Top set + back-offs</option><option value="doble_progresion">Doble progresión (series rectas)</option>
          </select>
        </label>
        <label className="text-[11px] text-muted-foreground">Categoría
          <select value={f.categoria} onChange={(e) => setF({ ...f, categoria: e.target.value })} className={cn(selectCls, "w-full")}>
            {["compuesto", "maquina", "aislamiento", "peso_corporal", "cardio"].map((c) => <option key={c} value={c}>{c.replace("_", " ")}</option>)}
          </select>
        </label>
      </div>
      {(["principales", "secundarios"] as const).map((k) => (
        <div key={k}>
          <div className="text-[11px] text-muted-foreground">Músculos {k}</div>
          <div className="mt-1 flex flex-wrap gap-1">
            {grupos.map((m) => (
              <button key={m} type="button" aria-pressed={f[k].includes(m)} onClick={() => toggle(k, m)}
                className={cn("min-h-7 rounded-md border px-2 text-xs", f[k].includes(m) ? "border-primary bg-primary/10 text-primary" : "border-border text-muted-foreground hover:text-foreground")}>{MUSCULO[m]}</button>
            ))}
          </div>
        </div>
      ))}
      <div className="flex flex-wrap gap-2">
        <Button size="sm" onClick={() => save()}>Guardar ajustes</Button>
        {Object.keys(ajustes).length > 0 && <Button size="sm" variant="ghost" onClick={() => save(true)}>Volver a los valores por defecto</Button>}
      </div>
      {msg && <Msg {...msg} />}
    </div>
  );
}

function Aliases({ id, alias, onSaved }: { id: string; alias: string[]; onSaved: () => void }) {
  const ex = useApi<ExIndex[]>("/gym/exercises");
  const [nombre, setNombre] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const run = async (f: () => Promise<unknown>, ok: string) => {
    try { await f(); setMsg({ ok: true, text: ok }); onSaved(); } catch (e) { setMsg({ ok: false, text: errMsg(e) }); }
  };
  return (
    <div className="space-y-2 text-sm">
      <p className="text-xs text-muted-foreground">Si en Hevy el mismo ejercicio aparece con otro nombre, únelos aquí: el historial se junta sin tocar Gym.md.</p>
      {alias.length > 0 && (
        <ul className="flex flex-wrap gap-1">
          {alias.map((a) => (
            <li key={a} className="flex items-center gap-1 rounded-md border border-border py-0.5 pr-0.5 pl-2 text-xs">{a}
              <Button size="icon-xs" variant="ghost" aria-label={`Quitar ${a}`} onClick={() => run(() => api(`/gym/exercises/aliases/${encodeURIComponent(a)}`, { method: "DELETE" }), "Alias quitado.")}><X /></Button>
            </li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap gap-2">
        <select aria-label="Ejercicio a unir" value={nombre} onChange={(e) => setNombre(e.target.value)} className={cn(selectCls, "min-w-0 flex-1")}>
          <option value="">Unir otro nombre a este ejercicio…</option>
          {ex.data?.filter((x) => x.id !== id).flatMap((x) => x.nombres).map((n) => <option key={n} value={n}>{n}</option>)}
        </select>
        <Button size="sm" variant="outline" disabled={!nombre} onClick={() => run(() => post("/gym/exercises/aliases", { nombre, exercise_id: id }), `«${nombre}» cuenta ahora como este ejercicio.`)}>Unir</Button>
      </div>
      {msg && <Msg {...msg} />}
    </div>
  );
}

export function ExerciseDetail({ id }: { id: string }) {
  const det = useApi<ExDetail>(`/gym/exercises/${id}`);
  const [periodo, setPeriodo] = useState("todo");
  const [desde, setDesde] = useState("");
  const [hasta, setHasta] = useState("");
  const q = periodo === "custom" ? `periodo=custom${desde ? `&desde=${desde}` : ""}${hasta ? `&hasta=${hasta}` : ""}` : `periodo=${periodo}`;
  const prog = useApi<Prog>(`/gym/exercises/${id}/progress?${q}`);
  const rows = useMemo(() => (prog.data?.puntos ?? []).map((p) => ({ ...p, f: p.fecha.slice(5) })), [prog.data]);
  if (det.error) return <ErrorState message={det.error} />;
  if (!det.data) return <Loading rows={8} />;
  const d = det.data;
  const r = d.records;
  const est = d.estancamiento;
  const ultima = d.historial_roles.at(-1);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
        {musc(d.ejercicio.principales) || "Sin clasificar"}{d.ejercicio.secundarios.length > 0 && ` · secundarios: ${musc(d.ejercicio.secundarios)}`}
        <span>· {d.config.categoria.replace("_", " ")} · {d.config.rep_min}–{d.config.rep_max} reps · +{num(d.config.incremento_kg, 2)} kg</span>
        <EstadoBadge e={est.estado} conf={est.confianza} />
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Stat k="Última ejecución" v={ultima ? day(ultima.fecha) : "—"} sub={ultima ? ultima.series.filter((s) => s.rol === "top").map(serie).join("") + " top" : ""} nivel="registrado" />
        <Stat k="Sesiones" v={String(d.ejercicio.sesiones)} sub={`${d.ejercicio.series} series efectivas`} nivel="registrado" />
        <Stat k="Peso máximo" v={r?.peso_max ? kg(r.peso_max.peso) : "—"} sub={r?.peso_max ? `${serie(r.peso_max)} · ${r.peso_max.fecha.slice(5)}` : "peso corporal"} nivel="registrado" />
        <Stat k="Mejor serie (volumen)" v={r?.volumen_serie ? serie(r.volumen_serie) : "—"} sub={r?.volumen_serie ? `${kg(r.volumen_serie.valor)} · ${r.volumen_serie.fecha.slice(5)}` : ""} nivel="registrado" />
        <Stat k="Mejor e1RM" v={r?.e1rm ? kg(r.e1rm.valor) : "—"} sub={r?.e1rm ? `de ${serie(r.e1rm)} · Epley` : "sin series de 1–12 reps"} nivel="estimacion" />
        <Stat k="Evolución del periodo" v={prog.data?.evolucion_pct == null ? "—" : `${prog.data.evolucion_pct > 0 ? "+" : ""}${prog.data.evolucion_pct} %`} sub="e1RM primera → última" nivel="estimacion" />
      </div>

      <Card>
        <CardHeader><CardTitle>Siguiente objetivo</CardTitle></CardHeader>
        <CardContent className="space-y-1.5 text-sm">
          <div className="flex flex-wrap items-center gap-2"><AccionBadge a={d.objetivo.accion} /><span>Top set: <TargetView t={d.objetivo.top} /></span>
            {d.objetivo.backoffs?.length > 0 && <span className="text-xs text-muted-foreground">Back-offs: {d.objetivo.backoffs.map((b) => `${b.peso == null ? "—" : kg(b.peso)}×${b.reps}`).join(" · ")}</span>}
            <NivelBadge n="recomendacion" /></div>
          <p>{d.objetivo.motivo}</p>
          <Evidencia items={d.objetivo.evidencia} />
        </CardContent>
      </Card>

      <div className="flex flex-wrap items-center gap-1" role="group" aria-label="Periodo">
        {PERIODOS.map(([k, l]) => (
          <button key={k} type="button" aria-pressed={periodo === k} onClick={() => setPeriodo(k)}
            className={cn("min-h-7 rounded-md px-2.5 text-xs", periodo === k ? "bg-muted text-foreground" : "text-muted-foreground hover:text-foreground")}>{l}</button>
        ))}
        {periodo === "custom" && <>
          <Input type="date" aria-label="Desde" value={desde} onChange={(e) => setDesde(e.target.value)} className="w-auto" />
          <Input type="date" aria-label="Hasta" value={hasta} onChange={(e) => setHasta(e.target.value)} className="w-auto" />
        </>}
      </div>
      {prog.error && <ErrorState message={prog.error} />}
      {prog.data && rows.length === 0 && <Empty message="Sin sesiones en ese periodo" />}
      {rows.length > 0 && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card><CardHeader><CardTitle>Carga por sesión (kg)</CardTitle></CardHeader><CardContent>
            <Lines curve="linear" data={rows} x="f" unit=" kg" label="Carga por sesión" series={[{ key: "peso_max", name: "Peso máximo (registrado)" }, { key: "top_peso", name: "Top set (registrado)" }, { key: "e1rm", name: "e1RM (estimado)", dashed: true }]} />
          </CardContent></Card>
          <Card><CardHeader><CardTitle>Repeticiones del top set</CardTitle></CardHeader><CardContent>
            <Lines curve="linear" data={rows} x="f" label="Repeticiones del top set" series={[{ key: "top_reps", name: "Reps del top set" }]} />
          </CardContent></Card>
          <Card><CardHeader><CardTitle>Volumen por sesión (kg)</CardTitle></CardHeader><CardContent>
            <Bars data={rows} x="f" y="volumen" unit=" kg" label="Volumen por sesión" height={180} />
          </CardContent></Card>
          <Card><CardHeader><CardTitle>Repeticiones efectivas por sesión</CardTitle></CardHeader><CardContent>
            <Bars data={rows} x="f" y="reps_total" label="Repeticiones efectivas" height={180} />
          </CardContent></Card>
        </div>
      )}
      {prog.data && <p className="text-[11px] text-muted-foreground">{prog.data.nota}</p>}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Tendencia</CardTitle></CardHeader>
          <CardContent className="space-y-2 text-sm">
            <div className="flex items-center gap-2"><EstadoBadge e={est.estado} conf={est.confianza} /><NivelBadge n="inferencia" /></div>
            {est.propuestas.length > 0 && <ul className="list-disc space-y-0.5 pl-5">{est.propuestas.map((p) => <li key={p}>{p}</li>)}</ul>}
            <Evidencia items={est.evidencia} label="Evidencia" />
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Récords</CardTitle></CardHeader>
          <CardContent className="space-y-2 text-sm">
            {!r && <Empty message="Sin series efectivas" />}
            {r && (
              <ul className="space-y-1">
                {r.peso_max && <li className="flex justify-between gap-2"><span>Peso máximo</span><span className="font-mono tabular-nums">{serie(r.peso_max)} · {r.peso_max.fecha.slice(5)}</span></li>}
                {r.volumen_sesion && <li className="flex justify-between gap-2"><span>Volumen en una sesión</span><span className="font-mono tabular-nums">{kg(r.volumen_sesion.valor)} · {r.volumen_sesion.fecha.slice(5)}</span></li>}
                {r.e1rm && <li className="flex justify-between gap-2"><span>e1RM <NivelBadge n="estimacion" /></span><span className="font-mono tabular-nums">≈ {kg(r.e1rm.valor)} ({serie(r.e1rm)})</span></li>}
                <li className="pt-1 text-xs text-muted-foreground">Más reps por peso: {Object.entries(r.reps_por_peso).sort((a, b) => Number(b[0]) - Number(a[0])).slice(0, 6).map(([p, v]) => `${p === "PC" ? "PC" : p}×${v.reps}`).join(" · ")}</li>
              </ul>
            )}
            {d.eventos_record.length > 0 && <Evidencia items={d.eventos_record.map((e) => `${e.fecha} · ${REC[e.tipo] ?? e.tipo}: ${e.detalle}`)} label="Historial de récords" />}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader><CardTitle>Sesiones</CardTitle></CardHeader>
        <CardContent className="divide-y divide-border">
          {[...d.historial_roles].reverse().map((h) => (
            <div key={h.sesion_id} className="grid gap-2 py-2 md:grid-cols-[8rem_1fr_auto]">
              <Link href={`/entrenamiento/?tab=history&w=${h.sesion_id}`} className="-my-1 py-1 text-sm hover:text-primary">{day(h.fecha)} <span className="text-xs text-muted-foreground">{h.sesion}</span></Link>
              <div className="space-y-1"><SerieChips series={h.series} />{h.avisos.length > 0 && <p className="text-xs text-warning">{h.avisos.join("; ")}</p>}{h.notas && <p className="text-xs text-muted-foreground">Nota: {h.notas}</p>}</div>
              <span className="font-mono text-xs tabular-nums text-muted-foreground">{kg(h.volumen)}</span>
            </div>
          ))}
          <p className="pt-2 text-[11px] text-muted-foreground">«top», «aprox.» e «intento» son el papel que el motor infiere con tu método (la serie más pesada con 3+ reps es el top set). «cal.» viene marcado de Hevy.</p>
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card><CardHeader><CardTitle>Progresión de este ejercicio</CardTitle></CardHeader><CardContent>
          <Settings key={JSON.stringify(d.config)} id={id} cfg={d.config} ajustes={d.ajustes} principales={d.ejercicio.principales} secundarios={d.ejercicio.secundarios} onSaved={det.reload} />
        </CardContent></Card>
        <Card><CardHeader><CardTitle>Nombres alternativos</CardTitle></CardHeader><CardContent>
          <Aliases id={id} alias={d.alias} onSaved={det.reload} />
        </CardContent></Card>
      </div>
    </div>
  );
}

function MusclesCard() {
  const [semanas, setSemanas] = useState(8);
  const m = useApi<Musculos>(`/gym/muscles?semanas=${semanas}`);
  const [sel, setSel] = useState("pecho");
  if (m.error) return <ErrorState message={m.error} />;
  if (!m.data) return <Loading rows={6} />;
  const x = m.data.musculos.find((g) => g.musculo === sel) ?? m.data.musculos[0];
  return (
    <Card>
      <CardHeader><CardTitle>Progresión muscular</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <select aria-label="Grupo muscular" value={x.musculo} onChange={(e) => setSel(e.target.value)} className={selectCls}>
            {m.data.musculos.map((g) => <option key={g.musculo} value={g.musculo}>{MUSCULO[g.musculo] ?? g.musculo}</option>)}
          </select>
          <select aria-label="Semanas" value={semanas} onChange={(e) => setSemanas(Number(e.target.value))} className={selectCls}>
            {[4, 8, 12, 26].map((n) => <option key={n} value={n}>{n} semanas</option>)}
          </select>
        </div>
        <Bars data={x.semanas.map((w) => ({ ...w, l: w.semana.slice(5) }))} x="l" y="ponderadas" label={`Series semanales de ${x.musculo}`} height={160} />
        <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted-foreground">
          <span>Media {num(x.media_semanal)} series/sem</span><span>Frecuencia {num(x.frecuencia_media)}/sem</span>
          <span>Tendencia {x.tendencia ?? "—"}</span><span>Última {x.ultima ? day(x.ultima) : "—"}</span>
        </div>
        {x.ejercicios.length > 0 && <p className="text-xs text-muted-foreground">Ejercicios: {x.ejercicios.join(", ")}</p>}
        <div className="overflow-x-auto">
          <table className="w-full min-w-[28rem] text-xs">
            <thead className="text-left text-muted-foreground"><tr><th className="py-1 font-normal">Músculo</th><th className="font-normal">Directas</th><th className="font-normal">Indirectas</th><th className="font-normal">Media/sem</th><th className="font-normal">Tendencia</th></tr></thead>
            <tbody className="divide-y divide-border">
              {m.data.musculos.map((g) => {
                const w = g.semanas.at(-1)!;
                return (
                  <tr key={g.musculo} className={cn(g.musculo === x.musculo && "text-primary")}>
                    <td className="py-1"><button type="button" className="-my-1 py-1 hover:underline" onClick={() => setSel(g.musculo)}>{MUSCULO[g.musculo] ?? g.musculo}</button></td>
                    <td className="font-mono tabular-nums">{num(w.directas)}</td><td className="font-mono tabular-nums">{num(w.indirectas)}</td>
                    <td className="font-mono tabular-nums">{num(g.media_semanal)}</td><td>{g.tendencia ?? "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="text-[11px] text-muted-foreground">{m.data.criterio} Directas e indirectas: semana en curso.</p>
      </CardContent>
    </Card>
  );
}

export function ProgressTab() {
  const st = useApi<{ ejercicios: (Estanc & { id: string; nombre: string })[]; criterio: string }>("/gym/stagnation");
  const ex = useApi<ExIndex[]>("/gym/exercises");
  const rec = useApi<{ eventos: Evento[]; criterio: string }>("/gym/records?dias=90");
  const [q, setQ] = useState("");
  const [tipo, setTipo] = useState("");
  const estado = Object.fromEntries((st.data?.ejercicios ?? []).map((e) => [e.id, e]));
  const lista = (ex.data ?? []).filter((x) => !q || x.nombre.toLowerCase().includes(q.toLowerCase()));
  const eventos = (rec.data?.eventos ?? []).filter((e) => !tipo || (tipo === "reales" ? e.nivel === "registrado" : e.nivel === "estimacion"));

  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Ejercicios</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            <Input placeholder="Buscar ejercicio" aria-label="Buscar ejercicio" value={q} onChange={(e) => setQ(e.target.value)} />
            {ex.error && <ErrorState message={ex.error} />}
            {!ex.data && <Loading rows={6} />}
            <ul className="max-h-[28rem] divide-y divide-border overflow-y-auto pr-1">
              {lista.map((x) => (
                <li key={x.id}>
                  <Link href={`/entrenamiento/?tab=progress&e=${x.id}`} className="flex items-center justify-between gap-2 py-2 text-sm hover:text-primary">
                    <span className="min-w-0 truncate">{x.nombre}<span className="block text-xs text-muted-foreground">{x.sesiones} sesiones · última {x.ultima.slice(5)}{x.mejor_e1rm ? ` · e1RM ≈ ${x.mejor_e1rm} kg` : ""}</span></span>
                    {estado[x.id] && <EstadoBadge e={estado[x.id].estado} conf={estado[x.id].confianza} />}
                  </Link>
                </li>
              ))}
            </ul>
            <p className="text-[11px] text-muted-foreground">{st.data?.criterio}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Récords personales (90 días)</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            <select aria-label="Tipo de récord" value={tipo} onChange={(e) => setTipo(e.target.value)} className={selectCls}>
              <option value="">Todos</option><option value="reales">Solo reales</option><option value="estimados">Solo estimados (e1RM)</option>
            </select>
            {rec.data && eventos.length === 0 && <Empty message="Sin récords en el periodo" />}
            <ul className="max-h-[28rem] divide-y divide-border overflow-y-auto pr-1">
              {eventos.map((e, i) => (
                <li key={i} className="flex items-center justify-between gap-2 py-1.5 text-sm">
                  <Link href={`/entrenamiento/?tab=progress&e=${e.ejercicio_id}`} className="min-w-0 truncate hover:text-primary">{e.nombre}<span className="block truncate text-xs text-muted-foreground">{REC[e.tipo] ?? e.tipo}: {e.detalle}</span></Link>
                  <span className="flex shrink-0 flex-col items-end gap-0.5 text-xs text-muted-foreground">{e.fecha.slice(5)}<NivelBadge n={e.nivel} /></span>
                </li>
              ))}
            </ul>
            <p className="text-[11px] text-muted-foreground">{rec.data?.criterio}</p>
          </CardContent>
        </Card>
      </div>
      <MusclesCard />
    </div>
  );
}
