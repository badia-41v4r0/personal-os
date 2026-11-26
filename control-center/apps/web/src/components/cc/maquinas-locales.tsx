"use client";

import { useEffect, useState } from "react";
import { Camera, Check, Copy, HardDrive, Pencil, Play, Plus, Power, Trash2, X } from "lucide-react";
import { Paso } from "@/components/cc/banco";
import { Field, TextField, selectClass, useAct } from "@/components/cc/form";
import { usePanel } from "@/components/cc/shell";
import { StatusDot } from "@/components/cc/status";
import { ErrorState, Loading } from "@/components/cc/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { api, post } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { BASE } from "@/lib/base";

type Vm = { vbox: string; uuid: string; estado: string; conectada: string | null };
type Maquina = { id: string; nombre: string; vbox: string; usuario: string; puerto: number; agentes: string[]; notas: string; pendiente: boolean; estado: string; comprobado: string | null };
type Agente = { id: string; nombre: string; descripcion: string };
type Estado = { virtualbox: { instalado: boolean; version: string | null }; vms: Vm[]; maquinas: Maquina[]; agentes: Agente[]; error?: string };
type Preparada = { id: string; puerto: number; hecho: string[]; comandos: { base: string; navegador: string } };
type Prueba = { ok: boolean; pasos: { paso: string; ok: boolean; detalle: string }[] };

const ESTADO: Record<string, string> = { running: "encendida", poweroff: "apagada", paused: "en pausa", saved: "guardada", aborted: "apagada (se cerró mal)", "no existe": "ya no existe en VirtualBox" };
const patch = (path: string, body: unknown) => api(path, { method: "PATCH", body: JSON.stringify(body) });

