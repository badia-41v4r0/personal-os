"use client";

import { useState } from "react";
import { AlertTriangle, Trash2 } from "lucide-react";
import { cn } from "cn";
import { Lines } from "@/components/cc/charts";
import { Empty, ErrorState, Loading } from "@/components/cc/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { api, post } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { day, errMsg, Msg, MUSCULO, NivelBadge, num, today } from "./common";

type Log = { fecha: string; energia: number | null; sueno: number | null; sueno_horas: number | null; agujetas: number | null; motivacion: number | null; estres: number | null; molestia_zona: string; molestia_intensidad: number | null; notas: string };
type Rec = {
  musculos: { musculo: string; ultima: string | null; dias: number | null; series_7d: number; media_semanal_previa: number; ratio: number | null; estado: string }[];
  sensaciones: Log[]; medias_14d: Record<string, number | null>; molestias: { zona: string; fuente: string; detalle: string }[];
  dias_seguidos_mismo_musculo: { fechas: string[]; musculos: string[] }[];
  correlaciones: { por_campo: Record<string, { n: number; r: number | null; texto: string }>; criterio: string };
  aviso: string; registros: Log[]; pausas: Pausa[];
};
type Pausa = { id: number; desde: string; hasta: string | null; motivo: string; nota: string; por: string };
const MOTIVOS: [string, string][] = [["enfermedad", "Enfermedad"], ["lesion", "Lesión"], ["vacaciones", "Vacaciones"], ["otro", "Otro"]];

