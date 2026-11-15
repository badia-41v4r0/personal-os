"use client";

import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

export type Point = { t: string; v: number };

/** Línea de una sola serie (sin leyenda: el título la nombra), 0–100 %, con tooltip y cruz. */
export function PctChart({ data, label }: { data: Point[]; label: string }) {
  return (
    <div className="h-36 w-full" role="img" aria-label={`${label}: ${data.at(-1)?.v.toFixed(0) ?? "—"} %`}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 6, right: 4, bottom: 0, left: -18 }}>
          <defs>
            <linearGradient id={`g-${label}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--chart-1)" stopOpacity={0.25} />
              <stop offset="100%" stopColor="var(--chart-1)" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid vertical={false} stroke="var(--border)" />
          <XAxis dataKey="t" tick={{ fill: "var(--muted-foreground)", fontSize: 10 }} tickLine={false} axisLine={false} minTickGap={40} />
          <YAxis domain={[0, 100]} ticks={[0, 50, 100]} tick={{ fill: "var(--muted-foreground)", fontSize: 10 }} tickLine={false} axisLine={false} />
          <Tooltip
            cursor={{ stroke: "var(--muted-foreground)", strokeDasharray: "3 3" }}
            contentStyle={{ background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }}
            labelStyle={{ color: "var(--muted-foreground)" }}
            itemStyle={{ color: "var(--foreground)" }}
            formatter={(v) => [`${Number(v).toFixed(1)} %`, label]}
          />
          <Area type="monotone" dataKey="v" stroke="var(--chart-1)" strokeWidth={2} fill={`url(#g-${label})`} isAnimationActive={false} dot={false} activeDot={{ r: 4 }} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Medidor con el valor en texto (nunca solo color). */
export function Meter({ label, pct, detail }: { label: string; pct: number; detail?: string }) {
  const tone = pct >= 90 ? "bg-destructive" : pct >= 75 ? "bg-warning" : "bg-primary";
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between gap-2 text-sm">
        <span className="truncate">{label}</span>
        <span className="font-mono text-xs tabular-nums text-muted-foreground">
          {pct.toFixed(0)} %{detail ? ` · ${detail}` : ""}
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-muted" role="meter" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label={label}>
        <div className={`h-full rounded-full ${tone} transition-[width] duration-500`} style={{ width: `${Math.min(pct, 100)}%` }} />
      </div>
    </div>
  );
}
