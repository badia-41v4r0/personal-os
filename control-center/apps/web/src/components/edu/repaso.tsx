"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Eye, Plus, Sparkles, Timer as TimerIcon, Trash2 } from "lucide-react";
import { cn } from "cn";
import { HBars } from "@/components/cc/charts";
import { Field, selectClass, useAct } from "@/components/cc/form";
import { Empty, ErrorState, Loading } from "@/components/cc/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { api, post } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { Chip, Stat, preguntarTutor } from "./common";

type Carta = { id: number; asignatura: string; tipo: "concepto" | "examen"; frente: string; dorso: string; fuente: string; autor: string; vence: string; intervalo: number; fallos: number; suspendida: boolean };
type Stats = { total: number; hoy: number; nuevas: number; racha_dias: number; retencion: { asig: string; acierto: number; revisiones: number }[]; por_asignatura: { asig: string; tarjetas: number }[] };
const CODIGOS = ["FP", "FC", "SC", "SD", "ARD", "CI"];
const NOTAS = [[0, "Otra vez", "1"], [3, "Difícil", "2"], [4, "Bien", "3"], [5, "Fácil", "4"]] as const;

function Pregunta({ c, onNota, modo, binaria }: { c: Carta; onNota: (n: number) => void; modo: "repaso" | "simulacro"; binaria?: boolean }) {
  const [ver, setVer] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => { ref.current?.focus(); }, []);
  const opciones = useMemo(() => (binaria ? ([[0, "Fallada", "1"], [4, "Acertada", "2"]] as const) : NOTAS), [binaria]);
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLElement && ["TEXTAREA", "INPUT", "SELECT"].includes(e.target.tagName)) return;
      if (e.key === " " || e.key === "Enter") { e.preventDefault(); setVer(true); return; }
      const o = opciones.find((x) => x[2] === e.key);
      if (ver && o) onNota(o[0]);
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [ver, onNota, opciones]);
  return (
    <div ref={ref} tabIndex={-1} className="space-y-4 outline-none">
      <div className="flex items-center gap-2 text-xs text-muted-foreground"><Chip code={c.asignatura} />{c.tipo === "examen" ? "Tipo examen" : "Concepto"}{c.fuente && <span className="truncate">· {c.fuente}</span>}</div>
      <p className="whitespace-pre-wrap text-lg font-medium leading-snug">{c.frente}</p>
      {!ver ? <Button onClick={() => setVer(true)}><Eye />Ver respuesta <kbd className="ml-1 rounded bg-primary-foreground/20 px-1 text-[10px]">espacio</kbd></Button> : (
        <>
          <div className="whitespace-pre-wrap rounded-lg bg-muted/60 p-3 text-sm">{c.dorso}</div>
          <div className="flex flex-wrap gap-2" role="group" aria-label={modo === "repaso" ? "¿Cómo de bien la sabías?" : "Resultado"}>
            {opciones.map(([n, l, k]) => <Button key={n} variant={n === 0 ? "outline" : "default"} onClick={() => onNota(n)}>{l}<kbd className="ml-1 rounded bg-foreground/10 px-1 text-[10px]">{k}</kbd></Button>)}
          </div>
        </>
      )}
    </div>
  );
}

function SesionRepaso({ asignatura, onFin }: { asignatura?: string; onFin: () => void }) {
  const q = useApi<Carta[]>(`/education/cards/due?limit=20${asignatura ? `&asignatura=${asignatura}` : ""}`);
  const [i, setI] = useState(0);
  const [hechas, setHechas] = useState(0);
  const a = useAct();
  const cola = q.data ?? [];
  const c = cola[i];
  const nota = useCallback((n: number) => {
    if (!c) return;
    void a.run(async () => { await post(`/education/cards/${c.id}/review`, { nota: n }); setHechas((h) => h + 1); setI((x) => x + 1); });
  }, [a, c]);
  if (q.loading && !q.data) return <Loading rows={3} />;
  if (q.error) return <ErrorState message={q.error} />;
  if (!c) return <div className="space-y-3"><Empty message={hechas ? `Sesión terminada: ${hechas} tarjetas repasadas.` : "No hay tarjetas pendientes hoy."} /><Button variant="outline" onClick={onFin}>Volver</Button></div>;
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between text-xs text-muted-foreground"><span>{i + 1} de {cola.length}</span><Button size="sm" variant="ghost" onClick={onFin}>Salir</Button></div>
      <Pregunta key={c.id} c={c} onNota={nota} modo="repaso" />
      {a.ErrorBox}
    </div>
  );
}

