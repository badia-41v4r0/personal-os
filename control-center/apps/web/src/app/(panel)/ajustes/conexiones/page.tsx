"use client";

import Link from "next/link";
import { PageHeader } from "@/components/cc/shell";
import { StatusDot, type Level } from "@/components/cc/status";
import { ErrorState, Loading } from "@/components/cc/states";
import { GoogleCard } from "@/components/cc/google-card";
import { AvisosPush } from "@/components/cc/avisos-push";
import { CredencialForm, useCredenciales } from "@/components/cc/credencial";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useApi } from "@/lib/hooks";
import { asistente } from "@/lib/asistente";

type Integracion = {
  id: string; nombre: string; uso: string; estado: "conectada" | "manual" | "sin_conectar"; detalle: string; como: string;
  modulos: string[]; activa: boolean;
};
const LEVEL: Record<Integracion["estado"], Level> = { conectada: "ok", manual: "unknown", sin_conectar: "warn" };
const TEXT: Record<Integracion["estado"], string> = { conectada: "Conectada", manual: "Sin comprobar", sin_conectar: "Sin conectar" };

/** Enlace directo a donde se conecta, cuando eso vive en otro apartado. */
const IR: Record<string, [string, string]> = {
  campus: ["/ajustes/ordenadores/", "Abrir los ordenadores"],
  hevy: ["/entrenamiento/?tab=history&importar=1", "Importar de Hevy"],
};

function Fila({ i }: { i: Integracion }) {
  const ir = IR[i.id];
  return (
    <div className="flex flex-wrap items-start gap-x-3 gap-y-1 py-3">
      <StatusDot level={LEVEL[i.estado]} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2 text-sm"><span className="font-medium">{i.nombre}</span><span className="text-xs text-muted-foreground">{i.uso}</span></div>
        {i.estado !== "conectada" && <p className="mt-0.5 text-xs text-muted-foreground">{i.como}</p>}
        {i.detalle && i.estado === "conectada" && <p className="mt-0.5 text-xs text-muted-foreground">{i.detalle}</p>}
      </div>
      <span className="text-xs text-muted-foreground">{TEXT[i.estado]}</span>
      {ir && <Link href={ir[0]} className="basis-full pl-5 text-xs text-primary hover:underline">{ir[1]} →</Link>}
    </div>
  );
}

function Telegram({ onCambio }: { onCambio: () => void }) {
  const c = useCredenciales();
  if (!c.data) return null;
  const listo = () => { c.reload(); onCambio(); };
  return (
    <Card>
      <CardHeader><CardTitle>Telegram</CardTitle></CardHeader>
      <CardContent className="space-y-3 text-sm">
        <p className="text-xs text-muted-foreground">Solo de salida: copia las alertas críticas a un bot tuyo. Crea el bot con @BotFather; tu chat id te lo da @userinfobot. Lo que le escribas al bot no lo lee nadie.</p>
        <CredencialForm clave="TELEGRAM_BOT_TOKEN" etiqueta="Token del bot" placeholder="123456789:AA…" puesta={c.data.TELEGRAM_BOT_TOKEN} onGuardada={listo} />
        <CredencialForm clave="TELEGRAM_CHAT_ID" etiqueta="Tu chat id" placeholder="123456789" secreta={false} puesta={c.data.TELEGRAM_CHAT_ID} onGuardada={listo} />
      </CardContent>
    </Card>
  );
}

export default function ConexionesPage() {
  const list = useApi<Integracion[]>("/home/integraciones", 60000);
  const activas = list.data?.filter((i) => i.activa) ?? [];
  const otras = list.data?.filter((i) => !i.activa) ?? [];
  const usa = (id: string) => activas.some((i) => i.id === id);
  return (
    <>
      <PageHeader title="Conexiones" description={`Con qué se conecta ${asistente()} y cómo conectarlo. Solo salen las de tus módulos activos.`} />
      {list.error && <ErrorState message={list.error} />}
      {list.loading && <Loading rows={6} />}
      {list.data && (
        <div className="space-y-6">
          <Card>
            <CardContent className="divide-y divide-border">
              {activas.map((i) => <Fila key={i.id} i={i} />)}
            </CardContent>
          </Card>
          {(usa("google") || usa("gmail")) && <GoogleCard />}
          {usa("telegram") && <Telegram onCambio={list.reload} />}
          <section aria-labelledby="avisos-push" className="space-y-3">
            <h2 id="avisos-push" className="text-sm font-medium">Avisos en el móvil y el PC</h2>
            <AvisosPush />
          </section>
          {otras.length > 0 && (
            <details className="rounded-lg border border-border px-4 py-2 text-sm">
              <summary className="cursor-pointer py-1 text-muted-foreground">De módulos desactivados ({otras.length})</summary>
              <div className="divide-y divide-border">{otras.map((i) => <Fila key={i.id} i={i} />)}</div>
              <p className="py-2 text-xs text-muted-foreground">Actívalos en <Link href="/ajustes/modulos/" className="text-primary hover:underline">Módulos</Link>.</p>
            </details>
          )}
        </div>
      )}
    </>
  );
}
