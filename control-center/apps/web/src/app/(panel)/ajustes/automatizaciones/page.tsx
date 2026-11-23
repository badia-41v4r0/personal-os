"use client";

import { useState } from "react";
import { PageHeader } from "@/components/cc/shell";
import { StatusRow } from "@/components/cc/status";
import { Empty, ErrorState, Loading } from "@/components/cc/states";
import { useAct } from "@/components/cc/form";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { api, post } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import type { Unit } from "@/lib/types";
import { unitLevel } from "@/lib/units";
import { asistente } from "@/lib/asistente";

type Timer = { id: string; titulo: string; detalle: string; usa_modelo: boolean; dias: string[]; horas: string[]; calendario: string[]; activo: boolean; proximo: string; ultimo: string; resultado: string; ejecutando: boolean };

const DIAS: [string, string][] = [["Mon", "L"], ["Tue", "M"], ["Wed", "X"], ["Thu", "J"], ["Fri", "V"], ["Sat", "S"], ["Sun", "D"]];
const NOMBRES: Record<string, string> = { Mon: "lunes", Tue: "martes", Wed: "miércoles", Thu: "jueves", Fri: "viernes", Sat: "sábado", Sun: "domingo" };

const fecha = (v: string) => (v ? new Date(v).toLocaleString("es-ES", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "");

function TimerCard({ t, onDone }: { t: Timer; onDone: () => void }) {
  const [dias, setDias] = useState(t.dias.length ? t.dias : DIAS.map(([d]) => d));
  const [horas, setHoras] = useState(t.horas.join(", "));
  const [activo, setActivo] = useState(t.activo);
  const a = useAct(onDone);
  const lista = horas.split(",").map((h) => h.trim().replace(/^(\d):/, "0$1:")).filter(Boolean);
  const valido = dias.length > 0 && lista.length > 0 && lista.every((h) => /^([01]\d|2[0-3]):[0-5]\d$/.test(h));
  const cambia = activo !== t.activo || lista.join() !== [...t.horas].sort().join() || [...dias].sort().join() !== [...(t.dias.length ? t.dias : DIAS.map(([d]) => d))].sort().join();
  const guardar = (encendido = activo) => a.run(() => api(`/system/timers/${t.id}`, { method: "PUT", body: JSON.stringify({ dias, horas: lista, activo: encendido }), headers: { "Content-Type": "application/json" } }));
  const editable = t.horas.length > 0;
  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <CardTitle className="flex flex-wrap items-center gap-2">{t.titulo}{t.usa_modelo && <Badge variant="secondary">Usa modelo</Badge>}</CardTitle>
            <p className="mt-1 text-xs text-muted-foreground">{t.detalle}</p>
          </div>
          <Switch aria-label={`Activar ${t.titulo}`} checked={activo} disabled={a.busy || !editable} onCheckedChange={(v: boolean) => { setActivo(v); if (valido) void guardar(v); }} />
        </div>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {a.ErrorBox}
        {!editable && <p className="text-xs text-warning">Este horario no se puede editar aquí: {t.calendario.join(", ")}</p>}
        {editable && (
          <>
            <div className="flex flex-wrap gap-1.5" role="group" aria-label="Días">
              {DIAS.map(([d, l]) => {
                const on = dias.includes(d);
                return <button key={d} type="button" aria-label={NOMBRES[d]} aria-pressed={on} onClick={() => setDias((x) => (on ? x.filter((y) => y !== d) : [...x, d]))} className={`size-9 rounded-full border text-xs font-medium ${on ? "border-primary bg-primary text-primary-foreground" : "border-border text-muted-foreground"}`}>{l}</button>;
              })}
            </div>
            <label className="grid gap-1 text-xs text-muted-foreground">Horas (separadas por comas)
              <input value={horas} onChange={(e) => setHoras(e.target.value)} placeholder="07:00, 18:45" className="h-9 rounded-lg border border-input bg-transparent px-3 text-sm text-foreground" />
            </label>
          </>
        )}
        <div className="space-y-2">
          <p className="text-xs text-muted-foreground">
            {t.ejecutando ? "En marcha ahora" : t.activo && t.proximo ? `Próximo: ${fecha(t.proximo)}` : "Desactivado"}
            {t.ultimo && ` · Último: ${fecha(t.ultimo)}`}
            {t.resultado && t.resultado !== "success" && <span className="text-destructive"> · falló</span>}
          </p>
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="outline" disabled={a.busy || t.ejecutando} onClick={() => void a.run(() => post(`/system/timers/${t.id}/run`))}>Ejecutar ahora</Button>
            {editable && <Button size="sm" disabled={a.busy || !valido || !cambia} onClick={() => void guardar()}>Guardar</Button>}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

export default function AutomatizacionesPage() {
  const timers = useApi<Timer[]>("/system/timers", 60000);
  const services = useApi<Unit[]>("/system/services", 30000);
  const colas = services.data?.filter((u) => u.scope === "user" && u.Id.endsWith(".path")) ?? [];
  return (
    <>
      <PageHeader title="Automatizaciones" description={`Lo que ${asistente()} hace solo. Cambia cuándo se ejecuta cada cosa, apágala o lánzala ahora.`} />
      {timers.error && <ErrorState message={timers.error} />}
      {timers.loading && <Loading rows={6} />}
      <div className="grid gap-4 lg:grid-cols-2">
        {timers.data?.map((t) => <TimerCard key={`${t.id}:${t.horas.join()}:${t.dias.join()}:${t.activo}`} t={t} onDone={timers.reload} />)}
      </div>
      <Card className="mt-4">
        <CardHeader><CardTitle>Al llegar trabajo a una cola</CardTitle></CardHeader>
        <CardContent className="grid gap-x-8 divide-border sm:grid-cols-2">
          {services.error && <ErrorState message={services.error} />}
          {services.data && colas.length === 0 && <Empty message="Ninguna" />}
          {colas.map((u) => <StatusRow key={u.Id} label={u.Description.replace(/^Jarvis:\s*/, "") || u.Id} level={unitLevel(u)} detail={u.ActiveState === "active" ? "Activa" : u.ActiveState} />)}
        </CardContent>
      </Card>
    </>
  );
}
