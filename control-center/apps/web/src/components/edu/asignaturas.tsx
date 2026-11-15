"use client";

import Link from "next/link";
import { useState } from "react";
import { BookOpen, FolderOpen, MessageSquare, Repeat } from "lucide-react";
import { useAct } from "@/components/cc/form";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Bar, Chip, Semaforo, Stat, cuentaAtras, fecha, preguntarTutor, type Asig } from "./common";

function Ficha({ a }: { a: Asig }) {
  const act = useAct();
  const [aviso, setAviso] = useState<string | null>(null);
  const preguntar = (texto: string) => act.run(async () => { await preguntarTutor(texto); setAviso("Enviado al tutor: te contesta en el chat de la derecha."); });
  const s = a.siguiente;
  return (
    <Card>
      <CardHeader className="gap-1">
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="flex min-w-0 items-center gap-2"><Chip code={a.codigo} /><span className="truncate">{a.nombre}</span></CardTitle>
          <Semaforo valor={a.semaforo} />
        </div>
        {a.formula && <p className="text-xs text-muted-foreground">{a.formula}{a.minimos && a.minimos !== "—" ? ` · mínimos: ${a.minimos}` : ""}</p>}
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-3 gap-3">
          <Stat label="Nota actual" value={a.nota_actual || "—"} />
          <Stat label="Pendientes" value={a.pendientes} hint={a.atrasadas ? <span className="text-destructive">{a.atrasadas} sin marcar</span> : "entregas"} />
          <Stat label="Repaso hoy" value={a.tarjetas_hoy} hint="tarjetas" />
        </div>
        {a.estado && <p className="text-sm">{a.estado}</p>}
        {s && (
          <p className="rounded-lg bg-muted/60 px-3 py-2 text-sm">
            <span className="text-muted-foreground">Siguiente: </span>{s.texto.replace(/^[^:]+:\s*/, "")}
            <span className={`ml-1 tabular-nums ${s.dias <= 3 ? "font-medium text-destructive" : "text-muted-foreground"}`}>· {fecha(s.fecha)} {s.hora} ({cuentaAtras(s.dias)})</span>
          </p>
        )}
        <div>
          <div className="mb-1 flex justify-between text-xs text-muted-foreground"><span>Bloques hechos</span><span className="tabular-nums">{a.bloques_hechos}/{a.bloques_pasados} · quedan {a.bloques_futuros}</span></div>
          <Bar value={a.bloques_hechos} max={a.bloques_pasados} tone={a.bloques_pasados && a.bloques_hechos / a.bloques_pasados < 0.6 ? "warn" : "primary"} label={`Bloques de ${a.nombre}`} />
        </div>
        <div className="flex flex-wrap gap-1.5">
          <Button size="sm" disabled={act.busy} onClick={() => preguntar(`Quiero estudiar ${a.nombre} (${a.codigo}) ahora. Mira mis notas de la semana y mis entregas y dime por dónde empiezo, empezando por los ejercicios. Sé breve.`)}><BookOpen />Estudiar</Button>
          <Button size="sm" variant="outline" disabled={act.busy} onClick={() => preguntar(`Genera entre 8 y 15 tarjetas de repaso de ${a.codigo} con las notas de /vault/Uni/Asignaturas/${a.nombre} y los ejercicios ❌/🔁. Prioriza ejercicios resolubles. Añádelas con uni.card.add (revisa antes uni.cards.due para no repetir) y dime cuántas has creado.`)}><Repeat />Generar tarjetas</Button>
          <Button size="sm" variant="outline" disabled={act.busy} onClick={() => preguntar(`Revisa mi borrador de ${a.codigo}: lo he dejado en /entregables/${a.codigo}/ (o en los adjuntos). Compáralo con el enunciado y los criterios y dime qué falta y las 3 mejoras que más nota darían.`)}><MessageSquare />Revisar borrador</Button>
          <Link href={`/educacion/?tab=archivos&ruta=${a.codigo}`} className="inline-flex h-7 items-center gap-1 rounded-lg border border-border px-2.5 text-[0.8rem] hover:bg-muted"><FolderOpen className="size-3.5" />Archivos</Link>
        </div>
        {aviso && <p role="status" className="text-xs text-muted-foreground">{aviso}</p>}
        {act.ErrorBox}
      </CardContent>
    </Card>
  );
}

export function AsignaturasTab({ asignaturas }: { asignaturas: Asig[] }) {
  return <div className="grid gap-4 lg:grid-cols-2 2xl:grid-cols-3">{asignaturas.map((a) => <Ficha key={a.codigo} a={a} />)}</div>;
}