function Comandos({ texto }: { texto: string }) {
  const [ok, setOk] = useState(false);
  const copiar = async () => {
    try { await navigator.clipboard.writeText(texto); setOk(true); setTimeout(() => setOk(false), 1500); } catch { /* sin https: se selecciona a mano */ }
  };
  return (
    <div className="relative rounded-md border border-border bg-muted/40">
      <pre className="max-h-56 overflow-auto p-2 pr-9 text-[11px] leading-relaxed whitespace-pre-wrap break-all select-all"><code>{texto}</code></pre>
      <button type="button" onClick={() => void copiar()} aria-label="Copiar comandos" className="absolute top-1.5 right-1.5 rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground">
        {ok ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
      </button>
    </div>
  );
}

function Agentes({ todos, valor, onChange }: { todos: Agente[]; valor: string[]; onChange: (v: string[]) => void }) {
  if (!todos.length) return <p className="text-xs text-muted-foreground">No hay agentes con la capacidad «ordenador». Actívala en Ajustes → Agentes.</p>;
  return (
    <div className="grid gap-1.5">
      {todos.map((a) => (
        <label key={a.id} className="flex items-start gap-2 rounded-md border border-border p-2 text-sm">
          <input type="checkbox" className="mt-0.5 accent-[var(--primary)]" checked={valor.includes(a.id)}
            onChange={(e) => onChange(e.target.checked ? [...valor, a.id] : valor.filter((x) => x !== a.id))} />
          <span className="min-w-0"><span className="font-medium">{a.nombre}</span><span className="block truncate text-xs text-muted-foreground">{a.descripcion}</span></span>
        </label>
      ))}
    </div>
  );
}

/** Asistente: elegir la VM → comandos para pegar dentro → probar → agentes y notas. */
function Asistente({ estado, continuar, onClose }: { estado: Estado; continuar: Maquina | null; onClose: () => void }) {
  const libres = estado.vms.filter((v) => !v.conectada);
  const [vbox, setVbox] = useState(continuar?.vbox ?? libres[0]?.vbox ?? "");
  const [nombre, setNombre] = useState(continuar?.nombre ?? "");
  const [instantanea, setInstantanea] = useState(true);
  const [prep, setPrep] = useState<Preparada | null>(null);
  const [usuario, setUsuario] = useState(continuar?.usuario ?? "");
  const [prueba, setPrueba] = useState<Prueba | null>(null);
  const [agentes, setAgentes] = useState<string[]>(continuar?.agentes ?? []);
  const [notas, setNotas] = useState(continuar?.notas ?? "");
  const a = useAct();
  const preparar = (vm: string, nom: string, snap: boolean) =>
    a.run(async () => setPrep(await post<Preparada>("/maquinas", { vbox: vm, nombre: nom, instantanea: snap })));
  // al continuar una pendiente, se piden otra vez sus comandos (no repite nada de lo ya hecho)
  useEffect(() => { if (continuar) void preparar(continuar.vbox, continuar.nombre, false); }, []);  // eslint-disable-line react-hooks/exhaustive-deps
  const vmEstado = estado.vms.find((v) => v.vbox === vbox)?.estado;
  return (
    <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
      <DialogHeader>
        <DialogTitle>{continuar ? `Conectar «${continuar.nombre}»` : "Conectar una máquina de VirtualBox"}</DialogTitle>
        <DialogDescription>Los agentes que elijas podrán usarla: comandos, archivos, pantalla y su navegador. Tu contraseña de la máquina no pasa por el panel.</DialogDescription>
      </DialogHeader>
      <ol className="space-y-5 text-sm">
        <Paso n={1} titulo="Elegir la máquina" hecho={!!prep}>
          {!prep ? (
            <div className="grid gap-2 sm:max-w-md">
              {libres.length === 0 && !continuar ? <p className="text-muted-foreground">Todas tus máquinas de VirtualBox ya están conectadas (o no tienes ninguna).</p> : <>
                <Field label="Máquina de VirtualBox">
                  <select className={selectClass} value={vbox} onChange={(e) => setVbox(e.target.value)} disabled={!!continuar}>
                    {(continuar ? estado.vms.filter((v) => v.vbox === continuar.vbox) : libres).map((v) => <option key={v.uuid} value={v.vbox}>{v.vbox} · {ESTADO[v.estado] ?? v.estado}</option>)}
                  </select>
                </Field>
                <TextField label="Nombre para el panel (opcional)" value={nombre} onChange={setNombre} placeholder="p. ej. VerilUOC (Fundamentos de computadores)" maxLength={80} />
                <label className="flex items-center justify-between gap-3 rounded-lg bg-muted/40 p-2 text-xs">
                  <span>Hacer antes una instantánea («{"antes-personal-os"}») para poder volver atrás</span>
                  <Switch checked={instantanea} onCheckedChange={setInstantanea} />
                </label>
                <p className="text-xs text-muted-foreground">
                  Se crea una clave solo para esta máquina y una redirección de puerto que solo se alcanza desde este PC (127.0.0.1).
                  La tarjeta de red 1 de la máquina tiene que estar en «NAT».
                </p>
                <Button size="sm" disabled={a.busy || !vbox} onClick={() => void preparar(vbox, nombre, instantanea)}>{a.busy ? "Preparando…" : "Preparar"}</Button>
              </>}
            </div>
          ) : <p className="text-xs text-muted-foreground">{vbox} · puerto local {prep.puerto}{prep.hecho.length ? ` · hecho ahora: ${prep.hecho.join(", ")}` : ""}</p>}
        </Paso>
        {prep && <Paso n={2} titulo="Pegar estos comandos dentro de la máquina" hecho={!!prueba?.ok}>
          <p className="text-muted-foreground">
            Enciéndela y ábrela en VirtualBox (<strong className="text-foreground">Mostrar</strong>), abre una terminal y pega esto. Te pedirá tu contraseña de la máquina (sudo).
            Instala SSH y <code>xdotool</code> (ratón y teclado), autoriza solo la clave de este panel y desactiva entrar con contraseña. Funciona en Debian y Ubuntu.
          </p>
          <Comandos texto={prep.comandos.base} />
          <details className="text-xs text-muted-foreground">
            <summary className="cursor-pointer">Opcional: que el agente pueda leer webs con la sesión que abras en su Chromium</summary>
            <p className="my-1.5">Hace que el Chromium (o Chrome) de la máquina se abra siempre con su puerto de depuración, que solo existe dentro de la máquina.</p>
            <Comandos texto={prep.comandos.navegador} />
          </details>
          {vmEstado && vmEstado !== "running" && <p className="text-xs text-warning">La máquina está {ESTADO[vmEstado] ?? vmEstado}: enciéndela antes.</p>}
        </Paso>}
        {prep && <Paso n={3} titulo="Probar la conexión" hecho={!!prueba?.ok}>
          <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); void a.run(async () => setPrueba(await post<Prueba>(`/maquinas/${prep.id}/probar`, { usuario: usuario.trim() }))); }}>
            <div className="w-48"><TextField label="Tu usuario en la máquina" value={usuario} onChange={setUsuario} placeholder="el que dijo el último comando" autoComplete="off" /></div>
            <Button type="submit" size="sm" variant="outline" disabled={a.busy || !usuario.trim()}>{a.busy ? "Probando…" : "Probar"}</Button>
          </form>
          {prueba && <ul className="space-y-1 text-xs">
            {prueba.pasos.map((p) => <li key={p.paso} className="flex gap-2">{p.ok ? <Check className="size-3.5 shrink-0 text-primary" /> : <X className="size-3.5 shrink-0 text-destructive" />}<span><span className="text-foreground">{p.paso}</span>{p.detalle && <span className="text-muted-foreground"> · {p.detalle}</span>}</span></li>)}
          </ul>}
        </Paso>}
        {prueba?.ok && prep && <Paso n={4} titulo="Qué agentes la usan">
          <Agentes todos={estado.agentes} valor={agentes} onChange={setAgentes} />
          <Field label="Notas para el agente (qué hay instalado, cómo abrir sus programas…)">
            <Textarea value={notas} onChange={(e) => setNotas(e.target.value)} rows={3} maxLength={2000} placeholder="p. ej. VerilUOC: setsid nohup java -jar ~/Desktop/VerilUOC_3.3.7.jar &" />
          </Field>
        </Paso>}
      </ol>
      {a.ErrorBox}
      <DialogFooter>
        <Button variant="outline" onClick={onClose}>{prueba?.ok ? "Cancelar" : "Cerrar (seguir luego)"}</Button>
        {prueba?.ok && prep && <Button disabled={a.busy} onClick={() => void a.run(async () => { await patch(`/maquinas/${prep.id}`, { agentes, notas }); onClose(); })}>Guardar</Button>}
      </DialogFooter>
    </DialogContent>
  );
}

