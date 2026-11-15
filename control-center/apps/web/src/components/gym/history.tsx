"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { GitCompare, Upload } from "lucide-react";
import { cn } from "cn";
import { Empty, ErrorState, Loading } from "@/components/cc/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useApi } from "@/lib/hooks";
import { post } from "@/lib/api";
import {
  type Comparacion, day, errMsg, type ExIndex, kg, Msg, MUSCULO, musc, NivelBadge, type Plan, selectCls, type Serie, SerieChips, serie, SESIONES, type Workout,
} from "./common";
import { ComparacionView } from "./training";
import { asistente } from "@/lib/asistente";

type Detail = Omit<Workout, "ejercicios"> & {
  ejercicios: { id: string; nombre: string; series: Serie[]; volumen: number; efectivas: number; notas: string; tipo: string; principales: string[]; secundarios: string[]; raw: string }[];
  hevy_traza: { external_id: string; titulo: string; inicio: string; fin: string; duracion_min: number | null; filas: number } | null;
  plan: Plan | null; comparacion: Comparacion | null; anterior: Workout | null;
  records: { tipo: string; nombre: string; detalle: string; nivel: string }[];
};
type Top = { peso: number | null; reps: number; e1rm: number | null } | null;
type Cmp = { a: Workout; b: Workout; ejercicios: { id: string; nombre: string; a: { top: Top; series: number; volumen: number } | null; b: { top: Top; series: number; volumen: number } | null }[] };
type Imp = { id: number; fecha: string; fuente: string; archivo: string; estado: string; errores: string[];
  resumen: { desde: string | null; entrenos: number; nuevos: { fecha: string; sesion: string; titulo: string; duracion_min: number | null; ejercicios: number; bloque: string }[]; ya_registrados: { fecha: string; titulo: string }[]; misma_fecha: { fecha: string; titulo: string }[]; avisos: string[]; aplicadas?: number } };
type Imports = { importaciones: Imp[]; telegram: { archivo: string; tamano: number; fecha: string; importado: boolean }[]; bandeja: string; trazas: number };

export function WorkoutDetail({ id }: { id: string }) {
  const { data, error } = useApi<Detail>(`/gym/workouts/${id}`);
  if (error) return <ErrorState message={error} />;
  if (!data) return <Loading rows={6} />;
  const dur = data.hevy_traza?.duracion_min ?? data.duracion_min;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-1 text-sm">
        <span>{day(data.fecha)}</span><span>{data.series} series efectivas</span><span>{kg(data.volumen)}</span>
        <span className={dur ? "" : "text-muted-foreground"}>Duración: {dur ? `${dur} min` : "no registrada"}</span>
        {data.hevy && <span className="text-muted-foreground">Hevy: {data.hevy}</span>}
        {data.anterior && <Link href={`/gym/?tab=history&cmp=${data.anterior.id},${data.id}`} className="-my-1 flex items-center gap-1 py-1 text-primary hover:underline"><GitCompare className="size-3.5" /> Comparar con la anterior ({data.anterior.fecha.slice(5)})</Link>}
      </div>
      <p className="text-[11px] text-muted-foreground">Fuente: {data.fuente}{data.hevy_traza ? ` · importado de Hevy (id ${data.hevy_traza.external_id}, ${data.hevy_traza.filas} filas originales)` : ""}. Descansos y RPE: solo si están registrados.</p>
      {data.records.length > 0 && (
        <div className="rounded-lg border border-success/30 bg-success/5 p-2 text-xs">
          <b>Récords en esta sesión:</b> {data.records.map((r) => `${r.nombre} ${r.detalle}${r.nivel === "estimacion" ? " (e1RM estimado)" : ""}`).join(" · ")}
        </div>
      )}
      <Card>
        <CardContent className="divide-y divide-border">
          {data.ejercicios.map((e) => (
            <div key={e.id + e.raw} className="grid gap-2 py-3 md:grid-cols-[1fr_auto]">
              <div className="min-w-0 space-y-1.5">
                <Link href={`/gym/?tab=progress&e=${e.id}`} className="-my-1 inline-block py-1 font-medium hover:text-primary">{e.nombre}</Link>
                <div className="text-xs text-muted-foreground">
                  {musc(e.principales) || (e.tipo === "cardio" ? "Cardio" : "Sin clasificar")}{e.secundarios.length > 0 && ` · secundarios: ${musc(e.secundarios)}`}
                </div>
                {e.series.length ? <SerieChips series={e.series} /> : <div className="text-xs text-muted-foreground">{e.raw}</div>}
                {e.notas && e.series.length > 0 && <div className="text-xs text-muted-foreground">Nota: {e.notas}</div>}
              </div>
              <div className="font-mono text-xs tabular-nums text-muted-foreground md:text-right">{e.efectivas} series<br />{kg(e.volumen)}</div>
            </div>
          ))}
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Comparación con lo planificado</CardTitle></CardHeader>
        <CardContent>
          {data.comparacion ? <><ComparacionView c={data.comparacion} /><Link href={`/gym/?tab=training&plan=${data.plan!.id}`} className="mt-2 inline-block text-xs text-primary hover:underline">Ver la planificación (v{data.plan!.version})</Link></>
            : <p className="text-sm text-muted-foreground">No había una sesión planificada asociada a este entreno. Se asocian solas si coinciden fecha y sesión; si no, desde Training → Planificadas.</p>}
        </CardContent>
      </Card>
    </div>
  );
}