function Pausas({ pausas, onChange }: { pausas: Pausa[]; onChange: () => void }) {
  const [desde, setDesde] = useState(today());
  const [hasta, setHasta] = useState("");
  const [motivo, setMotivo] = useState("enfermedad");
  const [nota, setNota] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const run = async (fn: () => Promise<unknown>, ok: string) => {
    try {
      await fn();
      setMsg({ ok: true, text: ok });
      onChange();
    } catch (e) {
      setMsg({ ok: false, text: errMsg(e) });
    }
  };
  const etiqueta = (m: string) => MOTIVOS.find(([k]) => k === m)?.[1] ?? m;
  return (
    <Card>
      <CardHeader><CardTitle>Periodos sin entrenar</CardTitle></CardHeader>
      <CardContent className="space-y-3 text-sm">
        <p className="text-xs text-muted-foreground">Enfermedad, lesión o vacaciones. Esos días no cuentan como sesiones perdidas ni se reprograman, y al volver el Coach propone la primera sesión de cada ejercicio al ~90 % de la carga, sin fallo; la segunda recupera la carga de antes.</p>
        <form className="grid gap-2 sm:grid-cols-[auto_auto_10rem]" onSubmit={(e) => { e.preventDefault(); void run(() => post("/gym/pauses", { desde, hasta: hasta || null, motivo, nota }), "Pausa guardada."); }}>
          <label className="grid gap-1 text-xs text-muted-foreground">Desde<Input type="date" value={desde} onChange={(e) => setDesde(e.target.value)} required /></label>
          <label className="grid gap-1 text-xs text-muted-foreground">Hasta (vacío = en curso)<Input type="date" value={hasta} min={desde} onChange={(e) => setHasta(e.target.value)} /></label>
          <label className="grid gap-1 text-xs text-muted-foreground">Motivo
            <select value={motivo} onChange={(e) => setMotivo(e.target.value)} className="h-9 rounded-md border border-input bg-background px-2 text-sm">
              {MOTIVOS.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>
          <Input className="sm:col-span-3" value={nota} maxLength={500} onChange={(e) => setNota(e.target.value)} placeholder="Nota (opcional)" aria-label="Nota" />
          <Button type="submit" size="sm" className="w-fit">Añadir pausa</Button>
        </form>
        {msg && <Msg ok={msg.ok} text={msg.text} />}
        {pausas.length === 0 ? <Empty message="Sin pausas registradas." /> : (
          <ul className="divide-y divide-border">
            {pausas.map((p) => (
              <li key={p.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                <span>
                  <b>{etiqueta(p.motivo)}</b> · {day(p.desde)} – {p.hasta ? day(p.hasta) : "en curso"}
                  {p.nota && <span className="block text-xs text-muted-foreground">{p.nota}</span>}
                </span>
                <span className="flex gap-1">
                  {!p.hasta && <Button size="sm" variant="outline" onClick={() => void run(() => post(`/gym/pauses/${p.id}/end`), "Pausa terminada: hoy vuelves.")}>Terminar</Button>}
                  <Button size="sm" variant="ghost" aria-label={`Borrar la pausa del ${p.desde}`} onClick={() => void run(() => api(`/gym/pauses/${p.id}`, { method: "DELETE" }), "Pausa borrada.")}><Trash2 className="size-4" /></Button>
                </span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

const CAMPOS: [keyof Log, string, string][] = [
  ["energia", "Energía", "1 muy baja · 5 muy alta"], ["sueno", "Sueño", "1 muy malo · 5 muy bueno"], ["agujetas", "Agujetas", "1 nada · 5 muchas"],
  ["motivacion", "Motivación", "1 nada · 5 mucha"], ["estres", "Estrés", "1 nada · 5 mucho"],
];
const ESTADO: Record<string, [string, string]> = {
  carga_alta: ["carga alta", "text-warning"], reciente: ["entrenado ayer/hoy", "text-muted-foreground"], sin_trabajar: ["+10 días sin trabajar", "text-warning"],
  carga_baja: ["carga baja", "text-muted-foreground"], normal: ["normal", "text-success"], sin_datos: ["sin datos", "text-muted-foreground"],
};

function Escala({ value, onChange, label }: { value: number | null; onChange: (v: number | null) => void; label: string }) {
  return (
    <div role="group" aria-label={label} className="flex gap-1">
      {[1, 2, 3, 4, 5].map((n) => (
        <button key={n} type="button" aria-pressed={value === n} onClick={() => onChange(value === n ? null : n)}
          className={cn("size-8 rounded-md border text-sm tabular-nums", value === n ? "border-primary bg-primary/10 text-primary" : "border-border text-muted-foreground hover:text-foreground")}>{n}</button>
      ))}
    </div>
  );
}

function Formulario({ inicial, onSaved }: { inicial: Log | undefined; onSaved: (texto: string) => void }) {
  const vacio: Log = { fecha: today(), energia: null, sueno: null, sueno_horas: null, agujetas: null, motivacion: null, estres: null, molestia_zona: "", molestia_intensidad: null, notas: "" };
  const [f, setF] = useState<Log>(inicial ?? vacio);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  async function save() {
    try {
      await post("/gym/recovery", f);
      onSaved(`Guardado el ${f.fecha}.`);
    } catch (e) {
      setMsg({ ok: false, text: errMsg(e) });
    }
  }
  return (
    <div className="space-y-3 text-sm">
      <label className="block text-xs text-muted-foreground">Día<Input type="date" max={today()} value={f.fecha} onChange={(e) => setF({ ...vacio, fecha: e.target.value })} className="w-auto" /></label>
      {CAMPOS.map(([k, l, h]) => (
        <div key={k} className="flex flex-wrap items-center justify-between gap-2">
          <span>{l} <span className="text-[11px] text-muted-foreground">({h})</span></span>
          <Escala label={l} value={f[k] as number | null} onChange={(v) => setF({ ...f, [k]: v })} />
        </div>
      ))}
      <label className="block text-xs text-muted-foreground">Horas de sueño<Input inputMode="decimal" value={f.sueno_horas ?? ""} onChange={(e) => setF({ ...f, sueno_horas: e.target.value === "" ? null : Number(e.target.value.replace(",", ".")) })} className="w-24" /></label>
      <div className="grid gap-2 sm:grid-cols-[1fr_auto]">
        <label className="text-xs text-muted-foreground">Molestia o dolor (zona)<Input placeholder="p. ej. hombro derecho, rodilla…" value={f.molestia_zona} onChange={(e) => setF({ ...f, molestia_zona: e.target.value })} /></label>
        <div className="text-xs text-muted-foreground">Intensidad<Escala label="Intensidad de la molestia" value={f.molestia_intensidad} onChange={(v) => setF({ ...f, molestia_intensidad: v })} /></div>
      </div>
      <Textarea placeholder="Notas" aria-label="Notas" value={f.notas} onChange={(e) => setF({ ...f, notas: e.target.value })} rows={2} />
      <Button size="sm" onClick={save}>Guardar sensaciones</Button>
      {msg && <Msg {...msg} />}
      <p className="text-[11px] text-muted-foreground">Si anotas una molestia, durante 10 días los ejercicios que cargan esa zona van sin fallo y sin subir carga. No es un diagnóstico: si el dolor sigue, consúltalo con un profesional.</p>
    </div>
  );
}

export function RecoveryTab() {
  const r = useApi<Rec>("/gym/recovery");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [guardado, setGuardado] = useState("");
  if (r.error) return <ErrorState message={r.error} />;
  if (!r.data) return <Loading rows={8} />;
  const d = r.data;
  const hoyLog = d.registros.find((l) => l.fecha === today());
  const serie = [...d.registros].reverse().slice(-30).map((l) => ({ ...l, f: l.fecha.slice(5) }));
  return (
    <div className="space-y-4">
      <p className="flex items-start gap-1.5 text-xs text-muted-foreground"><AlertTriangle className="mt-0.5 size-3.5 shrink-0" />{d.aviso}</p>
      {d.molestias.length > 0 && (
        <div role="alert" className="rounded-lg border border-warning/40 bg-warning/10 p-3 text-sm">
          <b>Molestias activas:</b> {d.molestias.map((m) => `${m.zona} (${m.fuente}${m.detalle ? `: ${m.detalle}` : ""})`).join(" · ")}. No fuerces los ejercicios de esa zona.
        </div>
      )}
      <Pausas pausas={d.pausas ?? []} onChange={r.reload} />
      <div className="grid gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <Card>
          <CardHeader><CardTitle className="flex items-center gap-2">Carga reciente por músculo <NivelBadge n="inferencia" /></CardTitle></CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[30rem] text-sm">
                <thead className="text-left text-xs text-muted-foreground">
                  <tr><th className="py-1 font-normal">Músculo</th><th className="font-normal">Última vez</th><th className="font-normal">Series 7 d</th><th className="font-normal">Media previa</th><th className="font-normal">Estado</th></tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {d.musculos.map((m) => (
                    <tr key={m.musculo}>
                      <td className="py-1.5">{MUSCULO[m.musculo] ?? m.musculo}</td>
                      <td className="text-xs text-muted-foreground">{m.ultima ? `${day(m.ultima)} (${m.dias} d)` : "—"}</td>
                      <td className="font-mono tabular-nums">{num(m.series_7d)}</td>
                      <td className="font-mono tabular-nums text-muted-foreground">{num(m.media_semanal_previa)}/sem</td>
                      <td className={cn("text-xs", ESTADO[m.estado]?.[1])}>{ESTADO[m.estado]?.[0] ?? m.estado}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-2 text-[11px] text-muted-foreground">Series de los últimos 7 días (principal 1, secundario 0,5) frente a la media semanal de las 3 semanas anteriores. «Carga alta» = más de 1,5× la habitual. Frecuencia no es recuperación.</p>
            {d.dias_seguidos_mismo_musculo.length > 0 && (
              <p className="mt-2 text-xs text-warning">Días seguidos con los mismos músculos principales: {d.dias_seguidos_mismo_musculo.map((x) => `${x.fechas.map((f) => f.slice(5)).join("→")} (${x.musculos.map((m) => MUSCULO[m] ?? m).join(", ")})`).join("; ")}</p>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>¿Cómo estás {hoyLog ? "(hoy ya registrado)" : "hoy"}?</CardTitle></CardHeader>
          <CardContent>
            <Formulario key={hoyLog?.fecha ?? "nuevo"} inicial={hoyLog} onSaved={(t) => { setGuardado(t); r.reload(); }} />
            {guardado && <div className="mt-2"><Msg ok text={guardado} /></div>}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle className="flex items-center gap-2">Sensaciones registradas <NivelBadge n="registrado" /></CardTitle></CardHeader>
          <CardContent className="space-y-3">
            {serie.length < 2 ? <Empty message="Registra tus sensaciones unos días para ver la tendencia." /> : (
              <Lines curve="linear" data={serie} x="f" label="Sensaciones" series={[{ key: "energia", name: "Energía" }, { key: "sueno", name: "Sueño" }, { key: "motivacion", name: "Motivación" }]} height={180} />
            )}
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
              Media 14 días: {CAMPOS.map(([k, l]) => `${l} ${d.medias_14d[k as string] ?? "—"}`).join(" · ")}
            </div>
            <ul className="max-h-60 divide-y divide-border overflow-y-auto text-xs">
              {d.registros.map((l) => (
                <li key={l.fecha} className="flex items-center justify-between gap-2 py-1">
                  <span className="min-w-0">
                    <b>{day(l.fecha)}</b> · {CAMPOS.filter(([k]) => l[k] != null).map(([k, lab]) => `${lab} ${l[k]}`).join(", ") || "—"}
                    {l.sueno_horas != null && ` · ${l.sueno_horas} h`}{l.molestia_zona && <span className="text-warning"> · molestia: {l.molestia_zona}{l.molestia_intensidad ? ` (${l.molestia_intensidad}/5)` : ""}</span>}
                    {l.notas && <span className="block truncate text-muted-foreground">{l.notas}</span>}
                  </span>
                  <Button size="icon-xs" variant="ghost" aria-label={`Borrar el registro del ${l.fecha}`} onClick={async () => {
                    try { await api(`/gym/recovery/${l.fecha}`, { method: "DELETE" }); r.reload(); } catch (e) { setMsg({ ok: false, text: errMsg(e) }); }
                  }}><Trash2 /></Button>
                </li>
              ))}
            </ul>
            {msg && <Msg {...msg} />}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle className="flex items-center gap-2">Sensaciones y rendimiento <NivelBadge n="inferencia" /></CardTitle></CardHeader>
          <CardContent className="space-y-1.5 text-sm">
            {CAMPOS.map(([k, l]) => {
              const c = d.correlaciones.por_campo[k as string];
              return <div key={k} className="flex justify-between gap-3"><span>{l}</span><span className="text-right text-xs text-muted-foreground">{c?.texto ?? "—"}</span></div>;
            })}
            <p className="pt-2 text-[11px] text-muted-foreground">{d.correlaciones.criterio} Correlación no implica causa; con pocos días no se calcula.</p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