function Editar({ m, todos, onClose }: { m: Maquina; todos: Agente[]; onClose: () => void }) {
  const [nombre, setNombre] = useState(m.nombre);
  const [agentes, setAgentes] = useState(m.agentes);
  const [notas, setNotas] = useState(m.notas);
  const a = useAct(onClose);
  return (
    <DialogContent className="sm:max-w-lg">
      <DialogHeader><DialogTitle>{m.nombre}</DialogTitle><DialogDescription>{m.vbox} · usuario {m.usuario} · puerto local {m.puerto}</DialogDescription></DialogHeader>
      <div className="grid gap-3">
        <TextField label="Nombre" value={nombre} onChange={setNombre} maxLength={80} />
        <Field label="Agentes que pueden usarla"><Agentes todos={todos} valor={agentes} onChange={setAgentes} /></Field>
        <Field label="Notas para el agente"><Textarea value={notas} onChange={(e) => setNotas(e.target.value)} rows={4} maxLength={2000} /></Field>
      </div>
      {a.ErrorBox}
      <DialogFooter>
        <Button variant="outline" onClick={onClose}>Cancelar</Button>
        <Button disabled={a.busy || !nombre.trim()} onClick={() => void a.run(() => patch(`/maquinas/${m.id}`, { nombre: nombre.trim(), agentes, notas }))}>Guardar</Button>
      </DialogFooter>
    </DialogContent>
  );
}