function Simulacro({ onFin }: { onFin: () => void }) {
  const [asig, setAsig] = useState("SD");
  const [n, setN] = useState(10);
  const [minutos, setMinutos] = useState(20);
  const [preg, setPreg] = useState<Carta[] | null>(null);
  const [i, setI] = useState(0);
  const [res, setRes] = useState<boolean[]>([]);
  const [resto, setResto] = useState(0);
  const a = useAct();
  useEffect(() => {
    if (!preg || res.length >= preg.length || !minutos) return;
    const t = setInterval(() => setResto((r) => Math.max(0, r - 1)), 1000);
    return () => clearInterval(t);
  }, [preg, res.length, minutos]);
  const empezar = () => a.run(async () => {
    const r = await post<{ preguntas: Carta[] }>("/education/simulacro", { asignatura: asig, n, minutos });
    setPreg(r.preguntas); setI(0); setRes([]); setResto(minutos * 60);
  });
  const nota = (v: number) => {
    const c = preg?.[i];
    if (!c) return;
    void a.run(async () => { await post(`/education/cards/${c.id}/review`, { nota: v, modo: "simulacro" }); setRes((r) => [...r, v > 0]); setI((x) => x + 1); });
  };
  if (!preg) {
    return (
      <div className="space-y-3">
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Asignatura"><select className={selectClass} value={asig} onChange={(e) => setAsig(e.target.value)}>{CODIGOS.map((c) => <option key={c}>{c}</option>)}</select></Field>
          <Field label="Preguntas"><select className={selectClass} value={n} onChange={(e) => setN(Number(e.target.value))}>{[5, 10, 15, 20, 30].map((x) => <option key={x}>{x}</option>)}</select></Field>
          <Field label="Tiempo"><select className={selectClass} value={minutos} onChange={(e) => setMinutos(Number(e.target.value))}>{[0, 10, 20, 30, 45, 60].map((x) => <option key={x} value={x}>{x ? `${x} min` : "Sin límite"}</option>)}</select></Field>
          <Button disabled={a.busy} onClick={empezar}><TimerIcon />Empezar</Button>
          <Button variant="ghost" onClick={onFin}>Volver</Button>
        </div>
        <p className="text-xs text-muted-foreground">Saca primero las de tipo examen y las que más has fallado. Cada respuesta actualiza su calendario de repaso.</p>
        {a.ErrorBox}
      </div>
    );
  }
  const fin = i >= preg.length || (minutos > 0 && resto === 0);
  if (fin) {
    const ok = res.filter(Boolean).length;
    const sin = preg.length - res.length;
    return (
      <div className="space-y-3">
        <div className="grid max-w-md grid-cols-3 gap-3"><Stat label="Acertadas" value={`${ok}/${preg.length}`} /><Stat label="Nota" value={(10 * ok / preg.length).toFixed(1)} hint="sobre 10" /><Stat label="Sin contestar" value={sin} /></div>
        {sin > 0 && <p className="text-xs text-muted-foreground">Se acabó el tiempo; las {sin} sin contestar cuentan como falladas en la nota, pero no cambian su calendario.</p>}
        <div className="flex gap-2"><Button onClick={() => setPreg(null)}>Otro simulacro</Button><Button variant="outline" onClick={onFin}>Volver</Button></div>
      </div>
    );
  }
  const mm = `${Math.floor(resto / 60)}:${String(resto % 60).padStart(2, "0")}`;
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between text-xs text-muted-foreground"><span>Pregunta {i + 1} de {preg.length}</span>{minutos > 0 && <span className={cn("font-mono tabular-nums", resto < 60 && "text-destructive")}>{mm}</span>}</div>
      <Pregunta key={preg[i].id} c={preg[i]} onNota={nota} modo="simulacro" binaria />
      {a.ErrorBox}
    </div>
  );
}

