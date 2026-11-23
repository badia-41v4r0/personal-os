"use client";

import { PageHeader } from "@/components/cc/shell";
import { MotorCard } from "@/components/cc/motor-card";

export default function MotorPage() {
  return (
    <>
      <PageHeader title="Motor de IA" description="Qué modelo responde y con qué cuenta. Las credenciales se guardan solo en tu PC." />
      <MotorCard />
    </>
  );
}