function Quitar({ m, onClose }: { m: Maquina; onClose: () => void }) {
  const a = useAct(onClose);
  return (
    <DialogContent className="sm:max-w-md">
      <DialogHeader>
        <DialogTitle>¿Dejar de usar «{m.nombre}»?</DialogTitle>
        <DialogDescription>Los agentes dejan de verla. Se borran su clave y su redirección de puerto. La máquina, sus datos y su instantánea no se tocan.</DialogDescription>
      </DialogHeader>
      {a.ErrorBox}
      <DialogFooter>
        <Button variant="outline" onClick={onClose}>Cancelar</Button>
        <Button variant="destructive" disabled={a.busy} onClick={() => void a.run(() => api(`/maquinas/${m.id}`, { method: "DELETE" }))}>Dejar de usarla</Button>
      </DialogFooter>
    </DialogContent>
  );
}

function Pantalla({ id }: { id: string }) {
  const [t, setT] = useState(() => Date.now());
  const [error, setError] = useState(false);
  useEffect(() => { const i = setInterval(() => setT(Date.now()), 4000); return () => clearInterval(i); }, []);
  if (error) return <p className="text-xs text-muted-foreground">No se pudo capturar la pantalla (¿está encendida?).</p>;
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={`${BASE}/api/v1/maquinas/${id}/captura?t=${t}`} alt="Pantalla de la máquina" className="w-full rounded-md border border-border" onError={() => setError(true)} />;
}

function Tarjeta({ m, agentes, onReload, onContinuar }: { m: Maquina; agentes: Agente[]; onReload: () => void; onContinuar: () => void }) {
  const [dialogo, setDialogo] = useState<"editar" | "quitar" | null>(null);
  const [ver, setVer] = useState(false);
  const a = useAct(onReload);
  const on = m.estado === "running";
  const nombres = m.agentes.map((id) => agentes.find((x) => x.id === id)?.nombre ?? id);
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="flex items-start justify-between gap-2">
        <span className="flex min-w-0 items-center gap-2"><HardDrive className="size-4 shrink-0 text-primary" /><span className="truncate font-medium">{m.nombre}</span></span>
        <span className="flex items-center gap-1.5 text-xs text-muted-foreground"><StatusDot level={on ? "ok" : m.estado === "paused" ? "warn" : "unknown"} />{ESTADO[m.estado] ?? m.estado}</span>
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5">
        <Badge variant="secondary">VirtualBox</Badge>
        {m.pendiente ? <Badge variant="outline" className="border-warning text-warning">sin terminar de conectar</Badge> : <Badge variant="outline">internet · usuario {m.usuario}</Badge>}
        {nombres.length ? nombres.map((n) => <Badge key={n} variant="outline">agente {n}</Badge>) : !m.pendiente && <Badge variant="outline">ningún agente</Badge>}
      </div>
      <p className="mt-2 truncate text-[11px] text-muted-foreground">{m.vbox}{m.comprobado ? ` · comprobada ${timeAgo(m.comprobado)}` : ""}</p>
      <div className="mt-3 flex flex-wrap gap-1.5">
        {m.pendiente && <Button size="sm" onClick={onContinuar}>Terminar de conectar</Button>}
        {m.estado !== "no existe" && (on
          ? <Button size="sm" variant="outline" disabled={a.busy} onClick={() => void a.run(() => post(`/maquinas/${m.id}/accion`, { que: "apagar" }))}><Power className="size-3.5" /> Apagar</Button>
          : <Button size="sm" variant="outline" disabled={a.busy} onClick={() => void a.run(() => post(`/maquinas/${m.id}/accion`, { que: "encender" }))}><Play className="size-3.5" /> {m.estado === "paused" ? "Reanudar" : "Encender"}</Button>)}
        {on && <Button size="sm" variant="outline" onClick={() => setVer((x) => !x)}><Camera className="size-3.5" /> {ver ? "Ocultar pantalla" : "Ver pantalla"}</Button>}
        {!m.pendiente && <Button size="sm" variant="ghost" onClick={() => setDialogo("editar")}><Pencil className="size-3.5" /> Editar</Button>}
        <Button size="sm" variant="ghost" onClick={() => setDialogo("quitar")} aria-label={`Dejar de usar ${m.nombre}`}><Trash2 className="size-3.5" /></Button>
      </div>
      {a.ErrorBox}
      {ver && on && <div className="mt-3"><Pantalla id={m.id} /></div>}
      <Dialog open={dialogo !== null} onOpenChange={(o) => { if (!o) setDialogo(null); }}>
        {dialogo === "editar" && <Editar m={m} todos={agentes} onClose={() => { setDialogo(null); onReload(); }} />}
        {dialogo === "quitar" && <Quitar m={m} onClose={() => { setDialogo(null); onReload(); }} />}
      </Dialog>
    </div>
  );
}

