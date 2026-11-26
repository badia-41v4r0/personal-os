"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { ArrowLeft, Camera, Download, Folder, FileText, Monitor, Play, Plus, RotateCw, ShieldCheck, Square, Terminal as TerminalIcon, Trash2 } from "lucide-react";
import { cn } from "cn";
import { PageHeader, usePanel } from "@/components/cc/shell";
import { StatusDot } from "@/components/cc/status";
import { Empty, ErrorState, Loading } from "@/components/cc/states";
import { MaquinasLocales } from "@/components/cc/maquinas-locales";
import { VcDesktop, VcTerminal } from "@/components/cc/vc-views";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { api, post } from "@/lib/api";
import { bytes, clock, timeAgo } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { BASE } from "@/lib/base";

type Live = { state: string; status: string; stats?: { cpu_pct: number; mem: string; mem_pct: number; pids: number } | null } | null;
type VC = { id: string; name: string; profile: "terminal" | "browser" | "desktop" | "canvas"; owner_agent: string | null; persistence: string; expires_at: string | null; internet: boolean; status: string; limits: { cpus: number; memory_mb: number; disk_mb: number }; created_by: string; created_at: string; last_activity: string; live: Live };
type Detail = VC & { disk_bytes?: number | null; events: { ts: string; type: string; actor: string; detail: Record<string, unknown> }[] };
type FileItem = { name: string; dir: boolean; size: number; mtime: number };

const PROFILE = { terminal: "Terminal", browser: "Browser", desktop: "Desktop", canvas: "Campus" };
const PERSIST: Record<string, string> = { ephemeral: "Efímero", persistent: "Persistente", ttl: "Con caducidad" };
const sel = "h-8 w-full rounded-lg border border-input bg-transparent px-2 text-sm dark:bg-input/30";

function NewVC({ onCreated }: { onCreated: (v: VC) => void }) {
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ name: "", profile: "terminal", persistence: "ephemeral", ttl_hours: 4, internet: false, cpus: 1, memory_mb: 1024, disk_mb: 2048, owner_agent: "" });
  const canvas = f.profile === "canvas";
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => setF((x) => ({ ...x, [k]: v }));
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onCreated(await post<VC>("/virtual-computers", { ...f, owner_agent: f.owner_agent.trim() || null }));
      setOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <Button size="sm" onClick={() => setOpen(true)}><Plus /> Nuevo ordenador</Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-lg">
          <form onSubmit={submit} className="space-y-4">
            <DialogHeader>
              <DialogTitle>Nuevo ordenador virtual</DialogTitle>
              <DialogDescription>Contenedor aislado: usuario sin privilegios, sin acceso a tu PC ni a tus secretos, con límites de CPU, RAM y disco.</DialogDescription>
            </DialogHeader>
            <div className="space-y-1.5"><Label htmlFor="vc-name">Nombre</Label><Input id="vc-name" required maxLength={64} value={f.name} onChange={(e) => set("name", e.target.value)} /></div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5"><Label htmlFor="vc-prof">Perfil</Label>
                <select id="vc-prof" className={sel} value={f.profile} onChange={(e) => { const p = e.target.value; set("profile", p); set("memory_mb", p === "terminal" ? 1024 : p === "canvas" ? 2048 : 1536); if (p === "canvas") { set("persistence", "persistent"); set("owner_agent", f.owner_agent || "tutor"); if (!f.name.trim()) set("name", "Campus"); } }}>
                  <option value="terminal">Terminal (Linux, Git, Python, Node)</option><option value="browser">Browser (Chromium + Playwright)</option><option value="desktop">Desktop (escritorio completo)</option><option value="canvas">Campus (navegador con tu sesión de la universidad)</option>
                </select></div>
              {canvas ? <div className="space-y-1.5"><Label htmlFor="vc-owner">Agente que lo usa</Label><Input id="vc-owner" maxLength={64} value={f.owner_agent} onChange={(e) => set("owner_agent", e.target.value)} /></div> :
              <div className="space-y-1.5"><Label htmlFor="vc-per">Persistencia</Label>
                <select id="vc-per" className={sel} value={f.persistence} onChange={(e) => set("persistence", e.target.value)}>
                  <option value="ephemeral">Efímero (se borra al pararlo)</option><option value="persistent">Persistente</option><option value="ttl">Con caducidad</option>
                </select></div>}
            </div>
            {!canvas && f.persistence === "ttl" && <div className="space-y-1.5"><Label htmlFor="vc-ttl">Caduca en (horas)</Label><Input id="vc-ttl" type="number" min={0.5} max={168} step={0.5} value={f.ttl_hours} onChange={(e) => set("ttl_hours", Number(e.target.value))} /></div>}
            <div className="grid grid-cols-3 gap-3">
              <div className="space-y-1.5"><Label htmlFor="vc-cpu">CPU</Label><select id="vc-cpu" className={sel} value={f.cpus} onChange={(e) => set("cpus", Number(e.target.value))}>{[0.5, 1, 2].map((c) => <option key={c} value={c}>{c}</option>)}</select></div>
              <div className="space-y-1.5"><Label htmlFor="vc-mem">RAM</Label><select id="vc-mem" className={sel} value={f.memory_mb} onChange={(e) => set("memory_mb", Number(e.target.value))}>{[512, 1024, 1536, 2048, 3072].map((m) => <option key={m} value={m}>{m >= 1024 ? `${m / 1024} GB` : `${m} MB`}</option>)}</select></div>
              <div className="space-y-1.5"><Label htmlFor="vc-disk">Disco</Label><select id="vc-disk" className={sel} value={f.disk_mb} onChange={(e) => set("disk_mb", Number(e.target.value))}>{[512, 2048, 5120, 10240].map((m) => <option key={m} value={m}>{m >= 1024 ? `${m / 1024} GB` : `${m} MB`}</option>)}</select></div>
            </div>
            {canvas ? (
              <p className="flex gap-2 rounded-lg bg-muted/40 p-3 text-xs text-muted-foreground"><ShieldCheck className="size-4 shrink-0 text-primary" />
                Persistente y sin red propia: sale solo por un proxy aparte que únicamente deja abrir las webs de tu campus (las que configuraste en Educación). Después de crearlo, inicia sesión desde la pestaña Escritorio; la sesión se guarda.</p>
            ) : <label className="flex items-center justify-between gap-3 rounded-lg bg-muted/40 p-3 text-sm">
              <span>Acceso a internet<span className="block text-xs text-muted-foreground">Por defecto sin red. Lo que descargue o visite son datos.</span></span>
              <Switch checked={f.internet} onCheckedChange={(v) => set("internet", v)} />
            </label>}
            {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => setOpen(false)}>Cancelar</Button>
              <Button type="submit" disabled={busy || !f.name.trim()}>{busy ? "Creando…" : "Crear"}</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}

