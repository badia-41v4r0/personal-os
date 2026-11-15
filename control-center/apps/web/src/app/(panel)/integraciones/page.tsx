"use client";

import { PageHeader } from "@/components/cc/shell";
import { StatusRow, type Level } from "@/components/cc/status";
import { ErrorState, Loading } from "@/components/cc/states";
import { Card, CardContent } from "@/components/ui/card";
import { useApi } from "@/lib/hooks";
import { asistente } from "@/lib/asistente";

type Integracion = { nombre: string; uso: string; estado: "conectada" | "manual" | "sin_conectar"; detalle: string };
const LEVEL: Record<Integracion["estado"], Level> = { conectada: "ok", manual: "unknown", sin_conectar: "warn" };
const TEXT: Record<Integracion["estado"], string> = { conectada: "Conectada", manual: "Manual", sin_conectar: "Sin conectar" };

export default function IntegracionesPage() {
  const list = useApi<Integracion[]>("/home/integraciones", 60000);
  return (
    <>
      <PageHeader title="Integraciones" description={`Con qué se conecta ${asistente()} y cómo.`} />
      {list.error && <ErrorState message={list.error} />}
      {list.loading && <Loading rows={6} />}
      {list.data && (
        <Card>
          <CardContent className="divide-y divide-border">
            {list.data.map((i) => (
              <div key={i.nombre}>
                <StatusRow label={i.nombre} level={LEVEL[i.estado]} detail={TEXT[i.estado]} />
                <p className="pb-2 text-xs text-muted-foreground">{i.uso}{i.detalle ? ` · ${i.detalle}` : ""}</p>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </>
  );
}
