"use client";

import { useState } from "react";
import { Target } from "lucide-react";
import { useAct, Field, TextField, selectClass } from "@/components/cc/form";
import { PageHeader } from "@/components/cc/shell";
import { Empty, ErrorState, Loading } from "@/components/cc/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { post } from "@/lib/api";
import { useApi } from "@/lib/hooks";

type Goal = { id: number; titulo: string; area: string; horizonte: string; estado: string; fecha: string | null; progreso: number | null; hitos: { id: number; titulo: string; hecho: boolean }[] };
type Habit = { id: number; nombre: string; hoy: boolean; racha: number; semana: boolean[] };

function GoalCard({ g, reload }: { g: Goal; reload: () => void }) {
  const [hito, setHito] = useState("");
  const a = useAct(reload);
  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-2">
        <div className="min-w-0">
          <CardTitle>{g.titulo}</CardTitle>
          <p className="mt-1 text-xs text-muted-foreground">{g.area} · plazo {g.horizonte}{g.fecha ? ` · ${g.fecha}` : ""}</p>
        </div>
        <span className="text-sm tabular-nums">{g.progreso == null ? "Sin hitos" : `${g.progreso} %`}</span>
      </CardHeader>
      <CardContent className="space-y-2">
        {a.ErrorBox}
        <ul className="space-y-1 text-sm">
          {g.hitos.map((h) => (
            <li key={h.id}><label className="flex min-h-8 items-center gap-2"><input type="checkbox" checked={h.hecho} onChange={() => void a.run(() => post(`/me/milestones/${h.id}/toggle`))} /><span className={h.hecho ? "text-muted-foreground line-through" : ""}>{h.titulo}</span></label></li>
          ))}
        </ul>
        <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); void a.run(() => post(`/me/goals/${g.id}/milestones`, { titulo: hito })).then(() => setHito("")); }}>
          <TextField label="Nuevo hito" value={hito} onChange={setHito} maxLength={200} />
          <Button type="submit" size="sm" variant="outline" className="self-end" disabled={!hito.trim() || a.busy}>Añadir</Button>
        </form>
        <div className="flex gap-2 pt-1">
          <Button size="sm" variant="ghost" onClick={() => void a.run(() => post(`/me/goals/${g.id}/status`, { estado: "done" }))}>Conseguido</Button>
          <Button size="sm" variant="ghost" onClick={() => void a.run(() => post(`/me/goals/${g.id}/status`, { estado: "abandoned" }))}>Abandonar</Button>
        </div>
      </CardContent>
    </Card>
  );
}

export default function ObjetivosPage() {
  const goals = useApi<Goal[]>("/me/goals");
  const habits = useApi<Habit[]>("/me/habits");
  const [titulo, setTitulo] = useState("");
  const [area, setArea] = useState("personal");
  const [horizonte, setHorizonte] = useState("medio");
  const [habito, setHabito] = useState("");
  const a = useAct(() => { goals.reload(); habits.reload(); });
  const activos = goals.data?.filter((g) => g.estado === "active") ?? [];
  const cerrados = goals.data?.filter((g) => g.estado !== "active") ?? [];
  return (
    <>
      <PageHeader title="Objetivos" description="Lo que persigues y los hábitos que te acercan. El progreso sale de hitos reales." />
      {goals.error && <ErrorState message={goals.error} />}
      {a.ErrorBox}
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          {goals.loading && <Loading rows={4} />}
          {goals.data && activos.length === 0 && <Card><CardContent><Empty message="Aún no tienes objetivos activos." /></CardContent></Card>}
          {activos.map((g) => <GoalCard key={g.id} g={g} reload={goals.reload} />)}
          {cerrados.length > 0 && <p className="text-xs text-muted-foreground">Cerrados: {cerrados.map((g) => `${g.titulo} (${g.estado === "done" ? "conseguido" : "abandonado"})`).join(" · ")}</p>}
        </div>
        <div className="space-y-4">
          <Card>
            <CardHeader><CardTitle className="flex items-center gap-2"><Target className="size-4 text-primary" />Nuevo objetivo</CardTitle></CardHeader>
            <CardContent>
              <form className="grid gap-2" onSubmit={(e) => { e.preventDefault(); void a.run(() => post("/me/goals", { titulo, area, horizonte })).then(() => setTitulo("")); }}>
                <TextField label="Objetivo" value={titulo} onChange={setTitulo} maxLength={200} required />
                <Field label="Área"><select className={selectClass} value={area} onChange={(e) => setArea(e.target.value)}>{["personal", "carrera", "fitness", "educacion", "finanzas"].map((x) => <option key={x}>{x}</option>)}</select></Field>
                <Field label="Plazo"><select className={selectClass} value={horizonte} onChange={(e) => setHorizonte(e.target.value)}>{["corto", "medio", "largo"].map((x) => <option key={x}>{x}</option>)}</select></Field>
                <Button type="submit" disabled={a.busy || !titulo.trim()}>Crear</Button>
              </form>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Hábitos</CardTitle></CardHeader>
            <CardContent className="space-y-2">
              {habits.data?.length === 0 && <Empty message="Sin hábitos todavía." />}
              {habits.data?.map((h) => (
                <label key={h.id} className="flex min-h-9 items-center gap-2 text-sm">
                  <input type="checkbox" checked={h.hoy} onChange={() => void a.run(() => post(`/me/habits/${h.id}/toggle`, {}))} />
                  <span className="min-w-0 flex-1 truncate">{h.nombre}</span>
                  <span className="text-xs text-muted-foreground tabular-nums">{h.racha ? `${h.racha} d` : ""}</span>
                </label>
              ))}
              <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); void a.run(() => post("/me/habits", { nombre: habito })).then(() => setHabito("")); }}>
                <TextField label="Nuevo hábito" value={habito} onChange={setHabito} maxLength={120} />
                <Button type="submit" size="sm" variant="outline" className="self-end" disabled={!habito.trim()}>Añadir</Button>
              </form>
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  );
}
