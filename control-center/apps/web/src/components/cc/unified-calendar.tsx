"use client";

// Calendario unificado: Google (sin Family), uni, tareas, trabajo, gym y vida en una sola vista.
// Solo lee de /calendar; marcar como hecho usa los mismos endpoints que las páginas de origen.

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { cn } from "cn";
import { Check, ChevronLeft, ChevronRight, ExternalLink, RefreshCw, Undo2 } from "lucide-react";
import { ErrorState, Loading } from "@/components/cc/states";
import { TaskCheck } from "@/components/cc/task-check";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { post } from "@/lib/api";
import { useApi } from "@/lib/hooks";

type Item = {
  id: string; capa: string; titulo: string; dia: string; hasta: string;
  inicio: string | null; fin: string | null; hecho: boolean | null; detalle: string; enlace: string | null; clave: string | null;
};
type Resp = { desde: string; hasta: string; hoy: string; capas: string[]; items: Item[]; errores: Record<string, string> };

const CAPAS: { id: string; label: string; dot: string; chip: string }[] = [
  { id: "google", label: "Google", dot: "bg-chart-1", chip: "border-chart-1/40 bg-chart-1/10" },
  { id: "uni", label: "Uni", dot: "bg-chart-3", chip: "border-chart-3/40 bg-chart-3/10" },
  { id: "tareas", label: "Tareas", dot: "bg-chart-2", chip: "border-chart-2/40 bg-chart-2/10" },
  { id: "trabajo", label: "Trabajo", dot: "bg-chart-4", chip: "border-chart-4/40 bg-chart-4/10" },
  { id: "gym", label: "Gym", dot: "bg-chart-5", chip: "border-chart-5/40 bg-chart-5/10" },
  { id: "vida", label: "Vida", dot: "bg-muted-foreground", chip: "border-border bg-muted" },
];
const CAPA = Object.fromEntries(CAPAS.map((c) => [c.id, c]));
const VISTAS = [["dia", "Día"], ["semana", "Semana"], ["mes", "Mes"], ["lista", "Lista"]] as const;
const PX_HORA = 48;  // alto de cada hora en la vista de día
const HORA_INICIAL = 7;  // hasta dónde se desplaza al abrir
type Vista = (typeof VISTAS)[number][0];
const KEY = "cc-calendar-prefs";

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const parse = (s: string) => new Date(s + "T12:00:00");
const addDays = (d: Date, n: number) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };
const lunes = (d: Date) => addDays(d, -((d.getDay() + 6) % 7));
const fmt = (s: string, o: Intl.DateTimeFormatOptions) => parse(s).toLocaleDateString("es-ES", o);
const hora = (i: Item) => (i.inicio ? (i.fin ? `${i.inicio}–${i.fin}` : i.inicio) : "");

/** Días que ocupa un elemento dentro del rango visible (los de varios días aparecen en cada uno). */
function porDia(items: Item[], desde: string, hasta: string) {
  const m = new Map<string, Item[]>();
  for (const it of items) {
    let d = it.dia < desde ? desde : it.dia;
    const fin = it.hasta > hasta ? hasta : it.hasta;
    for (let n = 0; d <= fin && n < 62; n++) {
      m.set(d, [...(m.get(d) ?? []), it]);
      d = iso(addDays(parse(d), 1));
    }
  }
  return m;
}

function Chip({ it, onClick, selected }: { it: Item; onClick?: () => void; selected?: boolean }) {
  const c = CAPA[it.capa];
  return (
    <button type="button" onClick={onClick} title={`${c.label}: ${it.titulo}`}
      className={cn("flex w-full min-w-0 items-center gap-1 rounded border px-1 py-0.5 text-left text-[11px] leading-tight", c.chip, it.hecho && "opacity-50 line-through", selected && "ring-1 ring-primary")}>
      {it.inicio && <span className="shrink-0 tabular-nums text-muted-foreground">{it.inicio}</span>}
      <span className="truncate">{it.titulo}</span>
    </button>
  );
}

