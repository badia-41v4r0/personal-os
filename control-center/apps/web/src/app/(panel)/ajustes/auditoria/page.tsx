"use client";

import { PageHeader } from "@/components/cc/shell";
import { Auditoria } from "@/components/cc/ajustes";

export default function AuditoriaPage() {
  return (
    <>
      <PageHeader title="Auditoría" description="Quién hizo qué y cuándo: tú, tu asistente o una rutina." />
      <Auditoria />
    </>
  );
}
