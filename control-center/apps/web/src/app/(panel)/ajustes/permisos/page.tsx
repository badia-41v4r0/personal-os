"use client";

import { PageHeader } from "@/components/cc/shell";
import { AutonomyCard } from "@/components/cc/ajustes";

export default function PermisosPage() {
  return (
    <>
      <PageHeader title="Autonomía" description="Qué pueden hacer los agentes sin preguntarte. Lo que sale fuera o cambia la configuración siempre espera tu aprobación en la Bandeja." />
      <div className="max-w-xl"><AutonomyCard /></div>
    </>
  );
}
