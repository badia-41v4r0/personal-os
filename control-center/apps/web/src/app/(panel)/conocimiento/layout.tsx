"use client";

import { Pestanas } from "@/components/cc/subnav";
import { CONOCIMIENTO_TABS } from "@/components/cc/nav";

export default function ConocimientoLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <Pestanas items={CONOCIMIENTO_TABS} label="Secciones de Conocimiento" />
      {children}
    </>
  );
}
