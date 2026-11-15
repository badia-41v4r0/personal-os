"use client";

import { useState } from "react";
import { Briefcase, HeartPulse, Landmark } from "lucide-react";
import { HBars } from "@/components/cc/charts";
import { Field, selectClass, useAct } from "@/components/cc/form";
import { Empty, ErrorState, Loading } from "@/components/cc/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { Chip, Stat } from "./common";

type Cruces = {
  ofertas: { analizadas: number; asignaturas: { asig: string; ofertas: number; ejemplos: string[] }[] };
  energia: { suficiente: boolean; dias_con_sueno: number; bloques_con_sueno_7h: number | null; bloques_con_menos_de_7h: number | null; bloques_dia_con_entreno: number | null; bloques_dia_sin_entreno: number | null; nota: string };
  coste: { asientos: number; pagado: number | null; creditos: number | null; por_credito: number | null; nota: string };
};
const n = (x: number | null, d = 1) => (x == null ? "—" : x.toLocaleString("es-ES", { maximumFractionDigits: d }));
const eur = (x: number | null) => (x == null ? "—" : x.toLocaleString("es-ES", { style: "currency", currency: "EUR" }));

function Creditos({ reload }: { reload: () => void }) {
  const [asig, setAsig] = useState("FP");
  const [cr, setCr] = useState("6");
  const a = useAct(reload);
  return (
    <div className="flex flex-wrap items-end gap-2 border-t border-border pt-3">
      <Field label="Créditos de"><select className={selectClass} value={asig} onChange={(e) => setAsig(e.target.value)}>{["FP", "FC", "SC", "SD", "ARD", "CI"].map((c) => <option key={c}>{c}</option>)}</select></Field>
      <Field label="ECTS"><Input className="w-20" inputMode="numeric" value={cr} onChange={(e) => setCr(e.target.value.replace(/\D/g, ""))} /></Field>
      <Button size="sm" variant="outline" disabled={a.busy || !cr} onClick={() => a.run(() => api("/education/credits", { method: "PUT", body: JSON.stringify({ asignatura: asig, creditos: Number(cr) }) }))}>Guardar</Button>
      {a.ErrorBox}
    </div>
  );
}

export function CrucesTab() {
  const c = useApi<Cruces>("/education/cruces");
  if (c.error) return <ErrorState message={c.error} />;
  if (!c.data) return <Loading rows={5} />;
  const { ofertas, energia, coste } = c.data;
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Card className="xl:col-span-2">
        <CardHeader><CardTitle className="flex items-center gap-2"><Briefcase className="size-4" />Qué piden tus ofertas y qué asignatura lo cubre</CardTitle></CardHeader>
        <CardContent className="grid gap-4 lg:grid-cols-2">
          {ofertas.analizadas === 0 ? <Empty message="Aún no hay ofertas analizadas (las trae el radar diario)." /> : (
            <>
              <HBars data={ofertas.asignaturas.map((a) => ({ name: a.asig, value: a.ofertas }))} label="Ofertas relacionadas por asignatura" />
              <ul className="space-y-2 text-sm">
                {ofertas.asignaturas.filter((a) => a.ofertas > 0).map((a) => <li key={a.asig}><Chip code={a.asig} className="mr-2" /><span className="text-muted-foreground">{a.ofertas} de {ofertas.analizadas} · {a.ejemplos[0]}</span></li>)}
              </ul>
            </>
          )}
          <p className="text-xs text-muted-foreground lg:col-span-2">Cuenta ofertas cuyo título o empresa contiene palabras clave de cada asignatura (criterio en el código, editable). Es una guía de qué repasar, no una medida exacta.</p>
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle className="flex items-center gap-2"><HeartPulse className="size-4" />Energía, sueño y entreno</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          {energia.suficiente ? (
            <div className="grid grid-cols-2 gap-3">
              <Stat label="Bloques/día con ≥ 7 h de sueño" value={n(energia.bloques_con_sueno_7h)} />
              <Stat label="Bloques/día con < 7 h" value={n(energia.bloques_con_menos_de_7h)} />
              <Stat label="Bloques/día con entreno" value={n(energia.bloques_dia_con_entreno)} />
              <Stat label="Bloques/día sin entreno" value={n(energia.bloques_dia_sin_entreno)} />
            </div>
          ) : <Empty message="Faltan datos de sueño (Salud) o de entreno para comparar." />}
          <p className="text-xs text-muted-foreground">{energia.nota} {energia.dias_con_sueno} días con sueño registrado.</p>
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle className="flex items-center gap-2"><Landmark className="size-4" />Coste de la matrícula</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <div className="grid grid-cols-3 gap-3"><Stat label="Pagado en matrícula" value={eur(coste.pagado)} /><Stat label="Créditos" value={coste.creditos ?? "—"} /><Stat label="Por crédito" value={eur(coste.por_credito)} /></div>
          <p className="text-xs text-muted-foreground">{coste.nota}</p>
          <Creditos reload={c.reload} />
        </CardContent>
      </Card>
    </div>
  );
}
