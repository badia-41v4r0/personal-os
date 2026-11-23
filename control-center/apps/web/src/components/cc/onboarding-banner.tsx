"use client";

import { useState } from "react";
import { Sparkles, X } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { usePanel } from "@/components/cc/shell";
import { JarvisDock } from "@/components/cc/jarvis-dock";
import { api, post } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import type { Instancia, Modulo } from "@/lib/instancia";
import type { Assistant } from "@/components/cc/assistants";

type Accion = { id: string; capability: string; summary: string; hash: string; status: string };

/** Lo que el asistente de onboarding ha propuesto y espera el OK del usuario (config.*.set). */
function Propuestas({ onCambio }: { onCambio: () => void }) {
  const acc = useApi<Accion[]>("/actions?estado=pending", 4000);
  const [busy, setBusy] = useState<string | null>(null);
  const pendientes = (acc.data ?? []).filter((a) => a.capability.startsWith("config."));
  if (pendientes.length === 0) return null;
  const decidir = async (a: Accion, aprobar: boolean) => {
    setBusy(a.id);
    try {
      await post(`/actions/${a.id}/decide`, { aprobar, hash: a.hash });
      await acc.reload();
      onCambio();
    } finally {
      setBusy(null);
    }
  };
  return (
    <div className="space-y-2">
      {pendientes.map((a) => (
        <div key={a.id} className="rounded-lg border border-primary/40 bg-primary/5 p-3 text-sm">
          <p className="mb-1 font-medium">Propuesta para guardar</p>
          <p className="break-words font-mono text-xs text-muted-foreground">{a.summary}</p>
          <div className="mt-2 flex gap-2">
            <Button size="sm" disabled={busy === a.id} onClick={() => decidir(a, true)}>Aprobar</Button>
            <Button size="sm" variant="ghost" disabled={busy === a.id} onClick={() => decidir(a, false)}>Rechazar</Button>
          </div>
        </div>
      ))}
    </div>
  );
}

async function marcar(inst: Instancia, mod: string, estado: "saltado" | "hecho") {
  await api("/instancia/config/onboarding", {
    method: "PUT",
    body: JSON.stringify({ hecho: inst.onboarding.hecho, apartados: { ...inst.onboarding.apartados, [mod]: estado } }),
  });
}

/** La primera vez que se abre un apartado: ofrece configurarlo con su asistente (o saltarlo). */
export function OnboardingBanner({ modulo }: { modulo: Modulo }) {
  const { inst, reloadInst } = usePanel();
  const [abierto, setAbierto] = useState(false);
  if (!inst || !inst.onboarding.hecho || modulo.nucleo && modulo.id !== "inicio" || inst.onboarding.apartados[modulo.id]) return null;
  const asistente: Assistant = {
    key: `onboarding-${modulo.id}`, name: `Configurar ${modulo.nombre}`, hint: "Asistente de bienvenida", base: `/assistants/onboarding-${modulo.id}`,
    quick: [{ label: "Empezar", icon: Sparkles, text: `Hola, quiero configurar ${modulo.nombre}.` }],
  };
  return (
    <Card className="mb-5 border-primary/30">
      <CardContent className="space-y-3 py-4">
        <div className="flex flex-wrap items-start gap-3">
          <Sparkles className="mt-0.5 size-5 text-primary" />
          <div className="min-w-0 flex-1 basis-60">
            <p className="font-medium">Primera vez en {modulo.nombre}</p>
            <p className="text-sm text-muted-foreground">{modulo.descripcion} Su asistente te ayuda a dejarlo listo; nada se guarda sin que lo apruebes. «Ahora no» la quita (puedes configurarlo después desde Ajustes → Módulos).</p>
          </div>
          <div className="flex w-full gap-2 sm:w-auto">
            {abierto
              ? <Button size="sm" variant="outline" onClick={() => setAbierto(false)}><X /> Plegar</Button>
              : <Button size="sm" onClick={() => setAbierto(true)}>Configurar con el asistente</Button>}
            <Button size="sm" variant="ghost" onClick={async () => { await marcar(inst, modulo.id, "saltado"); reloadInst(); }}>Ahora no</Button>
          </div>
        </div>
        {abierto && (
          <>
            <Propuestas onCambio={reloadInst} />
            <div className="h-[28rem] overflow-hidden rounded-lg border border-border"><JarvisDock assistant={asistente} /></div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
