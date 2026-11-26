"use client";

import { useEffect, useState } from "react";
import { Check, Copy, ExternalLink } from "lucide-react";
import { useAct, Field, TextField, selectClass } from "@/components/cc/form";
import { Loading } from "@/components/cc/states";
import { Button } from "@/components/ui/button";
import { post } from "@/lib/api";
import { useApi } from "@/lib/hooks";

export type BancoEstado = {
  app_id: string; clave: boolean; aspsp: { name: string; country: string } | null; banco: string | null;
  conectado: boolean; esperando: boolean; dias: number | null; valido_hasta: string | null;
  cuentas: { nombre: string; iban: string; ledger: string }[]; otras_divisas: string[];
  ultima: { fecha: string; hora: string; nuevos: number; por_revisar: number; saldo: string | null } | null;
  error: { fecha: string; hora: string; mensaje: string } | null;
  alias: number; paises: string[];
};
type App = { nombre: string | null; entorno: string; activa: boolean; redirect_urls: string[]; problemas: string[] };
type Aspsp = { name: string; country: string; dias: number | null };

const PANEL_EB = "https://enablebanking.com/cp/applications";
const DESCRIPCION = "Personal, non-commercial use: daily read-only sync of my own bank account balances and transactions into my self-hosted personal finance dashboard.";
const fecha = (iso: string) => new Date(iso.length === 10 ? `${iso}T12:00:00` : iso).toLocaleDateString("es-ES", { day: "numeric", month: "short", year: "numeric" });

/** Dirección a la que vuelve el banco: tiene que estar en «Allowed redirect URLs» de la aplicación de Enable Banking. */
export const vuelta = () => `${window.location.origin}/finanzas/banco`;

function Copiar({ texto }: { texto: string }) {
  const [ok, setOk] = useState(false);
  const copiar = async () => {
    try { await navigator.clipboard.writeText(texto); setOk(true); setTimeout(() => setOk(false), 1500); } catch { /* sin https no hay portapapeles: se selecciona a mano */ }
  };
  return (
    <div className="flex items-center gap-1 rounded-md border border-border bg-muted/40 px-2 py-1">
      <code className="min-w-0 flex-1 truncate text-xs select-all" title={texto}>{texto}</code>
      <button type="button" onClick={() => void copiar()} aria-label="Copiar" className="shrink-0 text-muted-foreground hover:text-foreground">{ok ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}</button>
    </div>
  );
}

export function Paso({ n, titulo, hecho, children }: { n: number; titulo: string; hecho?: boolean; children: React.ReactNode }) {
  return (
    <li className="grid grid-cols-[1.5rem_1fr] gap-x-2 gap-y-2">
      <span className={`grid size-6 place-items-center rounded-full text-xs font-medium ${hecho ? "bg-primary text-primary-foreground" : "border border-border text-muted-foreground"}`}>{hecho ? <Check className="size-3.5" /> : n}</span>
      <div className="min-w-0 space-y-2"><p className="pt-0.5 font-medium">{titulo}</p>{children}</div>
    </li>
  );
}