function Files({ id }: { id: string }) {
  const [path, setPath] = useState("/home/vc/trabajo");
  const r = useApi<{ path: string; items: FileItem[] }>(`/virtual-computers/${id}/files?path=${encodeURIComponent(path)}`);
  const up = path.split("/").slice(0, -1).join("/");
  return (
    <Card><CardContent className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <span className="truncate font-mono text-xs">{path}</span>
        {path !== "/home/vc" && <Button size="xs" variant="ghost" onClick={() => setPath(up || "/home/vc")}>Subir</Button>}
      </div>
      {r.error && <ErrorState message={r.error} />}
      {r.data?.items.length === 0 && <Empty message="Carpeta vacía" />}
      <ul className="divide-y divide-border">
        {r.data?.items.map((f) => (
          <li key={f.name} className="flex items-center justify-between gap-2 py-1.5 text-sm">
            {f.dir ? <button onClick={() => setPath(`${path}/${f.name}`)} className="flex items-center gap-2 hover:text-primary"><Folder className="size-3.5" />{f.name}</button>
              : <span className="flex min-w-0 items-center gap-2"><FileText className="size-3.5 shrink-0" /><span className="truncate">{f.name}</span></span>}
            {!f.dir && (
              <span className="flex shrink-0 items-center gap-2 text-xs text-muted-foreground">{bytes(f.size)}
                <a href={`${BASE}/api/v1/virtual-computers/${id}/download?path=${encodeURIComponent(`${path}/${f.name}`)}`} className="hover:text-primary" aria-label={`Descargar ${f.name}`}><Download className="size-3.5" /></a>
              </span>
            )}
          </li>
        ))}
      </ul>
      <p className="text-[11px] text-muted-foreground">Solo se puede descargar lo que hay dentro de /home/vc (máx. 50 MB por archivo). Las descargas quedan auditadas.</p>
    </CardContent></Card>
  );
}

