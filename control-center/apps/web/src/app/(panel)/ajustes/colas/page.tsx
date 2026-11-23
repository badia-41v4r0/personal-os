"use client";

import { PageHeader } from "@/components/cc/shell";
import { Colas, Temporizadores } from "@/components/cc/colas";

export default function ColasPage() {
  return (
    <>
      <PageHeader title="Colas y temporizadores" description="Trabajo en cola de los servicios del PC y cuándo se ejecuta cada temporizador." />
      <div className="space-y-6">
        <Colas />
        <Temporizadores />
      </div>
    </>
  );
}
