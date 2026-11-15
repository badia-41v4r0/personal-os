"use client";

import { useEffect, useState } from "react";
import { Cpu, HardDrive, MemoryStick, Thermometer, Timer } from "lucide-react";
import { PageHeader } from "@/components/cc/shell";
import { Meter } from "@/components/cc/spark";
import { Lines } from "@/components/cc/charts";
import { AlertsCard } from "@/components/cc/alerts";
import { StatusDot } from "@/components/cc/status";
import { Empty, ErrorState, Loading } from "@/components/cc/states";
import { ModelUsageCard } from "@/components/cc/claude-usage";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { cn } from "cn";
import { bytes, duration } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Container, Metrics, Unit } from "@/lib/types";
import { unitDetail, unitLevel } from "@/lib/units";
import { asistente } from "@/lib/asistente";

type HPoint = { ts: string; cpu: number | null; mem: number | null; swap: number | null; temp: number | null; gpu: number | null; vram: number | null; gpu_temp: number | null; disk: number | null; net_up: number | null; net_down: number | null };
const RANGES = ["1h", "6h", "24h", "7d", "14d"] as const;

function Stat({ icon: Icon, label, value, sub }: { icon: typeof Cpu; label: string; value: string; sub?: string }) {
  return (
    <Card size="sm">
      <CardContent className="space-y-1">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Icon className="size-3.5" /> {label}
        </div>
        <div className="font-mono text-2xl font-semibold tabular-nums tracking-tight">{value}</div>
        {sub && <div className="truncate text-xs text-muted-foreground">{sub}</div>}
      </CardContent>
    </Card>
  );
}

function Logs({ target, kind }: { target: string; kind: "unit" | "container" }) {
  const [lines, setLines] = useState<string[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    setLines(null);
    setErr(null);
    api<{ lines: string[] }>(`/system/logs/${kind}/${encodeURIComponent(target)}?lines=150`)
      .then((r) => setLines(r.lines))
      .catch((e) => setErr(e.message));
  }, [target, kind]);
  if (err) return <ErrorState message={err} />;
  if (!lines) return <Loading rows={6} />;
  if (!lines.length) return <Empty message="Sin líneas en el registro" />;
  return (
    <pre className="max-h-96 overflow-auto rounded-lg bg-black/40 p-3 font-mono text-[11px] leading-relaxed text-muted-foreground">
      {lines.join("\n")}
    </pre>
  );
}