function DetailView({ id }: { id: string }) {
  const router = useRouter();
  const { lastEvent } = usePanel();
  const d = useApi<Detail>(`/virtual-computers/${id}`, 15000);
  const [tab, setTab] = useState<"screen" | "terminal" | "files" | "logs" | "egress" | "events">("terminal");
  const [viewOnly, setViewOnly] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const logs = useApi<{ lines: string[] }>(tab === "logs" ? `/virtual-computers/${id}/logs?lines=200` : null);
  const egress = useApi<Egress[]>(tab === "egress" ? `/virtual-computers/${id}/egress?lines=300` : null, 10000);
  useEffect(() => {
    if (d.data && d.data.profile !== "terminal") setTab((t) => (t === "terminal" ? "screen" : t));
  }, [d.data]);
  useEffect(() => {
    if (lastEvent?.type.startsWith("vc.") && lastEvent.payload.id === id) d.reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastEvent]);

  const act = async (a: "start" | "stop" | "restart") => {
    setError(null);
    try {
      const r = await post<{ status: string }>(`/virtual-computers/${id}/${a}`);
      if (r.status === "deleted") router.push("/ajustes/ordenadores/");
      else d.reload();
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };
  const remove = async () => {
    if (!window.confirm("¿Eliminar este ordenador y todo su disco? No se puede deshacer.")) return;
    try { await api(`/virtual-computers/${id}`, { method: "DELETE" }); router.push("/ajustes/ordenadores/"); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };

  if (d.error) return <ErrorState message={d.error} />;
  if (!d.data) return <Loading rows={6} />;
  const v = d.data;
  const running = v.live?.state === "running";
  const tabs = [...(v.profile !== "terminal" ? [["screen", "Escritorio"]] : []), ["terminal", "Terminal"], ["files", "Archivos"], ["logs", "Registro"], ...(v.profile === "canvas" ? [["egress", "Accesos"]] : []), ["events", "Eventos"]] as [typeof tab, string][];
  return (
    <>
      <PageHeader title={v.name} description={`${PROFILE[v.profile]} · ${PERSIST[v.persistence]}${v.expires_at ? ` hasta ${clock(v.expires_at)}` : ""} · ${v.profile === "canvas" ? "solo webs de tu campus" : v.internet ? "con internet" : "sin internet"}`}
        actions={
          <div className="flex flex-wrap gap-2">
            <Button variant="ghost" size="sm" onClick={() => router.push("/ajustes/ordenadores/")}><ArrowLeft /> Ordenadores</Button>
            {running ? <Button size="sm" variant="outline" onClick={() => act("stop")}><Square /> Detener</Button> : <Button size="sm" variant="outline" onClick={() => act("start")}><Play /> Iniciar</Button>}
            {running && <Button size="sm" variant="outline" onClick={() => act("restart")}><RotateCw /> Reiniciar</Button>}
            {running && v.profile !== "terminal" && <a href={`${BASE}/api/v1/virtual-computers/${id}/screenshot`} target="_blank" rel="noopener" className="inline-flex h-7 items-center gap-1 rounded-lg px-2.5 text-[0.8rem] ring-1 ring-border hover:bg-muted"><Camera className="size-3.5" /> Captura</a>}
            <Button size="sm" variant="destructive" onClick={remove}><Trash2 /> Eliminar</Button>
          </div>
        } />
      {error && <div className="mb-3"><ErrorState message={error} /></div>}
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        {[
          ["Estado", running ? "En marcha" : v.status === "stopped" ? "Detenido" : v.status],
          ["CPU", v.live?.stats ? `${v.live.stats.cpu_pct.toFixed(1)} % de ${v.limits.cpus}` : "—"],
          ["RAM", v.live?.stats ? v.live.stats.mem : `límite ${v.limits.memory_mb} MB`],
          ["Disco", v.disk_bytes != null ? `${bytes(v.disk_bytes)} de ${bytes(v.limits.disk_mb * 1048576)}` : `límite ${bytes(v.limits.disk_mb * 1048576)}`],
          ["Dueño", v.owner_agent ? `agente ${v.owner_agent}` : v.created_by],
          ["Actividad", timeAgo(v.last_activity)],
        ].map(([k, val]) => <Card key={k} size="sm"><CardContent><div className="text-xs text-muted-foreground">{k}</div><div className="mt-0.5 truncate text-sm font-medium">{val}</div></CardContent></Card>)}
      </div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex gap-1" role="tablist">
          {tabs.map(([k, l]) => <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)} className={cn("rounded-md px-3 py-1.5 text-sm", tab === k ? "bg-muted" : "text-muted-foreground hover:text-foreground")}>{l}</button>)}
        </div>
        {tab === "screen" && <label className="flex items-center gap-2 text-xs text-muted-foreground"><Switch checked={viewOnly} onCheckedChange={setViewOnly} /> Solo mirar</label>}
      </div>
      {!running && (tab === "screen" || tab === "terminal") ? <Empty message="El ordenador está detenido: inícialo para verlo." /> : (
        <>
          {tab === "screen" && <VcDesktop id={id} viewOnly={viewOnly} />}
          {tab === "terminal" && <VcTerminal id={id} />}
          {tab === "files" && <Files id={id} />}
          {tab === "logs" && <pre className="max-h-[60vh] overflow-auto rounded-lg bg-black/40 p-3 font-mono text-[11px] text-muted-foreground">{logs.data?.lines.join("\n") || "Sin líneas"}</pre>}
          {tab === "egress" && (
            <ul className="max-h-[60vh] divide-y divide-border overflow-auto">
              {(egress.data ?? []).slice().reverse().map((e, i) => <li key={i} className="grid grid-cols-[4.5rem_3.5rem_1fr] gap-2 py-1 font-mono text-[11px] sm:grid-cols-[4.5rem_3.5rem_12rem_1fr]">
                <span className="text-muted-foreground">{new Date(e.ts * 1000).toLocaleTimeString("es-ES")}</span>
                <span className={e.ok ? "" : "text-destructive"}>{e.m}</span>
                <span className="truncate">{e.host}</span>
                <span className="col-span-3 truncate text-muted-foreground sm:col-span-1">{e.path}{e.ok ? "" : ` · bloqueado: ${e.motivo}`}</span>
              </li>)}
              {egress.data?.length === 0 && <li className="py-2 text-sm text-muted-foreground">Sin accesos todavía.</li>}
            </ul>
          )}
          {tab === "events" && (
            <ul className="divide-y divide-border">
              {v.events.map((e, i) => <li key={i} className="grid grid-cols-[8rem_8rem_1fr] gap-2 py-1.5 text-xs"><span className="text-muted-foreground">{clock(e.ts)}</span><span>{e.type}</span><span className="truncate text-muted-foreground">{e.actor} {Object.keys(e.detail).length ? JSON.stringify(e.detail) : ""}</span></li>)}
            </ul>
          )}
        </>
      )}
    </>
  );
}

