"use client";

import Link from "next/link";
import { useEffect, useMemo } from "react";
import { CalendarDays, Dumbbell, ListChecks, ShieldCheck } from "lucide-react";
import { PageHeader, usePanel } from "@/components/cc/shell";
import { Meter } from "@/components/cc/spark";
import { AlertsCard } from "@/components/cc/alerts";
import { ModelUsageCard } from "@/components/cc/claude-usage";
import { StatusDot, StatusRow, type Level } from "@/components/cc/status";
import { Empty, ErrorState, Loading } from "@/components/cc/states";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { bytes, clock, duration, timeAgo } from "@/lib/format";
import { useApi, type BusEvent } from "@/lib/hooks";
import type { Container, Health, Metrics, TranscriptItem, Unit } from "@/lib/types";
import { unitLevel } from "@/lib/units";
import { asistente } from "@/lib/asistente";

type MainState = { current_run: string | null; queued: number; tmux: boolean | null };
type Run = { id: string; status: string };

const EVENT_LABEL = (): Record<string, string> => ({
  "backend.started": "Backend arrancado",
  "run.queued": "Mensaje del panel en cola",
  "run.started": `Mensaje enviado a ${asistente()}`,
  "run.finished": `${asistente()} terminó de responder`,
  "run.interrupted": "Ejecución interrumpida",
  "session.created": "Conversación nueva",
  "agent.created": "Agente creado",
  "agent.updated": "Agente editado",
  "agent.activated": "Agente activado",
  "agent.deactivated": "Agente desactivado",
  "agent.deleted": "Agente eliminado",
  "vc.created": "Ordenador virtual creado",
  "vc.deleted": "Ordenador virtual eliminado",
  "vc.start": "Ordenador virtual iniciado",
  "vc.stop": "Ordenador virtual detenido",
  "vc.restart": "Ordenador virtual reiniciado",
  "vc.disk_limit": "Ordenador parado por disco",
  "alert.raised": "Alerta",
  "alert.resolved": "Alerta resuelta",
  "approval.decided": "Aprobación decidida",
  "memory.saved": "Nota editada en el panel",
  "tasks.changed": "Tarea marcada desde el panel",
  "claude.usage": "Uso de Claude",
});
// Eventos internos que no aportan en el timeline
const HIDDEN = new Set(["chat.updated", "claude.usage", "vc.running", "vc.stopped", "vc.registered"]);

function lvl(ok: boolean | null | undefined): Level {
  return ok == null ? "unknown" : ok ? "ok" : "down";
}

