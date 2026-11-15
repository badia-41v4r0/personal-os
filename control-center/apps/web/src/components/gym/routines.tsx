"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, Copy, Plus, Trash2 } from "lucide-react";
import { cn } from "cn";
import { Empty, ErrorState, Loading } from "@/components/cc/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api, ApiError, post } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { DIAS, descanso, errMsg, type ExIndex, Msg, NivelBadge, selectCls, today } from "./common";

type REx = { id?: string; nombre: string; series: number; rep_min: number; rep_max: number; descanso_s: number; metodo: string; incremento_kg?: number | null };
type Spec = { dias: Record<string, { nombre: string; ejercicios: REx[] }>; notas: string };
type Routine = {
  id: string; nombre: string; estado: string; version: number; creada_por: string; creada: string; actualizada: string; spec: Spec;
  versiones?: { version: number; autor: string; motivo: string; cambios: string[]; fecha: string; spec: Spec; resultados: { desde: string; hasta: string | null; sesiones: number; planes_cumplidos: number; cumplimiento_medio: number | null } }[];
};
type Cal = { desde: string; hasta: string; dias: { fecha: string; dia: string; prevista: string | null; estado: string; planificada_id: string | null; hechas: { id: string; nombre: string; series: number; volumen: number }[] }[];
  reprogramar: { tipo: string; sesion: string; desde: string; hasta: string | null; motivo: string }[]; rutina: { nombre: string; version: number } | null };

const iso = (d: Date) => d.toLocaleDateString("sv-SE");
const lunes = (d: Date) => { const x = new Date(d); x.setDate(x.getDate() - ((x.getDay() + 6) % 7)); return x; };
const add = (d: Date, n: number) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };
const EST: Record<string, string> = {
  hecho: "border-success/50 bg-success/10", extra: "border-success/30 bg-success/5", perdido: "border-destructive/40 bg-destructive/5",
  pendiente: "border-primary/40", pospuesto: "border-warning/50", reprogramado: "border-warning/40 border-dashed", descanso: "border-border opacity-60",
  pausa: "border-muted-foreground/40 border-dashed bg-muted/40",
};

