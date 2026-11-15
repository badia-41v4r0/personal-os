"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { Check, Clock, FileCode2, ShieldAlert, X } from "lucide-react";
import { cn } from "cn";
import { PageHeader, usePanel } from "@/components/cc/shell";
import { TaskCheck } from "@/components/cc/task-check";
import { Empty, ErrorState, Loading } from "@/components/cc/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useAct } from "@/components/cc/form";
import { post } from "@/lib/api";
import { clock, timeAgo } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Unit } from "@/lib/types";

type Tarea = { texto: string; fecha: string | null; area: string; hecho: boolean; hecho_el: string | null; atrasada?: boolean };
type Tasks = { pendientes: Tarea[]; hechas: Tarea[]; areas: Record<string, string>; fuente: string };
type Prop = { nombre: string; huella: string; valida: boolean; error?: string; tipo?: string; descripcion?: string; modelo?: string; herramientas?: string[]; sustituye?: boolean; destino?: string; archivos: Record<string, string>; impacto: string; solicitado_por: string };
type Hist = { id: number; ref: string; action: string; impact: string; status: string; decided_by: string; decided_at: string; result: string };
type Approvals = { pendientes: Prop[]; error: string | null; historial: Hist[]; archivo: { nombre: string; fecha: string; estado: string; path: string }[] };
type QItem = { id: string; estado: string; path: string; meta: Record<string, string>; titulo: string; resumen: string; resultado: string; mtime: number };
type Queue = { id: string; label: string; folder: string; items: QItem[]; pendientes: number };
type Requests = { pendientes: { fecha: string; texto: string }[]; hechas: { fecha: string; texto: string; resuelta: string }[]; path: string | null };

const TABS = [["approvals", "Aprobaciones"], ["queues", "Colas"], ["tasks", "Tareas"], ["timers", "Programadas"], ["requests", "Solicitudes"]] as const;
type Tab = (typeof TABS)[number][0];
const STATUS: Record<string, string> = { done: "instalada", error: "error", rejected: "rechazada", pending: "pendiente" };
const ESTADO: Record<string, string> = { cola: "en cola", "en-curso": "en curso", hechos: "hecho" };

