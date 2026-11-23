"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { cn } from "cn";
import { PageHeader, usePanel } from "@/components/cc/shell";
import { PendingActions, Propuestas, Solicitudes } from "@/components/cc/aprobaciones";
import { Empty, ErrorState, Loading } from "@/components/cc/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { api, post } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { rutaActual } from "@/lib/rutas";
import { asistente } from "@/lib/asistente";

type Aviso = { id: number; ts: string; level: string; title: string; body: string; url: string; read: boolean; pushed: number };
type Cuenta = { unread: number; por_decidir: number; acciones: number; solicitudes: number };

const LEVEL: Record<string, string> = { critical: "bg-destructive", action: "bg-primary", info: "bg-muted-foreground/50", silent: "bg-muted-foreground/30" };
const TABS = [["decidir", "Por decidir"], ["avisos", "Avisos"], ["solicitudes", "Solicitudes"]] as const;
type Tab = (typeof TABS)[number][0];

function Avisos({ onChange }: { onChange: () => void }) {
  const { lastEvent } = usePanel();
  const list = useApi<Aviso[]>("/notifications");
  const { reload } = list;
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (lastEvent?.type === "notification.created") reload();
  }, [lastEvent, reload]);
  const act = async (fn: () => Promise<unknown>) => {
    setErr(null);
    try {
      await fn();
      reload();
      onChange();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };
  const unread = list.data?.filter((a) => !a.read).length ?? 0;
  return (
    <Card>
      <CardContent>
        <div className="mb-2 flex items-center justify-between gap-2">
          <h2 className="text-sm font-medium">Avisos</h2>
          {unread > 0 && <Button variant="outline" size="sm" onClick={() => act(() => post("/notifications/read-all"))}>Marcar todo como leído</Button>}
        </div>
        {err && <ErrorState message={err} />}
        {list.error && <ErrorState message={list.error} />}
        {list.loading && <Loading rows={5} />}
        {list.data?.length === 0 && <Empty message="Todavía no hay avisos." />}
        <div className="divide-y divide-border">
          {list.data?.map((a) => (
            <div key={a.id} className="flex items-start gap-3 py-3">
              <span className={`mt-1.5 size-2 shrink-0 rounded-full ${a.read ? "bg-transparent" : LEVEL[a.level] ?? LEVEL.info}`} aria-hidden />
              <div className="min-w-0 flex-1">
                <Link
                  href={rutaActual(a.url)}
                  onClick={() => {
                    if (!a.read) void api(`/notifications/${a.id}/read`, { method: "POST" }).catch(() => {});
                  }}
                  className={`inline-block py-1 ${a.read ? "text-sm text-muted-foreground" : "text-sm font-medium"}`}
                >
                  {a.title}
                </Link>
                {a.body && <p className="mt-0.5 text-sm break-words whitespace-pre-line text-muted-foreground">{a.body}</p>}
                <p className="mt-1 text-xs text-muted-foreground">{timeAgo(a.ts)}{a.level === "critical" ? " · crítico" : ""}</p>
              </div>
              {!a.read && <Button variant="ghost" size="sm" onClick={() => act(() => post(`/notifications/${a.id}/read`))}>Leído</Button>}
            </div>
          ))}
        </div>
        <p className="mt-3 text-xs text-muted-foreground">
          Para recibirlos en el móvil, actívalos en <Link href="/ajustes/conexiones/" className="text-primary hover:underline">Ajustes → Conexiones</Link>.
        </p>
      </CardContent>
    </Card>
  );
}

export default function BandejaPage() {
  const cuenta = useApi<Cuenta>("/notifications/count", 60_000);
  const { lastEvent } = usePanel();
  const { reload } = cuenta;
  const [tab, setTab] = useState<Tab | null>(null);
  useEffect(() => {
    if (lastEvent?.type === "notification.created" || lastEvent?.type === "action.changed" || lastEvent?.type === "approval.decided") reload();
  }, [lastEvent, reload]);
  useEffect(() => {
    const t = new URLSearchParams(window.location.search).get("t") as Tab | null;
    if (t && TABS.some(([k]) => k === t)) setTab(t);
  }, []);
  // Sin pestaña elegida: «Por decidir» si hay algo esperando, si no los avisos
  const activa: Tab = tab ?? (cuenta.data && cuenta.data.acciones === 0 && cuenta.data.unread > 0 ? "avisos" : "decidir");
  const num: Record<Tab, number> = { decidir: cuenta.data?.acciones ?? 0, avisos: cuenta.data?.unread ?? 0, solicitudes: cuenta.data?.solicitudes ?? 0 };
  const elegir = (k: Tab) => {
    setTab(k);
    window.history.replaceState(null, "", k === "decidir" ? "/bandeja/" : `/bandeja/?t=${k}`);
  };

  return (
    <>
      <PageHeader title="Bandeja" description={`Lo que espera tu decisión y lo que ${asistente()} te ha avisado, en un solo sitio.`} />
      <div className="mb-4 flex flex-wrap gap-1" role="tablist" aria-label="Bandeja">
        {TABS.map(([k, l]) => (
          <button key={k} type="button" role="tab" aria-selected={activa === k} onClick={() => elegir(k)}
            className={cn("flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm", activa === k ? "bg-muted font-medium" : "text-muted-foreground hover:text-foreground")}>
            {l}
            {num[k] > 0 && <span className="rounded-full bg-primary/15 px-1.5 text-[11px] font-medium text-primary">{num[k]}</span>}
          </button>
        ))}
      </div>
      {activa === "decidir" && (
        <>
          <PendingActions />
          <Propuestas />
        </>
      )}
      {activa === "avisos" && <Avisos onChange={reload} />}
      {activa === "solicitudes" && <Solicitudes />}
    </>
  );
}
