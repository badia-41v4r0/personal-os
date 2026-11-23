"use client";

import { useEffect, useState } from "react";
import { Bell, BellOff, Send, Smartphone, Trash2 } from "lucide-react";
import { Empty, ErrorState } from "@/components/cc/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api, post } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { currentEndpointActive, disablePushHere, enablePush, isInstalled, isIOS, pushSupported, type PushConfig } from "@/lib/push";
import { asistente } from "@/lib/asistente";

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

/** Avisos en el móvil y el PC: activar en este dispositivo y ver o quitar los demás (Ajustes → Conexiones). */
export function AvisosPush() {
  const config = useApi<PushConfig>("/push/config");
  const [err, setErr] = useState<string | null>(null);
  const act = async (fn: () => Promise<unknown>) => {
    setErr(null);
    try {
      await fn();
      config.reload();
    } catch (e) {
      setErr(msgOf(e));
    }
  };
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader><CardTitle>Avisos en este dispositivo</CardTitle></CardHeader>
        <CardContent><Device onChange={config.reload} />{err && <ErrorState message={err} />}</CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Dispositivos con avisos</CardTitle></CardHeader>
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
  );
}
