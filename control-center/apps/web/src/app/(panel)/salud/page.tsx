"use client";

import { useState } from "react";
import { useAct, TextField } from "@/components/cc/form";
import { Lines } from "@/components/cc/charts";
import { PageHeader } from "@/components/cc/shell";
import { Empty, ErrorState } from "@/components/cc/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { post } from "@/lib/api";
import { useApi } from "@/lib/hooks";

type Health = { series: Record<string, { dia: string; valor: number }[]>; ultimas: { id: number; dia: string; metrica: string; valor: number; nota: string }[] };

export default function SaludPage() {
  const h = useApi<Health>("/me/health");
  const [metrica, setMetrica] = useState("peso");
  const [valor, setValor] = useState("");
  const a = useAct(h.reload);
  const series = Object.entries(h.data?.series ?? {});
  return (
    <>
      <PageHeader title="Salud" description="Peso, medidas, sueño o lo que quieras seguir. Cada medida queda con su fecha." />
      {h.error && <ErrorState message={h.error} />}
      {a.ErrorBox}
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          {h.data && series.length === 0 && <Card><CardContent><Empty message="Aún no has registrado ninguna medida." /></CardContent></Card>}
          {series.map(([m, d]) => (
            <Card key={m}>
              <CardHeader><CardTitle className="first-letter:uppercase">{m}</CardTitle></CardHeader>
              <CardContent><Lines data={d} x="dia" series={[{ key: "valor", name: m }]} label={`Evolución de ${m}`} /></CardContent>
            </Card>
          ))}
        </div>
        <Card className="self-start">
          <CardHeader><CardTitle>Registrar</CardTitle></CardHeader>
          <CardContent>
            <form className="grid gap-2" onSubmit={(e) => { e.preventDefault(); void a.run(() => post("/me/health", { metrica: metrica.trim().toLowerCase(), valor: Number(valor.replace(",", ".")) })).then(() => setValor("")); }}>
              <TextField label="Medida" value={metrica} onChange={setMetrica} maxLength={32} required />
              <TextField label="Valor" value={valor} onChange={setValor} inputMode="decimal" required />
              <Button type="submit" disabled={a.busy || !valor.trim()}>Guardar</Button>
            </form>
          </CardContent>
        </Card>
      </div>
    </>
  );
}
