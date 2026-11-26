"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { cn } from "cn";
import { usePanel } from "./shell";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { timeAgo, until } from "@/lib/format";
import { useApi } from "@/lib/hooks";

type Window = { name: string; utilization: number; resets_at: string | null };
type Item = { provider: string; model: string; available: boolean; ts?: string; windows: Window[] };

const MOTORES: [string, string][] = [
  ["claude", "Claude"],
  ["antigravity-flash", "Flash"],
  ["antigravity-opus", "Opus"],
  ["codex-terra", "Codex"],
];
const VIEJO = 24 * 3600_000; // un dato de hace más de un día se atenúa

function periodo(name: string) {
  if (name === "five_hour") return "Sesión (5 h)";
  if (name === "seven_day" || name === "weekly") return "Semanal";
  if (name === "monthly") return "Mensual";
  if (name === "daily") return "Diaria";
  return name.replaceAll("_", " ");
}

function Anillo({ pct, aviso }: { pct: number; aviso: boolean }) {
  const r = 11, c = 2 * Math.PI * r;
  return (
    <svg viewBox="0 0 26 26" className="size-[26px]" aria-hidden>
      <circle cx="13" cy="13" r={r} fill="none" strokeWidth="3" className="stroke-muted" />
      <circle cx="13" cy="13" r={r} fill="none" strokeWidth="3" strokeLinecap="round" strokeDasharray={c}
        strokeDashoffset={c * (1 - Math.min(pct, 100) / 100)} transform="rotate(-90 13 13)"
        className={cn("transition-[stroke-dashoffset] duration-500", aviso ? "stroke-amber-500" : "stroke-primary")} />
      <text x="13" y="16" textAnchor="middle" className="fill-foreground text-[8.5px] tabular-nums">{Math.round(pct)}</text>
    </svg>
  );
}

/** Consumo de cada motor en la barra lateral: la ventana más llena; el detalle, al pasar el ratón. */
export function ConsumoMotores() {
  const { lastEvent } = usePanel();
  const u = useApi<{ providers: Record<string, Item> }>("/models/usage", 120_000);
  useEffect(() => {
    if (lastEvent?.type === "models.usage" || lastEvent?.type === "claude.usage") u.reload();
  }, [lastEvent]); // eslint-disable-line react-hooks/exhaustive-deps
  const [ahora, setAhora] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setAhora(Date.now()), 60_000);
    return () => clearInterval(t);
  }, []);

  const motores = MOTORES.map(([key, corto]) => ({ key, corto, item: u.data?.providers[key] }))
    .filter((m): m is typeof m & { item: Item } => !!m.item?.windows?.length);
  if (!motores.length) return null;

  return (
    <div className="flex justify-between gap-1" role="group" aria-label="Consumo de los motores">
      {motores.map(({ key, corto, item }) => {
        const pct = Math.max(...item.windows.map((w) => w.utilization)) * 100;
        const viejo = !item.ts || ahora - new Date(item.ts).getTime() > VIEJO;
        return (
          <Tooltip key={key}>
            <TooltipTrigger
              render={<Link href="/ajustes/sistema/" />}
              aria-label={`${item.provider} · ${item.model}: ${Math.round(pct)} % consumido`}
              className={cn("flex flex-1 flex-col items-center gap-0.5 rounded-md py-1 text-[10px] hover:bg-sidebar-accent", viejo && "opacity-55")}
            >
              <Anillo pct={pct} aviso={pct >= 85} />
              {corto}
            </TooltipTrigger>
            <TooltipContent side="top" className="flex-col items-start gap-0.5">
              <span className="font-semibold">{item.provider} · {item.model}</span>
              {item.windows.map((w) => (
                <span key={w.name}>
                  {periodo(w.name)}: {Math.round(w.utilization * 100)} %{w.resets_at && ` · reinicia ${until(w.resets_at)}`}
                </span>
              ))}
              <span className="opacity-70">Medido {timeAgo(item.ts)}</span>
            </TooltipContent>
          </Tooltip>
        );
      })}
    </div>
  );
}
