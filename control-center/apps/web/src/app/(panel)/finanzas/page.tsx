"use client";

import { useEffect, useState } from "react";
import { Sparkles } from "lucide-react";
import { HBars } from "@/components/cc/charts";
import { Markdown } from "@/components/cc/markdown";
import { useAct, Field, TextField, selectClass } from "@/components/cc/form";
import { PageHeader, usePanel } from "@/components/cc/shell";
import { Empty, ErrorState, Loading } from "@/components/cc/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { post, upload } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import { useApi } from "@/lib/hooks";

type Account = { id: number; name: string; kind: string; balance: string; currency: string };
type Summary = {
  resumen: { ingresos: string; gastos: string; ahorro: string; por_categoria: Record<string, string> };
  patrimonio: { activos: string; pasivos: string; patrimonio: string };
  presupuesto: { cuenta: string; presupuesto: string; gastado: string; excedido: boolean }[];
  conciliacion: { id: number; cuenta: string; fecha: string; banco: string; ledger: string; diferencia: string; cuadra: boolean }[];
  conciliadas: { name: string; balance: string }[];
  por_revisar: number; hay_datos: boolean;
};
type Entry = { id: number; fecha: string; descripcion: string; estado: string; lineas: { cuenta: string; importe: string }[] };
type Preview = { filas: number; nuevos: number; duplicados: number; errores: string[]; muestra: { fecha: string; descripcion: string; importe: string }[] };

const eur = (v: string) => `${Number(v).toLocaleString("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`;
const short = (n: string) => n.split(":").slice(1).join(" · ") || n;
const KIND: Record<string, string> = { asset: "Activos", liability: "Pasivos", equity: "Patrimonio", income: "Ingresos", expense: "Gastos" };

function Stat({ label, value }: { label: string; value: string }) {
  return <Card><CardContent><div className="text-xs text-muted-foreground">{label}</div><div className="mt-1 text-xl font-semibold tabular-nums">{value}</div></CardContent></Card>;
}

function Importar({ cuentas, onDone }: { cuentas: Account[]; onDone: () => void }) {
  const bancos = cuentas.filter((c) => c.kind === "asset" || c.kind === "liability");
  const [cuenta, setCuenta] = useState("");
  const [contenido, setContenido] = useState("");
  const [nombre, setNombre] = useState("");
  const [fecha, setFecha] = useState("Fecha");
  const [descripcion, setDescripcion] = useState("Concepto");
  const [importe, setImporte] = useState("Importe");
  const [separador, setSeparador] = useState(";");
  const [coma, setComa] = useState(true);
  const [prev, setPrev] = useState<Preview | null>(null);
  const a = useAct();
  const body = () => ({ cuenta: cuenta || bancos[0]?.name, contenido, filename: nombre, mapa: { fecha, descripcion, importe, separador, coma_decimal: coma } });
  const esRevolut = contenido.replace(/^\uFEFF/, "").startsWith("Type,Product,Started Date");
  const ruta = esRevolut ? "/finance/import/revolut" : "/finance/import";
  const cuerpo = () => (esRevolut ? { contenido, filename: nombre } : body());
  return (
    <div className="grid gap-2">
      {a.ErrorBox}
      {contenido && !esRevolut && <Field label="Cuenta"><select className={selectClass} value={cuenta} onChange={(e) => setCuenta(e.target.value)}>{bancos.map((c) => <option key={c.id} value={c.name}>{short(c.name)}</option>)}</select></Field>}
      <Field label="Archivo CSV del banco">
        <input type="file" accept=".csv,text/csv" className="text-sm" onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) {
            setNombre(f.name);
            void f.text().then(setContenido);
            setPrev(null);
          }
        }} />
      </Field>
      {esRevolut && <p className="text-xs text-muted-foreground">Extracto de Revolut: se clasifica solo y separa los gastos de los movimientos entre tus cuentas.</p>}
      {contenido && !esRevolut && <><div className="grid grid-cols-3 gap-2">
        <TextField label="Columna fecha" value={fecha} onChange={setFecha} />
        <TextField label="Columna concepto" value={descripcion} onChange={setDescripcion} />
        <TextField label="Columna importe" value={importe} onChange={setImporte} />
      </div>
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <Field label="Separador"><select className={selectClass} value={separador} onChange={(e) => setSeparador(e.target.value)}><option value=";">;</option><option value=",">,</option><option value="&#9;">Tabulador</option></select></Field>
        <label className="flex items-center gap-2"><input type="checkbox" checked={coma} onChange={(e) => setComa(e.target.checked)} />Decimales con coma</label>
      </div></>}
      <Button variant="outline" disabled={!contenido || (!esRevolut && !bancos.length) || a.busy} onClick={() => void a.run(async () => setPrev(await post<Preview>(`${ruta}/preview`, cuerpo())))}>Vista previa</Button>
      {prev && (
        <div className="space-y-2 rounded-lg bg-muted p-3 text-sm">
          <p>{prev.filas} movimientos: {prev.nuevos} nuevos, {prev.duplicados} ya estaban.</p>
          {prev.errores.map((x) => <p key={x} className="text-xs text-destructive">{x}</p>)}
          <ul className="text-xs text-muted-foreground">{prev.muestra.slice(0, 5).map((m, i) => <li key={i} className="truncate">{m.fecha} · {m.descripcion} · {m.importe}</li>)}</ul>
          <Button size="sm" disabled={prev.errores.length > 0 || prev.nuevos === 0 || a.busy} onClick={() => void a.run(async () => { await post(ruta, cuerpo()); setPrev(null); setContenido(""); onDone(); })}>Importar {prev.nuevos}</Button>
        </div>
      )}
    </div>
  );
}

