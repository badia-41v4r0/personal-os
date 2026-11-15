"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { FolderOpen } from "lucide-react";
import { cn } from "cn";
import { PageHeader } from "@/components/cc/shell";
import { ErrorState, Loading } from "@/components/cc/states";
import { ArchivosTab } from "@/components/edu/archivos";
import { AsignaturasTab } from "@/components/edu/asignaturas";
import type { Overview } from "@/components/edu/common";
import { CrucesTab } from "@/components/edu/cruces";
import { HoyTab } from "@/components/edu/hoy";
import { PlanTab } from "@/components/edu/plan";
import { RepasoTab } from "@/components/edu/repaso";
import { useApi } from "@/lib/hooks";

const TABS = [["hoy", "Hoy"], ["asignaturas", "Asignaturas"], ["plan", "Plan"], ["repaso", "Repaso"], ["cruces", "Cruces"], ["archivos", "Archivos"]] as const;
type Tab = (typeof TABS)[number][0];

function EducacionInner() {
  const params = useSearchParams();
  const tab = (TABS.find(([k]) => k === params.get("tab"))?.[0] ?? "hoy") as Tab;
  const o = useApi<Overview>("/education/overview");
  return (
    <>
      <PageHeader
        title="Educación"
        description="Tu plan, tus entregas y lo que te prepara el tutor. Marcar aquí cuenta igual que en el Panel de Obsidian."
        actions={<Link href="/educacion/?tab=archivos" className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border px-3 text-sm hover:bg-muted"><FolderOpen className="size-4" />Ver archivos</Link>}
      />
      <nav aria-label="Secciones de Educación" className="-mx-1 mb-4 flex gap-1 overflow-x-auto border-b border-border px-1 pb-px">
        {TABS.map(([k, l]) => (
          <Link key={k} href={`/educacion/?tab=${k}`} aria-current={tab === k ? "page" : undefined}
            className={cn("relative flex min-h-10 shrink-0 items-center rounded-t-md px-3 py-2 text-sm whitespace-nowrap transition-colors",
              tab === k ? "text-foreground after:absolute after:inset-x-2 after:-bottom-px after:h-0.5 after:bg-foreground" : "text-muted-foreground hover:text-foreground")}>
            {l}
            {k === "repaso" && o.data && o.data.asignaturas.some((a) => a.tarjetas_hoy > 0) && <span className="ml-1.5 rounded-full bg-primary px-1.5 text-[10px] font-semibold leading-4 text-primary-foreground">{o.data.asignaturas.reduce((s, a) => s + a.tarjetas_hoy, 0)}</span>}
            {k === "hoy" && o.data && o.data.canvas_nuevos > 0 && <span aria-label="Cambios en Canvas" className="ml-1.5 size-2 rounded-full bg-amber-500" />}
          </Link>
        ))}
      </nav>
      {tab === "archivos" ? <ArchivosTab ruta={params.get("ruta") ?? ""} /> : (
        <>
          {o.error && <ErrorState message={o.error} />}
          {o.loading && !o.data && <Loading rows={6} />}
          {o.data && tab === "hoy" && <HoyTab o={o.data} reloadOverview={o.reload} />}
          {o.data && tab === "asignaturas" && <AsignaturasTab asignaturas={o.data.asignaturas} />}
          {o.data && tab === "plan" && <PlanTab hoy={o.data.hoy} />}
          {tab === "repaso" && <RepasoTab />}
          {tab === "cruces" && <CrucesTab />}
        </>
      )}
    </>
  );
}

export default function EducacionPage() {
  return <Suspense fallback={<Loading rows={6} />}><EducacionInner /></Suspense>;
}
