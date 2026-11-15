"use client";

import Link from "next/link";
import { useAct } from "@/components/cc/form";
import { PageHeader } from "@/components/cc/shell";
import { Empty, ErrorState, Loading } from "@/components/cc/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { post } from "@/lib/api";
import { useApi } from "@/lib/hooks";

type Fact = { id: number; subject: string; predicate: string; value: Record<string, unknown>; verification: string; confidence: number | null };
const LABEL: Record<string, string> = { inferred: "Propuesto por un agente", reported: "Reportado", imported: "Importado", confirmed: "Confirmado" };

export default function HechosPage() {
  const f = useApi<Fact[]>("/core/facts");
  const a = useAct(f.reload);
  const dudosos = f.data?.filter((x) => x.verification === "inferred") ?? [];
  const resto = f.data?.filter((x) => x.verification !== "inferred") ?? [];
  const fila = (x: Fact) => (
    <li key={x.id} className="flex flex-wrap items-center gap-2 py-2 text-sm">
      <div className="min-w-0 flex-1">
        <div>{x.subject} · {x.predicate}: <b>{String(x.value.v ?? JSON.stringify(x.value))}</b></div>
        <div className="text-xs text-muted-foreground">{LABEL[x.verification] ?? x.verification}</div>
      </div>
      {x.verification !== "confirmed" && <Button size="sm" onClick={() => void a.run(() => post(`/core/facts/${x.id}/verify`))}>Confirmar</Button>}
      <Button size="sm" variant="ghost" onClick={() => void a.run(() => post(`/core/facts/${x.id}/reject`))}>Descartar</Button>
    </li>
  );
  return (
    <>
      <PageHeader title="Qué sé de ti" description="Lo que Jarvis da por cierto. Lo propuesto por un agente no cuenta hasta que lo confirmes." actions={<Link href="/memory/" className="text-xs text-primary hover:underline">Volver a Conocimiento</Link>} />
      {f.error && <ErrorState message={f.error} />}
      {a.ErrorBox}
      {f.loading && <Loading rows={4} />}
      {f.data?.length === 0 && <Card><CardContent><Empty message="Todavía no hay hechos guardados." /></CardContent></Card>}
      <div className="space-y-4">
        {dudosos.length > 0 && <Card><CardContent><h2 className="mb-1 text-sm font-medium">Por confirmar</h2><ul className="divide-y divide-border">{dudosos.map(fila)}</ul></CardContent></Card>}
        {resto.length > 0 && <Card><CardContent><ul className="divide-y divide-border">{resto.map(fila)}</ul></CardContent></Card>}
      </div>
    </>
  );
}
