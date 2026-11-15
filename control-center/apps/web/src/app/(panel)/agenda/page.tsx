"use client";

import Link from "next/link";
import { BookOpen, Mail, RefreshCw, ListChecks, Newspaper } from "lucide-react";
import { cn } from "cn";
import { PageHeader, usePanel } from "@/components/cc/shell";
import { ErrorState, Loading } from "@/components/cc/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { TaskCheck } from "@/components/cc/task-check";
import { UnifiedCalendar } from "@/components/cc/unified-calendar";
import { useApi } from "@/lib/hooks";

type Evento = { id: string; calendario: string; titulo: string; lugar: string; dia: string; hasta: string; inicio: string | null; fin: string | null; de_jarvis: boolean };
type Tarea = { texto: string; fecha: string | null; area: string; atrasada?: boolean };
type Correo = { id?: string; de?: string; asunto?: string; fecha?: string; [k: string]: unknown };
type Agenda = {
  hoy: string;
  calendario: { eventos: Evento[]; error: string | null };
  correo: Record<string, { mensajes?: Correo[]; error?: string }>;
  uni: { bloques?: string[]; objetivos?: { asignatura: string; detalle: string }[]; entregas?: { fecha: string; hora: string; texto: string; hecho: boolean }[]; eventos?: { fecha: string; texto: string }[] };
  tareas: { hoy?: Tarea[]; proximas?: Tarea[]; sin_fecha?: Tarea[]; hechas_hoy?: Tarea[] };
  briefings: { path: string; name: string }[];
  diario: { path: string; name: string }[];
  digest: { path: string; mtime: string | null };
};

const CUENTA: Record<string, string> = { gmail: "Gmail", secundaria: "Segunda cuenta", zoho: "Zoho Mail" };
const dayLabel = (iso: string, hoy: string) => {
  if (iso === hoy) return "Hoy";
  const d = new Date(iso + "T12:00:00");
  return d.toLocaleDateString("es-ES", { weekday: "long", day: "numeric", month: "short" });
};

function TareaRow({ t, onDone }: { t: Tarea; onDone?: () => void }) {
  const AREA = usePanel().inst?.areas ?? {};
  return (
    <li className="flex items-start justify-between gap-2 py-1.5 text-sm">
      <span className="flex min-w-0 items-start gap-2"><TaskCheck texto={t.texto} onDone={onDone} className="mt-0.5" /><span className={cn("min-w-0", t.atrasada && "text-warning")}>{t.texto}</span></span>
      <span className="flex shrink-0 items-center gap-1.5">
        <Badge variant="outline" className="h-5 text-[10px] font-normal">{AREA[t.area] ?? t.area}</Badge>
        {t.fecha && <span className="text-xs text-muted-foreground">{t.fecha.slice(5)}</span>}
      </span>
    </li>
  );
}

export default function AgendaPage() {
  const a = useApi<Agenda>("/agenda?dias=7", 300_000);
  return (
    <>
      <PageHeader
        title="Agenda"
        description="Todo tu día en un calendario: Google (sin Family), uni, tareas, trabajo, gym y vida."
        actions={<Button variant="outline" size="sm" onClick={() => a.reload()}><RefreshCw /> Actualizar resumen</Button>}
      />
      <UnifiedCalendar />
      {a.error && <ErrorState message={a.error} />}
      {!a.data && !a.error && <Loading rows={8} />}
      {a.data && (
        <div className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          <div className="space-y-4">
            <Card>
              <CardHeader className="flex flex-row items-center justify-between">
                <CardTitle className="flex items-center gap-2"><ListChecks className="size-4" /> Tareas de hoy</CardTitle>
                <Link href="/tasks/?t=tasks" className="-my-1 py-1 text-xs text-primary hover:underline">Todas</Link>
              </CardHeader>
              <CardContent>
                {!a.data.tareas.hoy?.length && <p className="text-sm text-muted-foreground">Nada para hoy.</p>}
                <ul className="divide-y divide-border">{a.data.tareas.hoy?.map((t, i) => <TareaRow key={i} t={t} onDone={a.reload} />)}</ul>
                {(a.data.tareas.hechas_hoy?.length ?? 0) > 0 && <p className="mt-2 text-xs text-success">{a.data.tareas.hechas_hoy!.length} hechas hoy</p>}
              </CardContent>
            </Card>

            <Card>
              <CardHeader><CardTitle className="flex items-center gap-2"><Mail className="size-4" /> Correo sin leer (24 h)</CardTitle></CardHeader>
              <CardContent className="space-y-3">
                {Object.keys(a.data.correo).length === 0 && <p className="text-sm text-muted-foreground">Sin cuentas conectadas.</p>}
                {Object.entries(a.data.correo).map(([cuenta, v]) => (
                  <div key={cuenta}>
                    <div className="mb-1 text-xs font-medium">{CUENTA[cuenta] ?? cuenta}</div>
                    {v.error && <p className="text-xs text-destructive">{v.error}</p>}
                    {v.mensajes?.length === 0 && <p className="text-xs text-muted-foreground">Nada sin leer.</p>}
                    <ul className="space-y-1">
                      {v.mensajes?.map((m, i) => (
                        <li key={String(m.id ?? i)} className="text-xs">
                          <div className="truncate">{String(m.asunto ?? m.subject ?? "(sin asunto)")}</div>
                          <div className="truncate text-muted-foreground">{String(m.de ?? m.from ?? "")}</div>
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
                <p className="text-[11px] text-muted-foreground">Contenido externo: se muestra como dato. Para leer o responder, pídeselo a Jarvis (solo borradores).</p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader><CardTitle className="flex items-center gap-2"><Newspaper className="size-4" /> Resúmenes</CardTitle></CardHeader>
              <CardContent className="space-y-3 text-sm">
                <Link href={`/memory/?p=${encodeURIComponent(a.data.digest.path)}`} className="-my-1 flex items-center gap-2 py-1 hover:text-primary"><BookOpen className="size-3.5" /> Digest de hoy</Link>
                {[["Briefings", a.data.briefings], ["Diario", a.data.diario]].map(([t, list]) => (
                  <div key={t as string}>
                    <div className="mb-1 text-xs text-muted-foreground">{t as string}</div>
                    {(list as { path: string; name: string }[]).length === 0 && <p className="text-xs text-muted-foreground">Ninguno</p>}
                    <ul className="space-y-0.5">
                      {(list as { path: string; name: string }[]).map((x) => (
                        <li key={x.path}><Link href={`/memory/?p=${encodeURIComponent(x.path)}`} className="inline-block py-1 text-xs hover:text-primary">{x.name}</Link></li>
                      ))}
                    </ul>
                  </div>
                ))}
              </CardContent>
            </Card>
          </div>
        </div>
      )}
    </>
  );
}
