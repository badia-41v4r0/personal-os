"use client";

import { useEffect } from "react";
import { AlertOctagon, AlertTriangle, CheckCircle2, Info } from "lucide-react";
import { cn } from "cn";
import { usePanel } from "./shell";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { post } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import { useApi } from "@/lib/hooks";

type Alert = { id: number; severity: "info" | "warning" | "critical"; title: string; detail: string; status: string; started_at: string; resolved_at: string | null; notified: boolean };

const ICON = { critical: AlertOctagon, warning: AlertTriangle, info: Info };
const LABEL = { critical: "Crítica", warning: "Aviso", info: "Info" };

export function AlertsCard({ compact = false }: { compact?: boolean }) {
  const { lastEvent } = usePanel();
  const open = useApi<Alert[]>("/alerts?status=open", 60000);
  const recent = useApi<Alert[]>(compact ? null : "/alerts?status=resolved&limit=8");
  useEffect(() => {
    if (lastEvent?.type.startsWith("alert.")) {
      open.reload();
      recent.reload();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastEvent]);

  const dismiss = async (id: number) => {
    await post(`/alerts/${id}/resolve`);
    open.reload();
  };

  return (
    <Card>
      <CardHeader><CardTitle>Alertas {open.data && open.data.length > 0 && <span className="ml-1 font-mono text-sm text-warning">{open.data.length}</span>}</CardTitle></CardHeader>
      <CardContent className="space-y-2">
        {open.data?.length === 0 && <p className="flex items-center gap-2 text-sm text-muted-foreground"><CheckCircle2 className="size-4 text-success" /> Sin alertas abiertas</p>}
        {open.data?.map((a) => {
          const Icon = ICON[a.severity];
          return (
            <div key={a.id} className={cn("flex items-start justify-between gap-3 rounded-lg px-3 py-2 text-sm ring-1",
              a.severity === "critical" ? "bg-destructive/10 ring-destructive/30" : "bg-warning/10 ring-warning/30")}>
              <div className="flex min-w-0 gap-2">
                <Icon className={cn("mt-0.5 size-4 shrink-0", a.severity === "critical" ? "text-destructive" : "text-warning")} />
                <div className="min-w-0">
                  <div>{a.title} <span className="text-xs text-muted-foreground">· {LABEL[a.severity]}</span></div>
                  {a.detail && <div className="text-xs text-muted-foreground">{a.detail}</div>}
                  <div className="text-[11px] text-muted-foreground">desde {timeAgo(a.started_at)}{a.notified ? " · avisada por Telegram" : ""}</div>
                </div>
              </div>
              {!compact && <Button size="xs" variant="ghost" onClick={() => dismiss(a.id)} title="Se volverá a abrir si el problema sigue">Descartar</Button>}
            </div>
          );
        })}
        {!compact && (recent.data?.length ?? 0) > 0 && (
          <div className="pt-2">
            <div className="mb-1 text-xs text-muted-foreground">Resueltas recientemente</div>
            <ul className="space-y-0.5 text-xs text-muted-foreground">
              {recent.data!.map((a) => <li key={a.id} className="flex justify-between gap-2"><span className="truncate">{a.title}</span><span className="shrink-0">{timeAgo(a.resolved_at)}</span></li>)}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
