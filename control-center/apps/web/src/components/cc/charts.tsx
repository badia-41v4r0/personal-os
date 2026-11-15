"use client";

import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

const axis = { fill: "var(--muted-foreground)", fontSize: 10 };
const tip = {
  contentStyle: { background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 },
  labelStyle: { color: "var(--muted-foreground)" },
  itemStyle: { color: "var(--foreground)" },
};

/** Barras verticales de una serie (el título de la tarjeta la nombra). */
export function Bars({ data, x, y, unit = "", height = 180, label }: {
  data: Record<string, unknown>[]; x: string; y: string; unit?: string; height?: number; label: string;
}) {
  return (
    <div style={{ height }} className="w-full" role="img" aria-label={label}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 6, right: 4, bottom: 0, left: -12 }}>
          <CartesianGrid vertical={false} stroke="var(--border)" />
          <XAxis dataKey={x} tick={axis} tickLine={false} axisLine={false} />
          <YAxis tick={axis} tickLine={false} axisLine={false} />
          <Tooltip {...tip} cursor={{ fill: "var(--muted)", opacity: 0.4 }} formatter={(v) => [`${Number(v).toLocaleString("es-ES")}${unit}`, label]} />
          <Bar dataKey={y} fill="var(--chart-1)" radius={[4, 4, 0, 0]} maxBarSize={36} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Barras horizontales ordenadas (p. ej. series por músculo). */
export function HBars({ data, label, unit = "" }: { data: { name: string; value: number }[]; label: string; unit?: string }) {
  return (
    <div style={{ height: Math.max(120, data.length * 26) }} className="w-full" role="img" aria-label={label}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ top: 0, right: 16, bottom: 0, left: 8 }}>
          <CartesianGrid horizontal={false} stroke="var(--border)" />
          <XAxis type="number" tick={axis} tickLine={false} axisLine={false} />
          <YAxis type="category" dataKey="name" tick={{ ...axis, fontSize: 11 }} tickLine={false} axisLine={false} width={92} />
          <Tooltip {...tip} cursor={{ fill: "var(--muted)", opacity: 0.4 }} formatter={(v) => [`${Number(v).toLocaleString("es-ES")}${unit}`, label]} />
          <Bar dataKey="value" fill="var(--chart-1)" radius={[0, 4, 4, 0]} barSize={14} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Líneas con la misma unidad (un solo eje). Con 2+ series hay leyenda. */
export function Lines({ data, x, series, unit = "", height = 200, label, curve = "monotone" }: {
  data: Record<string, unknown>[]; x: string; series: { key: string; name: string; dashed?: boolean }[];
  unit?: string; height?: number; label: string; curve?: "monotone" | "linear";
}) {
  const colors = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)"];
  return (
    <div style={{ height }} className="w-full" role="img" aria-label={label}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 6, right: 8, bottom: 0, left: -12 }}>
          <CartesianGrid vertical={false} stroke="var(--border)" />
          <XAxis dataKey={x} tick={axis} tickLine={false} axisLine={false} minTickGap={24} />
          <YAxis tick={axis} tickLine={false} axisLine={false} domain={["auto", "auto"]} />
          <Tooltip {...tip} cursor={{ stroke: "var(--muted-foreground)", strokeDasharray: "3 3" }} formatter={(v, n) => [v == null ? "—" : `${Number(v).toLocaleString("es-ES")}${unit}`, n]} />
          {series.length > 1 && <Legend wrapperStyle={{ fontSize: 11, color: "var(--muted-foreground)" }} iconType="plainline" />}
          {series.map((s, i) => (
            <Line key={s.key} type={curve} dataKey={s.key} name={s.name} stroke={colors[i]} strokeWidth={2}
              strokeDasharray={s.dashed ? "5 4" : undefined} dot={{ r: 3 }} activeDot={{ r: 5 }} connectNulls isAnimationActive={false} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