function Mazo({ reload }: { reload: () => void }) {
  const [filtro, setFiltro] = useState("");
  const cartas = useApi<Carta[]>(`/education/cards?limit=300${filtro ? `&asignatura=${filtro}` : ""}`);
  const a = useAct(() => { cartas.reload(); reload(); });
  const [f, setF] = useState({ asignatura: "SD", tipo: "concepto", frente: "", dorso: "" });
  const nueva = () => a.run(async () => { await post("/education/cards", [{ asignatura: f.asignatura, tipo: f.tipo, frente: f.frente, dorso: f.dorso, fuente: "manual" }]); setF({ ...f, frente: "", dorso: "" }); });
  const lista = useMemo(() => cartas.data ?? [], [cartas.data]);
  return (
    <div className="grid gap-4 xl:grid-cols-[1fr_20rem]">
      <Card>
        <CardHeader className="flex-row items-center justify-between gap-2"><CardTitle>Tarjetas ({lista.length})</CardTitle>
          <select aria-label="Filtrar por asignatura" className={selectClass} value={filtro} onChange={(e) => setFiltro(e.target.value)}><option value="">Todas</option>{CODIGOS.map((c) => <option key={c}>{c}</option>)}</select>
        </CardHeader>
        <CardContent>
          {lista.length === 0 && <Empty message="Aún no hay tarjetas. Pídele al tutor que las genere desde Asignaturas." />}
          <ul className="divide-y divide-border">
            {lista.map((c) => (
              <li key={c.id} className={cn("flex items-start gap-3 py-2.5 text-sm", c.suspendida && "opacity-50")}>
                <Chip code={c.asignatura} />
                <div className="min-w-0 flex-1"><p className="font-medium">{c.frente}</p><p className="text-muted-foreground">{c.dorso}</p>
                  <p className="mt-0.5 text-[11px] text-muted-foreground">{c.tipo} · vence {c.vence.slice(5).split("-").reverse().join("/")} · {c.fallos} fallos · {c.autor}</p></div>
                <Button size="icon-sm" variant="ghost" aria-label="Borrar tarjeta" disabled={a.busy} onClick={() => a.run(() => api(`/education/cards/${c.id}`, { method: "DELETE" }))}><Trash2 /></Button>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
      <Card className="h-fit">
        <CardHeader><CardTitle>Nueva tarjeta</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <div className="flex gap-2">
            <Field label="Asignatura"><select className={selectClass} value={f.asignatura} onChange={(e) => setF({ ...f, asignatura: e.target.value })}>{CODIGOS.map((c) => <option key={c}>{c}</option>)}</select></Field>
            <Field label="Tipo"><select className={selectClass} value={f.tipo} onChange={(e) => setF({ ...f, tipo: e.target.value })}><option value="concepto">Concepto</option><option value="examen">Examen</option></select></Field>
          </div>
          <Field label="Pregunta"><Textarea rows={2} value={f.frente} onChange={(e) => setF({ ...f, frente: e.target.value })} /></Field>
          <Field label="Respuesta"><Textarea rows={3} value={f.dorso} onChange={(e) => setF({ ...f, dorso: e.target.value })} /></Field>
          <Button disabled={a.busy || !f.frente.trim() || !f.dorso.trim()} onClick={nueva}><Plus />Añadir</Button>
          {a.ErrorBox}
        </CardContent>
      </Card>
    </div>
  );
}

export function RepasoTab() {
  const st = useApi<Stats>("/education/cards/stats");
  const [modo, setModo] = useState<"inicio" | "repaso" | "simulacro" | "mazo">("inicio");
  const a = useAct();
  const [aviso, setAviso] = useState<string | null>(null);
  const volver = () => { setModo("inicio"); st.reload(); };
  if (modo === "repaso") return <Card><CardContent className="py-5"><SesionRepaso onFin={volver} /></CardContent></Card>;
  if (modo === "simulacro") return <Card><CardContent className="py-5"><Simulacro onFin={volver} /></CardContent></Card>;
  if (modo === "mazo") return <div className="space-y-3"><Button variant="ghost" size="sm" onClick={volver}>← Volver</Button><Mazo reload={st.reload} /></div>;
  const s = st.data;
  return (
    <div className="space-y-4">
      {st.error && <ErrorState message={st.error} />}
      {!s && st.loading && <Loading rows={3} />}
      {s && (
        <div className="grid gap-4 xl:grid-cols-2">
          <Card>
            <CardHeader><CardTitle>Repaso espaciado</CardTitle></CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-4 gap-3"><Stat label="Hoy" value={s.hoy} hint="pendientes" /><Stat label="Total" value={s.total} /><Stat label="Nuevas" value={s.nuevas} /><Stat label="Racha" value={`${s.racha_dias} d`} /></div>
              <div className="flex flex-wrap gap-2">
                <Button disabled={!s.hoy} onClick={() => setModo("repaso")}>Repasar {s.hoy || ""}</Button>
                <Button variant="outline" disabled={!s.total} onClick={() => setModo("simulacro")}><TimerIcon />Simulacro</Button>
                <Button variant="outline" onClick={() => setModo("mazo")}>Gestionar tarjetas</Button>
              </div>
              <div className="border-t border-border pt-3">
                <Button size="sm" variant="outline" disabled={a.busy} onClick={() => a.run(async () => { await preguntarTutor("Genera entre 8 y 12 tarjetas de repaso de cada asignatura que te cuesta (SC I, CI, SD, ARD) con mis notas de /vault/Uni/Asignaturas, priorizando ejercicios resolubles. Revisa antes uni.cards.due para no repetir y añádelas con uni.card.add."); setAviso("Encargo enviado al tutor: tarda un poco y las tarjetas aparecerán aquí."); })}><Sparkles />Pedir tarjetas al tutor</Button>
                {aviso && <p role="status" className="mt-2 text-xs text-muted-foreground">{aviso}</p>}
                {a.ErrorBox}
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Acierto por asignatura (30 días)</CardTitle></CardHeader>
            <CardContent>
              {s.retencion.length === 0 ? <Empty message="Aún no hay repasos que medir." /> : <HBars data={s.retencion.map((r) => ({ name: r.asig, value: r.acierto }))} label="Porcentaje de acierto" unit=" %" />}
              <p className="mt-2 text-xs text-muted-foreground">Acierto = «difícil», «bien» o «fácil». Las que más fallas vuelven antes.</p>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