export default function MonitorPage() {
  const { data: m, error } = useApi<Metrics>("/system/metrics", 5000);
  const services = useApi<Unit[]>("/system/services", 15000);
  const containers = useApi<Container[]>("/system/containers", 15000);
  const [range, setRange] = useState<(typeof RANGES)[number]>("24h");
  const hist = useApi<{ points: HPoint[]; interval_s: number }>(`/system/metrics/history?range=${range}`, 60000);
  const [logs, setLogs] = useState<{ target: string; kind: "unit" | "container" } | null>(null);
  const rows = (hist.data?.points ?? []).map((p) => {
    const d = new Date(p.ts);
    return { ...p, t: range === "7d" || range === "14d" ? d.toLocaleDateString("es-ES", { day: "2-digit", month: "2-digit" }) + " " + d.toLocaleTimeString("es-ES", { hour: "2-digit" }) + "h" : d.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" }) };
  });

  const temp = m ? Math.max(0, ...Object.values(m.temperatures)) : 0;
  const gpu = m?.gpu[0];

  return (
    <>
      <PageHeader title="Monitor" description="Métricas del PC anfitrión (vía Host Agent), servicios y contenedores. Datos reales." />
      {error && <div className="mb-4"><ErrorState message={`Host Agent: ${error}`} /></div>}
      {!m && !error && <Loading rows={4} />}
      {m && (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
            <Stat icon={Cpu} label="CPU" value={`${m.cpu.pct.toFixed(0)} %`} sub={`${m.cpu.count} hilos · carga ${m.cpu.load[0].toFixed(2)}`} />
            <Stat icon={MemoryStick} label="RAM" value={`${m.memory.pct.toFixed(0)} %`} sub={`${bytes(m.memory.used)} de ${bytes(m.memory.total)}`} />
            <Stat icon={MemoryStick} label="Swap" value={`${m.swap.pct.toFixed(0)} %`} sub={`${bytes(m.swap.used)} de ${bytes(m.swap.total)}`} />
            <Stat icon={Thermometer} label="Temperatura" value={temp ? `${temp.toFixed(0)} °C` : "—"} sub={Object.keys(m.temperatures).join(", ") || "sin sensores"} />
            <Stat icon={Cpu} label="GPU" value={gpu ? `${gpu.util_pct.toFixed(0)} %` : "—"} sub={gpu ? `VRAM ${(gpu.vram_used_mb / 1024).toFixed(1)}/${(gpu.vram_total_mb / 1024).toFixed(0)} GB · ${gpu.temp_c} °C` : "no detectada"} />
            <Stat icon={Timer} label="Encendido" value={duration(m.uptime_s)} sub={`red ↑ ${bytes(m.net.bytes_sent)} ↓ ${bytes(m.net.bytes_recv)}`} />
          </div>

          <div className="mt-4"><AlertsCard /></div>

          <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-medium">Historial <span className="text-xs font-normal text-muted-foreground">(una muestra por minuto, 14 días)</span></h2>
            <div className="flex gap-1" role="group" aria-label="Rango">
              {RANGES.map((r) => (
                <button key={r} onClick={() => setRange(r)} aria-pressed={range === r}
                  className={cn("rounded-md px-2.5 py-1 text-xs ring-1 ring-border", range === r && "bg-primary/15 text-primary ring-primary/30")}>{r}</button>
              ))}
            </div>
          </div>
          {hist.error && <ErrorState message={hist.error} />}
          {hist.data && rows.length < 2 && <Empty message="Aún no hay historial: se guarda una muestra cada minuto desde que arrancó el panel." />}
          {rows.length >= 2 && (
            <div className="mt-2 grid gap-4 lg:grid-cols-2">
              <Card><CardHeader><CardTitle>CPU (%)</CardTitle></CardHeader><CardContent><Lines data={rows} x="t" unit=" %" label="CPU" series={[{ key: "cpu", name: "CPU" }]} /></CardContent></Card>
              <Card><CardHeader><CardTitle>Memoria (%)</CardTitle></CardHeader><CardContent><Lines data={rows} x="t" unit=" %" label="Memoria" series={[{ key: "mem", name: "RAM" }, { key: "swap", name: "Swap", dashed: true }]} /></CardContent></Card>
              <Card><CardHeader><CardTitle>Temperatura (°C)</CardTitle></CardHeader><CardContent><Lines data={rows} x="t" unit=" °C" label="Temperatura" series={[{ key: "temp", name: "CPU" }, { key: "gpu_temp", name: "GPU", dashed: true }]} /></CardContent></Card>
              <Card><CardHeader><CardTitle>Red (KB/s)</CardTitle></CardHeader><CardContent><Lines data={rows} x="t" unit=" KB/s" label="Red" series={[{ key: "net_down", name: "Bajada" }, { key: "net_up", name: "Subida", dashed: true }]} /></CardContent></Card>
            </div>
          )}

          <div className="mt-4 grid gap-4 lg:grid-cols-3">
            <Card>
              <CardHeader><CardTitle className="flex items-center gap-2"><HardDrive className="size-4" /> Discos</CardTitle></CardHeader>
              <CardContent className="space-y-3">
                {m.disks.map((d) => (
                  <Meter key={d.mount} label={d.mount} pct={d.pct} detail={`${bytes(d.free)} libres`} />
                ))}
              </CardContent>
            </Card>
            <Card className="lg:col-span-2">
              <CardHeader><CardTitle>Procesos con más memoria</CardTitle></CardHeader>
              <CardContent>
                <div className="divide-y divide-border text-sm">
                  {m.top_processes.map((p) => (
                    <div key={p.pid} className="flex items-center justify-between gap-3 py-1.5">
                      <span className="truncate">{p.name} <span className="text-xs text-muted-foreground">#{p.pid}</span></span>
                      <span className="font-mono text-xs tabular-nums text-muted-foreground">{bytes(p.rss)}</span>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </div>
        </>
      )}

      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <ModelUsageCard />
        <Card>
          <CardHeader><CardTitle>Servicios y timers de {asistente()}</CardTitle></CardHeader>
          <CardContent>
            {services.error && <ErrorState message={services.error} />}
            {services.loading && <Loading rows={6} />}
            <div className="divide-y divide-border">
              {services.data?.map((u) => (
                <div key={u.Id} className="flex items-center justify-between gap-3 py-2">
                  <div className="flex min-w-0 items-center gap-2.5">
                    <StatusDot level={unitLevel(u)} />
                    <div className="min-w-0">
                      <div className="truncate font-mono text-xs">{u.Id}</div>
                      <div className="truncate text-xs text-muted-foreground">{u.Description}</div>
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <span className="text-xs text-muted-foreground">{unitDetail(u)}</span>
                    {u.scope === "user" && u.Id.endsWith(".service") && (
                      <Button variant="ghost" size="xs" onClick={() => setLogs({ target: u.Id, kind: "unit" })}>Logs</Button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
        <div className="space-y-4">
          <Card>
            <CardHeader><CardTitle>Contenedores Docker</CardTitle></CardHeader>
            <CardContent>
              {containers.error && <ErrorState message={containers.error} />}
              {containers.loading && <Loading rows={4} />}
              <div className="divide-y divide-border">
                {containers.data?.filter((c) => c.State === "running" || c.Names.startsWith("jarvis")).map((c) => (
                  <div key={c.ID} className="flex items-center justify-between gap-3 py-2">
                    <div className="flex min-w-0 items-center gap-2.5">
                      <StatusDot level={c.State === "running" ? (c.Status.includes("unhealthy") ? "down" : "ok") : "down"} />
                      <span className="truncate font-mono text-xs">{c.Names}</span>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      <span className="text-xs text-muted-foreground">{c.Status}</span>
                      {/^jarvis(-vc-.+)?$/.test(c.Names) && (
                        <Button variant="ghost" size="xs" onClick={() => setLogs({ target: c.Names, kind: "container" })}>Logs</Button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
              <p className="mt-2 text-xs text-muted-foreground">Se muestran los que están en marcha y los de {asistente()}. Logs solo de los de {asistente()}.</p>
            </CardContent>
          </Card>
          {logs && (
            <Card>
              <CardHeader className="flex flex-row items-center justify-between">
                <CardTitle className="font-mono text-sm">{logs.target}</CardTitle>
                <Button variant="ghost" size="xs" onClick={() => setLogs(null)}>Cerrar</Button>
              </CardHeader>
              <CardContent><Logs {...logs} /></CardContent>
            </Card>
          )}
        </div>
      </div>
    </>
  );
}