function Fila({ it, onChanged }: { it: Item; onChanged: () => void }) {
  const c = CAPA[it.capa];
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function alternar() {
    if (!it.clave) return;
    setBusy(true);
    setErr(null);
    try { await post("/me/education/check", { clave: it.clave, hecho: !it.hecho }); onChanged(); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); onChanged(); }
    finally { setBusy(false); }
  }
  return (
    <li className="flex items-start gap-2 py-2 text-sm">
      {it.capa === "tareas" ? (
        <TaskCheck texto={it.titulo} hecho={!!it.hecho} onDone={onChanged} className="mt-0.5" />
      ) : it.capa === "uni" && it.clave ? (
        <button type="button" onClick={alternar} disabled={busy} aria-label={it.hecho ? `Deshacer «${it.titulo}»` : `Marcar «${it.titulo}» como hecho`}
          title={err ?? (it.hecho ? "Deshacer" : "Marcar como hecho")}
          className={cn("relative mt-0.5 inline-flex size-[18px] shrink-0 items-center justify-center rounded-[5px] ring-1 ring-border before:absolute before:-inset-2 before:content-[''] hover:ring-success", err && "ring-destructive")}>
          {it.hecho ? <Undo2 className="size-3" /> : <Check className="size-3 text-success opacity-0 hover:opacity-100" />}
        </button>
      ) : (
        <span className={cn("mt-1.5 size-2 shrink-0 rounded-full", c.dot)} aria-hidden />
      )}
      <div className="min-w-0 flex-1">
        <div className={cn("break-words", it.hecho && "text-muted-foreground line-through")}>{it.titulo}</div>
        {err && <div role="alert" className="text-xs text-destructive">{err}</div>}
        <div className="text-xs text-muted-foreground">
          <span className="font-medium">{c.label}</span>
          {hora(it) && ` · ${hora(it)}`}{!hora(it) && it.capa === "google" && " · todo el día"}
          {it.detalle && ` · ${it.detalle}`}
        </div>
      </div>
      {it.enlace && <Link href={it.enlace} aria-label={`Abrir ${c.label}`} className="-m-1.5 shrink-0 p-1.5 text-muted-foreground hover:text-primary"><ExternalLink className="size-3.5" /></Link>}
    </li>
  );
}

const minutos = (h: string) => { const [a, b] = h.split(":").map(Number); return a * 60 + b; };

/** Coloca los elementos con hora en columnas para que los solapados no se pisen. */
function disponer(items: Item[], dia: string) {
  const bloques = items.filter((i) => i.inicio).map((i) => {
    const ini = i.dia < dia ? 0 : minutos(i.inicio!);
    let fin = i.hasta > dia ? 24 * 60 : i.fin ? minutos(i.fin) : ini + 60;
    if (fin <= ini) fin = Math.min(ini + 60, 24 * 60);
    return { it: i, ini, fin, col: 0, cols: 1 };
  }).sort((a, b) => a.ini - b.ini || a.fin - b.fin);
  let grupo: typeof bloques = [];
  let tope = -1;
  const cerrar = () => { const n = Math.max(0, ...grupo.map((b) => b.col)) + 1; grupo.forEach((b) => { b.cols = n; }); grupo = []; };
  for (const b of bloques) {
    if (grupo.length && b.ini >= tope) cerrar();
    const usadas = new Set(grupo.filter((g) => g.fin > b.ini).map((g) => g.col));
    while (usadas.has(b.col)) b.col++;
    grupo.push(b);
    tope = Math.max(tope, b.fin);
  }
  cerrar();
  return bloques;
}

