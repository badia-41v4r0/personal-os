"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { Pencil } from "lucide-react";
import { cn } from "cn";
import { Empty, ErrorState, Loading } from "@/components/cc/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api, post } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { type Comparacion, day, errMsg, kg, Msg, NivelBadge, num, type Plan, type Propuesta, selectCls, serie } from "./common";
import { RecommendedCard } from "./overview";
import { PlanEditor, PlanStateBadge, SessionExercises } from "./session";

type Recs = { siguiente: Propuesta | null; planificada: Plan | null; reprogramar: { id: string; tipo: string; sesion: string; desde: string; hasta: string | null; motivo: string }[] };

const EST: Record<string, string> = { cumplido: "text-success", parcial: "text-warning", no_cumplido: "text-destructive", omitido: "text-destructive", hecho: "" };

export function ComparacionView({ c }: { c: Comparacion }) {
  if (c.estado !== "asociada") return <p className="text-sm text-muted-foreground">Sin entreno asociado: no se compara hasta que haya uno de la misma fecha y sesión, o lo asocies a mano.</p>;
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-1 text-sm">
        <span>Cumplimiento: <b className="font-mono tabular-nums">{c.cumplimiento ?? "—"} %</b></span>
        <span className="text-muted-foreground">Volumen previsto {kg(c.volumen_previsto)} · real {kg(c.volumen_real)}</span>
        <NivelBadge n="calculado" />
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[34rem] text-sm">
          <thead className="text-left text-xs text-muted-foreground">
            <tr><th className="py-1 font-normal">Ejercicio</th><th className="font-normal">Series</th><th className="font-normal">Top set previsto</th><th className="font-normal">Real</th><th className="font-normal">Estado</th></tr>
          </thead>
          <tbody className="divide-y divide-border">
            {c.ejercicios.map((e) => (
              <tr key={e.id}>
                <td className="py-1.5 pr-2">{e.nombre}</td>
                <td className="font-mono tabular-nums">{e.series_hechas}/{e.series_previstas}</td>
                <td className="font-mono tabular-nums">{e.objetivo?.reps != null ? serie({ peso: e.objetivo.peso ?? null, reps: e.objetivo.reps }) : "—"}</td>
                <td className="font-mono tabular-nums">{e.real ? serie(e.real) : "—"}
                  {e.diferencia_peso != null && e.diferencia_peso !== 0 && <span className="text-xs text-muted-foreground"> ({e.diferencia_peso > 0 ? "+" : ""}{num(e.diferencia_peso)} kg)</span>}
                  {e.diferencia_reps != null && e.diferencia_reps !== 0 && <span className="text-xs text-muted-foreground"> ({e.diferencia_reps > 0 ? "+" : ""}{e.diferencia_reps} reps)</span>}
                </td>
                <td className={cn("text-xs", EST[e.estado])}>{e.estado.replace("_", " ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {c.anadidos.length > 0 && <p className="text-xs text-muted-foreground">Añadidos (no previstos): {c.anadidos.map((a) => `${a.nombre} (${a.series} series)`).join(", ")}</p>}
      {c.criterio && <p className="text-[11px] text-muted-foreground">{c.criterio}</p>}
    </div>
  );
}

function PlanDetail({ id, onChanged }: { id: string; onChanged: () => void }) {
  const p = useApi<Plan>(`/gym/plans/${id}`);
  const [editar, setEditar] = useState(false);
  const [wid, setWid] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  if (p.error) return <ErrorState message={p.error} />;
  if (!p.data) return <Loading rows={4} />;
  const d = p.data;
  const act = async (f: () => Promise<unknown>, ok: string) => {
    try {
      await f();
      setMsg({ ok: true, text: ok });
      p.reload();
      onChanged();
    } catch (e) {
      setMsg({ ok: false, text: errMsg(e) });
    }
  };
  const estado = (e: string) => act(() => api(`/gym/plans/${id}`, { method: "PATCH", body: JSON.stringify({ estado: e, motivo: `Marcada como ${e} desde el panel`, version_base: d.version }) }), `Marcada como ${e}.`);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <b>{d.nombre}</b><span className="text-muted-foreground">{day(d.fecha)}</span><PlanStateBadge estado={d.estado} />
        <span className="text-xs text-muted-foreground">v{d.version} · {d.creada_por}{d.origen_fecha ? ` · movida desde el ${d.origen_fecha}` : ""}</span>
      </div>
      {editar ? (
        <PlanEditor plan={d} fecha={d.fecha} nombre={d.nombre} onCancel={() => setEditar(false)} onSaved={() => { setEditar(false); p.reload(); onChanged(); }} />
      ) : (
        <>
          <SessionExercises ejercicios={d.ejercicios} compact />
          <div className="flex flex-wrap gap-2">
            {!d.workout_id && ["aceptada", "pospuesta"].includes(d.estado) && <Button size="sm" variant="outline" onClick={() => setEditar(true)}><Pencil /> Modificar</Button>}
            {!d.workout_id && d.estado !== "omitida" && <Button size="sm" variant="ghost" onClick={() => estado("omitida")}>No la haré</Button>}
            {!d.workout_id && d.estado !== "descartada" && <Button size="sm" variant="ghost" onClick={() => estado("descartada")}>Descartar</Button>}
          </div>
        </>
      )}
      <div className="space-y-2">
        <h3 className="text-sm font-medium">Previsto frente a realizado</h3>
        {d.comparacion ? <ComparacionView c={d.comparacion} /> : <p className="text-sm text-muted-foreground">Aún sin entreno asociado.</p>}
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="text-muted-foreground">Asociación {d.link_mode === "manual" ? "manual" : d.link_mode === "auto" ? "automática (misma fecha y sesión)" : "pendiente"}.</span>
          <select aria-label="Entreno a asociar" value={wid} onChange={(e) => setWid(e.target.value)} className={selectCls}>
            <option value="">Elegir entreno (±3 días)…</option>
            {d.candidatas?.map((c) => <option key={c.id} value={c.id}>{c.fecha} · {c.nombre}</option>)}
          </select>
          <Button size="xs" variant="outline" disabled={!wid} onClick={() => act(() => post(`/gym/plans/${id}/link`, { workout_id: wid }), "Asociada.")}>Asociar</Button>
          {d.workout_id && <Button size="xs" variant="ghost" onClick={() => act(() => post(`/gym/plans/${id}/link`, { workout_id: null }), "Asociación quitada.")}>Quitar asociación</Button>}
        </div>
      </div>
      {(d.versiones?.length ?? 0) > 1 && (
        <div>
          <h3 className="text-sm font-medium">Versiones</h3>
          <ul className="mt-1 space-y-0.5 text-xs text-muted-foreground">
            {d.versiones!.slice().reverse().map((v) => <li key={v.version}>v{v.version} · {v.fecha.slice(0, 10)} · {v.autor}: {v.motivo} ({v.ejercicios.length} ejercicios)</li>)}
          </ul>
        </div>
      )}
      {msg && <Msg {...msg} />}
    </div>
  );
}

export function TrainingTab() {
  const params = useSearchParams();
  const router = useRouter();
  const recs = useApi<Recs>("/gym/recommendations");
  const plans = useApi<Plan[]>("/gym/plans");
  const editar = params.get("editar") === "1";
  const pid = params.get("plan");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const reload = () => { recs.reload(); plans.reload(); };
  const s = recs.data?.planificada ?? recs.data?.siguiente ?? null;

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader><CardTitle>{recs.data?.planificada ? "Sesión planificada" : "Entrenamiento recomendado"}</CardTitle></CardHeader>
        <CardContent>
          {editar && s ? (
            <PlanEditor key={s.fecha + s.nombre} plan={recs.data?.planificada ?? undefined} propuesta={recs.data?.siguiente ?? undefined} fecha={s.fecha} nombre={s.nombre}
              onCancel={() => router.replace("/gym/?tab=training")}
              onSaved={() => { router.replace("/gym/?tab=training"); reload(); }} />
          ) : <RecommendedCard compact={false} onChanged={reload} />}
        </CardContent>
      </Card>

      {(recs.data?.reprogramar.length ?? 0) > 0 && (
        <Card>
          <CardHeader><CardTitle>Sesiones perdidas esta semana</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            {recs.data!.reprogramar.map((r) => (
              <div key={r.id} className="flex flex-wrap items-center justify-between gap-2 border-b border-border pb-2 text-sm last:border-0">
                <div className="min-w-0">
                  <div>{r.sesion} del {day(r.desde)} → {r.hasta ? <b>{day(r.hasta)}</b> : <b>no recuperarla</b>} <NivelBadge n="recomendacion" /></div>
                  <div className="text-xs text-muted-foreground">{r.motivo}</div>
                </div>
                <Button size="sm" variant="outline" onClick={async () => {
                  try { await post(`/gym/recommendations/${r.id}/accept`, {}); setMsg({ ok: true, text: "Hecho." }); reload(); } catch (e) { setMsg({ ok: false, text: errMsg(e) }); }
                }}>Aceptar</Button>
              </div>
            ))}
            {msg && <Msg {...msg} />}
          </CardContent>
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <Card>
          <CardHeader><CardTitle>Planificadas</CardTitle></CardHeader>
          <CardContent>
            {plans.error && <ErrorState message={plans.error} />}
            {plans.data?.length === 0 && <Empty message="Aún no has aceptado ninguna planificación. Acepta la recomendada y aquí verás lo previsto frente a lo realizado." />}
            <ul className="divide-y divide-border">
              {plans.data?.map((p) => (
                <li key={p.id}>
                  <Link href={`/gym/?tab=training&plan=${p.id}`} className={cn("grid grid-cols-[6.5rem_1fr_auto] items-center gap-2 py-2 text-sm hover:text-primary", pid === p.id && "text-primary")}>
                    <span className="text-muted-foreground">{day(p.fecha)}</span>
                    <span className="truncate">{p.nombre} <span className="text-xs text-muted-foreground">v{p.version}</span></span>
                    <span className="flex items-center gap-2 text-xs">{p.comparacion?.cumplimiento != null && <span className="font-mono tabular-nums">{p.comparacion.cumplimiento} %</span>}<PlanStateBadge estado={p.estado} /></span>
                  </Link>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Detalle</CardTitle></CardHeader>
          <CardContent>{pid ? <PlanDetail key={pid} id={pid} onChanged={reload} /> : <Empty message="Elige una sesión planificada para ver lo previsto frente a lo realizado." />}</CardContent>
        </Card>
      </div>
    </div>
  );
}
