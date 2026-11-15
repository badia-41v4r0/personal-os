"use client";

import { useEffect, useState } from "react";
import { CalendarPlus, GraduationCap, Play, RefreshCw, Square, Wand2 } from "lucide-react";
import { useAct } from "@/components/cc/form";
import { Empty, ErrorState, Loading } from "@/components/cc/states";
import { Lines } from "@/components/cc/charts";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api, post } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { Bar, Chip, ESTADOS, Stat, cuentaAtras, fecha, preguntarTutor, type Entrega, type Estado, type Overview } from "./common";

type Item = { clave: string; texto: string; hecho: boolean };
type EntregaCheck = Item & { fecha: string; hora: string; atrasada: boolean };
type Tarea = { texto: string; fecha: string | null; atrasada: boolean };
type Edu = { entregas: EntregaCheck[]; bloques_hoy: Item[]; objetivos_semana: Item[]; tareas: Tarea[] };
type Timer = { activo: boolean; id?: number; label?: string; asignatura?: string; segundos?: number; desde?: string };
type Cambio = { id: number; tipo: "nuevo" | "movido" | "retirado"; titulo: string; antes: string; ahora: string; visto: boolean };
type Plan = { dias: { dia: string; entregas: Entrega[] }[] };

const HORAS = ["10:30", "12:30", "16:00"];
const mmss = (s: number) => `${String(Math.floor(s / 3600)).padStart(2, "0")}:${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;

function Check({ texto, hecho, onChange, busy, detalle, aviso }: { texto: string; hecho: boolean; onChange: (v: boolean) => void; busy: boolean; detalle?: string; aviso?: string }) {
  return (
    <li>
      <label className="flex cursor-pointer items-start gap-3 py-2.5 text-sm">
        <input type="checkbox" checked={hecho} disabled={busy} onChange={(e) => onChange(e.target.checked)} className="mt-0.5 size-[18px] shrink-0 accent-primary" />
        <span className={`min-w-0 flex-1 ${hecho ? "text-muted-foreground line-through" : ""}`}>{texto}</span>
        {(aviso || detalle) && (
          <span className="flex shrink-0 flex-col items-end gap-1">
            {detalle && <span className="text-xs text-muted-foreground tabular-nums">{detalle}</span>}
            {aviso && <Badge variant="destructive">{aviso}</Badge>}
          </span>
        )}
      </label>
    </li>
  );
}

function Cronometro({ onChange }: { onChange: () => void }) {
  const t = useApi<Timer>("/education/timer", 30000);
  const [ahora, setAhora] = useState(() => Date.now());
  const a = useAct(() => { t.reload(); onChange(); });
  useEffect(() => {
    if (!t.data?.activo) return;
    const i = setInterval(() => setAhora(Date.now()), 1000);
    return () => clearInterval(i);
  }, [t.data?.activo]);
  if (!t.data?.activo) return null;
  // `desde` es UTC sin zona: el reloj no depende de cuánto tarde en llegar la respuesta
  const seg = t.data.desde ? Math.max(0, Math.floor((ahora - Date.parse(`${t.data.desde}Z`)) / 1000)) : t.data.segundos ?? 0;
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-primary/30 bg-primary/5 px-3 py-2 text-sm">
      <span className="font-mono text-base font-semibold tabular-nums" aria-live="off">{mmss(seg)}</span>
      <span className="min-w-0 flex-1 truncate">{t.data.asignatura && <Chip code={t.data.asignatura} className="mr-2" />}{t.data.label || "Sesión de estudio"}</span>
      <Button size="sm" variant="outline" disabled={a.busy} onClick={() => a.run(() => post("/education/timer/stop"))}><Square />Terminar</Button>
      {a.ErrorBox}
    </div>
  );
}

function ComoVas({ o }: { o: Overview }) {
  const p = o.progreso, t = o.tiempo;
  const tono = p.estado === "no_cabe" ? "bad" : p.estado === "justo" ? "warn" : "primary";
  const texto = p.estado === "no_cabe" ? `Faltan ${-p.margen} bloques de hueco: el plan no cabe hasta el ${fecha(p.fin)}.` : p.estado === "justo" ? `Te sobran solo ${p.margen} bloques hasta el ${fecha(p.fin)}.` : `Te sobran ${p.margen} bloques hasta el ${fecha(p.fin)}.`;
  return (
    <Card>
      <CardHeader><CardTitle>Cómo vas</CardTitle></CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-3 gap-3">
          <Stat label="Hechos hasta hoy" value={`${p.hechos}/${p.planificados_hasta_hoy}`} hint="bloques de 2 h" />
          <Stat label="Por hacer" value={p.restantes} hint={`caben ${p.capacidad}`} />
          <Stat label="Margen" value={p.margen > 0 ? `+${p.margen}` : p.margen} hint={p.estado === "ok" ? "con holgura" : p.estado === "justo" ? "justo" : "no cabe"} />
        </div>
        <div className="space-y-1.5">
          <Bar value={p.hechos} max={p.planificados_hasta_hoy} label="Bloques hechos frente a planificados" />
          <Bar value={p.restantes} max={Math.max(p.capacidad, 1)} tone={tono} label="Carga pendiente frente a capacidad restante" />
          <p className="text-xs text-muted-foreground">{texto}</p>
          {p.avisos > 0 && <p className="text-xs text-muted-foreground">El planificador no encuentra hueco antes del límite para <strong className="text-foreground">{p.avisos}</strong> tareas{p.ejemplos_avisos[0] ? <> (por ejemplo, «{p.ejemplos_avisos[0].split(":")[0]}»)</> : null}. «Reprogramar desde hoy» las recoloca y te lo detalla.</p>}
        </div>
        {t.sesiones > 0 && t.media_min != null && (
          <p className="border-t border-border pt-3 text-xs text-muted-foreground">
            Tus {t.sesiones} sesiones cronometradas (30 días) duran de media <strong className="text-foreground">{t.media_min} min</strong> frente a los {t.plan_min} que supone el plan{t.media_min < t.plan_min * 0.75 ? ": quizá puedas meter más por bloque." : t.media_min > t.plan_min * 1.1 ? ": el plan se queda corto." : "."}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function Acciones({ reload }: { reload: () => void }) {
  const a = useAct(reload);
  const [aviso, setAviso] = useState<string | null>(null);
  const [confirmar, setConfirmar] = useState(false);
  const estudiar = () => a.run(async () => {
    const c = await api<{ bloque: { texto: string } | null; mensaje: string }>("/education/study-context");
    await preguntarTutor(c.mensaje);
    if (c.bloque) await post("/education/timer/start", { label: c.bloque.texto });
    setAviso(c.bloque ? `Cronómetro en marcha para «${c.bloque.texto}». Tu tutor ya te está contestando.` : "No hay bloques pendientes hoy. Se lo he preguntado al tutor.");
  });
  const reprogramar = () => a.run(async () => {
    const r = await post<{ avisos: string[] }>("/education/reschedule");
    setConfirmar(false);
    setAviso(r.avisos.length ? `Plan recalculado con avisos: ${r.avisos.slice(0, 2).join(" · ")}` : "Plan recalculado desde hoy con lo que has marcado.");
  });
  const calendario = () => a.run(async () => {
    const r = await post<{ creados: number; errores: string[] }>("/education/calendar-sync?dias=7");
    setAviso(r.errores.length ? `Google no ha respondido: ${r.errores[0]}` : `${r.creados} bloques nuevos en Google Calendar (7 días).`);
  });
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <Button disabled={a.busy} onClick={estudiar}><Play />Estudiar ahora</Button>
        {!confirmar ? <Button variant="outline" disabled={a.busy} onClick={() => setConfirmar(true)}><Wand2 />Reprogramar desde hoy</Button> : (
          <span className="flex items-center gap-2 rounded-lg border border-border px-2 py-1 text-sm">
            Reescribe «Plan diario» de las notas semanales.
            <Button size="sm" disabled={a.busy} onClick={reprogramar}>Sí, recalcular</Button>
            <Button size="sm" variant="ghost" onClick={() => setConfirmar(false)}>No</Button>
          </span>
        )}
        <Button variant="outline" disabled={a.busy} onClick={calendario}><CalendarPlus />Plan → Google Calendar</Button>
      </div>
      {aviso && <p role="status" className="text-sm text-muted-foreground">{aviso}</p>}
      {a.ErrorBox}
    </div>
  );
}

function CambiosCanvas({ o, reload }: { o: Overview; reload: () => void }) {
  const c = useApi<Cambio[]>(o.canvas_nuevos ? "/education/canvas" : null);
  const a = useAct(() => { c.reload(); reload(); });
  const nuevos = (c.data ?? []).filter((x) => !x.visto);
  if (!nuevos.length) return null;
  const txt = (x: Cambio) => (x.tipo === "nuevo" ? `Nuevo: ${x.titulo} (${fecha(x.ahora)})` : x.tipo === "movido" ? `${x.titulo}: ${fecha(x.antes)} → ${fecha(x.ahora)}` : `Retirado: ${x.titulo} (${fecha(x.antes)})`);
  return (
    <Card className="border-amber-500/40">
      <CardHeader className="flex-row items-center justify-between gap-2">
        <CardTitle>Canvas ha cambiado</CardTitle>
        <div className="flex gap-1.5">
          <Button size="sm" variant="outline" disabled={a.busy} onClick={() => a.run(() => post("/education/canvas/check"))}><RefreshCw />Comprobar</Button>
          <Button size="sm" variant="ghost" disabled={a.busy} onClick={() => a.run(() => post("/education/canvas/seen"))}>Marcar vistos</Button>
        </div>
      </CardHeader>
      <CardContent>
        <ul className="space-y-1 text-sm">{nuevos.slice(0, 8).map((x) => <li key={x.id}>{txt(x)}</li>)}</ul>
        <p className="mt-2 text-xs text-muted-foreground">Sale del calendario de Canvas en Google. Compruébalo en el aula antes de mover nada (pídeselo al tutor).</p>
        {a.ErrorBox}
      </CardContent>
    </Card>
  );
}

function EstadoEntrega({ e, busy, onChange }: { e: Entrega; busy: boolean; onChange: (s: Estado) => void }) {
  return (
    <select aria-label={`Estado de ${e.texto}`} value={e.estado} disabled={busy} onChange={(ev) => onChange(ev.target.value as Estado)}
      className="h-8 shrink-0 rounded-md border border-input bg-transparent px-1.5 text-xs dark:bg-input/30">
      {ESTADOS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
    </select>
  );
}

export function HoyTab({ o, reloadOverview }: { o: Overview; reloadOverview: () => void }) {
  const e = useApi<Edu>("/me/education");
  const plan = useApi<Plan>("/education/plan?dias=45");
  const [marcando, setMarcando] = useState(false);
  const [todas, setTodas] = useState(false);
  const refrescar = () => { e.reload(); plan.reload(); reloadOverview(); };
  const a = useAct(refrescar);
  const marcar = (fn: () => Promise<unknown>) => { setMarcando(true); void a.run(fn).finally(() => setMarcando(false)); };
  const uni = (clave: string, hecho: boolean) => marcar(() => post("/me/education/check", { clave, hecho }));
  const d = e.data;
  const ocupado = marcando || e.loading;
  const entregas = (plan.data?.dias ?? []).flatMap((x) => x.entregas);
  const pendientes = entregas.filter((x) => !x.hecha);
  const visibles = todas ? pendientes : pendientes.filter((x) => x.dias <= 14);
  const ocultas = pendientes.length - pendientes.filter((x) => x.dias <= 14).length;
  const atrasadas = d?.entregas.filter((x) => x.atrasada) ?? [];
  return (
    <div className="space-y-4">
      <Acciones reload={refrescar} />
      <Cronometro onChange={reloadOverview} />
      <CambiosCanvas o={o} reload={reloadOverview} />
      {e.error && <ErrorState message={e.error} />}
      {a.ErrorBox}
      <div className="grid gap-4 xl:grid-cols-2">
        <ComoVas o={o} />
        <Card>
          <CardHeader><CardTitle>Carga por semana</CardTitle></CardHeader>
          <CardContent>
            <Lines data={o.carga.filter((s) => s.actual || s.planificadas_h > 0 || s.reales_h != null).map((s) => ({ semana: fecha(s.semana), plan: s.planificadas_h, cap: s.capacidad_h, real: s.reales_h }))} x="semana" unit=" h" height={170} label="Horas por semana"
              series={[{ key: "plan", name: "Planificadas" }, { key: "cap", name: "Capacidad", dashed: true }, { key: "real", name: "Reales (cronómetro)" }]} />
            <p className="mt-1 text-xs text-muted-foreground">Una semana por encima de la capacidad es el pico que conviene ver con tiempo.</p>
          </CardContent>
        </Card>
        {e.loading && !d && <Loading rows={6} />}
        {d && (
          <>
            <Card>
              <CardHeader><CardTitle>Plan de hoy</CardTitle></CardHeader>
              <CardContent>
                {d.bloques_hoy.length === 0 && <Empty message="Nada planificado hoy." />}
                <ul className="divide-y divide-border">
                  {d.bloques_hoy.map((b, i) => <Check key={b.clave} texto={b.texto} hecho={b.hecho} detalle={HORAS[i]} busy={ocupado} onChange={(v) => uni(b.clave, v)} />)}
                </ul>
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle>Tareas de la uni</CardTitle></CardHeader>
              <CardContent>
                {d.tareas.length === 0 && <Empty message="Ninguna pendiente." />}
                <ul className="divide-y divide-border">
                  {d.tareas.map((t) => <Check key={t.texto} texto={t.texto} hecho={false} aviso={t.atrasada ? "Atrasada" : undefined} detalle={t.fecha && !t.atrasada ? fecha(t.fecha) : undefined} busy={ocupado} onChange={() => marcar(() => post("/tasks/done", { texto: t.texto }))} />)}
                </ul>
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle>Entregas</CardTitle></CardHeader>
              <CardContent>
                {atrasadas.length > 0 && (
                  <ul className="mb-2 divide-y divide-border rounded-lg border border-destructive/30 bg-destructive/5 px-3">
                    {atrasadas.map((x) => <Check key={x.clave} texto={x.texto} hecho={x.hecho} aviso="Sin marcar" detalle={`${fecha(x.fecha)} ${x.hora}`} busy={ocupado} onChange={(v) => uni(x.clave, v)} />)}
                  </ul>
                )}
                {pendientes.length === 0 && atrasadas.length === 0 && <Empty message="Sin entregas en 45 días." />}
                <ul className="divide-y divide-border">
                  {visibles.map((x) => (
                    <li key={x.clave} className="flex items-start gap-3 py-2.5 text-sm">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2"><Chip code={x.asig} /><span className="min-w-0 flex-1">{x.texto.replace(/^[^:]+:\s*/, "")}</span></div>
                        <div className={`mt-1 text-xs tabular-nums ${x.dias <= 2 ? "font-medium text-destructive" : "text-muted-foreground"}`}>{fecha(x.clave.split("|")[1])} {x.hora} · {cuentaAtras(x.dias)}</div>
                      </div>
                      <EstadoEntrega e={x} busy={ocupado} onChange={(s) => marcar(() => post("/education/entrega-estado", { clave: x.clave, estado: s }))} />
                    </li>
                  ))}
                </ul>
                {ocultas > 0 && <Button variant="ghost" size="sm" className="mt-2" onClick={() => setTodas((v) => !v)}>{todas ? "Ver solo las próximas" : `Ver las ${ocultas} siguientes`}</Button>}
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle>Objetivos de la semana</CardTitle></CardHeader>
              <CardContent>
                {d.objetivos_semana.length === 0 && <Empty message="Sin objetivos esta semana." />}
                <ul className="divide-y divide-border">
                  {d.objetivos_semana.map((x) => <Check key={x.clave} texto={x.texto} hecho={x.hecho} busy={ocupado} onChange={(v) => uni(x.clave, v)} />)}
                </ul>
              </CardContent>
            </Card>
          </>
        )}
      </div>
      <p className="flex items-center gap-1.5 text-xs text-muted-foreground"><GraduationCap className="size-3.5" />Marcar aquí cuenta igual que marcarlo en el Panel de Obsidian; «Entregada» es lo mismo que marcar la casilla.</p>
    </div>
  );
}
