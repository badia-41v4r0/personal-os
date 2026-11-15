"use client";

import Link from "next/link";
import { useEffect } from "react";
import { ArrowRight, BriefcaseBusiness, CalendarDays, Dumbbell, GraduationCap, Landmark, Sparkles, Target } from "lucide-react";
import type { ReactNode } from "react";
import { Bars } from "@/components/cc/charts";
import { CheckInCard, type CheckInView } from "@/components/cc/checkin-card";
import { usePanel } from "@/components/cc/shell";
import { Empty, ErrorState, Loading } from "@/components/cc/states";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useApi } from "@/lib/hooks";
import { asistente } from "@/lib/asistente";

type AgendaItem = { hora: string | null; fin: string | null; titulo: string; tipo: string };
type Home = {
  saludo: string; nombre: string; fecha: string; foco: string[]; agenda: AgendaItem[]; agenda_error: string | null;
  gym: { sesiones: number; planificadas: number; volumen: number; series: number; volumen_pct: number | null; series_pct: number | null; por_dia: { dia: string; volumen: number }[] };
  estudios: { entregas_semana: number; proxima: { fecha: string; texto: string } | null };
  carrera: { pipeline: Record<string, number>; candidaturas: number; ofertas_nuevas: number };
  tareas: { pendientes: number; atrasadas: number };
  preocupa: { alertas: number; avisos: number };
  objetivos: { id: number; titulo: string; progreso: number | null }[] | null;
  finanzas: { ahorro: string; gastos: string; ingresos: string } | null;
  checkin: CheckInView;
  estado_general: { dias: number; checkins: number; de: number; animo: number | null; energia: number | null; sueno: number | null; habitos_hoy: [number, number] } | null;
  insights: { tipo: "aviso" | "siguiente" | "bien"; titulo: string; texto: string; fuente: string; url: string }[];
};

const INSIGHT: Record<string, string> = { aviso: "bg-warning/12", siguiente: "bg-primary/8", bien: "bg-success/12" };

const signed = (n: number) => `${n > 0 ? "+" : ""}${n.toLocaleString("es-ES")} %`;

function Tile({ href, icon: Icon, title, children }: { href: string; icon: typeof Dumbbell; title: string; children: ReactNode }) {
  return (
    <Link href={href} className="min-w-0 rounded-xl border border-border bg-card p-4 transition-colors hover:border-primary/40">
      <div className="flex items-center gap-2 text-sm font-medium"><Icon className="size-4 text-primary" />{title}</div>
      <div className="mt-3 text-sm">{children}</div>
    </Link>
  );
}

function Pending({ children }: { children: ReactNode }) {
  return <span className="text-muted-foreground">{children}</span>;
}

function SectionLink({ href, children }: { href: string; children: ReactNode }) {
  return <Link href={href} className="-my-1 inline-flex items-center gap-1 py-1 text-xs text-primary hover:underline">{children}<ArrowRight className="size-3" /></Link>;
}