export default function Dashboard() {
  const { lastEvent } = usePanel();
  const health = useApi<Health>("/health", 15000);
  const state = useApi<MainState>("/sessions/main/state", 10000);
  const metrics = useApi<Metrics>("/system/metrics", 10000);
  const services = useApi<Unit[]>("/system/services", 30000);
  const containers = useApi<Container[]>("/system/containers", 30000);
  const timeline = useApi<BusEvent[]>("/events/recent?limit=60");
  const chat = useApi<{ items: TranscriptItem[] }>("/sessions/main/messages?limit=400", 30000);
  const runs = useApi<Run[]>("/agents/runs?limit=50", 30000);
  const appr = useApi<{ pendientes: unknown[] }>("/approvals", 120000);
  const queues = useApi<{ pendientes: number }[]>("/queues", 60000);
  const vcsList = useApi<{ live: { state: string } | null }[]>("/virtual-computers", 60000);
  const tasks = useApi<{ pendientes: { texto: string; fecha: string | null; atrasada?: boolean }[] }>("/tasks", 60000);
  const agenda = useApi<{ hoy: string; calendario: { eventos: { id: string; titulo: string; dia: string; inicio: string | null }[]; error: string | null }; uni: { entregas?: { fecha: string; hora: string; texto: string }[] } }>("/agenda?dias=7", 300000);

  useEffect(() => {
    if (lastEvent && !HIDDEN.has(lastEvent.type)) timeline.reload();
    if (lastEvent?.type.startsWith("run.")) {
      runs.reload();
      state.reload();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastEvent]);

  const jarvisContainer = containers.data?.find((c) => c.Names === "jarvis");
  const failed = services.data?.filter((u) => unitLevel(u) === "down") ?? [];
  const lastTelegram = useMemo(
    () => [...(chat.data?.items ?? [])].reverse().find((i) => i.kind === "message" && i.channel === "telegram"),
    [chat.data],
  );
  const recentMessages = useMemo(
    () => (chat.data?.items ?? []).filter((i) => i.kind === "message" && i.role !== "system").slice(-5).reverse(),
    [chat.data],
  );
  const activity = (timeline.data ?? []).filter((e) => !HIDDEN.has(e.type)).slice(0, 12);
  const running = (runs.data ?? []).filter((r) => r.status === "running" || r.status === "queued").length;

  const overall: Level =
    health.data?.host_agent === "down" || state.data?.tmux === false || jarvisContainer?.State !== "running"
      ? "down"
      : failed.length
        ? "warn"
        : health.data
          ? "ok"
          : "unknown";

  return (
    <>
      <PageHeader
        title="Sistema"
        description={`Estado de ${asistente()} y del PC en tiempo real.`}
        actions={
          <div className="flex items-center gap-2 rounded-full border border-border px-3 py-1 text-xs">
            <StatusDot level={overall} pulse />
            {overall === "ok" ? "Todo en orden" : overall === "warn" ? "Hay avisos" : overall === "down" ? "Algo no responde" : "Comprobando…"}
          </div>
        }
      />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Card>
          <CardHeader><CardTitle>Componentes</CardTitle></CardHeader>
          <CardContent className="divide-y divide-border">
            <StatusRow label={`${asistente()} (contenedor)`} level={lvl(jarvisContainer ? jarvisContainer.State === "running" : containers.data ? false : null)} detail={jarvisContainer?.Status} />
            <StatusRow label="Claude Code (tmux)" level={lvl(state.data?.tmux)} detail={state.data?.current_run ? "trabajando" : state.data?.tmux ? "en espera" : undefined} />
            <StatusRow label="Telegram" level={lastTelegram ? "ok" : "unknown"} detail={lastTelegram ? `último: ${timeAgo(lastTelegram.ts)}` : "sin mensajes en esta sesión"} />
            <StatusRow label="Backend" level={lvl(health.data?.backend === "ok")} />
            <StatusRow label="Frontend" level="ok" detail="sirviendo esta página" />
            <StatusRow label="Host Agent" level={lvl(health.data ? health.data.host_agent === "ok" : null)} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Actividad</CardTitle></CardHeader>
          <CardContent className="grid grid-cols-2 gap-4">
            {[
              ["Agentes activos", state.data?.tmux ? "1" : "0", `${asistente()}`],
              ["Ejecuciones en curso", String(running), "del panel"],
              ["Servicios con fallos", String(failed.length), failed.map((f) => f.Id).join(", ") || "ninguno"],
              ["Ordenadores virtuales", String(vcsList.data?.filter((v) => v.live?.state === "running").length ?? "—"), `${vcsList.data?.length ?? 0} creados`],
            ].map(([k, v, s]) => (
              <div key={k} className="min-w-0">
                <div className="font-mono text-2xl font-semibold tabular-nums">{v}</div>
                <div className="text-xs">{k}</div>
                <div className="truncate text-[11px] text-muted-foreground" title={s}>{s}</div>
              </div>
            ))}
          </CardContent>
        </Card>

        <ModelUsageCard />

        <Card>
          <CardHeader><CardTitle>Ordenador anfitrión</CardTitle></CardHeader>
          <CardContent>
            {metrics.error && <ErrorState message={metrics.error} />}
            {!metrics.data && !metrics.error && <Loading rows={3} />}
            {metrics.data && (
              <div className="grid gap-3">
                <Meter label="CPU" pct={metrics.data.cpu.pct} />
                <Meter label="RAM" pct={metrics.data.memory.pct} detail={`${bytes(metrics.data.memory.available)} libres`} />
                <Meter label="Swap" pct={metrics.data.swap.pct} />
                {metrics.data.gpu[0] && (
                  <Meter label="VRAM" pct={(100 * metrics.data.gpu[0].vram_used_mb) / metrics.data.gpu[0].vram_total_mb} detail={`${metrics.data.gpu[0].temp_c} °C`} />
                )}
                {metrics.data.disks.slice(0, 1).map((d) => (
                  <Meter key={d.mount} label={`Disco ${d.mount}`} pct={d.pct} detail={`${bytes(d.free)} libres`} />
                ))}
                <p className="text-xs text-muted-foreground">Encendido desde hace {duration(metrics.data.uptime_s)} · <Link href="/ajustes/monitor/" className="text-primary hover:underline">Ver monitor</Link></p>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="mt-4"><AlertsCard compact /></div>

      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle>Últimos mensajes</CardTitle>
            <Link href="/conversaciones/" className="-my-1 py-1 text-xs text-primary hover:underline">Abrir chat</Link>
          </CardHeader>
          <CardContent>
            {chat.loading && <Loading rows={4} />}
            {chat.data && recentMessages.length === 0 && <Empty message="Sin mensajes en la sesión actual" />}
            <ul className="divide-y divide-border">
              {recentMessages.map((m) => (
                <li key={m.uuid} className="flex gap-3 py-2 text-sm">
                  <span className="w-16 shrink-0 text-xs text-muted-foreground">{clock(m.ts).split(" ")[1] ?? ""}</span>
                  <span className="w-16 shrink-0 text-xs text-muted-foreground">{m.role === "user" ? "Tú" : `${asistente()}`}</span>
                  <span className="line-clamp-2 min-w-0 flex-1">{m.text}</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Cronología</CardTitle></CardHeader>
          <CardContent>
            {timeline.loading && <Loading rows={4} />}
            {timeline.data && activity.length === 0 && <Empty message="Sin actividad registrada todavía" />}
            <ol className="relative space-y-3 border-l border-border pl-4">
              {activity.map((e) => (
                <li key={e.id} className="text-sm">
                  <span className="absolute -left-[4.5px] mt-1.5 size-2 rounded-full bg-primary/60" />
                  <div>{EVENT_LABEL()[e.type] ?? e.type}{typeof e.payload.title === "string" ? `: ${e.payload.title}` : ""}</div>
                  <div className="text-[11px] text-muted-foreground">
                    {timeAgo(e.ts)}
                    {typeof e.payload.status === "string" ? ` · ${e.payload.status}` : ""}
                  </div>
                </li>
              ))}
            </ol>
          </CardContent>
        </Card>
      </div>

      <div className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Link href="/tareas/" className="group rounded-xl border border-border p-4 transition-colors hover:border-primary/40">
          <div className="flex items-center justify-between text-sm">
            <span className="flex items-center gap-2"><ListChecks className="size-4 text-primary" />Tareas pendientes</span>
            <span className="font-mono text-lg font-semibold tabular-nums">{tasks.data?.pendientes.length ?? "—"}</span>
          </div>
          <ul className="mt-2 space-y-0.5 text-xs text-muted-foreground">
            {tasks.data?.pendientes.slice(0, 3).map((t, i) => <li key={i} className={`truncate ${t.atrasada ? "text-warning" : ""}`}>{t.fecha ? `${t.fecha.slice(5)} · ` : ""}{t.texto}</li>)}
          </ul>
        </Link>
        <Link href="/bandeja/" className="group rounded-xl border border-border p-4 transition-colors hover:border-primary/40">
          <div className="flex items-center justify-between text-sm">
            <span className="flex items-center gap-2"><ShieldCheck className="size-4 text-primary" />Aprobaciones</span>
            <span className="font-mono text-lg font-semibold tabular-nums">{appr.data?.pendientes.length ?? "—"}</span>
          </div>
          <p className="mt-2 text-xs text-muted-foreground">
            {appr.data ? (appr.data.pendientes.length ? `Propuestas de ${asistente()} esperando tu revisión` : "Nada pendiente") : "Cargando…"}
            {queues.data && ` · ${queues.data.reduce((n, q) => n + q.pendientes, 0)} tareas en cola`}
          </p>
        </Link>
        <Link href="/agenda/" className="group rounded-xl border border-border p-4 transition-colors hover:border-primary/40">
          <div className="flex items-center gap-2 text-sm"><CalendarDays className="size-4 text-primary" />Próximos eventos</div>
          {agenda.data?.calendario.error && <p className="mt-2 text-xs text-warning">{agenda.data.calendario.error}</p>}
          <ul className="mt-2 space-y-0.5 text-xs text-muted-foreground">
            {[...(agenda.data?.uni.entregas ?? []).map((e) => ({ k: `e${e.fecha}${e.texto}`, d: e.fecha, t: `📌 ${e.texto}` })),
              ...(agenda.data?.calendario.eventos ?? []).map((e) => ({ k: e.id, d: e.dia, t: `${e.inicio ? e.inicio + " " : ""}${e.titulo}` }))]
              .sort((x, y) => x.d.localeCompare(y.d)).slice(0, 4)
              .map((x) => <li key={x.k} className="truncate">{x.d.slice(5)} · {x.t}</li>)}
            {agenda.data && !agenda.data.calendario.eventos.length && !agenda.data.uni.entregas?.length && <li>Nada en 7 días</li>}
          </ul>
        </Link>
        <Link href="/entrenamiento/" className="rounded-xl border border-border p-4 text-sm hover:border-primary/40"><span className="flex items-center gap-2"><Dumbbell className="size-4 text-primary" />Gimnasio</span><p className="mt-2 text-xs text-muted-foreground">Historial, progresión y músculos</p></Link>
      </div>
    </>
  );
}