type PlanRow = { cuenta: string; media: string; presupuesto: string | null; gastado: string | null };

function Presupuesto({ onDone }: { onDone: () => void }) {
  const plan = useApi<PlanRow[]>("/finance/budgets/plan");
  const [valores, setValores] = useState<Record<string, string>>({});
  const refrescar = () => { setValores({}); plan.reload(); onDone(); };
  const a = useAct(refrescar);
  const filas = plan.data ?? [];
  const valor = (f: PlanRow) => valores[f.cuenta] ?? (f.presupuesto ? String(Number(f.presupuesto)) : "");
  const cambiadas = filas.filter((f) => valores[f.cuenta] !== undefined && valores[f.cuenta].trim() !== (f.presupuesto ? String(Number(f.presupuesto)) : ""));
  const mes = new Date().toLocaleDateString("sv-SE").slice(0, 7);
  const rellenar = () => setValores(Object.fromEntries(filas.filter((f) => !f.presupuesto).map((f) => [f.cuenta, String(Math.ceil(Number(f.media)))])));
  const guardar = () => a.run(async () => {
    for (const f of cambiadas) await post("/finance/budgets", { cuenta: f.cuenta, mes, importe: (valores[f.cuenta].trim() || "0").replace(",", ".") });
  });
  return (
    <div className="space-y-3">
      {a.ErrorBox}
      <p className="text-xs text-muted-foreground">Cada límite sigue vigente los meses siguientes hasta que lo cambies. Déjalo vacío para quitarlo.</p>
      {plan.loading && <Loading rows={6} />}
      {plan.data && filas.length === 0 && <Empty message="Aún no hay gastos con los que calcular." />}
      {filas.length > 0 && (
        <table className="w-full text-sm">
          <thead><tr className="text-right text-xs text-muted-foreground"><th className="py-1 text-left font-normal">Categoría</th><th className="font-normal">Media 3 meses</th><th className="w-36 pl-4 font-normal">Límite al mes</th></tr></thead>
          <tbody>
            {filas.map((f) => (
              <tr key={f.cuenta} className="border-t border-border text-right tabular-nums">
                <td className="py-1.5 text-left">{short(f.cuenta)}</td>
                <td>{eur(f.media)}</td>
                <td className="py-1 pl-4"><input aria-label={`Límite de ${short(f.cuenta)}`} inputMode="decimal" value={valor(f)} onChange={(e) => setValores((v) => ({ ...v, [f.cuenta]: e.target.value }))} className="h-8 w-full rounded-lg border border-input bg-transparent px-2 text-right text-sm" /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {filas.length > 0 && (
        <div className="flex flex-wrap justify-end gap-2">
          <Button type="button" size="sm" variant="ghost" onClick={rellenar}>Rellenar vacíos con la media</Button>
          <Button type="button" size="sm" disabled={a.busy || !cambiadas.length} onClick={() => void guardar()}>Guardar{cambiadas.length ? ` (${cambiadas.length})` : ""}</Button>
        </div>
      )}
    </div>
  );
}

type Savings = { cuentas: { cuenta: string; saldo: string; valorada: string | null; dudosa: boolean }[]; patrimonio: string | null };

function Ahorro({ onDone }: { onDone: () => void }) {
  const s = useApi<Savings>("/finance/savings");
  const [nueva, setNueva] = useState("");
  const [valores, setValores] = useState<Record<string, string>>({});
  const a = useAct(() => { s.reload(); onDone(); });
  const guardar = (cuenta: string) => a.run(async () => {
    await post("/finance/value", { cuenta, valor: (valores[cuenta] ?? "").replace(",", ".") });
    setValores((v) => ({ ...v, [cuenta]: "" }));
  });
  return (
    <div className="grid gap-3">
      {a.ErrorBox}
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-xs text-muted-foreground">Pon lo que tienes de verdad en cada sitio. El patrimonio aparece cuando todas las cuentas tienen su valor.</p>
        {s.data?.patrimonio != null && <p className="text-sm">Patrimonio <b className="text-base tabular-nums">{eur(s.data.patrimonio)}</b></p>}
      </div>
      <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {s.data?.cuentas.filter((c) => c.cuenta !== "asset:banco" || Number(c.saldo) !== 0).map((c) => (
          <li key={c.cuenta} className="rounded-lg border border-border p-3 text-sm">
            <div className="flex justify-between gap-2"><span className="truncate">{short(c.cuenta)}</span><b className="tabular-nums">{eur(c.saldo)}</b></div>
            <p className={`mt-0.5 text-xs ${c.dudosa ? "text-warning" : "text-muted-foreground"}`}>{c.dudosa ? "Sin valor real todavía" : c.valorada ? `Valor del ${c.valorada}` : "Sin movimientos"}</p>
            <form className="mt-2 flex gap-2" onSubmit={(e) => { e.preventDefault(); void guardar(c.cuenta); }}>
              <input aria-label={`Valor actual de ${short(c.cuenta)}`} inputMode="decimal" placeholder="Valor hoy (€)" value={valores[c.cuenta] ?? ""} onChange={(e) => setValores((v) => ({ ...v, [c.cuenta]: e.target.value }))} className="h-8 min-w-0 flex-1 rounded-lg border border-input bg-transparent px-2 text-sm" />
              <Button type="submit" size="sm" variant="outline" disabled={!valores[c.cuenta]?.trim() || a.busy}>Guardar</Button>
            </form>
          </li>
        ))}
      </ul>
      <form className="flex max-w-md gap-2" onSubmit={(e) => { e.preventDefault(); void a.run(() => post("/finance/accounts", { name: `asset:${nueva.trim().toLowerCase()}`, kind: "asset" })).then(() => setNueva("")); }}>
        <TextField label="Nueva cuenta de ahorro" value={nueva} onChange={setNueva} placeholder="fondo, broker, efectivo…" maxLength={100} />
        <Button type="submit" size="sm" variant="outline" className="self-end" disabled={!nueva.trim()}>Crear</Button>
      </form>
    </div>
  );
}

function Ticket() {
  const [hecho, setHecho] = useState(false);
  const a = useAct();
  return (
    <div className="grid gap-2 text-sm">
      {a.ErrorBox}
      <p className="text-xs text-muted-foreground">El agente de finanzas lo lee y te propone el asiento. No se apunta nada sin tu aprobación.</p>
      <input type="file" accept="image/*,.pdf" aria-label="Foto del ticket" className="text-sm" onChange={(e) => {
        const f = e.target.files?.[0];
        if (f) {
          setHecho(false);
          void a.run(async () => { await upload(`/finance/ticket?name=${encodeURIComponent(f.name)}`, f); setHecho(true); });
        }
      }} />
      {hecho && <p role="status" className="text-xs text-success">Enviado. Te avisaré cuando esté la propuesta.</p>}
    </div>
  );
}

function Revisar({ entries, cuentas, onDone }: { entries: Entry[]; cuentas: Account[]; onDone: () => void }) {
  const a = useAct(onDone);
  const destinos = cuentas.filter((c) => (c.kind === "expense" || c.kind === "income" || c.name === "asset:otras-cuentas-propias") && !c.name.endsWith("sin-categorizar"));
  const [recordar, setRecordar] = useState(true);
  return (
    <div>
      {a.ErrorBox}
      <label className="mb-1 flex min-h-8 items-center gap-2 text-xs"><input type="checkbox" checked={recordar} onChange={(e) => setRecordar(e.target.checked)} />Recordar para este comercio</label>
      <ul className="divide-y divide-border">
        {entries.map((e) => {
          const banco = e.lineas.find((l) => !l.cuenta.includes("sin-categorizar"));
          return (
            <li key={e.id} className="flex flex-wrap items-center gap-2 py-2 text-sm">
              <span className="min-w-0 flex-1 truncate" title={e.descripcion}>{e.fecha.slice(5)} · {e.descripcion}</span>
              <span className="tabular-nums">{banco ? eur(banco.importe) : ""}</span>
              <select aria-label={`Categoría de ${e.descripcion}`} className={selectClass} defaultValue="" onChange={(ev) => void a.run(() => post(`/finance/entries/${e.id}/categorize`, { cuenta: ev.target.value, recordar }))}>
                <option value="" disabled>Categoría…</option>
                {destinos.map((c) => <option key={c.id} value={c.name}>{short(c.name)}</option>)}
              </select>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

type Overview = { meses: { mes: string; ingresos: string; gastos: string; bizum_recibido: string; bizum_enviado: string }[]; categorias: Record<string, string> };
type Analysis = { texto: string | null; fecha: string | null };

const TABS = [["resumen", "Resumen"], ["movimientos", "Movimientos"], ["presupuesto", "Presupuesto"], ["cuentas", "Cuentas y ahorro"], ["herramientas", "Importar y ajustes"]] as const;
type Tab = (typeof TABS)[number][0];
const MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];

function AnalysisCard() {
  const { lastEvent } = usePanel();
  const an = useApi<Analysis>("/finance/analysis");
  const { reload } = an;
  const [pedido, setPedido] = useState(false);
  const a = useAct();
  useEffect(() => {
    if (lastEvent?.type === "finance.analysis") {
      setPedido(false);
      reload();
    }
  }, [lastEvent, reload]);
  return (
    <Card className="border-primary/20 bg-primary/5">
      <CardHeader className="flex flex-row items-start justify-between gap-3">
        <div>
          <CardTitle className="flex items-center gap-2"><Sparkles className="size-4 text-primary" />Análisis de tus gastos</CardTitle>
          {an.data?.fecha && <p className="mt-1 text-xs text-muted-foreground">Del agente de finanzas · {timeAgo(an.data.fecha)}</p>}
        </div>
        <Button size="sm" variant="outline" disabled={pedido || a.busy} onClick={() => { setPedido(true); void a.run(() => post("/finance/analysis/run")); }}>{pedido ? "Analizando…" : "Actualizar"}</Button>
      </CardHeader>
      <CardContent>
        {a.ErrorBox}
        {an.data?.texto ? <div className="prose-cc max-w-none"><Markdown source={an.data.texto} onWiki={() => {}} imageSrc={(n) => n} /></div> : !an.loading && <Empty message="Pulsa Actualizar para que el agente analice tus gastos." />}
      </CardContent>
    </Card>
  );
}

function Resumen({ data }: { data: Summary }) {
  const o = useApi<Overview>("/finance/overview");
  const cats = Object.entries(o.data?.categorias ?? {}).map(([name, v]) => ({ name, value: Number(v) }));
  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Gastos del año por categoría</CardTitle></CardHeader>
          <CardContent>
            {o.loading && <Loading rows={6} />}
            {o.data && cats.length === 0 && <Empty message="Sin gastos este año." />}
            {cats.length > 0 && <HBars data={cats} unit=" €" label="Gastos del año por categoría" />}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Mes a mes</CardTitle><p className="text-xs text-muted-foreground">Sin Bizum, que va aparte porque gran parte es dinero compartido.</p></CardHeader>
          <CardContent>
            {o.loading && <Loading rows={6} />}
            <table className="w-full text-sm">
              <thead><tr className="text-right text-xs text-muted-foreground"><th className="py-1 text-left font-normal">Mes</th><th className="font-normal">Ingresos</th><th className="font-normal">Gastos</th><th className="font-normal">Bizum neto</th></tr></thead>
              <tbody>
                {o.data?.meses.map((m) => (
                  <tr key={m.mes} className="border-t border-border text-right tabular-nums">
                    <td className="py-1.5 text-left capitalize">{MESES[Number(m.mes.slice(5)) - 1]}</td>
                    <td>{eur(m.ingresos)}</td><td>{eur(m.gastos)}</td><td>{eur(String(Number(m.bizum_recibido) - Number(m.bizum_enviado)))}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      </div>
      {data.presupuesto.length > 0 && (
        <Card>
          <CardHeader><CardTitle>Presupuesto de este mes</CardTitle></CardHeader>
          <CardContent>
            <ul className="grid gap-x-8 gap-y-3 text-sm sm:grid-cols-2">
              {data.presupuesto.map((p) => {
                const pct = Math.min(100, (Number(p.gastado) / Number(p.presupuesto)) * 100);
                return (
                  <li key={p.cuenta}>
                    <div className="flex justify-between gap-2"><span className="truncate">{short(p.cuenta)}</span><span className={`tabular-nums ${p.excedido ? "text-destructive" : "text-muted-foreground"}`}>{eur(p.gastado)} de {eur(p.presupuesto)}</span></div>
                    <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-muted"><div className={`h-full rounded-full ${p.excedido ? "bg-destructive" : "bg-primary"}`} style={{ width: `${pct}%` }} /></div>
                  </li>
                );
              })}
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

export default function FinanzasPage() {
  const s = useApi<Summary>("/finance/summary");
  const accounts = useApi<Account[]>("/finance/accounts");
  const pending = useApi<Entry[]>("/finance/entries?estado=pending");
  const recent = useApi<Entry[]>("/finance/entries?limit=50");
  const [nombre, setNombre] = useState("");
  const [tipo, setTipo] = useState("expense");
  const [tab, setTab] = useState<Tab>("resumen");
  const reload = () => { s.reload(); accounts.reload(); pending.reload(); recent.reload(); };
  const a = useAct(reload);
  const crear = () => {
    const prefijo = `${tipo}:`;
    const name = nombre.trim().toLowerCase();
    return a.run(() => post("/finance/accounts", { name: name.startsWith(prefijo) ? name : prefijo + name, kind: tipo })).then(() => setNombre(""));
  };
  return (
    <>
      <PageHeader title="Finanzas" description="Cada movimiento cuadra con tu banco." actions={<a href="/api/v1/finance/export.beancount" className="-my-1 py-1 text-xs text-primary hover:underline">Exportar</a>} />
      {s.error && <ErrorState message={s.error} />}
      {a.ErrorBox}
      {s.loading && <Loading rows={5} />}
      {s.data && (
        <div className="space-y-4">
          <AnalysisCard />
          {s.data.hay_datos && (
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              {s.data.conciliadas[0] ? <Stat label="Saldo en la cuenta" value={eur(s.data.conciliadas[0].balance)} /> : <Stat label="Saldo" value="—" />}
              <Stat label="Ingresos del mes" value={eur(s.data.resumen.ingresos)} />
              <Stat label="Gastos del mes" value={eur(s.data.resumen.gastos)} />
              <Stat label="Ahorro del mes" value={eur(s.data.resumen.ahorro)} />
            </div>
          )}
          {s.data.conciliacion.some((c) => !c.cuadra) && <ErrorState message={`Hay descuadres con el banco: ${s.data.conciliacion.filter((c) => !c.cuadra).map((c) => `${short(c.cuenta)} el ${c.fecha} (${eur(c.diferencia)})`).join(", ")}`} />}
          <nav aria-label="Secciones de finanzas" className="flex gap-1 overflow-x-auto border-b border-border">
            {TABS.map(([k, l]) => (
              <button key={k} type="button" aria-current={tab === k ? "page" : undefined} onClick={() => setTab(k)} className={`shrink-0 border-b-2 px-3 py-2 text-sm ${tab === k ? "border-primary font-medium" : "border-transparent text-muted-foreground hover:text-foreground"}`}>
                {l}{k === "movimientos" && s.data && s.data.por_revisar > 0 ? ` (${s.data.por_revisar})` : ""}
              </button>
            ))}
          </nav>

          {tab === "resumen" && <Resumen data={s.data} />}

          {tab === "movimientos" && (
            <div className="space-y-4">
              {s.data.por_revisar > 0 && (
                <Card>
                  <CardHeader><CardTitle>Por revisar ({s.data.por_revisar})</CardTitle><p className="text-xs text-muted-foreground">No cuentan en los totales hasta que los categorices.</p></CardHeader>
                  <CardContent><Revisar entries={pending.data ?? []} cuentas={accounts.data ?? []} onDone={reload} /></CardContent>
                </Card>
              )}
              <Card>
                <CardHeader><CardTitle>Últimos movimientos</CardTitle></CardHeader>
                <CardContent>
                  {recent.data?.length === 0 && <Empty message="Sin movimientos todavía." />}
                  <ul className="divide-y divide-border text-sm">
                    {recent.data?.map((e) => {
                      const banco = e.lineas.find((l) => l.cuenta === "asset:revolut" || l.cuenta === "asset:revolut-divisas") ?? e.lineas[0];
                      return (
                        <li key={e.id} className="flex items-center gap-3 py-1.5">
                          <span className="w-12 shrink-0 text-xs text-muted-foreground tabular-nums">{e.fecha.slice(5)}</span>
                          <span className="min-w-0 flex-1 truncate" title={e.descripcion}>{e.descripcion}</span>
                          {e.estado === "pending" && <span className="text-xs text-warning">Por revisar</span>}
                          <span className="tabular-nums">{banco ? eur(banco.importe) : ""}</span>
                          <Button variant="ghost" size="sm" disabled={e.estado !== "posted"} onClick={() => void a.run(() => post(`/finance/entries/${e.id}/reverse`))}>Revertir</Button>
                        </li>
                      );
                    })}
                  </ul>
                </CardContent>
              </Card>
            </div>
          )}

          {tab === "cuentas" && (
            <Card>
              <CardHeader><CardTitle>Cuentas, ahorro e inversión</CardTitle></CardHeader>
              <CardContent><Ahorro onDone={reload} /></CardContent>
            </Card>
          )}

          {tab === "presupuesto" && (
            <Card>
              <CardHeader><CardTitle>Presupuesto mensual</CardTitle></CardHeader>
              <CardContent><Presupuesto onDone={reload} /></CardContent>
            </Card>
          )}

          {tab === "herramientas" && (
            <div className="grid gap-4 lg:grid-cols-3">
              <Card>
                <CardHeader><CardTitle>Importar extracto</CardTitle></CardHeader>
                <CardContent><Importar cuentas={accounts.data ?? []} onDone={reload} /></CardContent>
              </Card>
              <Card>
                <CardHeader><CardTitle>Foto de un ticket</CardTitle></CardHeader>
                <CardContent><Ticket /></CardContent>
              </Card>
              <Card>
                <CardHeader><CardTitle>Nueva categoría</CardTitle></CardHeader>
                <CardContent>
                  <form className="grid gap-2" onSubmit={(e) => { e.preventDefault(); void crear(); }}>
                    <TextField label="Nombre" value={nombre} onChange={setNombre} placeholder="mascotas, regalos…" maxLength={120} />
                    <Field label="Tipo"><select className={selectClass} value={tipo} onChange={(e) => setTipo(e.target.value)}>{Object.entries(KIND).filter(([k]) => k === "expense" || k === "income").map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>
                    <Button type="submit" size="sm" variant="outline" disabled={!nombre.trim()}>Crear</Button>
                  </form>
                </CardContent>
              </Card>
            </div>
          )}
        </div>
      )}
    </>
  );
}