export default function Inicio() {
  const { lastEvent } = usePanel();
  const home = useApi<Home>("/home", 120000);
  const { reload } = home;
  useEffect(() => {
    if (lastEvent?.type === "tasks.changed" || lastEvent?.type === "gym.updated") {
      reload();
    }
  }, [lastEvent, reload]);

  if (home.error) return <ErrorState message={home.error} />;
  const d = home.data;
  if (!d) return <Loading rows={8} />;
  const pctGym = d.gym.planificadas ? Math.min(100, Math.round((100 * d.gym.sesiones) / d.gym.planificadas)) : 0;
  const preocupa = d.preocupa.alertas + d.tareas.atrasadas;

  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-[1fr_minmax(0,24rem)]">
        <div className="flex flex-col justify-center py-2">
          <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">{d.saludo}, {d.nombre}.</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {preocupa === 0 ? "Nada urgente por ahora." : [d.tareas.atrasadas ? `${d.tareas.atrasadas} ${d.tareas.atrasadas === 1 ? "tarea atrasada" : "tareas atrasadas"}` : "", d.preocupa.alertas ? `${d.preocupa.alertas} ${d.preocupa.alertas === 1 ? "alerta abierta" : "alertas abiertas"}` : ""].filter(Boolean).join(" · ")}
          </p>
        </div>
        <div className="rounded-xl bg-primary/8 p-4">
          <h2 className="mb-2 flex items-center gap-2 text-sm font-medium"><Target className="size-4 text-primary" />Foco del día</h2>
          {d.foco.length === 0 ? <p className="text-sm text-muted-foreground">Nada planificado para hoy.</p> : (
            <ul className="space-y-1 text-sm">{d.foco.map((f) => <li key={f} className="line-clamp-2" title={f}>{f}</li>)}</ul>
          )}
        </div>
      </div>

      <CheckInCard data={d.checkin} onChange={reload} />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 2xl:grid-cols-5">
        <Tile href="/gym/" icon={Dumbbell} title="Entrenamiento">
          <div><b className="tabular-nums">{d.gym.sesiones} / {d.gym.planificadas}</b> sesiones</div>
          <div className="mt-2 h-1.5 rounded-full bg-muted" role="progressbar" aria-valuenow={pctGym} aria-valuemin={0} aria-valuemax={100} aria-label="Sesiones de la semana"><div className="h-full rounded-full bg-success" style={{ width: `${pctGym}%` }} /></div>
        </Tile>
        <Tile href="/objetivos/" icon={Target} title="Objetivos">{d.objetivos ? <>{d.objetivos.length} {d.objetivos.length === 1 ? "activo" : "activos"}</> : <Pending>Sin objetivos todavía</Pending>}</Tile>
        <Tile href="/carrera/" icon={BriefcaseBusiness} title="Carrera">
          {d.carrera.ofertas_nuevas} {d.carrera.ofertas_nuevas === 1 ? "oferta nueva" : "ofertas nuevas"}
          <div className="text-xs text-muted-foreground">{d.carrera.candidaturas} en seguimiento</div>
        </Tile>
        <Tile href="/educacion/" icon={GraduationCap} title="Estudios">
          {d.estudios.entregas_semana} {d.estudios.entregas_semana === 1 ? "entrega" : "entregas"} esta semana
          {d.estudios.proxima && <div className="truncate text-xs text-muted-foreground" title={d.estudios.proxima.texto}>{d.estudios.proxima.texto}</div>}
        </Tile>
        <Tile href="/finanzas/" icon={Landmark} title="Finanzas">{d.finanzas ? <><b className="tabular-nums">{Number(d.finanzas.ahorro).toLocaleString("es-ES", { minimumFractionDigits: 2 })} €</b><div className="text-xs text-muted-foreground">Ahorro del mes</div></> : <Pending>Sin cuentas todavía</Pending>}</Tile>
      </div>

      <div className="grid gap-4 xl:grid-cols-2 2xl:grid-cols-3">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="flex items-center gap-2"><CalendarDays className="size-4 text-primary" />Agenda de hoy</CardTitle>
            <SectionLink href="/agenda/">Ver agenda</SectionLink>
          </CardHeader>
          <CardContent>
            {d.agenda_error && <ErrorState message={d.agenda_error} />}
            {d.agenda.length === 0 && !d.agenda_error && <Empty message="Nada en la agenda de hoy" />}
            <ul className="divide-y divide-border">
              {d.agenda.map((a, i) => (
                <li key={`${a.titulo}-${i}`} className="flex gap-3 py-1.5 text-sm">
                  <span className="w-24 shrink-0 text-xs text-muted-foreground tabular-nums">{a.hora ? `${a.hora}${a.fin ? ` – ${a.fin}` : ""}` : a.tipo === "estudio" ? "Estudio" : "Todo el día"}</span>
                  <span className="min-w-0 flex-1 truncate" title={a.titulo}>{a.titulo}</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="flex items-center gap-2"><Dumbbell className="size-4 text-primary" />Entrenamiento</CardTitle>
            <SectionLink href="/gym/">Ver detalles</SectionLink>
          </CardHeader>
          <CardContent>
            <div className="mb-3 flex flex-wrap gap-x-6 gap-y-1 text-sm">
              <div><div className="text-xs text-muted-foreground">Volumen, frente a la semana pasada</div><b className="text-lg tabular-nums">{d.gym.volumen_pct == null ? "—" : signed(d.gym.volumen_pct)}</b></div>
              <div><div className="text-xs text-muted-foreground">Series</div><b className="text-lg tabular-nums">{d.gym.series_pct == null ? "—" : signed(d.gym.series_pct)}</b></div>
            </div>
            <Bars data={d.gym.por_dia} x="dia" y="volumen" unit=" kg" height={120} label="Volumen por día de esta semana" />
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Estado general</CardTitle></CardHeader>
          <CardContent>
            {!d.estado_general ? <Empty message="Haz tu primer check-in y aquí verás cómo van tu ánimo, tu energía y tu sueño." /> : (
              <div className="space-y-3 text-sm">
                <p className="text-xs text-muted-foreground">Últimos {d.estado_general.dias} días · {d.estado_general.checkins} check-ins</p>
                <div className="grid grid-cols-3 gap-3">
                  {([["Ánimo", d.estado_general.animo, "/5"], ["Energía", d.estado_general.energia, "/5"], ["Sueño", d.estado_general.sueno, " h"]] as const).map(([k, v, u]) => (
                    <div key={k}><div className="text-xs text-muted-foreground">{k}</div><b className="text-lg tabular-nums">{v == null ? "—" : `${v.toLocaleString("es-ES")}${u}`}</b></div>
                  ))}
                </div>
                {d.estado_general.habitos_hoy[1] > 0 && <p className="text-xs text-muted-foreground">Hábitos de hoy: {d.estado_general.habitos_hoy[0]} de {d.estado_general.habitos_hoy[1]}</p>}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader><CardTitle className="flex items-center gap-2"><Sparkles className="size-4 text-primary" />Insights de {asistente()}</CardTitle></CardHeader>
          <CardContent>
            {d.insights.length === 0 && <Empty message="Nada destacable ahora mismo." />}
            <div className="grid gap-2 sm:grid-cols-3 xl:grid-cols-1 2xl:grid-cols-3">
              {d.insights.map((i) => (
                <Link key={i.titulo} href={i.url} className={`rounded-lg p-3 text-sm ${INSIGHT[i.tipo]}`}>
                  <div className="font-medium">{i.titulo}</div>
                  <p className="mt-1 text-muted-foreground">{i.texto}</p>
                  <p className="mt-1 text-[11px] text-muted-foreground">Fuente: {i.fuente}</p>
                </Link>
              ))}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="flex items-center gap-2"><Target className="size-4 text-primary" />Objetivos activos</CardTitle>
            <SectionLink href="/objetivos/">Ver todos</SectionLink>
          </CardHeader>
          <CardContent>
            {!d.objetivos && <Empty message="Crea tu primer objetivo para verlo aquí." />}
            <ul className="space-y-2 text-sm">
              {d.objetivos?.map((g) => (
                <li key={g.id}>
                  <div className="flex justify-between gap-2"><span className="truncate">{g.titulo}</span><span className="text-xs text-muted-foreground tabular-nums">{g.progreso == null ? "Sin hitos" : `${g.progreso} %`}</span></div>
                  {g.progreso != null && <div className="mt-1 h-1.5 rounded-full bg-muted"><div className="h-full rounded-full bg-primary" style={{ width: `${g.progreso}%` }} /></div>}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
