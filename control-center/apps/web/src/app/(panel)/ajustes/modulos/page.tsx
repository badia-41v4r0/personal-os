"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { PageHeader, usePanel } from "@/components/cc/shell";
import { ErrorState, Loading } from "@/components/cc/states";
import { Card, CardContent } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";
import type { Modulo } from "@/lib/instancia";

const INTEGRACION: Record<string, string> = {
  google: "Google", zoho: "Zoho Mail", github: "GitHub", telegram: "Telegram", campus: "Campus de tu universidad", tmdb: "TMDB (opcional)",
};

export default function ModulosPage() {
  const { inst, reloadInst } = usePanel();
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [avisos, setAvisos] = useState<string[]>([]);

  if (!inst) return <Loading rows={6} />;

  const cambiar = async (m: Modulo, activo: boolean) => {
    setBusy(m.id);
    setError(null);
    try {
      const activos = inst.modulos.filter((x) => (x.id === m.id ? activo : x.activo)).map((x) => x.id);
      const r = await api<{ avisos: string[] }>("/instancia/modulos", { method: "PUT", body: JSON.stringify({ activos }) });
      setAvisos(r.avisos ?? []);
      reloadInst();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const reconfigurar = async (m: Modulo) => {
    const apartados = { ...inst.onboarding.apartados };
    delete apartados[m.id];
    await api("/instancia/config/onboarding", { method: "PUT", body: JSON.stringify({ hecho: inst.onboarding.hecho, apartados }) });
    reloadInst();
    router.push(m.web[0]);
  };

  return (
    <>
      <PageHeader title="Módulos" description="Activa solo lo que vayas a usar. Lo desactivado desaparece del panel y ningún agente puede usarlo." />
      {error && <div className="mb-4"><ErrorState message={error} /></div>}
      {avisos.length > 0 && <div className="mb-4 rounded-lg border border-border p-3 text-sm">{avisos.map((a) => <p key={a}>{a}</p>)}</div>}
      <div className="grid gap-3 md:grid-cols-2">
        {inst.modulos.map((m) => (
          <Card key={m.id}>
            <CardContent className="flex items-start gap-3 py-4">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-sm font-medium">{m.nombre}</h2>
                  {m.nucleo && <Badge variant="secondary">Siempre activo</Badge>}
                </div>
                <p className="mt-1 text-sm text-muted-foreground">{m.descripcion}</p>
                {m.activo && !m.nucleo && m.web.length > 0 && (
                  <button type="button" className="mt-1 text-xs text-primary underline" onClick={() => void reconfigurar(m)}>Configurar con su asistente</button>
                )}
                {m.integraciones.length > 0 && (
                  <p className="mt-1 text-xs text-muted-foreground">Necesita conectar: {m.integraciones.map((i) => INTEGRACION[i] ?? i).join(", ")}</p>
                )}
              </div>
              <Switch aria-label={`Activar ${m.nombre}`} checked={m.activo} disabled={m.nucleo || busy !== null}
                onCheckedChange={(v: boolean) => void cambiar(m, v)} />
            </CardContent>
          </Card>
        ))}
      </div>
    </>
  );
}
