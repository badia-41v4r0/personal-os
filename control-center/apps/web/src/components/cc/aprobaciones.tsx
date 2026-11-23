"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Check, FileCode2, ShieldAlert, X } from "lucide-react";
import { cn } from "cn";
import { usePanel } from "@/components/cc/shell";
import { Empty, ErrorState, Loading } from "@/components/cc/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { post } from "@/lib/api";
import { clock } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { asistente } from "@/lib/asistente";

// Lo que espera tu decisión: acciones de los agentes, propuestas de skills y subagentes, y solicitudes de permisos.

type Prop = { nombre: string; huella: string; valida: boolean; error?: string; tipo?: string; descripcion?: string; modelo?: string; herramientas?: string[]; sustituye?: boolean; destino?: string; archivos: Record<string, string>; impacto: string; solicitado_por: string };
type Hist = { id: number; ref: string; action: string; impact: string; status: string; decided_by: string; decided_at: string; result: string };
type Approvals = { pendientes: Prop[]; error: string | null; historial: Hist[]; archivo: { nombre: string; fecha: string; estado: string; path: string }[] };
type Requests = { pendientes: { fecha: string; texto: string }[]; hechas: { fecha: string; texto: string; resuelta: string }[]; path: string | null };

const STATUS: Record<string, string> = { done: "instalada", error: "error", rejected: "rechazada", pending: "pendiente" };

type ActionItem = { id: string; capability: string; level: number; actor: string; reason: string; summary: string; payload: Record<string, unknown>; hash: string; tainted: boolean; expires_at: string | null };

export function PendingActions() {
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
            <div className="grid grid-cols-[1fr_1.4fr] gap-2 sm:flex">
              <Button size="sm" variant="outline" className="h-10 sm:order-2 sm:h-8" onClick={() => void decide(a, false)}>Rechazar</Button>
              <Button size="sm" className="h-10 sm:order-1 sm:h-8" onClick={() => void decide(a, true)}>Aprobar</Button>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

export function Propuestas() {
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
        {a.data.pendientes.length === 0 && <Card><CardContent><Empty message={`Nada espera tu decisión.`} /></CardContent></Card>}
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
            <DialogDescription>Se instalará exactamente esto (huella {sel?.huella.slice(0, 12)}…). Si {asistente()} lo cambia antes de aprobar, no se instalará.</DialogDescription>
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
          <DialogHeader><DialogTitle>Rechazar «{reject?.nombre}»</DialogTitle><DialogDescription>Se archiva en Propuestas/_archivo con el motivo, que {asistente()} podrá leer.</DialogDescription></DialogHeader>
          <Textarea value={motivo} onChange={(e) => setMotivo(e.target.value)} maxLength={500} placeholder="Motivo (opcional)" aria-label="Motivo" />
          <DialogFooter><Button variant="ghost" onClick={() => setReject(null)}>Cancelar</Button><Button variant="destructive" onClick={doReject} disabled={busy}>Rechazar</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}


export function Solicitudes() {
  const r = useApi<Requests>("/requests");
  if (r.error) return <ErrorState message={r.error} />;
  if (!r.data) return <Loading rows={4} />;
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card className="lg:col-span-2">
        <CardHeader><CardTitle>Pendientes ({r.data.pendientes.length})</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          {r.data.pendientes.map((x, i) => <div key={i} className="rounded-lg bg-muted/40 p-3 text-sm"><div className="mb-1 text-xs text-muted-foreground">{x.fecha} · {asistente()}</div>{x.texto}</div>)}
          <p className="text-xs text-muted-foreground">Son cosas que {asistente()} no puede resolverse solo (permisos, scripts, cuentas). Se hacen en una sesión de Claude Code en el PC; al terminar se marcan con ✅ en {r.data.path && <Link href={`/conocimiento/?p=${encodeURIComponent(r.data.path)}`} className="text-primary hover:underline">solicitudes.md</Link>}.</p>
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Resueltas</CardTitle></CardHeader>
        <CardContent><ul className="space-y-2 text-xs text-muted-foreground">{r.data.hechas.map((x, i) => <li key={i}><span className="text-success">✅</span> {x.texto.slice(0, 120)}… <span className="block">{x.resuelta}</span></li>)}</ul></CardContent>
      </Card>
    </div>
  );
}

