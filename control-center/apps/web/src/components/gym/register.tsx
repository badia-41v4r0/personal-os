"use client";

import { useState } from "react";
import { useAct, TextField } from "@/components/cc/form";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { post } from "@/lib/api";

type Preview = { sesion: string; ejercicios: { nombre: string; series: string[] }[]; avisos: string[] };
const hoy = () => new Date().toLocaleDateString("sv-SE");

/** Registro diario: pegas el entreno de Hevy, ves qué se ha entendido y confirmas. Sin modelo: 0 tokens. */
export function RegisterTab() {
  const [texto, setTexto] = useState("");
  const [fecha, setFecha] = useState(hoy);
  const [prev, setPrev] = useState<Preview | null>(null);
  const [hecho, setHecho] = useState<string | null>(null);
  const a = useAct();
  return (
    <Card>
      <CardHeader><CardTitle>Registrar el entreno de hoy</CardTitle></CardHeader>
      <CardContent className="grid max-w-2xl gap-3">
        {a.ErrorBox}
        {hecho && <p role="status" className="text-sm text-success">{hecho}</p>}
        <TextField label="Fecha" type="date" value={fecha} onChange={(v) => { setFecha(v); setPrev(null); }} />
        <label className="grid gap-1 text-xs text-muted-foreground">
          <span>Pega aquí el entreno de Hevy, o escríbelo como «Press banca: 80×8, 80×8»</span>
          <Textarea rows={10} value={texto} onChange={(e) => { setTexto(e.target.value); setPrev(null); setHecho(null); }} />
        </label>
        <Button variant="outline" disabled={!texto.trim() || a.busy} onClick={() => void a.run(async () => setPrev(await post<Preview>("/gym/register/preview", { texto, fecha })))}>Revisar</Button>
        {prev && (
          <div className="space-y-2 rounded-lg bg-muted p-3 text-sm">
            <p className="font-medium">{prev.sesion} · {prev.ejercicios.length} ejercicios</p>
            <ul className="space-y-0.5">{prev.ejercicios.map((e) => <li key={e.nombre}>{e.nombre}: <span className="text-muted-foreground">{e.series.join(", ")}</span></li>)}</ul>
            {prev.avisos.map((x) => <p key={x} className="text-xs text-warning">{x}</p>)}
            <Button size="sm" disabled={!prev.ejercicios.length || a.busy} onClick={() => void a.run(async () => {
              await post("/gym/register", { texto, fecha });
              setHecho(`${prev.sesion} guardado.`);
              setPrev(null);
              setTexto("");
            })}>Guardar</Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