function usecToDate(v?: string): string | null {
  if (!v || v === "0" || v === "n/a") return null;
  if (/^\d+$/.test(v)) return new Date(Number(v) / 1000).toISOString();
  const d = new Date(v.replace(/^[A-Za-z]{3} /, "").replace(/ [A-Z]{3,4}$/, ""));
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

type ActionItem = { id: string; capability: string; level: number; actor: string; reason: string; summary: string; payload: Record<string, unknown>; hash: string; tainted: boolean; expires_at: string | null };

function PendingActions() {
  const { lastEvent } = usePanel();
  const list = useApi<ActionItem[]>("/actions?estado=pending", 60_000);
  const { reload } = list;
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (lastEvent?.type === "action.changed" || lastEvent?.type === "notification.created") {
      reload();
    }
  }, [lastEvent, reload]);
  const decide = async (a: ActionItem, aprobar: boolean) => {
    setError(null);
    try {
      await post(`/actions/${a.id}/decide`, { aprobar, hash: a.hash });
      reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      reload();
    }
  };
  if (!list.data?.length && !error) return null;
  return (
    <div className="mb-4 space-y-3">
      <h2 className="text-sm font-medium">Acciones que esperan tu decisión</h2>
      {error && <ErrorState message={error} />}
      {list.data?.map((a) => (
        <Card key={a.id}>
          <CardContent className="space-y-2">
            <div className="font-medium">{a.summary}</div>
            <p className="text-xs text-muted-foreground">Lo pide {a.actor}{a.reason ? `: ${a.reason}` : ""}</p>
            {a.tainted && <p className="text-xs text-warning">Esta ejecución ha leído contenido externo: revisa que tenga sentido.</p>}
            <pre className="max-h-40 overflow-auto rounded-lg bg-muted p-2 text-xs">{JSON.stringify(a.payload, null, 2)}</pre>
            <div className="flex gap-2">
              <Button size="sm" onClick={() => void decide(a, true)}>Aprobar</Button>
              <Button size="sm" variant="outline" onClick={() => void decide(a, false)}>Rechazar</Button>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function ApprovalsTab() {
  const { lastEvent } = usePanel();
  const a = useApi<Approvals>("/approvals", 60_000);
  const [sel, setSel] = useState<Prop | null>(null);
  const [reject, setReject] = useState<Prop | null>(null);
  const [motivo, setMotivo] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (lastEvent?.type === "approval.decided") a.reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastEvent]);

  const approve = async (p: Prop) => {
    setBusy(true);
    setError(null);
    try {
      await post(`/approvals/proposals/${p.nombre}/approve`, { hash: p.huella });
      setSel(null);
      a.reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      a.reload();
    } finally {
      setBusy(false);
    }
  };
  const doReject = async () => {
    if (!reject) return;
    setBusy(true);
    try {
      await post(`/approvals/proposals/${reject.nombre}/reject`, { motivo });
      setReject(null);
      setMotivo("");
      a.reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  if (a.error) return <ErrorState message={a.error} />;
  if (!a.data) return <Loading rows={5} />;
  return (
    <div className="grid gap-4 xl:grid-cols-3">
      <div className="space-y-3 xl:col-span-2">
        {a.data.error && <ErrorState message={`No se pudieron leer las propuestas: ${a.data.error}`} />}
        {error && <ErrorState message={error} />}
        {a.data.pendientes.length === 0 && <Card><CardContent><Empty message="No hay propuestas de Jarvis pendientes." /></CardContent></Card>}
        {a.data.pendientes.map((p) => (
          <Card key={p.nombre}>
            <CardContent className="space-y-3">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <div className="flex items-center gap-2 font-medium"><FileCode2 className="size-4 text-primary" />{p.nombre}
                    <Badge variant="outline">{p.tipo ?? "?"}</Badge>{!p.valida && <Badge variant="outline" className="border-destructive/40 text-destructive">no válida</Badge>}</div>
                  <p className="mt-1 text-sm text-muted-foreground">{p.descripcion || p.error}</p>
                </div>
                <span className="text-xs text-muted-foreground">Solicitado por {p.solicitado_por}</span>
              </div>
              <div className={cn("flex items-start gap-2 rounded-lg px-3 py-2 text-sm", p.valida ? "bg-muted/50" : "bg-destructive/10 text-destructive")}>
                <ShieldAlert className="mt-0.5 size-4 shrink-0" /> <span><b>Impacto:</b> {p.impacto}</span>
              </div>
              {!p.valida && p.error && <pre className="whitespace-pre-wrap rounded-lg bg-muted p-2 text-xs">{p.error}</pre>}
              <div className="flex flex-wrap gap-2">
                <Button size="sm" variant="outline" onClick={() => setSel(p)}>Revisar contenido ({Object.keys(p.archivos).length} archivos)</Button>
                <Button size="sm" variant="ghost" onClick={() => setReject(p)}><X /> Rechazar</Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
      <div className="space-y-4">
        <Card>
          <CardHeader><CardTitle>Historial</CardTitle></CardHeader>
          <CardContent>
            {a.data.historial.length === 0 && a.data.archivo.length === 0 && <p className="text-sm text-muted-foreground">Sin decisiones todavía.</p>}
            <ul className="space-y-2 text-xs">
              {a.data.historial.map((h) => (
                <li key={h.id}>
                  <div className="flex justify-between gap-2"><span className="truncate">{h.action}</span>
                    <span className={cn(h.status === "done" && "text-success", h.status === "error" && "text-destructive")}>{STATUS[h.status] ?? h.status}</span></div>
                  <div className="text-muted-foreground">{h.decided_by} · {clock(h.decided_at)}</div>
                  {h.status === "error" && <div className="truncate text-destructive/80" title={h.result}>{h.result}</div>}
                </li>
              ))}
            </ul>
            {a.data.archivo.length > 0 && (
              <>
                <div className="mt-3 mb-1 text-xs text-muted-foreground">Archivo de bin/aprobar</div>
                <ul className="space-y-1 text-xs">
                  {a.data.archivo.map((x) => <li key={x.path} className="flex justify-between gap-2"><span className="truncate" title={x.path}>{x.nombre}</span><span className="shrink-0 text-muted-foreground">{x.estado} · {x.fecha}</span></li>)}
                </ul>
              </>
            )}
          </CardContent>
        </Card>
      </div>

      <Dialog open={!!sel} onOpenChange={(o) => !o && setSel(null)}>
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>Revisar «{sel?.nombre}»</DialogTitle>
            <DialogDescription>Se instalará exactamente esto (huella {sel?.huella.slice(0, 12)}…). Si Jarvis lo cambia antes de aprobar, no se instalará.</DialogDescription>
          </DialogHeader>
          <div className="max-h-[50vh] space-y-3 overflow-auto">
            {sel && Object.entries(sel.archivos).map(([f, c]) => (
              <div key={f}><div className="mb-1 font-mono text-xs text-muted-foreground">{f}</div><pre className="whitespace-pre-wrap rounded-lg bg-muted p-3 font-mono text-[11px]">{c}</pre></div>
            ))}
          </div>
          <p className="text-xs text-muted-foreground">{sel?.impacto}</p>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setSel(null)}>Cancelar</Button>
            <Button onClick={() => sel && approve(sel)} disabled={busy || !sel?.valida}><Check /> {busy ? "Instalando…" : "Aprobar e instalar"}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog open={!!reject} onOpenChange={(o) => !o && setReject(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle>Rechazar «{reject?.nombre}»</DialogTitle><DialogDescription>Se archiva en Propuestas/_archivo con el motivo, que Jarvis podrá leer.</DialogDescription></DialogHeader>
          <Textarea value={motivo} onChange={(e) => setMotivo(e.target.value)} maxLength={500} placeholder="Motivo (opcional)" aria-label="Motivo" />
          <DialogFooter><Button variant="ghost" onClick={() => setReject(null)}>Cancelar</Button><Button variant="destructive" onClick={doReject} disabled={busy}>Rechazar</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function QueuesTab() {
  const q = useApi<Queue[]>("/queues", 30_000);
  const [open, setOpen] = useState<string | null>(null);
  if (q.error) return <ErrorState message={q.error} />;
  if (!q.data) return <Loading rows={5} />;
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {q.data.map((queue) => (
        <Card key={queue.id}>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle>{queue.label}</CardTitle>
            <span className="text-xs text-muted-foreground">{queue.pendientes ? `${queue.pendientes} pendientes` : "al día"}</span>
          </CardHeader>
          <CardContent>
            {queue.items.length === 0 && <p className="text-sm text-muted-foreground">Vacía.</p>}
            <ul className="divide-y divide-border">
              {queue.items.map((it) => (
                <li key={it.path} className="py-2 text-sm">
                  <button onClick={() => setOpen(open === it.path ? null : it.path)} className="flex w-full items-start justify-between gap-2 text-left">
                    <span className="min-w-0"><span className="block truncate">{it.titulo}</span>
                      <span className="text-xs text-muted-foreground">{[it.meta.repo, it.meta.tipo, it.meta.modelo].filter(Boolean).join(" · ")} {timeAgo(new Date(it.mtime * 1000).toISOString())}</span></span>
                    <Badge variant="outline" className={cn("shrink-0", it.estado !== "hechos" && "border-warning/40 text-warning")}>{ESTADO[it.estado]}</Badge>
                  </button>
                  {open === it.path && (
                    <div className="mt-2 space-y-2 text-xs">
                      {it.resumen && <p className="whitespace-pre-wrap text-muted-foreground">{it.resumen}</p>}
                      {it.resultado && <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-lg bg-muted p-2">{it.resultado}</pre>}
                      <Link href={`/memory/?p=${encodeURIComponent(it.path.endsWith(".md") ? it.path : `${it.path}/${it.meta.titulo ? "tarea.md" : "info.md"}`)}`} className="text-primary hover:underline">Abrir en Memory</Link>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      ))}
      <p className="text-xs text-muted-foreground lg:col-span-2">Las colas las crea Jarvis cuando le confirmas un encargo y se procesan solas en segundos (una tarea cada vez). Aquí se consultan; no se aprueban de nuevo.</p>
    </div>
  );
}

function NewTask({ areas, onDone }: { areas: Record<string, string>; onDone: () => void }) {
  const [texto, setTexto] = useState("");
  const [fecha, setFecha] = useState("");
  const [area, setArea] = useState("personal");
  const act = useAct(onDone);
  const crear = () => act.run(async () => {
    await post("/tasks", { texto, fecha: fecha || null, area });
    setTexto("");
    setFecha("");
  });
  return (
    <form className="mb-3 grid gap-2 sm:grid-cols-[1fr_9rem_10rem_auto]" onSubmit={(e) => { e.preventDefault(); if (texto.trim()) void crear(); }}>
      <Input value={texto} maxLength={300} onChange={(e) => setTexto(e.target.value)} placeholder="Nueva tarea…" aria-label="Nueva tarea" />
      <Input type="date" value={fecha} onChange={(e) => setFecha(e.target.value)} aria-label="Fecha (opcional)" />
      <select value={area} onChange={(e) => setArea(e.target.value)} aria-label="Área" className="h-9 rounded-md border border-input bg-background px-2 text-sm">
        {Object.entries(areas).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
      </select>
      <Button type="submit" size="sm" disabled={act.busy || !texto.trim()}>{act.busy ? "Guardando…" : "Añadir"}</Button>
      {act.error && <div className="sm:col-span-4">{act.ErrorBox}</div>}
    </form>
  );
}

function TasksTab() {
  const t = useApi<Tasks>("/tasks", 60_000);
  const [area, setArea] = useState("");
  const pend = useMemo(() => (t.data?.pendientes ?? []).filter((x) => !area || x.area === area), [t.data, area]);
  if (t.error) return <ErrorState message={t.error} />;
  if (!t.data) return <Loading rows={6} />;
  return (
    <div className="grid gap-4 xl:grid-cols-3">
      <Card className="xl:col-span-2">
        <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2">
          <CardTitle>Pendientes ({pend.length})</CardTitle>
          <div className="flex flex-wrap gap-1">
            {[["", "Todas"], ...Object.entries(t.data.areas)].map(([k, v]) => (
              <button key={k} onClick={() => setArea(k)} className={cn("rounded-full px-3 py-1.5 text-xs ring-1 ring-border lg:px-2.5 lg:py-0.5", area === k && "bg-primary/15 text-primary ring-primary/30")}>{v}</button>
            ))}
          </div>
        </CardHeader>
        <CardContent>
          <NewTask areas={t.data.areas} onDone={t.reload} />
          <ul className="divide-y divide-border">
            {pend.map((x, i) => (
              <li key={`${x.texto}-${i}`} className="flex items-start justify-between gap-3 py-2 text-sm">
                <span className="flex min-w-0 items-start gap-2.5"><TaskCheck texto={x.texto} onDone={t.reload} className="mt-0.5" /><span className={cn(x.atrasada && "text-warning")}>{x.texto}</span></span>
                <span className="flex shrink-0 items-center gap-2">
                  <Badge variant="outline" className="h-5 text-[10px] font-normal">{t.data!.areas[x.area] ?? x.area}</Badge>
                  <span className={cn("w-12 text-right text-xs", x.atrasada ? "text-warning" : "text-muted-foreground")}>{x.fecha ? x.fecha.slice(5) : "—"}</span>
                </span>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-muted-foreground">Las tareas viven en la base de datos del panel. <code className="font-mono">Tareas.md</code> es una copia: en Obsidian solo se acepta marcar casillas; lo demás se descarta. Al marcar una tarea también se marca en el Panel de Obsidian.</p>
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Hechas recientemente</CardTitle></CardHeader>
        <CardContent><ul className="space-y-1.5 text-sm">
          {t.data.hechas.slice(0, 15).map((x, i) => <li key={`${x.texto}-${i}`} className="flex items-start justify-between gap-2 text-muted-foreground"><span className="line-through decoration-muted-foreground/40">{x.texto}</span><span className="flex shrink-0 items-center gap-1 text-xs">{x.hecho_el?.slice(5) ?? ""}<TaskCheck texto={x.texto} hecho onDone={t.reload} /></span></li>)}
        </ul></CardContent>
      </Card>
    </div>
  );
}

function TimersTab() {
  const s = useApi<Unit[]>("/system/services", 60_000);
  if (s.error) return <ErrorState message={s.error} />;
  if (!s.data) return <Loading rows={6} />;
  const timers = s.data.filter((u) => u.Id.endsWith(".timer")).map((u) => ({ ...u, next: usecToDate(u.NextElapseUSecRealtime), last: usecToDate(u.LastTriggerUSec) }))
    .sort((x, y) => (x.next ?? "z").localeCompare(y.next ?? "z"));
  const paths = s.data.filter((u) => u.Id.endsWith(".path"));
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader><CardTitle className="flex items-center gap-2"><Clock className="size-4" /> Temporizadores</CardTitle></CardHeader>
        <CardContent><ul className="divide-y divide-border">
          {timers.map((u) => (
            <li key={u.Id} className="py-2 text-sm">
              <div className="flex justify-between gap-2"><span className="truncate">{u.Description.replace(/^Jarvis: /, "")}</span><span className="shrink-0 text-xs">{u.next ? clock(u.next) : "—"}</span></div>
              <div className="flex justify-between gap-2 text-xs text-muted-foreground"><span className="font-mono">{u.Id}</span><span>última: {u.last ? timeAgo(u.last) : "—"}</span></div>
            </li>
          ))}
        </ul></CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Vigilantes de colas</CardTitle></CardHeader>
        <CardContent><ul className="divide-y divide-border">
          {paths.map((u) => <li key={u.Id} className="flex justify-between gap-2 py-2 text-sm"><span className="truncate">{u.Description.replace(/^Jarvis: /, "")}</span><span className="text-xs text-muted-foreground">{u.SubState}</span></li>)}
        </ul>
        <p className="mt-2 text-xs text-muted-foreground">Logs y estado detallado en Monitor.</p></CardContent>
      </Card>
    </div>
  );
}

function RequestsTab() {
  const r = useApi<Requests>("/requests");
  if (r.error) return <ErrorState message={r.error} />;
  if (!r.data) return <Loading rows={4} />;
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card className="lg:col-span-2">
        <CardHeader><CardTitle>Pendientes ({r.data.pendientes.length})</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          {r.data.pendientes.map((x, i) => <div key={i} className="rounded-lg bg-muted/40 p-3 text-sm"><div className="mb-1 text-xs text-muted-foreground">{x.fecha} · Jarvis</div>{x.texto}</div>)}
          <p className="text-xs text-muted-foreground">Son cosas que Jarvis no puede resolverse solo (permisos, scripts, cuentas). Se hacen en una sesión de Claude Code en el PC; al terminar se marcan con ✅ en {r.data.path && <Link href={`/memory/?p=${encodeURIComponent(r.data.path)}`} className="text-primary hover:underline">solicitudes.md</Link>}.</p>
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Resueltas</CardTitle></CardHeader>
        <CardContent><ul className="space-y-2 text-xs text-muted-foreground">{r.data.hechas.map((x, i) => <li key={i}><span className="text-success">✅</span> {x.texto.slice(0, 120)}… <span className="block">{x.resuelta}</span></li>)}</ul></CardContent>
      </Card>
    </div>
  );
}

export default function TasksPage() {
  const [tab, setTab] = useState<Tab>("approvals");
  useEffect(() => {
    const t = new URLSearchParams(window.location.search).get("t") as Tab | null;
    if (t && TABS.some(([k]) => k === t)) setTab(t);
  }, []);
  return (
    <>
      <PageHeader title="Tasks & Approvals" description="Aprobaciones de Jarvis, colas de trabajo, tareas, tareas programadas y solicitudes de permisos." />
      <div className="mb-4 flex flex-wrap gap-1" role="tablist">
        {TABS.map(([k, l]) => <button key={k} role="tab" aria-selected={tab === k} onClick={() => { setTab(k); window.history.replaceState(null, "", `/tasks/?t=${k}`); }} className={cn("rounded-md px-3 py-1.5 text-sm", tab === k ? "bg-muted" : "text-muted-foreground hover:text-foreground")}>{l}</button>)}
      </div>
      {tab === "approvals" && <><PendingActions /><ApprovalsTab /></>}
      {tab === "queues" && <QueuesTab />}
      {tab === "tasks" && <TasksTab />}
      {tab === "timers" && <TimersTab />}
      {tab === "requests" && <RequestsTab />}
    </>
  );
}