type Egress = { ts: number; m: string; host: string; path: string; ok: boolean; motivo: string };

function ListView() {
  const router = useRouter();
  const { lastEvent } = usePanel();
  const list = useApi<VC[]>("/virtual-computers", 15000);
  useEffect(() => {
    if (lastEvent?.type.startsWith("vc.")) list.reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastEvent]);
  return (
    <>
      <PageHeader title="Ordenadores virtuales" description="Entornos aislados (contenedores endurecidos, no máquinas virtuales) para ti y para los agentes."
        actions={<NewVC onCreated={(v) => router.push(`/ajustes/ordenadores/?v=${v.id}`)} />} />
      {list.error && <ErrorState message={list.error} />}
      {list.loading && <Loading rows={4} />}
      {list.data?.length === 0 && <Empty message="No hay ordenadores. Crea uno o deja que un agente con esa capacidad lo pida." />}
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {list.data?.map((v) => {
          const running = v.live?.state === "running";
          const Icon = v.profile === "terminal" ? TerminalIcon : Monitor;
          return (
            <button key={v.id} onClick={() => router.push(`/ajustes/ordenadores/?v=${v.id}`)} className="rounded-xl border border-border bg-card p-4 text-left transition-colors hover:border-primary/40">
              <div className="flex items-start justify-between gap-2">
                <span className="flex min-w-0 items-center gap-2"><Icon className="size-4 shrink-0 text-primary" /><span className="truncate font-medium">{v.name}</span></span>
                <span className="flex items-center gap-1.5 text-xs text-muted-foreground"><StatusDot level={running ? "ok" : v.status === "error" ? "down" : "unknown"} />{running ? "en marcha" : v.status === "stopped" ? "detenido" : v.status}</span>
              </div>
              <div className="mt-3 flex flex-wrap gap-1.5">
                <Badge variant="secondary">{PROFILE[v.profile]}</Badge><Badge variant="outline">{PERSIST[v.persistence]}</Badge>
                {v.internet && <Badge variant="outline">internet</Badge>}{v.owner_agent && <Badge variant="outline">agente {v.owner_agent}</Badge>}
              </div>
              <div className="mt-3 grid grid-cols-3 gap-2 text-[11px] text-muted-foreground">
                <span>CPU {v.live?.stats ? `${v.live.stats.cpu_pct.toFixed(0)} %` : "—"}</span>
                <span>RAM {v.live?.stats ? `${v.live.stats.mem_pct.toFixed(0)} %` : "—"}</span>
                <span className="text-right">{timeAgo(v.last_activity)}</span>
              </div>
            </button>
          );
        })}
      </div>
      <p className="mt-6 max-w-3xl text-xs text-muted-foreground">
        Aislamiento: usuario sin privilegios, raíz de solo lectura, sin capacidades de Linux, sin red salvo que la actives, sin acceso a tu carpeta personal, al socket de Docker ni a secretos.
        Son contenedores: comparten el kernel con el PC (menos aislamiento que una máquina virtual). Como mucho 3 en marcha a la vez.
      </p>
      <MaquinasLocales />
    </>
  );
}

function Inner() {
  const id = useSearchParams().get("v");
  return id ? <DetailView id={id} /> : <ListView />;
}

export default function VirtualComputersPage() {
  return <Suspense fallback={<Loading rows={6} />}><Inner /></Suspense>;
}