function CompareView({ a, b }: { a: string; b: string }) {
  const { data, error } = useApi<Cmp>(`/gym/workouts/${a}/compare/${b}`);
  if (error) return <ErrorState message={error} />;
  if (!data) return <Loading rows={5} />;
  const t = (x: Top) => (x ? serie(x) : "—");
  return (
    <Card>
      <CardHeader><CardTitle>{data.a.nombre} {day(data.a.fecha)} frente a {data.b.nombre} {day(data.b.fecha)}</CardTitle></CardHeader>
      <CardContent className="space-y-2">
        <div className="flex flex-wrap gap-x-6 text-sm"><span>Series: {data.a.series} → {data.b.series}</span><span>Volumen: {kg(data.a.volumen)} → {kg(data.b.volumen)}</span></div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[30rem] text-sm">
            <thead className="text-left text-xs text-muted-foreground"><tr><th className="py-1 font-normal">Ejercicio</th><th className="font-normal">Top set A</th><th className="font-normal">Top set B</th><th className="font-normal">Series</th><th className="font-normal">Volumen</th></tr></thead>
            <tbody className="divide-y divide-border">
              {data.ejercicios.map((e) => {
                const ea = e.a?.top?.e1rm, eb = e.b?.top?.e1rm;
                return (
                  <tr key={e.id}>
                    <td className="py-1.5 pr-2"><Link href={`/gym/?tab=progress&e=${e.id}`} className="hover:text-primary">{e.nombre}</Link></td>
                    <td className="font-mono tabular-nums">{e.a ? t(e.a.top) : "—"}</td>
                    <td className={cn("font-mono tabular-nums", ea && eb && (eb > ea ? "text-success" : eb < ea ? "text-destructive" : ""))}>{e.b ? t(e.b.top) : "—"}</td>
                    <td className="font-mono tabular-nums">{e.a?.series ?? "—"} → {e.b?.series ?? "—"}</td>
                    <td className="font-mono text-xs tabular-nums">{e.a ? kg(e.a.volumen) : "—"} → {e.b ? kg(e.b.volumen) : "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="text-[11px] text-muted-foreground">Top set inferido (la serie más pesada con 3+ reps). El color compara su e1RM estimado.</p>
      </CardContent>
    </Card>
  );
}

function Importar() {
  const imp = useApi<Imports>("/gym/imports");
  const [texto, setTexto] = useState("");
  const [archivo, setArchivo] = useState("");
  const [desde, setDesde] = useState("");
  const [prev, setPrev] = useState<Imp | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async (f: () => Promise<Imp>, aplicar = false) => {
    setBusy(true);
    setMsg(null);
    try {
      const r = await f();
      if (aplicar) {
        setPrev(null);
        setMsg({ ok: true, text: `Añadidas ${r.resumen.aplicadas ?? 0} sesiones a Gym.md.` });
      } else setPrev(r);
      imp.reload();
    } catch (e) {
      setMsg({ ok: false, text: errMsg(e) });
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="space-y-3 text-sm">
      <p className="text-xs text-muted-foreground">Hevy no tiene API sin Pro: exporta el CSV (Perfil → Ajustes → Exportar datos) y súbelo aquí o mándalo a {asistente()} por Telegram. Solo se añaden a Gym.md los días que aún no están; antes ves la vista previa.</p>
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex cursor-pointer items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 hover:bg-muted"><Upload className="size-4" /> {archivo || "Elegir CSV"}
          <input type="file" accept=".csv,text/csv" className="sr-only" onChange={async (e) => {
            const f = e.target.files?.[0];
            if (!f) return;
            if (f.size > 5 * 1024 * 1024) return setMsg({ ok: false, text: "Archivo de más de 5 MB" });
            setArchivo(f.name);
            setTexto(await f.text());
          }} />
        </label>
        <label className="text-xs text-muted-foreground">Desde (opcional) <Input type="date" value={desde} onChange={(e) => setDesde(e.target.value)} className="inline-flex w-auto" /></label>
        <Button size="sm" disabled={!texto || busy} onClick={() => run(() => post<Imp>("/gym/import/hevy", { texto, archivo, desde: desde || undefined }))}>Vista previa</Button>
      </div>
      {(imp.data?.telegram.length ?? 0) > 0 && (
        <div>
          <div className="text-xs text-muted-foreground">CSV de Hevy recibidos por Telegram</div>
          <ul className="mt-1 divide-y divide-border">
            {imp.data!.telegram.map((t) => (
              <li key={t.archivo} className="flex items-center justify-between gap-2 py-1.5 text-xs">
                <span className="min-w-0 truncate">{t.archivo} · {t.fecha.replace("T", " ")}{t.importado && " · ya importado"}</span>
                <Button size="xs" variant="outline" disabled={busy} onClick={() => run(() => post<Imp>("/gym/import/hevy", { telegram: t.archivo, desde: desde || undefined }))}>Vista previa</Button>
              </li>
            ))}
          </ul>
        </div>
      )}
      {prev && (
        <div className="space-y-2 rounded-lg border border-border p-3">
          <div className="font-medium">Vista previa ({prev.archivo || prev.fuente}) · {prev.resumen.entrenos} entrenos en el CSV</div>
          {prev.errores.length > 0 && <div className="text-xs text-destructive">Errores ({prev.errores.length}): {prev.errores.slice(0, 5).join("; ")}</div>}
          {prev.resumen.avisos.length > 0 && <div className="text-xs text-warning">Avisos: {prev.resumen.avisos.slice(0, 5).join("; ")}</div>}
          <div className="text-xs">Nuevos: {prev.resumen.nuevos.length || "ninguno"} · ya en Gym.md: {prev.resumen.ya_registrados.length}{prev.resumen.misma_fecha.length ? ` · segundo entreno el mismo día (no se añade): ${prev.resumen.misma_fecha.map((m) => m.fecha).join(", ")}` : ""}</div>
          {prev.resumen.nuevos.map((n) => <pre key={n.fecha} className="overflow-x-auto rounded bg-muted/50 p-2 text-[11px]">{n.bloque}</pre>)}
          <div className="flex gap-2">
            <Button size="sm" disabled={busy || !prev.resumen.nuevos.length || prev.estado !== "preview"} onClick={() => run(() => post<Imp>(`/gym/import/${prev.id}/apply`), true)}>Añadir {prev.resumen.nuevos.length} a Gym.md</Button>
            <Button size="sm" variant="ghost" onClick={() => setPrev(null)}>Cancelar</Button>
          </div>
        </div>
      )}
      {msg && <Msg {...msg} />}
      {(imp.data?.importaciones.length ?? 0) > 0 && (
        <details className="text-xs">
          <summary className="cursor-pointer py-1 text-muted-foreground">Registro de importaciones ({imp.data!.importaciones.length}) · {imp.data!.trazas} entrenos con trazabilidad de Hevy</summary>
          <ul className="mt-1 space-y-0.5 text-muted-foreground">
            {imp.data!.importaciones.map((i) => <li key={i.id}>{i.fecha.slice(0, 16).replace("T", " ")} · {i.fuente} · {i.archivo || "—"} · {i.estado}{i.resumen.aplicadas != null ? ` · ${i.resumen.aplicadas} añadidas` : ""}{i.errores.length ? ` · ${i.errores.length} errores` : ""}</li>)}
          </ul>
        </details>
      )}
    </div>
  );
}

export function HistoryTab() {
  const params = useSearchParams();
  const exercises = useApi<ExIndex[]>("/gym/exercises");
  const [desde, setDesde] = useState("");
  const [hasta, setHasta] = useState("");
  const [ejercicio, setEjercicio] = useState("");
  const [musculo, setMusculo] = useState("");
  const [tipo, setTipo] = useState("");
  const [sel, setSel] = useState<string[]>([]);
  const q = new URLSearchParams(Object.entries({ desde, hasta, ejercicio, musculo, tipo }).filter(([, v]) => v)).toString();
  const workouts = useApi<Workout[]>(`/gym/workouts${q ? `?${q}` : ""}`);
  const cmp = params.get("cmp")?.split(",");
  const tipos = [...SESIONES, ...(workouts.data?.map((w) => w.nombre) ?? [])].filter((v, i, a) => a.indexOf(v) === i);

  return (
    <div className="space-y-4">
      {cmp?.length === 2 && <CompareView a={cmp[0]} b={cmp[1]} />}
      <Card>
        <CardHeader><CardTitle>Entrenamientos</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
            <Input type="date" value={desde} onChange={(e) => setDesde(e.target.value)} aria-label="Desde" />
            <Input type="date" value={hasta} onChange={(e) => setHasta(e.target.value)} aria-label="Hasta" />
            <select value={ejercicio} onChange={(e) => setEjercicio(e.target.value)} aria-label="Ejercicio" className={selectCls}>
              <option value="">Todos los ejercicios</option>
              {exercises.data?.map((x) => <option key={x.id} value={x.id}>{x.nombre}</option>)}
            </select>
            <select value={musculo} onChange={(e) => setMusculo(e.target.value)} aria-label="Grupo muscular" className={selectCls}>
              <option value="">Todos los músculos</option>
              {Object.entries(MUSCULO).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            <select value={tipo} onChange={(e) => setTipo(e.target.value)} aria-label="Rutina" className={selectCls}>
              <option value="">Todas las sesiones</option>
              {tipos.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            Marca dos para compararlas.
            {sel.length === 2 && <Link href={`/gym/?tab=history&cmp=${[...sel].sort().join(",")}`} className="flex items-center gap-1 text-primary hover:underline"><GitCompare className="size-3.5" /> Comparar</Link>}
            {sel.length > 0 && <button type="button" className="hover:text-foreground" onClick={() => setSel([])}>Quitar selección</button>}
          </div>
          {workouts.error && <ErrorState message={workouts.error} />}
          {workouts.loading && <Loading rows={4} />}
          {workouts.data?.length === 0 && <Empty message="Ninguna sesión con esos filtros" />}
          <ul className="divide-y divide-border">
            {workouts.data?.map((w) => (
              <li key={w.id} className="flex items-center gap-2">
                <input type="checkbox" aria-label={`Seleccionar ${w.fecha} ${w.nombre}`} className="size-4 shrink-0 accent-primary"
                  checked={sel.includes(w.id)} disabled={!sel.includes(w.id) && sel.length >= 2}
                  onChange={(e) => setSel(e.target.checked ? [...sel, w.id] : sel.filter((x) => x !== w.id))} />
                <Link href={`/gym/?tab=history&w=${w.id}`} className="grid min-w-0 flex-1 grid-cols-[6.5rem_1fr_auto] items-center gap-3 py-2 text-sm hover:text-primary">
                  <span className="text-muted-foreground">{day(w.fecha)}</span>
                  <span className="truncate">{w.nombre} <span className="text-xs text-muted-foreground">· {w.ejercicios} ejercicios{w.planificada ? " · planificada" : ""}</span></span>
                  <span className="font-mono text-xs tabular-nums text-muted-foreground">{w.series} series · {kg(w.volumen)}{w.duracion_min ? ` · ${w.duracion_min} min` : ""}</span>
                </Link>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
      <Card id="importar">
        <CardHeader><CardTitle className="flex items-center gap-2">Importar de Hevy <NivelBadge n="registrado" /></CardTitle></CardHeader>
        <CardContent><Importar /></CardContent>
      </Card>
    </div>
  );
}
