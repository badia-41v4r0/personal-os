"use client";

import Link from "next/link";
import { useState } from "react";
import { Clock } from "lucide-react";
import { cn } from "cn";
import { ErrorState, Loading } from "@/components/cc/states";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { clock, timeAgo } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Unit } from "@/lib/types";
import { asistente } from "@/lib/asistente";

// Colas de trabajo (carpetas de la vault que vigilan los servicios) y temporizadores de systemd.

type QItem = { id: string; estado: string; path: string; meta: Record<string, string>; titulo: string; resumen: string; resultado: string; mtime: number };
type Queue = { id: string; label: string; folder: string; items: QItem[]; pendientes: number };

const ESTADO: Record<string, string> = { cola: "en cola", "en-curso": "en curso", hechos: "hecho" };

function usecToDate(v?: string): string | null {
  if (!v || v === "0" || v === "n/a") return null;
  if (/^\d+$/.test(v)) return new Date(Number(v) / 1000).toISOString();
  const d = new Date(v.replace(/^[A-Za-z]{3} /, "").replace(/ [A-Z]{3,4}$/, ""));
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

export function Colas() {
  const q = useApi<Queue[]>("/queues", 30_000);
  const [open, setOpen] = useState<string | null>(null);
  if (q.error) return <ErrorState message={q.error} />;
  if (!q.data) return <Loading rows={5} />;
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {q.data.map((queue) => (
        <Card key={queue.id}>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle>{queue.label}</CardTitle>
            <span className="text-xs text-muted-foreground">{queue.pendientes ? `${queue.pendientes} pendientes` : "al día"}</span>
          </CardHeader>
          <CardContent>
            {queue.items.length === 0 && <p className="text-sm text-muted-foreground">Vacía.</p>}
            <ul className="divide-y divide-border">
              {queue.items.map((it) => (
                <li key={it.path} className="py-2 text-sm">
                  <button onClick={() => setOpen(open === it.path ? null : it.path)} className="flex w-full items-start justify-between gap-2 text-left">
                    <span className="min-w-0"><span className="block truncate">{it.titulo}</span>
                      <span className="text-xs text-muted-foreground">{[it.meta.repo, it.meta.tipo, it.meta.modelo].filter(Boolean).join(" · ")} {timeAgo(new Date(it.mtime * 1000).toISOString())}</span></span>
                    <Badge variant="outline" className={cn("shrink-0", it.estado !== "hechos" && "border-warning/40 text-warning")}>{ESTADO[it.estado]}</Badge>
                  </button>
                  {open === it.path && (
                    <div className="mt-2 space-y-2 text-xs">
                      {it.resumen && <p className="whitespace-pre-wrap text-muted-foreground">{it.resumen}</p>}
                      {it.resultado && <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-lg bg-muted p-2">{it.resultado}</pre>}
                      <Link href={`/conocimiento/?p=${encodeURIComponent(it.path.endsWith(".md") ? it.path : `${it.path}/${it.meta.titulo ? "tarea.md" : "info.md"}`)}`} className="text-primary hover:underline">Abrir la nota</Link>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      ))}
      <p className="text-xs text-muted-foreground lg:col-span-2">Las colas las crea {asistente()} cuando le confirmas un encargo y se procesan solas en segundos (una tarea cada vez). Aquí se consultan; no se aprueban de nuevo.</p>
    </div>
  );
}


export function Temporizadores() {
  const s = useApi<Unit[]>("/system/services", 60_000);
  if (s.error) return <ErrorState message={s.error} />;
  if (!s.data) return <Loading rows={6} />;
  const timers = s.data.filter((u) => u.Id.endsWith(".timer")).map((u) => ({ ...u, next: usecToDate(u.NextElapseUSecRealtime), last: usecToDate(u.LastTriggerUSec) }))
    .sort((x, y) => (x.next ?? "z").localeCompare(y.next ?? "z"));
  const paths = s.data.filter((u) => u.Id.endsWith(".path"));
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader><CardTitle className="flex items-center gap-2"><Clock className="size-4" /> Temporizadores</CardTitle></CardHeader>
        <CardContent><ul className="divide-y divide-border">
          {timers.map((u) => (
            <li key={u.Id} className="py-2 text-sm">
              <div className="flex justify-between gap-2"><span className="truncate">{u.Description.replace(/^Jarvis: /, "")}</span><span className="shrink-0 text-xs">{u.next ? clock(u.next) : "—"}</span></div>
              <div className="flex justify-between gap-2 text-xs text-muted-foreground"><span className="font-mono">{u.Id}</span><span>última: {u.last ? timeAgo(u.last) : "—"}</span></div>
            </li>
          ))}
        </ul></CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Vigilantes de colas</CardTitle></CardHeader>
        <CardContent><ul className="divide-y divide-border">
          {paths.map((u) => <li key={u.Id} className="flex justify-between gap-2 py-2 text-sm"><span className="truncate">{u.Description.replace(/^Jarvis: /, "")}</span><span className="text-xs text-muted-foreground">{u.SubState}</span></li>)}
        </ul>
        <p className="mt-2 text-xs text-muted-foreground">Logs y estado detallado en Monitor.</p></CardContent>
      </Card>
    </div>
  );
}

