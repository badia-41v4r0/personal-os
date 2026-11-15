"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Bell, BellOff, Send, Smartphone, Trash2 } from "lucide-react";
import { PageHeader, usePanel } from "@/components/cc/shell";
import { Empty, ErrorState, Loading } from "@/components/cc/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api, post } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { currentEndpointActive, disablePushHere, enablePush, isInstalled, isIOS, pushSupported, type PushConfig } from "@/lib/push";
import { asistente } from "@/lib/asistente";

type Aviso = { id: number; ts: string; level: string; title: string; body: string; url: string; read: boolean; pushed: number };

const LEVEL: Record<string, string> = { critical: "bg-destructive", action: "bg-primary", info: "bg-muted-foreground/50", silent: "bg-muted-foreground/30" };
const msgOf = (e: unknown) => (e instanceof Error ? e.message : String(e));

function Device({ onChange }: { onChange: () => void }) {
  const [active, setActive] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    currentEndpointActive().then(setActive).catch(() => setActive(false));
  }, []);

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setErr(null);
    setMsg(null);
    try {
      await fn();
    } catch (e) {
      setErr(msgOf(e));
    } finally {
      setBusy(false);
    }
  };

  if (isIOS() && !isInstalled()) {
    return (
      <div className="space-y-2 text-sm">
        <p className="font-medium">Instala el panel para recibir avisos</p>
        <ol className="list-decimal space-y-1 pl-5 text-muted-foreground">
          <li>Abre esta página en Safari.</li>
          <li>Toca Compartir y luego «Añadir a pantalla de inicio».</li>
          <li>Abre {asistente()} desde ese icono, entra y vuelve aquí.</li>
        </ol>
      </div>
    );
  }
  if (!pushSupported()) return <p className="text-sm text-muted-foreground">Este navegador no admite notificaciones push.</p>;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        {active ? (
          <>
            <Button
              disabled={busy}
              onClick={() =>
                run(async () => {
                  const r = await post<{ pushed: number }>("/push/test");
                  setMsg(r.pushed ? "Prueba enviada. Debería llegarte en unos segundos." : "Aviso guardado, pero no se pudo entregar a ningún dispositivo.");
                  onChange();
                })
              }
            >
              <Send /> Enviar prueba
            </Button>
            <Button
              variant="outline"
              disabled={busy}
              onClick={() =>
                run(async () => {
                  await disablePushHere();
                  setActive(false);
                })
              }
            >
              <BellOff /> Desactivar aquí
            </Button>
          </>
        ) : (
          <Button
            disabled={busy}
            onClick={() =>
              run(async () => {
                await enablePush();
                setActive(true);
                onChange();
              })
            }
          >
            <Bell /> Activar avisos en este dispositivo
          </Button>
        )}
      </div>
      {msg && <p role="status" className="text-sm text-muted-foreground">{msg}</p>}
      {err && <ErrorState message={err} />}
    </div>
  );
}

export default function AvisosPage() {
  const { lastEvent } = usePanel();
  const list = useApi<Aviso[]>("/notifications");
  const config = useApi<PushConfig>("/push/config");
  const { reload: reloadList } = list;
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (lastEvent?.type === "notification.created") {
      reloadList();
    }
  }, [lastEvent, reloadList]);

  const refresh = () => {
    list.reload();
    config.reload();
  };
  const act = async (fn: () => Promise<unknown>) => {
    setErr(null);
    try {
      await fn();
      refresh();
    } catch (e) {
      setErr(msgOf(e));
    }
  };
  const unread = list.data?.filter((a) => !a.read).length ?? 0;

  return (
    <>
      <PageHeader
        title="Avisos"
        description={`Todo lo que ${asistente()} te notifica. Lo que no suene en el móvil también queda aquí.`}
        actions={unread > 0 ? <Button variant="outline" onClick={() => act(() => post("/notifications/read-all"))}>Marcar todo como leído</Button> : undefined}
      />
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader><CardTitle>Bandeja</CardTitle></CardHeader>
          <CardContent>
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
                      href={a.url}
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
                  {!a.read && (
                    <Button variant="ghost" size="sm" onClick={() => act(() => post(`/notifications/${a.id}/read`))}>Leído</Button>
                  )}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
        <div className="space-y-4">
          <Card>
            <CardHeader><CardTitle>Este dispositivo</CardTitle></CardHeader>
            <CardContent><Device onChange={refresh} /></CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Dispositivos</CardTitle></CardHeader>
            <CardContent>
              {config.error && <ErrorState message={config.error} />}
              {config.data?.subscriptions.length === 0 && <Empty message="Ningún dispositivo activado." />}
              <div className="divide-y divide-border">
                {config.data?.subscriptions.map((d) => (
                  <div key={d.id} className="flex items-center gap-3 py-2">
                    <Smartphone className="size-4 shrink-0 text-muted-foreground" />
                    <div className="min-w-0 flex-1 text-sm">
                      <div>{d.label || d.host}</div>
                      <div className={d.last_error ? "truncate text-xs text-destructive" : "text-xs text-muted-foreground"}>
                        {d.last_error ? "Último envío falló" : d.last_ok_at ? `Último envío ${timeAgo(d.last_ok_at)}` : "Sin envíos todavía"}
                      </div>
                    </div>
                    <Button variant="ghost" size="icon-sm" aria-label={`Quitar ${d.label || d.host}`} onClick={() => act(() => api(`/push/subscriptions/${d.id}`, { method: "DELETE" }))}>
                      <Trash2 />
                    </Button>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  );
}