function VistaDia({ items, dia, hoy, onChanged }: { items: Item[]; dia: string; hoy: string; onChanged: () => void }) {
  const caja = useRef<HTMLDivElement>(null);
  const [ahora, setAhora] = useState(() => new Date());
  useEffect(() => { const t = setInterval(() => setAhora(new Date()), 60_000); return () => clearInterval(t); }, []);
  useEffect(() => { caja.current?.scrollTo({ top: HORA_INICIAL * PX_HORA - 8 }); }, [dia]);
  const bloques = useMemo(() => disponer(items, dia), [items, dia]);
  const sinHora = items.filter((i) => !i.inicio);
  const min = ahora.getHours() * 60 + ahora.getMinutes();
  return (
    <Card>
      <CardContent className="space-y-3 pt-4">
        {sinHora.length > 0 && (
          <section aria-label="Sin hora">
            <h3 className="mb-1 text-xs font-medium tracking-wide text-muted-foreground uppercase">Sin hora</h3>
            <ul className="divide-y divide-border">{sinHora.map((it) => <Fila key={it.id} it={it} onChanged={onChanged} />)}</ul>
          </section>
        )}
        <div ref={caja} className="relative max-h-[34rem] overflow-y-auto rounded-lg border border-border" role="group" aria-label="Horas del día">
          <div className="relative" style={{ height: 24 * PX_HORA }}>
            {Array.from({ length: 24 }, (_, h) => (
              <div key={h} className="absolute inset-x-0 border-t border-border/60" style={{ top: h * PX_HORA }}>
                <span className="absolute -top-2 left-1 bg-card px-0.5 text-[10px] tabular-nums text-muted-foreground">{String(h).padStart(2, "0")}:00</span>
              </div>
            ))}
            <div className="absolute inset-y-0 right-1 left-12">
              {bloques.map(({ it, ini, fin, col, cols }) => {
                const c = CAPA[it.capa];
                return (
                  <div key={it.id} title={`${c.label}: ${it.titulo} ${hora(it)}`}
                    className={cn("absolute overflow-hidden rounded border px-1.5 py-0.5 text-[11px] leading-tight", c.chip, it.hecho && "opacity-50")}
                    style={{ top: (ini / 60) * PX_HORA, height: Math.max(((fin - ini) / 60) * PX_HORA - 2, 18), left: `${(col / cols) * 100}%`, width: `calc(${100 / cols}% - 2px)` }}>
                    <div className={cn("truncate font-medium", it.hecho && "line-through")}>{it.titulo}</div>
                    <div className="truncate text-muted-foreground">{hora(it)}{it.detalle && ` · ${it.detalle}`}</div>
                  </div>
                );
              })}
              {dia === hoy && (
                <div className="pointer-events-none absolute inset-x-0 z-10 border-t-2 border-destructive" style={{ top: (min / 60) * PX_HORA }} aria-label="Hora actual">
                  <span className="absolute -top-1 -left-1 size-2 rounded-full bg-destructive" />
                </div>
              )}
            </div>
          </div>
        </div>
        {bloques.length === 0 && sinHora.length === 0 && <p className="text-center text-sm text-muted-foreground">Nada este día con las capas activas.</p>}
      </CardContent>
    </Card>
  );
}

