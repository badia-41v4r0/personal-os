"use client";

import { useMemo, useState } from "react";
import { cn } from "cn";
import { PageHeader } from "@/components/cc/shell";
import { TaskCheck } from "@/components/cc/task-check";
import { ErrorState, Loading } from "@/components/cc/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useAct } from "@/components/cc/form";
import { Pencil, Trash2 } from "lucide-react";
import { api, post } from "@/lib/api";
import { useApi } from "@/lib/hooks";

type Tarea = { id: number; texto: string; fecha: string | null; area: string; hecho: boolean; hecho_el: string | null; atrasada?: boolean };
type Tasks = { pendientes: Tarea[]; hechas: Tarea[]; areas: Record<string, string>; fuente: string };

function NewTask({ areas, onDone }: { areas: Record<string, string>; onDone: () => void }) {
  const [texto, setTexto] = useState("");
  const [fecha, setFecha] = useState("");
  const [area, setArea] = useState("personal");
  const act = useAct(onDone);
  const crear = () => act.run(async () => {
    await post("/tasks", { texto, fecha: fecha || null, area });
    setTexto("");
    setFecha("");
  });
  return (
    <form className="mb-3 grid gap-2 sm:grid-cols-[1fr_9rem_10rem_auto]" onSubmit={(e) => { e.preventDefault(); if (texto.trim()) void crear(); }}>
      <Input value={texto} maxLength={300} onChange={(e) => setTexto(e.target.value)} placeholder="Nueva tarea…" aria-label="Nueva tarea" />
      <Input type="date" value={fecha} onChange={(e) => setFecha(e.target.value)} aria-label="Fecha (opcional)" />
      <select value={area} onChange={(e) => setArea(e.target.value)} aria-label="Área" className="h-9 rounded-md border border-input bg-background px-2 text-sm">
        {Object.entries(areas).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
      </select>
      <Button type="submit" size="sm" disabled={act.busy || !texto.trim()}>{act.busy ? "Guardando…" : "Añadir"}</Button>
      {act.error && <div className="sm:col-span-4">{act.ErrorBox}</div>}
    </form>
  );
}

// Una tarea pendiente: casilla, y a la derecha editar (en la propia fila) y borrar (con confirmación en la fila).
function TaskRow({ t, areas, onDone }: { t: Tarea; areas: Record<string, string>; onDone: () => void }) {
  const [modo, setModo] = useState<"ver" | "editar" | "borrar">("ver");
  const [texto, setTexto] = useState(t.texto);
  const [fecha, setFecha] = useState(t.fecha ?? "");
  const [area, setArea] = useState(t.area);
  const act = useAct(() => { setModo("ver"); onDone(); });
  const editar = () => { setTexto(t.texto); setFecha(t.fecha ?? ""); setArea(t.area); setModo("editar"); };
  const guardar = () => act.run(() => api(`/tasks/${t.id}`, { method: "PATCH", body: JSON.stringify({ texto, fecha: fecha || null, area }) }));
  const borrar = () => act.run(() => api(`/tasks/${t.id}`, { method: "DELETE" }));

  if (modo === "editar") {
    return (
      <li className="py-2">
        <form className="grid gap-2 sm:grid-cols-[1fr_9rem_10rem_auto]" onSubmit={(e) => { e.preventDefault(); if (texto.trim()) void guardar(); }}
          onKeyDown={(e) => { if (e.key === "Escape") setModo("ver"); }}>
          <Input value={texto} maxLength={300} onChange={(e) => setTexto(e.target.value)} aria-label="Texto de la tarea" autoFocus />
          <Input type="date" value={fecha} onChange={(e) => setFecha(e.target.value)} aria-label="Fecha (vacía: sin fecha)" />
          <select value={area} onChange={(e) => setArea(e.target.value)} aria-label="Área" className="h-9 rounded-md border border-input bg-background px-2 text-sm">
            {Object.entries(areas).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            {!(area in areas) && <option value={area}>{area}</option>}
          </select>
          <span className="flex gap-1">
            <Button type="submit" size="sm" disabled={act.busy || !texto.trim()}>{act.busy ? "Guardando…" : "Guardar"}</Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => setModo("ver")} disabled={act.busy}>Cancelar</Button>
          </span>
          {act.error && <div className="sm:col-span-4">{act.ErrorBox}</div>}
        </form>
      </li>
    );
  }
  return (
    <li className="group/row py-2 text-sm">
      <div className="flex items-start justify-between gap-3">
        <span className="flex min-w-0 items-start gap-2.5"><TaskCheck texto={t.texto} onDone={onDone} className="mt-0.5" /><span className={cn(t.atrasada && "text-warning")}>{t.texto}</span></span>
        <span className="flex shrink-0 items-center gap-2">
          {modo === "borrar" ? (
            <span className="flex items-center gap-1 text-xs">
              ¿Borrar?
              <Button type="button" size="xs" variant="destructive" onClick={() => void borrar()} disabled={act.busy}>{act.busy ? "Borrando…" : "Sí"}</Button>
              <Button type="button" size="xs" variant="ghost" onClick={() => setModo("ver")} disabled={act.busy}>No</Button>
            </span>
          ) : (
            <span className="flex items-center opacity-100 transition-opacity lg:opacity-0 lg:group-hover/row:opacity-100 lg:group-focus-within/row:opacity-100">
              <Button type="button" size="icon-xs" variant="ghost" onClick={editar} title="Editar" aria-label={`Editar «${t.texto}»`}><Pencil /></Button>
              <Button type="button" size="icon-xs" variant="ghost" onClick={() => setModo("borrar")} title="Borrar" aria-label={`Borrar «${t.texto}»`}
                className="hover:text-destructive"><Trash2 /></Button>
            </span>
          )}
          <Badge variant="outline" className="h-5 text-[10px] font-normal">{areas[t.area] ?? t.area}</Badge>
          <span className={cn("w-12 text-right text-xs", t.atrasada ? "text-warning" : "text-muted-foreground")}>{t.fecha ? t.fecha.slice(5) : "—"}</span>
        </span>
      </div>
      {act.error && <div className="mt-2">{act.ErrorBox}</div>}
    </li>
  );
}

function TasksTab() {
  const t = useApi<Tasks>("/tasks", 60_000);
  const [area, setArea] = useState("");
  const pend = useMemo(() => (t.data?.pendientes ?? []).filter((x) => !area || x.area === area), [t.data, area]);
  if (t.error) return <ErrorState message={t.error} />;
  if (!t.data) return <Loading rows={6} />;
  return (
    <div className="grid gap-4 xl:grid-cols-3">
      <Card className="xl:col-span-2">
        <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2">
          <CardTitle>Pendientes ({pend.length})</CardTitle>
          <div className="flex flex-wrap gap-1">
            {[["", "Todas"], ...Object.entries(t.data.areas)].map(([k, v]) => (
              <button key={k} onClick={() => setArea(k)} className={cn("rounded-full px-3 py-1.5 text-xs ring-1 ring-border lg:px-2.5 lg:py-0.5", area === k && "bg-primary/15 text-primary ring-primary/30")}>{v}</button>
            ))}
          </div>
        </CardHeader>
        <CardContent>
          <NewTask areas={t.data.areas} onDone={t.reload} />
          <ul className="divide-y divide-border">
            {pend.map((x) => <TaskRow key={x.id} t={x} areas={t.data!.areas} onDone={t.reload} />)}
          </ul>
          <p className="mt-2 text-xs text-muted-foreground">Las tareas viven en la base de datos del panel. <code className="font-mono">Tareas.md</code> es una copia: en Obsidian solo se acepta marcar casillas; lo demás se descarta. Para editar o borrar una tarea, usa el lápiz o la papelera de su fila. Al marcar una tarea también se marca en el Panel de Obsidian.</p>
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Hechas recientemente</CardTitle></CardHeader>
        <CardContent><ul className="space-y-1.5 text-sm">
          {t.data.hechas.slice(0, 15).map((x, i) => <li key={`${x.texto}-${i}`} className="flex items-start justify-between gap-2 text-muted-foreground"><span className="line-through decoration-muted-foreground/40">{x.texto}</span><span className="flex shrink-0 items-center gap-1 text-xs">{x.hecho_el?.slice(5) ?? ""}<TaskCheck texto={x.texto} hecho onDone={t.reload} /></span></li>)}
        </ul></CardContent>
      </Card>
    </div>
  );
}

export default function TareasPage() {
  return (
    <>
      <PageHeader title="Tareas" description="Lo que tienes pendiente. Lo que espera tu aprobación está en la Bandeja." />
      <TasksTab />
    </>
  );
}
