"use client";

import { PageHeader, usePanel } from "@/components/cc/shell";
import { PerfilCard } from "@/components/cc/ajustes";
import { CuentaForm } from "@/components/cc/cuenta-form";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default function AjustesPage() {
  const { me, live } = usePanel();
  return (
    <>
      <PageHeader title="Tú y tu cuenta" description="Tu usuario y contraseña del panel, cómo te llama tu asistente y cómo se llama." />
      <div className="grid gap-4 lg:grid-cols-2">
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
      </div>
    </>
  );
}
