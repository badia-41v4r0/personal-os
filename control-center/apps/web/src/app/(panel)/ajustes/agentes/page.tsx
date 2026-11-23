"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { ArrowLeft, Bot, Copy, Download, History, Play, Plus, Power, PowerOff, Save, ShieldAlert, Trash2 } from "lucide-react";
import { cn } from "cn";
import { PageHeader } from "@/components/cc/shell";
import { Empty, ErrorState, Loading } from "@/components/cc/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { api, post } from "@/lib/api";
import { clock, timeAgo } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { asistente } from "@/lib/asistente";

type Spec = { name: string; target: "jarvis" | "panel"; description: string; objective: string; specialty: string; instructions: string; restrictions: string; level: "read" | "propose" | "execute"; model: "sonnet" | "opus" | "inherit"; internet: boolean; vault: boolean; virtual_computer: boolean; subagents?: boolean };
type Agent = { id: string; name: string; description: string; origin: "repo" | "panel"; status: "draft" | "active" | "inactive"; target: "jarvis" | "panel"; level: string; model: string; specialty: string; internet: boolean; vault: boolean; virtual_computer: boolean; subagents?: boolean; version: number; tools: string[]; workdir: string; runs: number; last_run: string | null; updated_at: string; file: string | null };
type AgentFull = Agent & { spec: Spec; rendered: string; apply_note: string };
type Version = { version: number; author: string; note: string; created_at: string; rendered: string };
type Run = { id: string; session_id: string | null; status: string; created_at: string; ended_at: string | null; tools_used: string[]; error: string; usage: Record<string, number | null> };
type Confirm = { needs_confirm: true; file: string; rendered?: string; note: string };

const EMPTY: Spec = { name: "", target: "panel", description: "", objective: "", specialty: "", instructions: "", restrictions: "", level: "read", model: "sonnet", internet: false, vault: false, virtual_computer: false, subagents: false };
const STATUS: Record<string, { label: string; cls: string }> = {
  active: { label: "Activo", cls: "border-success/40 text-success" }, draft: { label: "Borrador", cls: "border-warning/40 text-warning" }, inactive: { label: "Inactivo", cls: "text-muted-foreground" },
};
const LEVEL: Record<string, string> = { read: "Read", propose: "Propose", execute: "Execute" };
const RUN: Record<string, string> = { queued: "en cola", running: "en curso", done: "hecha", error: "error", interrupted: "interrumpida" };
const sel = "h-8 w-full rounded-lg border border-input bg-transparent px-2 text-sm dark:bg-input/30";

