"use client";

import { PageHeader, usePanel } from "@/components/cc/shell";
import { ErrorState, Loading } from "@/components/cc/states";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { clock } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { post } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { GoogleCard } from "@/components/cc/google-card";
import { MotorCard } from "@/components/cc/motor-card";
import { CuentaForm } from "@/components/cc/cuenta-form";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { useState } from "react";
import Link from "next/link";

type Audit = { id: number; ts: string; actor: string; action: string; target: string; outcome: string };

type Autonomy = { pausado: boolean; revocaciones: { id: number; agente: string; capacidad: string; motivo: string }[] };
type Chain = { ok: boolean; checked: number; broken_at: number | null };

function AutonomyCard() {
  const a = useApi<Autonomy>("/autonomy", 30000);
  const chain = useApi<Chain>("/audit/verify");
  const paused = a.data?.pausado;
  return (
    <Card>
      <CardHeader><CardTitle>Autonomía de los agentes</CardTitle></CardHeader>
      <CardContent className="space-y-3 text-sm">
        <p className="text-muted-foreground">{paused ? "En pausa: ningún agente puede ejecutar acciones." : "Activa, dentro de los permisos de cada capacidad."}</p>
        <Button variant={paused ? "default" : "destructive"} size="sm" onClick={() => void post("/autonomy/pause", { pausado: !paused }).then(a.reload)}>
          {paused ? "Reanudar agentes" : "Pausar todos los agentes"}
        </Button>
        {chain.data && <p className={chain.data.ok ? "text-xs text-muted-foreground" : "text-xs text-destructive"}>{chain.data.ok ? `Auditoría íntegra: ${chain.data.checked} registros comprobados.` : `Auditoría alterada en el registro ${chain.data.broken_at}.`}</p>}
      </CardContent>
    </Card>
  );
}

/** Tu nombre y el de tu asistente: se usan en el panel, en los avisos y en las instrucciones de los agentes. */
function PerfilCard() {
  const { inst, reloadInst } = usePanel();
  const perfil = useApi<{ datos: Record<string, unknown> }>("/instancia/config/perfil");
  const [nombre, setNombre] = useState<string | null>(null);
  const [asis, setAsis] = useState<string | null>(null);
  const [estado, setEstado] = useState<string | null>(null);
  if (!inst || !perfil.data) return <Card><CardContent><Loading rows={2} /></CardContent></Card>;
  const n = nombre ?? inst.nombre;
  const a = asis ?? inst.asistente;
  const guardar = async () => {
    setEstado(null);
    try {
      await api("/instancia/config/perfil", { method: "PUT", body: JSON.stringify({ ...perfil.data!.datos, nombre: n.trim(), asistente: a.trim() || "Jarvis" }) });
      reloadInst();
      setEstado("Guardado");
    } catch (e) {
      setEstado(e instanceof Error ? e.message : String(e));
    }
  };
  return (
    <Card>
      <CardHeader><CardTitle>Tú y tu asistente</CardTitle></CardHeader>
      <CardContent className="space-y-3 text-sm">
        <label className="block space-y-1" htmlFor="p-nombre"><span className="font-medium">Cómo te llama</span>
          <Input id="p-nombre" value={n} onChange={(e) => setNombre(e.target.value)} /></label>
        <label className="block space-y-1" htmlFor="p-asis"><span className="font-medium">Nombre de tu asistente</span>
          <Input id="p-asis" value={a} maxLength={40} onChange={(e) => setAsis(e.target.value)} placeholder="Jarvis" /></label>
        <div className="flex items-center justify-between gap-2"><span className="text-xs text-muted-foreground">{estado}</span>
          <Button size="sm" disabled={!n.trim() || (n === inst.nombre && a === inst.asistente)} onClick={guardar}>Guardar</Button></div>
      </CardContent>
    </Card>
  );
}

export default function SettingsPage() {
  const { me, live } = usePanel();
  const audit = useApi<Audit[]>("/audit?limit=100");
  return (
    <>
      <PageHeader title="Configuración" description="Cuenta, módulos, conexiones y registro de auditoría."
        actions={<Link href="/settings/modulos/" className="inline-flex h-8 items-center rounded-lg px-3 text-sm ring-1 ring-border hover:bg-muted">Módulos</Link>} />
      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader><CardTitle>Cuenta</CardTitle></CardHeader>
          <CardContent className="space-y-2 text-sm">
            <div className="flex justify-between"><span className="text-muted-foreground">Usuario</span><span>{me.username}</span></div>
            <div className="flex justify-between"><span className="text-muted-foreground">Rol</span><span>{me.role}</span></div>
            <div className="flex justify-between"><span className="text-muted-foreground">Tiempo real</span><span>{live === "ws" ? "WebSocket" : live === "poll" ? "Sondeo" : "—"}</span></div>
            <div className="border-t border-border pt-3"><CuentaForm key={me.username} usuario={me.username} onHecho={() => window.location.reload()} /></div>
          </CardContent>
        </Card>
        <PerfilCard />
        <div className="lg:col-span-2"><MotorCard /></div>
        <AutonomyCard />
        <GoogleCard />
        <Card className="lg:col-span-3">
          <CardHeader><CardTitle>Auditoría</CardTitle></CardHeader>
          <CardContent>
            {audit.error && <ErrorState message={audit.error} />}
            {audit.loading && <Loading rows={6} />}
            <div className="max-h-[32rem] divide-y divide-border overflow-y-auto">
              {audit.data?.map((a) => (
                <div key={a.id} className="grid grid-cols-[7rem_1fr_auto] gap-3 py-1.5 text-xs">
                  <span className="text-muted-foreground">{clock(a.ts)}</span>
                  <span className="truncate"><span className="font-mono">{a.action}</span> {a.target && <span className="text-muted-foreground">· {a.target}</span>}</span>
                  <span className={a.outcome === "ok" ? "text-success" : "text-destructive"}>{a.actor} · {a.outcome}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </>
  );
}