/** Paso 1: lo que hay que escribir en el formulario de Enable Banking, ya con la dirección de este panel. */
function CrearApp() {
  const origen = window.location.origin;  // solo se pinta en el navegador, cuando ya ha cargado el estado
  const http = origen.startsWith("http://");
  const filas: [string, string][] = [
    ["Application name", "Personal OS"],
    ["Allowed redirect URLs", `${origen}/finanzas/banco`],
    ["Application description", DESCRIPCION],
    ["Privacy URL", `${origen}/privacidad`],
    ["Terms URL", `${origen}/condiciones`],
  ];
  return (
    <div className="space-y-2 text-muted-foreground">
      <p>
        Crea una cuenta en <a href={PANEL_EB} target="_blank" rel="noreferrer" className="text-primary hover:underline">Enable Banking <ExternalLink className="inline size-3" /></a>{" "}
        (gratis para leer tus propias cuentas) y registra una aplicación nueva de tipo <strong className="text-foreground">Production</strong>, no Sandbox. Rellénala así:
      </p>
      <dl className="grid gap-1.5 sm:grid-cols-[11rem_1fr] sm:items-center">
        {filas.map(([k, v]) => <div key={k} className="contents"><dt className="text-xs">{k}</dt><dd className="min-w-0"><Copiar texto={v} /></dd></div>)}
        <dt className="text-xs">Email for data protection</dt><dd className="text-xs">Tu propio correo.</dd>
      </dl>
      {http && <p className="text-xs text-warning">Tu panel no va por https. Si Enable Banking no acepta esa dirección, pon <code>https://localhost{origen.replace(/^http:\/\/[^:/]+/, "")}/finanzas/banco</code>: al volver del banco la página no cargará, y bastará con pegar aquí la dirección.</p>}
      <p className="text-xs">En la clave, elige que la genere el navegador: se descargará un archivo <code>.pem</code> con el nombre del Application ID. Guárdalo: lo subes en el paso 2.</p>
    </div>
  );
}

/** Paso 2: Application ID y clave privada (la guarda el Host Agent en secrets/, nunca vuelve al navegador). */
function SubirClave({ estado, onDone }: { estado: BancoEstado; onDone: () => void }) {
  const [appId, setAppId] = useState(estado.app_id);
  const [pem, setPem] = useState<{ nombre: string; texto: string } | null>(null);
  const a = useAct(onDone);
  const leer = (f: File | undefined) => {
    if (!f) return;
    void f.text().then((texto) => {
      setPem({ nombre: f.name, texto });
      const id = f.name.replace(/\.pem$/i, "").toLowerCase();
      if (!appId && /^[0-9a-f-]{36}$/.test(id)) setAppId(id);  // el navegador lo nombra con el Application ID
    });
  };
  return (
    <form className="grid gap-2 sm:max-w-md" onSubmit={(e) => { e.preventDefault(); void a.run(() => post("/finance/banco/app", { app_id: appId.trim().toLowerCase(), pem: pem?.texto ?? null })).then(() => setPem(null)); }}>
      <Field label="Clave privada (.pem)">
        <span className="flex items-center gap-2">
          <span className="cursor-pointer rounded-md border border-border bg-background px-2 py-1 text-xs text-foreground hover:bg-muted">
            Elegir archivo
            <input type="file" accept=".pem,application/x-pem-file" onChange={(e) => leer(e.target.files?.[0])} className="sr-only" />
          </span>
          <span className="truncate text-xs">{pem ? pem.nombre : "Ningún archivo elegido"}</span>
        </span>
      </Field>
      <TextField label="Application ID" value={appId} onChange={setAppId} placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" />
      {estado.clave && !pem && <p className="text-xs text-muted-foreground">Ya hay una clave guardada para esta aplicación. Sube otra solo si la cambias.</p>}
      {a.ErrorBox}
      <Button type="submit" size="sm" variant="outline" disabled={a.busy || !/^[0-9a-f-]{36}$/i.test(appId.trim()) || (!pem && !estado.clave)}>Guardar</Button>
    </form>
  );
}

/** Paso 3: lo que dice Enable Banking de la aplicación (entorno, activa, direcciones de vuelta). */
function Comprobar({ onApp }: { onApp: (a: App | null) => void }) {
  const r = useApi<App>("/finance/banco/aplicacion");
  const origen = typeof window === "undefined" ? "" : vuelta();
  useEffect(() => { onApp(r.data ?? null); }, [r.data, onApp]);
  if (r.loading) return <Loading rows={1} />;
  if (r.error) return <p role="alert" className="text-destructive">{r.error}</p>;
  if (!r.data) return null;
  const problemas = [...r.data.problemas];
  if (r.data.redirect_urls.length && !r.data.redirect_urls.includes(origen)) {
    problemas.push(`La dirección de este panel (${origen}) no está entre las «Allowed redirect URLs»: al volver del banco tendrás que pegar la dirección aquí.`);
  }
  return (
    <div className="space-y-1">
      {problemas.length === 0 ? <p className="text-muted-foreground">Todo en orden: «{r.data.nombre}», Production y activa.</p>
        : <ul className="list-disc space-y-1 pl-4 text-warning">{problemas.map((p) => <li key={p}>{p}</li>)}</ul>}
      <Button size="sm" variant="ghost" onClick={() => r.reload()}>Volver a comprobar</Button>
    </div>
  );
}

/** Paso 4: país y banco, de la lista de Enable Banking. */
function ElegirBanco({ estado, onDone }: { estado: BancoEstado; onDone: () => void }) {
  const [pais, setPais] = useState(estado.aspsp?.country ?? "ES");
  const lista = useApi<Aspsp[]>(`/finance/banco/bancos?pais=${pais}`);
  const [nombre, setNombre] = useState(estado.aspsp?.name ?? "");
  const a = useAct(onDone);
  return (
    <div className="grid gap-2 sm:max-w-md">
      <div className="grid grid-cols-[6rem_1fr] gap-2">
        <Field label="País"><select className={selectClass} value={pais} onChange={(e) => { setPais(e.target.value); setNombre(""); }}>{estado.paises.map((p) => <option key={p} value={p}>{p}</option>)}</select></Field>
        <Field label="Banco">
          <select className={selectClass} value={nombre} onChange={(e) => setNombre(e.target.value)} disabled={!lista.data}>
            <option value="">{lista.loading ? "Cargando…" : "Elige tu banco"}</option>
            {lista.data?.map((b) => <option key={b.name} value={b.name}>{b.name}</option>)}
          </select>
        </Field>
      </div>
      {lista.error && <p role="alert" className="text-destructive">{lista.error}</p>}
      {estado.conectado && nombre && nombre !== estado.banco && <p className="text-xs text-warning">Al cambiar de banco se olvida la conexión con {estado.banco}; lo ya apuntado se queda.</p>}
      {a.ErrorBox}
      <Button size="sm" variant="outline" disabled={!nombre || a.busy || (nombre === estado.aspsp?.name && pais === estado.aspsp?.country)} onClick={() => void a.run(() => post("/finance/banco/banco", { nombre, pais }))}>Elegir</Button>
    </div>
  );
}

/** Si la vuelta del banco no carga (dirección no registrada o sin https), se pega aquí. */
function PegarVuelta({ onDone }: { onDone: () => void }) {
  const [url, setUrl] = useState("");
  const a = useAct(onDone);
  return (
    <form className="grid gap-2" onSubmit={(e) => { e.preventDefault(); void a.run(async () => { await post("/finance/banco/vuelta", { url: url.trim() }); await post("/finance/banco/sincronizar"); }).then(() => setUrl("")); }}>
      <TextField label="Dirección a la que te devolvió el banco (lleva code=…)" value={url} onChange={setUrl} placeholder="https://…/finanzas/banco?state=…&code=…" />
      {a.ErrorBox}
      <Button type="submit" size="sm" disabled={!url.includes("code=") || a.busy}>{a.busy ? "Conectando…" : "Terminar la conexión"}</Button>
    </form>
  );
}

export function Banco({ onDone }: { onDone: () => void }) {
  const e = useApi<BancoEstado>("/finance/banco");
  const [app, setApp] = useState<App | null>(null);
  const [pegar, setPegar] = useState(false);
  const a = useAct(() => { e.reload(); onDone(); });
  if (e.loading || !e.data) return <Loading rows={3} />;
  const d = e.data;
  const reload = () => { e.reload(); onDone(); };
  const caduca = d.dias !== null && d.dias <= 7;
  const listoApp = !!d.app_id && d.clave;
  const conectar = () => a.run(async () => {
    const r = await post<{ url: string; pegar: boolean }>("/finance/banco/conectar", { redirect_url: vuelta() });
    if (r.pegar) { setPegar(true); window.open(r.url, "_blank", "noopener"); } else window.location.href = r.url;
  });

  if (d.conectado && listoApp) {
    return (
      <div className="space-y-3 text-sm">
        <p>
          <span className="font-medium">{d.banco}</span> conectado. Se descargan los movimientos cada día a las 3:00.
          {d.dias !== null && <span className={caduca ? " text-warning" : " text-muted-foreground"}> {d.dias < 0 ? "El permiso ha caducado." : `Permiso válido ${d.dias} días más (hasta el ${fecha(d.valido_hasta!)}).`}</span>}
        </p>
        {d.cuentas.length > 0 && <p className="text-muted-foreground">Cuentas: {d.cuentas.map((c) => `${c.nombre || "cuenta"}${c.iban ? ` ···${c.iban}` : ""} → ${c.ledger.split(":").slice(1).join(" · ")}`).join("; ")}.</p>}
        {d.otras_divisas.length > 0 && <p className="text-xs text-muted-foreground">Las cuentas en {d.otras_divisas.join(", ")} no se descargan: súbelas con su extracto.</p>}
        {d.ultima && <p className="text-muted-foreground">Última descarga: {fecha(d.ultima.fecha)} a las {d.ultima.hora} · {d.ultima.nuevos} nuevos{d.ultima.por_revisar ? `, ${d.ultima.por_revisar} por revisar` : ""}</p>}
        {d.error && <p role="alert" className="text-destructive">Falló el {fecha(d.error.fecha)} a las {d.error.hora}: {d.error.mensaje}</p>}
        {a.ErrorBox}
        {(pegar || d.esperando) && <PegarVuelta onDone={reload} />}
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant={caduca ? "default" : "outline"} disabled={a.busy} onClick={() => void conectar()}>Reconectar</Button>
          <Button size="sm" variant="outline" disabled={a.busy} onClick={() => void a.run(() => post("/finance/banco/sincronizar"))}>{a.busy ? "Descargando…" : "Descargar ahora"}</Button>
        </div>
        <details className="text-muted-foreground">
          <summary className="cursor-pointer text-xs">Cambiar de banco o de aplicación</summary>
          <ol className="mt-3 space-y-4">
            <Paso n={1} titulo="Aplicación y clave" hecho={listoApp}><SubirClave estado={d} onDone={reload} /></Paso>
            <Paso n={2} titulo="Banco" hecho={!!d.aspsp}><ElegirBanco estado={d} onDone={reload} /></Paso>
          </ol>
        </details>
      </div>
    );
  }

  return (
    <div className="space-y-3 text-sm">
      <p className="text-muted-foreground">Conecta tu banco para que los movimientos lleguen solos cada noche. Es de solo lectura: el panel nunca puede mover dinero. Lo hace Enable Banking (open banking europeo), que es gratis para tus propias cuentas.</p>
      <ol className="space-y-5">
        <Paso n={1} titulo="Crea la aplicación en Enable Banking" hecho={listoApp}><CrearApp /></Paso>
        <Paso n={2} titulo="Sube la clave y el Application ID" hecho={listoApp}><SubirClave estado={d} onDone={reload} /></Paso>
        <Paso n={3} titulo="Comprueba la aplicación" hecho={!!app && app.problemas.length === 0 && app.redirect_urls.includes(vuelta())}>
          {listoApp ? <Comprobar onApp={setApp} /> : <p className="text-muted-foreground">Primero el paso 2.</p>}
          <p className="text-xs text-muted-foreground">Para activarla, en su panel pulsa «Activate by linking accounts» y da permiso con tu banco.</p>
        </Paso>
        <Paso n={4} titulo="Elige tu banco" hecho={!!d.aspsp}>{listoApp ? <ElegirBanco estado={d} onDone={reload} /> : <p className="text-muted-foreground">Primero el paso 2.</p>}</Paso>
        <Paso n={5} titulo="Conecta" hecho={d.conectado}>
          <p className="text-muted-foreground">Irás a {d.banco ?? "tu banco"} para dar permiso de lectura (dura hasta 180 días; el panel te avisa antes de que caduque).</p>
          {a.ErrorBox}
          <Button size="sm" disabled={!listoApp || !d.aspsp || a.busy} onClick={() => void conectar()}>Conectar</Button>
          {(pegar || d.esperando) && <PegarVuelta onDone={reload} />}
        </Paso>
      </ol>
    </div>
  );
}
