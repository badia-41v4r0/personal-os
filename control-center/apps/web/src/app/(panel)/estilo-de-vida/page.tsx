"use client";

import { useState } from "react";
import { Trash2 } from "lucide-react";
import { useAct, Field, TextField, selectClass } from "@/components/cc/form";
import { PageHeader } from "@/components/cc/shell";
import { Empty, ErrorState } from "@/components/cc/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api, post } from "@/lib/api";
import { useApi } from "@/lib/hooks";

type Item = { id: number; tipo: string; titulo: string; dia: string | null; nota: string };
const TIPOS: [string, string][] = [["viaje", "Viajes"], ["actividad", "Actividades"], ["compra", "Compras"], ["garantia", "Garantías"], ["suscripcion", "Suscripciones"], ["interes", "Intereses"]];

export default function EstiloPage() {
  const list = useApi<Item[]>("/me/lifestyle");
  const [tipo, setTipo] = useState("viaje");
  const [titulo, setTitulo] = useState("");
  const [dia, setDia] = useState("");
  const a = useAct(list.reload);
  return (
    <>
      <PageHeader title="Estilo de vida" description="Viajes, actividades, compras, garantías y lo que te interesa." />
      {list.error && <ErrorState message={list.error} />}
      {a.ErrorBox}
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="grid gap-4 self-start sm:grid-cols-2 lg:col-span-2">
          {list.data?.length === 0 && <Card className="sm:col-span-2"><CardContent><Empty message="Aún no has añadido nada." /></CardContent></Card>}
          {TIPOS.map(([k, label]) => {
            const items = list.data?.filter((i) => i.tipo === k) ?? [];
            if (items.length === 0) return null;
            return (
              <Card key={k}>
                <CardHeader><CardTitle>{label}</CardTitle></CardHeader>
                <CardContent>
                  <ul className="divide-y divide-border">
                    {items.map((i) => (
                      <li key={i.id} className="flex items-center gap-2 py-1.5 text-sm">
                        <span className="min-w-0 flex-1 truncate">{i.titulo}</span>
                        {i.dia && <span className="text-xs text-muted-foreground tabular-nums">{i.dia}</span>}
                        <Button variant="ghost" size="icon-sm" aria-label={`Quitar ${i.titulo}`} onClick={() => void a.run(() => api(`/me/lifestyle/${i.id}`, { method: "DELETE" }))}><Trash2 /></Button>
                      </li>
                    ))}
                  </ul>
                </CardContent>
              </Card>
            );
          })}
        </div>
        <Card className="self-start">
          <CardHeader><CardTitle>Añadir</CardTitle></CardHeader>
          <CardContent>
            <form className="grid gap-2" onSubmit={(e) => { e.preventDefault(); void a.run(() => post("/me/lifestyle", { tipo, titulo, dia: dia || null })).then(() => { setTitulo(""); setDia(""); }); }}>
              <Field label="Tipo"><select className={selectClass} value={tipo} onChange={(e) => setTipo(e.target.value)}>{TIPOS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>
              <TextField label="Título" value={titulo} onChange={setTitulo} maxLength={200} required />
              <TextField label="Fecha" type="date" value={dia} onChange={setDia} />
              <Button type="submit" disabled={a.busy || !titulo.trim()}>Guardar</Button>
            </form>
          </CardContent>
        </Card>
      </div>
    </>
  );
}