function Calendario() {
  const [modo, setModo] = useState<"semana" | "mes">("semana");
  const [ref, setRef] = useState(() => new Date());
  const ini = modo === "semana" ? lunes(ref) : lunes(new Date(ref.getFullYear(), ref.getMonth(), 1));
  const fin = modo === "semana" ? add(ini, 6) : add(lunes(new Date(ref.getFullYear(), ref.getMonth() + 1, 0)), 6);
  const c = useApi<Cal>(`/gym/calendar?desde=${iso(ini)}&hasta=${iso(fin)}`);
  const mover = (n: number) => setRef(modo === "semana" ? add(ref, 7 * n) : new Date(ref.getFullYear(), ref.getMonth() + n, 1));
  const titulo = modo === "semana" ? `Semana del ${ini.toLocaleDateString("es-ES", { day: "numeric", month: "short" })}` : ref.toLocaleDateString("es-ES", { month: "long", year: "numeric" });
  return (
    <Card>
      <CardHeader><CardTitle>Calendario</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <Button size="icon-sm" variant="ghost" aria-label="Anterior" onClick={() => mover(-1)}><ChevronLeft /></Button>
          <span className={cn("min-w-36 text-center text-sm font-medium", modo === "mes" && "capitalize")}>{titulo}</span>
          <Button size="icon-sm" variant="ghost" aria-label="Siguiente" onClick={() => mover(1)}><ChevronRight /></Button>
          <Button size="sm" variant="ghost" onClick={() => setRef(new Date())}>Hoy</Button>
          <div className="ml-auto flex gap-1" role="group" aria-label="Vista">
            {(["semana", "mes"] as const).map((m) => <button key={m} type="button" aria-pressed={modo === m} onClick={() => setModo(m)} className={cn("min-h-7 rounded-md px-2.5 text-xs capitalize", modo === m ? "bg-muted" : "text-muted-foreground")}>{m}</button>)}
          </div>
        </div>
        {c.error && <ErrorState message={c.error} />}
        {!c.data && !c.error && <Loading rows={3} />}
        {c.data && (
          <div className={cn("grid gap-1.5", modo === "semana" ? "grid-cols-1 sm:grid-cols-7" : "grid-cols-7")}>
            {modo === "mes" && DIAS.map((d) => <div key={d} className="text-center text-[10px] text-muted-foreground">{d.slice(0, 2)}</div>)}
            {c.data.dias.map((d) => {
              const fuera = modo === "mes" && new Date(d.fecha + "T12:00").getMonth() !== ref.getMonth();
              return (
                <div key={d.fecha} className={cn("min-w-0 rounded-md border p-1.5 text-xs", EST[d.estado], fuera && "opacity-40", d.fecha === today() && "ring-1 ring-primary")}>
                  <div className="flex justify-between gap-1 text-muted-foreground"><span>{modo === "semana" ? `${d.dia.slice(0, 3)} ${d.fecha.slice(8)}` : d.fecha.slice(8)}</span>{modo === "semana" && <span>{d.estado}</span>}</div>
                  {d.hechas.length > 0 ? d.hechas.map((h) => <Link key={h.id} href={`/gym/?tab=history&w=${h.id}`} className="-my-0.5 block truncate py-1 font-medium hover:text-primary">{h.nombre}</Link>)
                    : d.planificada_id ? <Link href={`/gym/?tab=training&plan=${d.planificada_id}`} className="-my-0.5 block truncate py-1 hover:text-primary">{d.prevista}</Link>
                    : <div className="truncate">{d.prevista ?? (modo === "semana" ? "Descanso" : "")}</div>}
                  {modo === "semana" && d.hechas[0] && <div className="text-muted-foreground">{d.hechas[0].series} series</div>}
                </div>
              );
            })}
          </div>
        )}
        <p className="text-[11px] text-muted-foreground">Verde: hecho · azul: pendiente · rojo: perdido · discontinuo: reprogramado · gris discontinuo: pausa (enfermedad, lesión o vacaciones; no cuenta como perdido). {c.data?.rutina ? `Rutina: ${c.data.rutina.nombre} v${c.data.rutina.version}.` : "Rutina por defecto de Gym.md."}</p>
        {(c.data?.reprogramar.length ?? 0) > 0 && (
          <div className="rounded-lg border border-border p-2 text-xs">
            <b>Reorganizar la semana</b> <NivelBadge n="recomendacion" />
            <ul className="mt-1 space-y-0.5">{c.data!.reprogramar.map((r) => <li key={r.desde}>{r.sesion} ({r.desde.slice(5)}) → {r.hasta ? r.hasta.slice(5) : "no recuperarla"}: {r.motivo}</li>)}</ul>
            <Link href="/gym/?tab=training" className="inline-block py-1 text-primary hover:underline">Aceptarlo en Training</Link>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function Editor({ r, onSaved }: { r: Routine; onSaved: () => void }) {
  const ex = useApi<ExIndex[]>("/gym/exercises");
  const [spec, setSpec] = useState<Spec>(() => JSON.parse(JSON.stringify(r.spec?.dias ? r.spec : { dias: {}, notas: "" })));
  const [nombre, setNombre] = useState(r.nombre);
  const [motivo, setMotivo] = useState("");
  const [confirmar, setConfirmar] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const activa = r.estado === "active";
  const setDia = (k: string, v: Spec["dias"][string] | null) => setSpec((s) => {
    const dias = { ...s.dias };
    if (v) dias[k] = v; else delete dias[k];
    return { ...s, dias };
  });
  const setEj = (k: string, i: number, p: Partial<REx>) => setDia(k, { ...spec.dias[k], ejercicios: spec.dias[k].ejercicios.map((e, j) => (j === i ? { ...e, ...p } : e)) });
  const mover = (k: string, i: number, d: number) => { const l = [...spec.dias[k].ejercicios]; const [x] = l.splice(i, 1); l.splice(i + d, 0, x); setDia(k, { ...spec.dias[k], ejercicios: l }); };

  async function save() {
    try {
      await api(`/gym/routines/${r.id}`, { method: "PATCH", body: JSON.stringify({ nombre, spec, motivo, confirmar, version_base: r.version }) });
      setMsg({ ok: true, text: "Guardada (si había cambios, como versión nueva)." });
      setConfirmar(false);
      onSaved();
    } catch (e) {
      setMsg({ ok: false, text: e instanceof ApiError && e.status === 428 ? "Es la rutina activa: marca «Confirmo el cambio» y explica el motivo." : errMsg(e) });
    }
  }
  return (
    <div className="space-y-3 text-sm">
      <datalist id="gym-ej-rutina">{ex.data?.map((x) => <option key={x.id} value={x.nombre} />)}</datalist>
      <Input aria-label="Nombre de la rutina" value={nombre} onChange={(e) => setNombre(e.target.value)} />
      {DIAS.map((dn, i) => {
        const k = String(i);
        const d = spec.dias[k];
        return (
          <div key={k} className="rounded-lg border border-border p-2">
            <div className="flex flex-wrap items-center gap-2">
              <label className="flex items-center gap-1.5"><input type="checkbox" className="size-4 accent-primary" checked={!!d} onChange={(e) => setDia(k, e.target.checked ? { nombre: "", ejercicios: [] } : null)} /> {dn}</label>
              {d && <Input aria-label={`Sesión del ${dn}`} placeholder="Nombre (Push, Pull…)" value={d.nombre} onChange={(e) => setDia(k, { ...d, nombre: e.target.value })} className="h-7 w-40" />}
              {!d && <span className="text-xs text-muted-foreground">descanso</span>}
            </div>
            {d && (
              <div className="mt-2 space-y-1.5">
                {d.ejercicios.map((e, j) => (
                  <div key={j} className="grid grid-cols-[1fr_auto] gap-1.5 sm:grid-cols-[minmax(0,1fr)_repeat(4,4.5rem)_8.5rem_auto]">
                    <Input aria-label="Ejercicio" list="gym-ej-rutina" value={e.nombre} className="col-span-2 h-7 sm:col-span-1"
                      onChange={(ev) => setEj(k, j, { nombre: ev.target.value, id: ex.data?.find((x) => x.nombre === ev.target.value)?.id })} />
                    {([["series", "Series"], ["rep_min", "Mín."], ["rep_max", "Máx."], ["descanso_s", "Desc. s"]] as const).map(([f, l]) => (
                      <Input key={f} aria-label={l} title={l} inputMode="numeric" className="h-7" value={e[f]} onChange={(ev) => setEj(k, j, { [f]: Number(ev.target.value) || 0 } as Partial<REx>)} />
                    ))}
                    <select aria-label="Método" value={e.metodo} onChange={(ev) => setEj(k, j, { metodo: ev.target.value })} className={cn(selectCls, "h-7 text-xs")}>
                      <option value="top_set">Top set + back-offs</option><option value="doble_progresion">Doble progresión</option>
                    </select>
                    <div className="flex">
                      <Button size="icon-sm" variant="ghost" aria-label="Subir" disabled={j === 0} onClick={() => mover(k, j, -1)}><ArrowUp /></Button>
                      <Button size="icon-sm" variant="ghost" aria-label="Bajar" disabled={j === d.ejercicios.length - 1} onClick={() => mover(k, j, 1)}><ArrowDown /></Button>
                      <Button size="icon-sm" variant="ghost" aria-label="Quitar" onClick={() => setDia(k, { ...d, ejercicios: d.ejercicios.filter((_, x) => x !== j) })}><Trash2 /></Button>
                    </div>
                  </div>
                ))}
                <Button size="xs" variant="outline" onClick={() => setDia(k, { ...d, ejercicios: [...d.ejercicios, { nombre: "", series: 3, rep_min: 8, rep_max: 12, descanso_s: 90, metodo: "top_set" }] })}><Plus /> Ejercicio</Button>
              </div>
            )}
          </div>
        );
      })}
      <Input placeholder={activa ? "Motivo del cambio (obligatorio en la rutina activa)" : "Motivo del cambio"} aria-label="Motivo" value={motivo} onChange={(e) => setMotivo(e.target.value)} />
      {activa && <label className="flex items-center gap-2 text-xs"><input type="checkbox" className="size-4 accent-primary" checked={confirmar} onChange={(e) => setConfirmar(e.target.checked)} /> Confirmo el cambio de la rutina activa (se guarda como versión nueva)</label>}
      <Button size="sm" onClick={save} disabled={Object.values(spec.dias).some((d) => !d.nombre.trim() || d.ejercicios.some((e) => !e.nombre.trim()))}>Guardar</Button>
      {msg && <Msg {...msg} />}
    </div>
  );
}

function RoutineDetail({ id, onChanged }: { id: string; onChanged: () => void }) {
  const r = useApi<Routine>(`/gym/routines/${id}`);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  if (r.error) return <ErrorState message={r.error} />;
  if (!r.data) return <Loading rows={6} />;
  const d = r.data;
  const act = async (f: () => Promise<unknown>, ok: string) => {
    try { await f(); setMsg({ ok: true, text: ok }); r.reload(); onChanged(); } catch (e) { setMsg({ ok: false, text: errMsg(e) }); }
  };
  const estado = (e: string, confirmar = false) => act(() => api(`/gym/routines/${id}`, { method: "PATCH", body: JSON.stringify({ estado: e, confirmar, motivo: `Estado → ${e}` }) }), `Rutina ${e === "active" ? "activada" : e === "archived" ? "archivada" : "en borrador"}.`);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className={cn("rounded-md border px-1.5 py-0.5 text-[11px]", d.estado === "active" ? "border-success/40 text-success" : "text-muted-foreground")}>{d.estado === "active" ? "activa" : d.estado === "archived" ? "archivada" : "borrador"}</span>
        <span className="text-xs text-muted-foreground">v{d.version} · {d.creada_por}</span>
        <div className="ml-auto flex flex-wrap gap-2">
          {d.estado !== "active" && <Button size="sm" onClick={() => { if (window.confirm(`¿Activar «${d.nombre}»? Pasa a ser la rutina del motor y la otra activa vuelve a borrador.`)) estado("active", true); }}>Activar</Button>}
          {d.estado === "active" && <Button size="sm" variant="ghost" onClick={() => estado("draft")}>Desactivar</Button>}
          <Button size="sm" variant="outline" onClick={() => act(() => post(`/gym/routines/${id}/duplicate`), "Duplicada.")}><Copy /> Duplicar</Button>
          {d.estado !== "archived" && d.estado !== "active" && <Button size="sm" variant="ghost" onClick={() => estado("archived")}>Archivar</Button>}
        </div>
      </div>
      {msg && <Msg {...msg} />}
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {Object.entries(d.spec.dias ?? {}).sort().map(([k, v]) => (
          <div key={k} className="rounded-lg border border-border p-2 text-sm">
            <div className="font-medium">{DIAS[Number(k)]} · {v.nombre}</div>
            <ul className="mt-1 space-y-0.5 text-xs text-muted-foreground">
              {v.ejercicios.map((e, i) => <li key={i} className="flex justify-between gap-2"><span className="truncate">{e.nombre}</span><span className="shrink-0 font-mono">{e.series}×{e.rep_min}–{e.rep_max} · {descanso(e.descanso_s)}</span></li>)}
              {!v.ejercicios.length && <li>Sin ejercicios: el motor usa los habituales de esa sesión</li>}
            </ul>
          </div>
        ))}
      </div>
      <details>
        <summary className="cursor-pointer py-1 text-sm font-medium">Editar</summary>
        <div className="pt-2"><Editor key={d.version} r={d} onSaved={() => { r.reload(); onChanged(); }} /></div>
      </details>
      <div>
        <h3 className="text-sm font-medium">Versiones</h3>
        <ul className="mt-1 divide-y divide-border">
          {d.versiones?.map((v) => (
            <li key={v.version} className="space-y-0.5 py-2 text-xs">
              <div className="flex flex-wrap items-center gap-2"><b>v{v.version}</b><span className="text-muted-foreground">{v.fecha.slice(0, 10)} · {v.autor}</span>
                {v.version !== d.version && <Button size="xs" variant="ghost" onClick={() => {
                  if (!window.confirm(`¿Restaurar la v${v.version}? Se guarda como una versión nueva.`)) return;
                  act(() => post(`/gym/routines/${id}/restore/${v.version}`, { confirmar: true, motivo: `Restaurada la v${v.version}` }), `Restaurada la v${v.version}.`);
                }}>Restaurar</Button>}
              </div>
              <div>{v.motivo}</div>
              {v.cambios?.length > 0 && <div className="text-muted-foreground">Cambios: {v.cambios.join("; ")}</div>}
              <div className="text-muted-foreground">Resultados ({v.resultados.desde} → {v.resultados.hasta ?? "hoy"}): {v.resultados.sesiones} sesiones{v.resultados.cumplimiento_medio != null ? `, cumplimiento medio ${v.resultados.cumplimiento_medio} % en ${v.resultados.planes_cumplidos} planificadas` : ""}</div>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

export function RoutinesTab() {
  const params = useSearchParams();
  const router = useRouter();
  const rid = params.get("r");
  const list = useApi<Routine[]>("/gym/routines");
  const [nombre, setNombre] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const crear = async (desde_historial: boolean) => {
    try {
      const r = await post<Routine>("/gym/routines", desde_historial ? { nombre: nombre || "Mi rutina actual", desde_historial: true } : { nombre: nombre || "Rutina nueva", spec: { dias: {}, notas: "" } });
      setMsg({ ok: true, text: "Creada en borrador." });
      setNombre("");
      list.reload();
      router.push(`/gym/?tab=routines&r=${r.id}`);
    } catch (e) {
      setMsg({ ok: false, text: errMsg(e) });
    }
  };
  return (
    <div className="space-y-4">
      <Calendario />
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
        <Card>
          <CardHeader><CardTitle>Rutinas</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            {list.error && <ErrorState message={list.error} />}
            {list.data?.length === 0 && <p className="text-sm text-muted-foreground">Aún no hay rutinas en el panel: el motor usa tu rutina de Gym.md (L Leg day, M Push, X Pull, J Lower, V Upper) con los ejercicios que repites. Crea una a partir de tu historial para fijarla y versionarla.</p>}
            <ul className="divide-y divide-border">
              {list.data?.map((r) => (
                <li key={r.id}>
                  <Link href={`/gym/?tab=routines&r=${r.id}`} className={cn("flex items-center justify-between gap-2 py-2 text-sm hover:text-primary", rid === r.id && "text-primary")}>
                    <span className="truncate">{r.nombre}</span>
                    <span className="shrink-0 text-xs text-muted-foreground">{r.estado === "active" ? "activa" : r.estado === "archived" ? "archivada" : "borrador"} · v{r.version}</span>
                  </Link>
                </li>
              ))}
            </ul>
            <Input placeholder="Nombre de la rutina nueva" aria-label="Nombre de la rutina nueva" value={nombre} onChange={(e) => setNombre(e.target.value)} />
            <div className="flex flex-wrap gap-2">
              <Button size="sm" onClick={() => crear(true)}>Crear desde mi historial</Button>
              <Button size="sm" variant="outline" onClick={() => crear(false)}>Crear vacía</Button>
            </div>
            {msg && <Msg {...msg} />}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>{list.data?.find((r) => r.id === rid)?.nombre ?? "Detalle"}</CardTitle></CardHeader>
          <CardContent>{rid ? <RoutineDetail key={rid} id={rid} onChanged={list.reload} /> : <Empty message="Elige una rutina" />}</CardContent>
        </Card>
      </div>
    </div>
  );
}