/** Máquinas de VirtualBox del usuario que los agentes pueden usar (p. ej. una asignatura con su propio software). */
export function MaquinasLocales() {
  const { lastEvent, me } = usePanel();
  const r = useApi<Estado>("/maquinas", 20000);
  const [asistente, setAsistente] = useState<{ continuar: Maquina | null } | null>(null);
  const admin = me?.role === "admin";
  useEffect(() => {
    if (lastEvent?.type === "maquinas.changed") r.reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastEvent]);
  const cerrar = () => { setAsistente(null); r.reload(); };
  return (
    <section className="mt-10" aria-labelledby="maquinas-locales">
      <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 id="maquinas-locales" className="text-base font-semibold">Máquinas locales</h2>
          <p className="max-w-3xl text-sm text-muted-foreground">
            Máquinas virtuales tuyas de VirtualBox, con su propio software e internet (p. ej. la que pide una asignatura). Tú entras en ellas
            cuando quieras (VirtualBox → Mostrar) y los agentes que elijas las usan por SSH, solo desde este PC.
          </p>
        </div>
        {admin && r.data?.virtualbox.instalado && <Button size="sm" variant="outline" onClick={() => setAsistente({ continuar: null })}><Plus className="size-3.5" /> Conectar una máquina</Button>}
      </div>
      {r.loading && <Loading rows={2} />}
      {r.error && <ErrorState message={r.error} />}
      {r.data && !r.data.virtualbox.instalado && (
        <p className="rounded-lg border border-dashed border-border p-4 text-sm text-muted-foreground">
          {r.data.error ? `No se pudo consultar: ${r.data.error}.` : "VirtualBox no está instalado en este PC."} Es opcional: solo hace falta si alguna tarea necesita
          una máquina virtual concreta. Instálalo con el gestor de paquetes de tu distribución y vuelve aquí.
        </p>
      )}
      {r.data?.virtualbox.instalado && r.data.maquinas.length === 0 && (
        <p className="rounded-lg border border-dashed border-border p-4 text-sm text-muted-foreground">
          {r.data.vms.length ? `Tienes ${r.data.vms.length} ${r.data.vms.length === 1 ? "máquina" : "máquinas"} en VirtualBox y ninguna conectada.` : "VirtualBox no tiene ninguna máquina todavía."}
        </p>
      )}
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {r.data?.maquinas.map((m) => <Tarjeta key={m.id} m={m} agentes={r.data!.agentes} onReload={r.reload} onContinuar={() => setAsistente({ continuar: m })} />)}
      </div>
      {r.data?.virtualbox.instalado && <p className="mt-3 max-w-3xl text-xs text-muted-foreground">
        VirtualBox {r.data.virtualbox.version}. Al cerrar la ventana de una máquina, elige «Continuar en segundo plano»: si la pausas, los agentes la reanudan solos.
        Dentro de la máquina el agente actúa como tu usuario (sin sudo). Lo que lee en webs o documentos son datos, no órdenes.
      </p>}
      <Dialog open={asistente !== null} onOpenChange={(o) => { if (!o) cerrar(); }}>
        {asistente && r.data && <Asistente estado={r.data} continuar={asistente.continuar} onClose={cerrar} />}
      </Dialog>
    </section>
  );
}