function Editor({ initial, isNew, baseVersion, onSaved }: { initial: Spec; isNew: boolean; baseVersion?: number; onSaved: (a: AgentFull) => void }) {
  const [s, setS] = useState<Spec>(initial);
  const [preview, setPreview] = useState<{ ok: boolean; errors: string[]; rendered: string; tools: string[]; system_prompt: string | null } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = <K extends keyof Spec>(k: K, v: Spec[K]) => setS((x) => ({ ...x, [k]: v }));
  const dirty = JSON.stringify(s) !== JSON.stringify(initial);

  useEffect(() => {
    const t = setTimeout(() => {
      if (s.description.length < 10 || s.instructions.length < 10 || s.name.length < 2) {
        setPreview(null);
        return;
      }
      post<typeof preview>("/agents/validate", { spec: s }).then(setPreview).catch(() => {});
    }, 400);
    return () => clearTimeout(t);
  }, [s]);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const a = isNew ? await post<AgentFull>("/agents", { spec: s }) : await api<AgentFull>(`/agents/${s.name}`, { method: "PATCH", body: JSON.stringify({ spec: s, base_version: baseVersion }) });
      onSaved(a);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Card>
        <CardContent className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5"><Label htmlFor="a-name">Nombre</Label><Input id="a-name" value={s.name} disabled={!isNew} onChange={(e) => set("name", e.target.value.toLowerCase())} placeholder="analista-gym" /></div>
            <div className="space-y-1.5"><Label htmlFor="a-target">Tipo</Label>
              <select id="a-target" className={sel} value={s.target} disabled={!isNew} onChange={(e) => set("target", e.target.value as Spec["target"])}>
                <option value="panel">Agente del panel (lanza conversaciones)</option><option value="jarvis">Subagente de {asistente()}</option>
              </select></div>
          </div>
          <div className="space-y-1.5"><Label htmlFor="a-desc">Descripción <span className="text-xs text-muted-foreground">(cuándo usarlo)</span></Label><Textarea id="a-desc" rows={2} value={s.description} onChange={(e) => set("description", e.target.value)} /></div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5"><Label htmlFor="a-obj">Objetivo</Label><Input id="a-obj" value={s.objective} onChange={(e) => set("objective", e.target.value)} /></div>
            <div className="space-y-1.5"><Label htmlFor="a-spec">Especialidad</Label><Input id="a-spec" value={s.specialty} onChange={(e) => set("specialty", e.target.value)} placeholder="gym, uni, empresa…" /></div>
          </div>
          <div className="space-y-1.5"><Label htmlFor="a-inst">Instrucciones principales</Label><Textarea id="a-inst" rows={10} className="font-mono text-xs" value={s.instructions} onChange={(e) => set("instructions", e.target.value)} /></div>
          <div className="space-y-1.5"><Label htmlFor="a-res">Restricciones</Label><Textarea id="a-res" rows={3} value={s.restrictions} onChange={(e) => set("restrictions", e.target.value)} placeholder="Qué no debe hacer nunca" /></div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5"><Label htmlFor="a-level">Capacidad</Label>
              <select id="a-level" className={sel} value={s.level} onChange={(e) => set("level", e.target.value as Spec["level"])}>
                <option value="read">Read: leer y buscar</option><option value="propose">Propose: además escribir (borradores, su carpeta)</option><option value="execute" disabled={!s.virtual_computer || s.target === "jarvis"}>Execute: comandos en su ordenador virtual</option>
              </select></div>
            <div className="space-y-1.5"><Label htmlFor="a-model">Modelo</Label>
              <select id="a-model" className={sel} value={s.model} onChange={(e) => set("model", e.target.value as Spec["model"])}>
                <option value="sonnet">Sonnet</option><option value="opus">Opus</option><option value="inherit">El de {asistente()}</option>
              </select></div>
          </div>
          <div className="space-y-2 rounded-lg bg-muted/40 p-3 text-sm">
            <label className="flex items-center justify-between gap-3">Acceso a internet<Switch checked={s.internet} onCheckedChange={(v) => set("internet", v)} /></label>
            <label className="flex items-center justify-between gap-3">Memoria: leer la vault (solo lectura)<Switch checked={s.vault || s.target === "jarvis"} disabled={s.target === "jarvis"} onCheckedChange={(v) => set("vault", v)} /></label>
            <label className="flex items-center justify-between gap-3">Puede lanzar subagentes <span className="ml-auto mr-2 text-[11px] text-muted-foreground">con sus mismos permisos</span><Switch checked={!!s.subagents} disabled={s.target === "jarvis"} onCheckedChange={(v) => set("subagents", v)} /></label>
            <label className="flex items-center justify-between gap-3">Puede pedir su ordenador virtual<Switch checked={s.virtual_computer} disabled={s.target === "jarvis"} onCheckedChange={(v) => { set("virtual_computer", v); if (!v && s.level === "execute") set("level", "propose"); }} /></label>
            {s.target === "jarvis" && <p className="text-xs text-muted-foreground">Un subagente de {asistente()} ve lo mismo que {asistente()} (vault, sin internet) y nunca más: sus permisos los limita la configuración de {asistente()}.</p>}
          </div>
          {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
          <div className="flex justify-end gap-2">
            <Button onClick={save} disabled={busy || !dirty || (preview !== null && !preview.ok)}><Save /> {busy ? "Guardando…" : isNew ? "Guardar borrador" : "Guardar versión nueva"}</Button>
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Vista previa</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          {!preview && <p className="text-sm text-muted-foreground">Rellena nombre, descripción e instrucciones para ver el archivo resultante.</p>}
          {preview && !preview.ok && (
            <ul className="space-y-1 rounded-lg bg-destructive/10 p-3 text-sm text-destructive">{preview.errors.map((e) => <li key={e}>• {e}</li>)}</ul>
          )}
          {preview && (
            <>
              <div className="flex flex-wrap gap-1">{preview.tools.map((t) => <Badge key={t} variant="outline" className="font-mono text-[10px]">{t}</Badge>)}</div>
              <div className="text-xs text-muted-foreground">{s.target === "jarvis" ? `Se escribirá en agent/.claude/agents/${s.name}.md al activarlo:` : "Archivo en formato Claude Code (exportable):"}</div>
              <pre className="max-h-[32rem] overflow-auto rounded-lg bg-muted p-3 font-mono text-[11px] whitespace-pre-wrap">{preview.rendered}</pre>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function ConfirmDialog({ c, onConfirm, onClose }: { c: Confirm | null; onConfirm: () => void; onClose: () => void }) {
  return (
    <Dialog open={!!c} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><ShieldAlert className="size-4 text-warning" /> Cambio en la configuración de {asistente()}</DialogTitle>
          <DialogDescription>{c?.note} Archivo: <code className="font-mono">{c?.file}</code></DialogDescription>
        </DialogHeader>
        {c?.rendered && <pre className="max-h-80 overflow-auto rounded-lg bg-muted p-3 font-mono text-[11px] whitespace-pre-wrap">{c.rendered}</pre>}
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>Cancelar</Button>
          <Button onClick={onConfirm}>Confirmar</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Detail({ id }: { id: string }) {
  const router = useRouter();
  const [tab, setTab] = useState<"config" | "versions" | "runs">("config");
  const a = useApi<AgentFull>(`/agents/${id}`);
  const versions = useApi<Version[]>(tab === "versions" ? `/agents/${id}/versions` : null);
  const runs = useApi<Run[]>(`/agents/runs?agent_id=${id}&limit=50`);
  const [confirm, setConfirm] = useState<{ c: Confirm; action: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showVersion, setShowVersion] = useState<Version | null>(null);

  const act = async (action: "activate" | "deactivate", confirmed = false) => {
    setError(null);
    try {
      const r = await post<AgentFull | Confirm>(`/agents/${id}/${action}`, { confirm: confirmed });
      if ("needs_confirm" in r) setConfirm({ c: r, action });
      else { setConfirm(null); a.reload(); }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };
  const run = async (fn: () => Promise<unknown>) => {
    setError(null);
    try { await fn(); } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };

  if (a.error) return <ErrorState message={a.error} />;
  if (!a.data) return <Loading rows={8} />;
  const d = a.data;
  const errors = (runs.data ?? []).filter((r) => r.status === "error");
  const toolCount = new Map<string, number>();
  (runs.data ?? []).forEach((r) => r.tools_used.forEach((t) => toolCount.set(t, (toolCount.get(t) ?? 0) + 1)));
  const cost = (runs.data ?? []).reduce((s, r) => s + (Number(r.usage?.cost_usd) || 0), 0);

  return (
    <>
      <PageHeader
        title={d.name}
        description={d.description}
        actions={
          <div className="flex flex-wrap gap-2">
            <Button variant="ghost" size="sm" onClick={() => router.push("/ajustes/agentes/")}><ArrowLeft /> Agentes</Button>
            {d.target === "panel" && d.status === "active" && (
              <Button size="sm" onClick={() => run(async () => { const s = await post<{ id: string }>(`/agents/${id}/sessions`, {}); router.push(`/conversaciones/?s=${s.id}`); })}><Play /> Iniciar conversación</Button>
            )}
            {d.status !== "active" ? <Button size="sm" variant="outline" onClick={() => act("activate")}><Power /> Activar</Button>
              : <Button size="sm" variant="outline" onClick={() => act("deactivate")}><PowerOff /> Desactivar</Button>}
            <Button size="sm" variant="outline" onClick={() => { const n = prompt("Nombre de la copia (minúsculas y guiones)"); if (n) run(async () => { await post(`/agents/${id}/duplicate`, { name: n }); router.push(`/ajustes/agentes/?a=${n}`); }); }}><Copy /> Duplicar</Button>
            <a href={`/api/v1/agents/${id}/export`} className="inline-flex h-7 items-center gap-1 rounded-lg px-2.5 text-[0.8rem] ring-1 ring-border hover:bg-muted"><Download className="size-3.5" /> Exportar</a>
            {d.origin === "panel" && d.status !== "active" && (
              <Button size="sm" variant="destructive" onClick={() => confirm_delete(id, () => router.push("/ajustes/agentes/"), setError)}><Trash2 /> Eliminar</Button>
            )}
          </div>
        }
      />
      {error && <div className="mb-4"><ErrorState message={error} /></div>}
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
        {[
          ["Estado", STATUS[d.status].label], ["Tipo", d.target === "jarvis" ? `Subagente de ${asistente()}` : "Agente del panel"],
          ["Capacidad", LEVEL[d.level] ?? d.level], ["Modelo", d.model], ["Ejecuciones", String(d.runs)], ["Última", d.last_run ? timeAgo(d.last_run) : "—"],
        ].map(([k, v]) => (
          <Card key={k} size="sm"><CardContent><div className="text-xs text-muted-foreground">{k}</div><div className="mt-0.5 truncate text-sm font-medium">{v}</div></CardContent></Card>
        ))}
      </div>
      <p className="mb-4 text-xs text-muted-foreground">{d.apply_note} Versión {d.version}. Origen: {d.origin === "repo" ? "importado de agent/.claude/agents" : "creado en el panel"}. Carpeta: {d.workdir}. Ordenador virtual: {d.virtual_computer ? "lo pide cuando lo necesita (sin red, 2 h)" : "no"}.</p>
      <div className="mb-4 flex gap-1" role="tablist">
        {([["config", "Configuración"], ["versions", "Versiones"], ["runs", `Ejecuciones (${runs.data?.length ?? 0})`]] as const).map(([k, l]) => (
          <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)} className={cn("rounded-md px-3 py-1.5 text-sm", tab === k ? "bg-muted text-foreground" : "text-muted-foreground hover:text-foreground")}>{l}</button>
        ))}
      </div>
      {tab === "config" && <Editor key={d.version} initial={d.spec} isNew={false} baseVersion={d.version} onSaved={() => a.reload()} />}
      {tab === "versions" && (
        <div className="grid gap-4 lg:grid-cols-[18rem_1fr]">
          <Card><CardContent>
            {versions.loading && <Loading rows={3} />}
            <ul className="divide-y divide-border">
              {versions.data?.map((v) => (
                <li key={v.version} className="flex items-center justify-between gap-2 py-2 text-sm">
                  <button onClick={() => setShowVersion(v)} className={cn("min-w-0 text-left hover:text-primary", showVersion?.version === v.version && "text-primary")}>
                    <div>v{v.version} · {v.note}</div><div className="text-xs text-muted-foreground">{v.author} · {clock(v.created_at)}</div>
                  </button>
                  {v.version !== d.version && <Button size="xs" variant="outline" onClick={() => run(async () => { await post(`/agents/${id}/restore`, { version: v.version, base_version: d.version }); a.reload(); versions.reload(); })}><History /> Restaurar</Button>}
                </li>
              ))}
            </ul>
          </CardContent></Card>
          <Card><CardContent>
            {showVersion ? <pre className="max-h-[36rem] overflow-auto font-mono text-[11px] whitespace-pre-wrap">{showVersion.rendered}</pre> : <Empty message="Elige una versión para verla" />}
          </CardContent></Card>
        </div>
      )}
      {tab === "runs" && (
        <div className="grid gap-4 lg:grid-cols-3">
          <Card className="lg:col-span-2"><CardContent>
            {runs.data?.length === 0 && <Empty message={d.target === "jarvis" ? `Los subagentes de ${asistente()} se ejecutan dentro de su sesión: sus usos se ven en el Chat (herramienta Agent).` : "Aún no hay ejecuciones."} />}
            <ul className="divide-y divide-border">
              {runs.data?.map((r) => (
                <li key={r.id} className="grid gap-1 py-2 text-sm md:grid-cols-[7rem_1fr_auto]">
                  <span className="text-xs text-muted-foreground">{clock(r.created_at)}</span>
                  <span className="min-w-0">
                    {r.session_id && <Link href={`/conversaciones/?s=${r.session_id}`} className="font-mono text-xs hover:text-primary">{r.id.slice(0, 8)}</Link>}
                    {r.tools_used.length > 0 && <span className="ml-2 text-xs text-muted-foreground">{r.tools_used.join(", ")}</span>}
                    {r.error && <span className="block truncate text-xs text-destructive" title={r.error}>{r.error}</span>}
                  </span>
                  <span className={cn("text-xs", r.status === "done" && "text-success", r.status === "error" && "text-destructive")}>{RUN[r.status] ?? r.status}</span>
                </li>
              ))}
            </ul>
          </CardContent></Card>
          <Card><CardHeader><CardTitle>Resumen</CardTitle></CardHeader><CardContent className="space-y-2 text-sm">
            <div className="flex justify-between"><span className="text-muted-foreground">Errores</span><span>{errors.length}</span></div>
            <div className="flex justify-between"><span className="text-muted-foreground">Coste equivalente API</span><span>{cost ? `${cost.toFixed(2)} $` : "—"}</span></div>
            <div className="pt-2 text-xs text-muted-foreground">Herramientas usadas</div>
            {[...toolCount.entries()].map(([t, n]) => <div key={t} className="flex justify-between text-xs"><span className="font-mono">{t}</span><span>{n}</span></div>)}
            <p className="pt-2 text-[11px] text-muted-foreground">El coste es orientativo: con la suscripción no se paga por uso, pero consume del límite.</p>
          </CardContent></Card>
        </div>
      )}
      <ConfirmDialog c={confirm?.c ?? null} onClose={() => setConfirm(null)} onConfirm={() => confirm && act(confirm.action as "activate" | "deactivate", true)} />
    </>
  );
}

async function confirm_delete(id: string, done: () => void, setError: (e: string) => void) {
  if (!window.confirm(`¿Eliminar el agente «${id}»? Sus versiones se borran; las conversaciones se conservan.`)) return;
  try {
    await api(`/agents/${id}`, { method: "DELETE" });
    done();
  } catch (e) {
    setError(e instanceof Error ? e.message : String(e));
  }
}

function List() {
  const router = useRouter();
  const agents = useApi<Agent[]>("/agents");
  const [q, setQ] = useState("");
  const list = useMemo(() => (agents.data ?? []).filter((a) => !q || `${a.name} ${a.description} ${a.specialty}`.toLowerCase().includes(q.toLowerCase())), [agents.data, q]);
  return (
    <>
      <PageHeader title="Agentes" description="Definiciones permanentes. Las conversaciones están en Chat y cada respuesta es una ejecución."
        actions={<Button size="sm" onClick={() => router.push("/ajustes/agentes/?new=1")}><Plus /> Nuevo agente</Button>} />
      <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Buscar agentes" className="mb-4 max-w-sm" aria-label="Buscar agentes" />
      {agents.error && <ErrorState message={agents.error} />}
      {agents.loading && <Loading rows={4} />}
      {agents.data && list.length === 0 && <Empty message="Ningún agente" />}
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {list.map((a) => (
          <Link key={a.id} href={`/ajustes/agentes/?a=${a.id}`} className="group rounded-xl border border-border bg-card p-4 transition-colors hover:border-primary/40">
            <div className="flex items-start justify-between gap-2">
              <div className="flex min-w-0 items-center gap-2"><Bot className="size-4 shrink-0 text-primary" /><span className="truncate font-medium">{a.name}</span></div>
              <Badge variant="outline" className={STATUS[a.status].cls}>{STATUS[a.status].label}</Badge>
            </div>
            <p className="mt-2 line-clamp-2 text-xs text-muted-foreground">{a.description}</p>
            <div className="mt-3 flex flex-wrap gap-1.5 text-[11px]">
              <Badge variant="secondary">{a.target === "jarvis" ? `Subagente de ${asistente()}` : "Panel"}</Badge>
              <Badge variant="outline">{LEVEL[a.level] ?? a.level}</Badge>
              <Badge variant="outline">{a.model}</Badge>
              {a.internet && <Badge variant="outline">internet</Badge>}
              {a.virtual_computer && <Badge variant="outline">ordenador</Badge>}
              {a.subagents && <Badge variant="outline">subagentes</Badge>}
              {a.origin === "repo" && <Badge variant="outline">repo</Badge>}
            </div>
            <div className="mt-3 flex justify-between text-[11px] text-muted-foreground"><span>{a.runs} ejecuciones</span><span>{a.last_run ? `última ${timeAgo(a.last_run)}` : `v${a.version}`}</span></div>
          </Link>
        ))}
      </div>
    </>
  );
}

function AgentsInner() {
  const params = useSearchParams();
  const router = useRouter();
  const id = params.get("a");
  if (params.get("new")) {
    return (
      <>
        <PageHeader title="Nuevo agente" description="Nace como borrador y sin ejecutar comandos. Actívalo cuando lo hayas revisado."
          actions={<Button variant="ghost" size="sm" onClick={() => router.push("/ajustes/agentes/")}><ArrowLeft /> Agentes</Button>} />
        <Editor initial={EMPTY} isNew onSaved={(a) => router.push(`/ajustes/agentes/?a=${a.id}`)} />
      </>
    );
  }
  return id ? <Detail id={id} /> : <List />;
}

export default function AgentsPage() {
  return <Suspense fallback={<Loading rows={6} />}><AgentsInner /></Suspense>;
}
