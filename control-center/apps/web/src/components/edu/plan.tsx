"use client";

import { useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "cn";
import { Empty, ErrorState, Loading } from "@/components/cc/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useApi } from "@/lib/hooks";
import { Chip, DIAS, diaSemana, fecha, type Dia } from "./common";

type Plan = { desde: string; dias: Dia[] };
const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const sumar = (f: string, n: number) => { const d = new Date(f + "T12:00:00"); d.setDate(d.getDate() + n); return iso(d); };
const lunesDe = (f: string) => { const d = new Date(f + "T12:00:00"); d.setDate(d.getDate() - ((d.getDay() + 6) % 7)); return iso(d); };

function DiaSemana({ d, hoy }: { d: Dia; hoy: string }) {
  const esHoy = d.dia === hoy;
  return (
    <Card className={cn(esHoy && "ring-1 ring-primary/50")}>
      <CardContent className="space-y-2 py-3">
        <div className="flex items-baseline justify-between"><span className="text-sm font-semibold first-letter:uppercase">{diaSemana(d.dia)} {fecha(d.dia)}</span>{esHoy && <span className="text-xs text-primary">hoy</span>}</div>
        {d.entregas.map((e) => (
          <div key={e.clave} className={cn("rounded-md border px-2 py-1.5 text-xs", e.hecha ? "border-border text-muted-foreground line-through" : e.dias <= 2 ? "border-destructive/40 bg-destructive/5" : "border-amber-500/40 bg-amber-500/5")}>
            <div className="flex items-center gap-1.5"><Chip code={e.asig} /><span className="font-medium">Entrega {e.hora}</span></div>
            <div className="mt-0.5">{e.texto.replace(/^[^:]+:\s*/, "")}</div>
          </div>
        ))}
        {d.bloques.length === 0 && d.entregas.length === 0 && <p className="text-xs text-muted-foreground">Libre</p>}
        {d.bloques.map((b) => (
          <div key={b.clave} className={cn("flex items-start gap-2 text-xs", b.hecho && "text-muted-foreground line-through")}>
            <span className="w-[4.2rem] shrink-0 tabular-nums text-muted-foreground">{b.hora.slice(0, 5)}</span>
            <span className="min-w-0 flex-1"><Chip code={b.asig} className="mr-1" />{b.texto.replace(/^[A-Z]+ · /, "")}</span>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function Mes({ plan, hoy, mes }: { plan: Plan; hoy: string; mes: string }) {
  const por = new Map(plan.dias.map((d) => [d.dia, d]));
  const primero = `${mes}-01`;
  const ini = lunesDe(primero);
  const celdas = Array.from({ length: 42 }, (_, i) => sumar(ini, i));
  return (
    <div role="grid" aria-label="Calendario del mes" className="grid grid-cols-7 gap-px overflow-hidden rounded-lg border border-border bg-border text-xs">
      {DIAS.map((d) => <div key={d} className="bg-muted/60 px-1 py-1 text-center font-medium text-muted-foreground">{d}</div>)}
      {celdas.map((f) => {
        const d = por.get(f);
        const fuera = f.slice(0, 7) !== mes;
        const hechos = d?.bloques.filter((b) => b.hecho).length ?? 0;
        return (
          <div key={f} role="gridcell" className={cn("min-h-16 bg-card p-1 sm:min-h-24", fuera && "opacity-40", f === hoy && "ring-1 ring-inset ring-primary")}>
            <div className="tabular-nums text-muted-foreground">{Number(f.slice(8))}</div>
            {d?.entregas.map((e) => <div key={e.clave} className={cn("mt-0.5 truncate rounded px-1", e.hecha ? "text-muted-foreground line-through" : "bg-amber-500/15")} title={e.texto}>{e.asig || "·"} {e.hora}</div>)}
            {d && d.bloques.length > 0 && (
              <div className="mt-0.5 flex flex-wrap gap-0.5" aria-label={`${d.bloques.length} bloques, ${hechos} hechos`}>
                {d.bloques.map((b) => <span key={b.clave} title={b.texto} className={cn("rounded px-0.5 text-[10px] leading-4", b.hecho ? "bg-muted text-muted-foreground line-through" : "bg-primary/15")}>{b.asig || "·"}</span>)}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

export function PlanTab({ hoy }: { hoy: string }) {
  const [vista, setVista] = useState<"semana" | "mes">("semana");
  const [ancla, setAncla] = useState(hoy);
  const mes = ancla.slice(0, 7);
  const lunes = lunesDe(ancla);
  const desde = vista === "semana" ? lunes : lunesDe(`${mes}-01`);
  const dias = vista === "semana" ? 7 : 42;
  const p = useApi<Plan>(`/education/plan?desde=${desde}&dias=${dias}`);
  const mover = (n: number) => {
    if (vista === "semana") return setAncla(sumar(ancla, 7 * n));
    const d = new Date(`${mes}-15T12:00:00`);
    d.setMonth(d.getMonth() + n);
    setAncla(iso(d));
  };
  const titulo = vista === "semana" ? `Semana del ${fecha(lunes)} al ${fecha(sumar(lunes, 6))}` : new Date(`${mes}-15T12:00:00`).toLocaleDateString("es-ES", { month: "long", year: "numeric" });
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Button size="icon-sm" variant="outline" aria-label="Anterior" onClick={() => mover(-1)}><ChevronLeft /></Button>
        <Button size="icon-sm" variant="outline" aria-label="Siguiente" onClick={() => mover(1)}><ChevronRight /></Button>
        <Button size="sm" variant="ghost" onClick={() => setAncla(hoy)}>Hoy</Button>
        <h2 className="min-w-0 flex-1 text-sm font-semibold first-letter:uppercase">{titulo}</h2>
        <div className="flex rounded-lg bg-muted p-0.5" role="group" aria-label="Vista">
          {(["semana", "mes"] as const).map((v) => <button key={v} type="button" aria-pressed={vista === v} onClick={() => setVista(v)} className={cn("rounded-md px-3 py-1 text-sm capitalize", vista === v ? "bg-background shadow-sm" : "text-muted-foreground")}>{v}</button>)}
        </div>
      </div>
      {p.error && <ErrorState message={p.error} />}
      {p.loading && !p.data && <Loading rows={5} />}
      {p.data && vista === "semana" && <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">{p.data.dias.map((d) => <DiaSemana key={d.dia} d={d} hoy={hoy} />)}</div>}
      {p.data && vista === "mes" && <Mes plan={p.data} hoy={hoy} mes={mes} />}
      {p.data && p.data.dias.every((d) => !d.bloques.length && !d.entregas.length) && <Empty message="No hay nada planificado en este periodo." />}
      <p className="text-xs text-muted-foreground">Entregas en ámbar (rojo si faltan 2 días o menos). El plan se recalcula con «Reprogramar desde hoy», en la pestaña Hoy.</p>
    </div>
  );
}
