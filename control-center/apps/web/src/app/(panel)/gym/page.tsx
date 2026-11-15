"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { ArrowLeft } from "lucide-react";
import { cn } from "cn";
import { PageHeader } from "@/components/cc/shell";
import { Loading } from "@/components/cc/states";
import { CoachTab } from "@/components/gym/coach";
import { HistoryTab, WorkoutDetail } from "@/components/gym/history";
import { OverviewTab } from "@/components/gym/overview";
import { ExerciseDetail, ProgressTab } from "@/components/gym/progress";
import { RecoveryTab } from "@/components/gym/recovery";
import { RoutinesTab } from "@/components/gym/routines";
import { TrainingTab } from "@/components/gym/training";
import type { ExIndex } from "@/components/gym/common";
import { useApi } from "@/lib/hooks";

import { RegisterTab } from "@/components/gym/register";

const TABS = [
  ["overview", "Overview"], ["registrar", "Registrar"], ["training", "Training"], ["progress", "Progress"], ["recovery", "Recovery"],
  ["history", "History"], ["routines", "Routines"], ["coach", "Coach"],
] as const;
type Tab = (typeof TABS)[number][0];

function GymInner() {
  const params = useSearchParams();
  const router = useRouter();
  const w = params.get("w");
  const e = params.get("e");
  // Compatibilidad: ?w= y ?e= sin pestaña abren History y Progress
  const tab = (params.get("tab") as Tab | null) ?? (w ? "history" : e ? "progress" : "overview");
  const exercises = useApi<ExIndex[]>(e ? "/gym/exercises" : null);
  const detalle = (tab === "history" && w) || (tab === "progress" && e);
  const title = tab === "history" && w ? `Sesión ${w.slice(0, 10)}` : tab === "progress" && e ? exercises.data?.find((x) => x.id === e)?.nombre ?? "Ejercicio" : "Gym";
  return (
    <>
      <PageHeader
        title={title}
        description={detalle ? undefined : "Entrenas con Hevy como siempre; Jarvis planifica, analiza y te propone. Los entrenos salen de Areas/Gym.md."}
        actions={detalle && <button onClick={() => router.back()} className="-my-1 flex items-center gap-1 rounded-md px-2 py-1.5 text-sm text-muted-foreground hover:bg-muted hover:text-foreground"><ArrowLeft className="size-4" /> Volver</button>}
      />
      <nav aria-label="Secciones del gym" className="-mx-1 mb-4 flex gap-1 overflow-x-auto border-b border-border px-1 pb-px">
        {TABS.map(([k, l]) => (
          <Link key={k} href={`/gym/?tab=${k}`} aria-current={tab === k ? "page" : undefined}
            className={cn("relative shrink-0 rounded-t-md px-3 py-2 text-sm whitespace-nowrap transition-colors",
              tab === k ? "text-foreground after:absolute after:inset-x-2 after:-bottom-px after:h-0.5 after:bg-foreground" : "text-muted-foreground hover:text-foreground")}>
            {l}
          </Link>
        ))}
      </nav>
      <div>
        {tab === "overview" && <OverviewTab />}
        {tab === "registrar" && <RegisterTab />}
        {tab === "training" && <TrainingTab />}
        {tab === "progress" && (e ? <ExerciseDetail key={e} id={e} /> : <ProgressTab />)}
        {tab === "recovery" && <RecoveryTab />}
        {tab === "history" && (w ? <WorkoutDetail key={w} id={w} /> : <HistoryTab />)}
        {tab === "routines" && <RoutinesTab />}
        {tab === "coach" && <CoachTab />}
      </div>
    </>
  );
}

export default function GymPage() {
  return (
    <Suspense fallback={<Loading rows={6} />}>
      <GymInner />
    </Suspense>
  );
}