export function UnifiedCalendar() {
  const hoy = iso(new Date());
  const [vista, setVista] = useState<Vista>("mes");
  const [ancla, setAncla] = useState(hoy);
  const [sel, setSel] = useState(hoy);
  const [capas, setCapas] = useState<string[]>(CAPAS.map((c) => c.id));
  const [canvas, setCanvas] = useState(false);

  useEffect(() => {
    try {
      const p = JSON.parse(localStorage.getItem(KEY) ?? "{}");
      if (Array.isArray(p.capas)) setCapas(p.capas.filter((c: string) => CAPA[c]));
      if (typeof p.canvas === "boolean") setCanvas(p.canvas);
      if (VISTAS.some(([v]) => v === p.vista)) setVista(p.vista);
    } catch { /* sin almacenamiento: valores por defecto */ }
  }, []);
  useEffect(() => {
    try { localStorage.setItem(KEY, JSON.stringify({ capas, canvas, vista })); } catch { /* opcional */ }
  }, [capas, canvas, vista]);

  const { desde, hasta, titulo } = useMemo(() => {
    const a = parse(ancla);
    if (vista === "dia") return { desde: ancla, hasta: ancla, titulo: fmt(ancla, { weekday: "long", day: "numeric", month: "long", year: "numeric" }) };
    if (vista === "semana") {
      const l = lunes(a);
      return { desde: iso(l), hasta: iso(addDays(l, 6)), titulo: `${fmt(iso(l), { day: "numeric", month: "short" })} – ${fmt(iso(addDays(l, 6)), { day: "numeric", month: "short", year: "numeric" })}` };
    }
    const ini = new Date(a.getFullYear(), a.getMonth(), 1, 12);
    const fin = new Date(a.getFullYear(), a.getMonth() + 1, 0, 12);
    return { desde: iso(lunes(ini)), hasta: iso(addDays(lunes(fin), 6)), titulo: fmt(iso(ini), { month: "long", year: "numeric" }) };
  }, [ancla, vista]);

  const q = `/calendar?desde=${desde}&hasta=${hasta}&capas=${capas.join(",")}&canvas=${canvas}`;
  const r = useApi<Resp>(capas.length ? q : null, 300_000);
  const dias = useMemo(() => porDia(r.data?.items ?? [], desde, hasta), [r.data, desde, hasta]);
  const mesActual = parse(ancla).getMonth();

  const mover = (n: number) => {
    const a = parse(ancla);
    const nuevo = vista === "dia" ? addDays(a, n) : vista === "semana" ? addDays(a, 7 * n) : new Date(a.getFullYear(), a.getMonth() + n, 1, 12);
    setAncla(iso(nuevo));
    if (vista === "dia") setSel(iso(nuevo));
  };
  const alternarCapa = (id: string) => setCapas((c) => (c.includes(id) ? c.filter((x) => x !== id) : [...c, id]));
  const diasRango = useMemo(() => {
    const out: string[] = [];
    for (let d = desde; d <= hasta; d = iso(addDays(parse(d), 1))) out.push(d);
    return out;
  }, [desde, hasta]);
  const detalle = dias.get(sel) ?? [];

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1">
          <Button variant="outline" size="icon" onClick={() => mover(-1)} aria-label="Anterior"><ChevronLeft /></Button>
          <Button variant="outline" size="sm" onClick={() => { setAncla(hoy); setSel(hoy); }}>Hoy</Button>
          <Button variant="outline" size="icon" onClick={() => mover(1)} aria-label="Siguiente"><ChevronRight /></Button>
        </div>
        <h2 className="min-w-0 flex-1 text-base font-semibold first-letter:uppercase">{titulo}</h2>
        <div className="flex rounded-lg border border-border p-0.5" role="tablist" aria-label="Vista">
          {VISTAS.map(([v, l]) => (
            <button key={v} type="button" role="tab" aria-selected={vista === v} onClick={() => { if (v === "dia") setAncla(sel); setVista(v); }}
              className={cn("min-h-8 rounded-md px-3 text-sm", vista === v ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground")}>{l}</button>
          ))}
        </div>
        <Button variant="outline" size="icon" onClick={() => r.reload()} aria-label="Actualizar"><RefreshCw /></Button>
      </div>

      <div className="flex flex-wrap items-center gap-1.5" aria-label="Capas">
        {CAPAS.map((c) => {
          const on = capas.includes(c.id);
          return (
            <button key={c.id} type="button" onClick={() => alternarCapa(c.id)} aria-pressed={on}
              className={cn("inline-flex min-h-8 items-center gap-1.5 rounded-full border px-3 text-xs", on ? "border-border bg-card" : "border-dashed text-muted-foreground opacity-60")}>
              <span className={cn("size-2 rounded-full", c.dot)} aria-hidden />{c.label}
            </button>
          );
        })}
        <label className="ml-1 inline-flex min-h-8 items-center gap-1.5 text-xs text-muted-foreground" title="Sus entregas ya salen en Uni; activarlo las duplica">
          <input type="checkbox" checked={canvas} onChange={(e) => setCanvas(e.target.checked)} /> Incluir calendario de Canvas
        </label>
      </div>

      {r.error && <ErrorState message={r.error} />}
      {Object.entries(r.data?.errores ?? {}).map(([k, m]) => <ErrorState key={k} message={`${CAPA[k]?.label ?? k}: ${m}`} />)}
      {!capas.length && <p className="text-sm text-muted-foreground">Activa al menos una capa.</p>}
      {!r.data && !r.error && capas.length > 0 && <Loading rows={8} />}

      {r.data && (
        <div className={cn("grid gap-3", vista !== "dia" && "lg:grid-cols-[1fr_20rem]")}>
          <div>
            {vista === "dia" && <VistaDia items={dias.get(ancla) ?? []} dia={ancla} hoy={hoy} onChanged={r.reload} />}
            {vista === "mes" && (
              <div className="hidden md:block">
                <div className="grid grid-cols-7 gap-px overflow-hidden rounded-lg border border-border bg-border text-xs">
                  {["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"].map((n) => <div key={n} className="bg-muted px-2 py-1 font-medium text-muted-foreground">{n}</div>)}
                  {diasRango.map((d) => {
                    const its = dias.get(d) ?? [];
                    return (
                      <div key={d} onClick={() => setSel(d)}
                        className={cn("min-h-24 min-w-0 cursor-pointer space-y-0.5 bg-card p-1", parse(d).getMonth() !== mesActual && "bg-muted/40 text-muted-foreground", d === sel && "ring-2 ring-inset ring-primary")}>
                        <div className={cn("px-1 text-[11px]", d === hoy && "font-bold text-primary")}>{parse(d).getDate()}</div>
                        {its.slice(0, 3).map((it) => <Chip key={it.id} it={it} onClick={() => setSel(d)} />)}
                        {its.length > 3 && <div className="px-1 text-[11px] text-muted-foreground">+{its.length - 3} más</div>}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
            {vista === "semana" && (
              <div className="hidden gap-2 md:grid md:grid-cols-7">
                {diasRango.map((d) => (
                  <div key={d} onClick={() => setSel(d)} className={cn("min-w-0 cursor-pointer space-y-1 rounded-lg border border-border bg-card p-2", d === sel && "ring-2 ring-primary")}>
                    <div className={cn("text-xs font-medium first-letter:uppercase", d === hoy && "text-primary")}>{fmt(d, { weekday: "short", day: "numeric" })}</div>
                    {(dias.get(d) ?? []).map((it) => <Chip key={it.id} it={it} onClick={() => setSel(d)} />)}
                  </div>
                ))}
              </div>
            )}
            {/* Lista: vista elegida, o la del móvil cuando la rejilla no cabe */}
            <div className={cn(vista === "dia" && "hidden", vista !== "lista" && "md:hidden")}>
              <Card>
                <CardContent className="space-y-4 pt-4">
                  {[...dias.entries()].sort(([a], [b]) => a.localeCompare(b)).filter(([d]) => vista === "semana" || parse(d).getMonth() === mesActual).map(([d, its]) => (
                    <section key={d}>
                      <h3 className={cn("mb-1 text-xs font-medium tracking-wide uppercase", d === hoy ? "text-primary" : "text-muted-foreground")}>{d === hoy ? "Hoy · " : ""}{fmt(d, { weekday: "long", day: "numeric", month: "short" })}</h3>
                      <ul className="divide-y divide-border">{its.map((it) => <Fila key={it.id} it={it} onChanged={r.reload} />)}</ul>
                    </section>
                  ))}
                  {dias.size === 0 && <p className="py-6 text-center text-sm text-muted-foreground">Nada en este periodo con las capas activas.</p>}
                </CardContent>
              </Card>
            </div>
          </div>

          <Card className={cn("hidden h-fit md:block", vista === "dia" && "md:hidden")}>
            <CardContent className="pt-4">
              <div className="mb-1 flex items-center justify-between gap-2">
                <h3 className="text-sm font-medium first-letter:uppercase">{sel === hoy ? "Hoy · " : ""}{fmt(sel, { weekday: "long", day: "numeric", month: "long" })}</h3>
                <Button variant="outline" size="sm" onClick={() => { setAncla(sel); setVista("dia"); }}>Ver por horas</Button>
              </div>
              {detalle.length === 0 ? <p className="py-4 text-sm text-muted-foreground">Nada este día.</p> : (
                <ul className="divide-y divide-border">{detalle.map((it) => <Fila key={it.id} it={it} onChanged={r.reload} />)}</ul>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
