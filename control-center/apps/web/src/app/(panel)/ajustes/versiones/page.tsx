"use client";

import { useEffect, useState } from "react";
import { ArchiveRestore, ArrowUpCircle, CheckCircle2, Hammer, History, Loader2, RefreshCw, Undo2 } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { PageHeader, usePanel } from "@/components/cc/shell";
import { ErrorState, Loading } from "@/components/cc/states";
import { avisarCambios, type Operacion } from "@/components/cc/cambios";
import { abrirConversacion } from "@/components/cc/chat/chat-flotante";
import type { Personalizacion } from "@/components/cc/chat/constructor";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { post } from "@/lib/api";
import { bytes, timeAgo } from "@/lib/format";
import { useApi } from "@/lib/hooks";

type PersonalizacionAplicada = { commit: string; fecha: string; titulo: string; deshecha: boolean; archivos: string[]; n_archivos: number };
type Copia = { id: string; tam: number; base: boolean; vault: boolean };
type Historial = Pick<Operacion, "id" | "op" | "titulo" | "estado" | "inicio" | "fin" | "error" | "codigo" | "version_antes" | "version_despues">;
type Estado = {
  version: string; estado: Operacion | null; en_marcha: boolean; origen: boolean; personalizaciones: PersonalizacionAplicada[];
  copias: Copia[]; historial: Historial[]; personalizacion_abierta: Personalizacion | null;
};
type Busqueda = { actual: string; ultima: string; hay_nueva: boolean; notas: string; origen: boolean; error: string };

const boton = "inline-flex h-9 items-center gap-1.5 rounded-lg px-3 text-sm font-medium transition-colors disabled:opacity-50";
const ESTADO: Record<string, [string, string]> = {
  ok: ["Hecho", "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300"],
  revertido: ["Vuelto atrás", "bg-amber-500/15 text-amber-700 dark:text-amber-300"],
  fallo: ["No se hizo", "bg-muted text-muted-foreground"],
  roto: ["Falló", "bg-destructive/15 text-destructive"],
  en_curso: ["En curso", "bg-primary/15 text-primary"],
};
const OP: Record<string, string> = { aplicar: "Personalización", deshacer: "Deshacer", actualizar: "Actualización", restaurar: "Restaurar copia", desplegar: "Recompilar" };

function fechaCopia(id: string): string {
  const m = id.match(/^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})/);
  if (!m) return id;
  return new Intl.DateTimeFormat("es-ES", { dateStyle: "medium", timeStyle: "short" }).format(new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]));
}

export default function Versiones() {
  const { lastEvent } = usePanel();
  const est = useApi<Estado>("/cambios", 15000);
  const [busqueda, setBusqueda] = useState<Busqueda | null>(null);
  const [buscando, setBuscando] = useState(false);
  const [trabajando, setTrabajando] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [restaurar, setRestaurar] = useState<{ id: string; vault: boolean } | null>(null);
  const { reload } = est;
  useEffect(() => {
    if (lastEvent?.type?.startsWith("cambios.") || lastEvent?.type === "backend.started") void reload();
  }, [lastEvent, reload]);

  const lanzar = async (clave: string, ruta: string, cuerpo: object, pregunta: string) => {
    if (!window.confirm(pregunta)) return;
    setTrabajando(clave);
    setError(null);
    try {
      await post(ruta, cuerpo);
      avisarCambios();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setTrabajando(null);
      void reload();
    }
  };
  const buscar = async () => {
    setBuscando(true);
    setError(null);
    try {
      setBusqueda(await post<Busqueda>("/cambios/buscar"));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBuscando(false);
    }
  };
  const juntarConConstructor = async (version: string) => {
    setTrabajando("juntar");
    setError(null);
    try {
      const r = await post<{ conversacion: string }>("/constructor/actualizacion", { version });
      abrirConversacion("constructor", r.conversacion);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setTrabajando(null);
    }
  };

  const d = est.data;
  const ultima = d?.estado;
  const conflictoActualizacion = ultima?.op === "actualizar" && ultima.codigo === "conflicto" && busqueda?.hay_nueva;
  const ocupado = !!d?.en_marcha || trabajando !== null;

  return (
    <div className="space-y-4">
      <PageHeader title="Versiones" description="Actualiza Personal OS, deshaz personalizaciones y vuelve a una copia de seguridad, sin tocar la terminal." />
      {error && <ErrorState message={error} />}
      {est.error && !d && <ErrorState message={est.error} />}
      {!d && !est.error && <Loading rows={4} />}
      {d && (
        <>
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2"><ArrowUpCircle className="size-4" /> Personal OS {d.version}</CardTitle>
              <CardDescription>Antes de actualizar se hace una copia de seguridad de tus datos. Si la versión nueva no arranca, el panel vuelve solo a la que tienes ahora. Tus personalizaciones se conservan.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {!d.origen ? (
                <p className="text-sm text-muted-foreground">Esta instalación no tiene un repositorio de origen del que traer versiones (se actualiza desde la terminal).</p>
              ) : (
                <div className="flex flex-wrap items-center gap-2">
                  <button type="button" onClick={() => void buscar()} disabled={buscando || ocupado} className={`${boton} ring-1 ring-border hover:bg-muted`}>
                    {buscando ? <Loader2 className="size-4 animate-spin" /> : <RefreshCw className="size-4" />} Buscar actualizaciones
                  </button>
                  {busqueda && !busqueda.error && !busqueda.hay_nueva && <span className="flex items-center gap-1.5 text-sm text-muted-foreground"><CheckCircle2 className="size-4 text-emerald-500" /> Tienes la última versión</span>}
                  {busqueda?.error && <span className="text-sm text-destructive">{busqueda.error}</span>}
                </div>
              )}
              {busqueda?.hay_nueva && (
                <div className="rounded-xl border border-primary/30 bg-primary/5 p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="flex-1 font-medium">Versión {busqueda.ultima} disponible</span>
                    <button type="button" disabled={ocupado || !!d.personalizacion_abierta} className={`${boton} bg-primary text-primary-foreground hover:bg-primary/90`}
                      title={d.personalizacion_abierta ? "Termina antes la personalización abierta" : undefined}
                      onClick={() => void lanzar("actualizar", "/cambios/actualizar", { version: busqueda.ultima },
                        `Se actualizará Personal OS a la versión ${busqueda.ultima}.\n\nAntes se hace una copia de seguridad y, si algo falla, vuelve solo a la versión ${d.version}. El panel se reiniciará (unos minutos).\n\n¿Actualizar?`)}>
                      {trabajando === "actualizar" ? <Loader2 className="size-4 animate-spin" /> : <ArrowUpCircle className="size-4" />} Actualizar
                    </button>
                  </div>
                  {d.personalizacion_abierta && <p className="mt-2 text-xs text-muted-foreground">Tienes una personalización abierta con el Constructor: aplícala o descártala antes de actualizar.</p>}
                  {conflictoActualizacion && (
                    <div className="mt-3 flex flex-wrap items-center gap-2 rounded-lg bg-amber-500/10 p-3 text-sm">
                      <span className="flex-1">La versión nueva choca con tus personalizaciones. El Constructor puede juntarlas y enseñártelo en una vista previa antes de aplicar.</span>
                      <button type="button" disabled={ocupado || !!d.personalizacion_abierta} onClick={() => void juntarConConstructor(busqueda.ultima)} className={`${boton} bg-amber-500 text-amber-950 hover:bg-amber-400`}>
                        {trabajando === "juntar" ? <Loader2 className="size-4 animate-spin" /> : <Hammer className="size-4" />} Juntar con el Constructor
                      </button>
                    </div>
                  )}
                  {busqueda.notas && <div className="prose prose-sm mt-3 max-w-none text-sm dark:prose-invert [&_h3]:mt-3 [&_h3]:text-sm [&_h3]:font-semibold [&_ul]:list-disc [&_ul]:pl-5"><ReactMarkdown remarkPlugins={[remarkGfm]}>{busqueda.notas}</ReactMarkdown></div>}
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2"><Hammer className="size-4" /> Tus personalizaciones</CardTitle>
              <CardDescription>Los cambios que has aplicado con el Constructor. Puedes deshacer cualquiera: se quita y el panel se reinicia, con copia de seguridad antes.</CardDescription>
            </CardHeader>
            <CardContent>
              {d.personalizacion_abierta && (
                <div className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-border bg-muted/40 p-3 text-sm">
                  <span className="flex-1">Hay una personalización abierta en el chat del Constructor ({d.personalizacion_abierta.estado === "preparando" ? "preparándose" : "con vista previa"}).</span>
                  <button type="button" onClick={() => abrirConversacion("constructor", d.personalizacion_abierta!.conversacion)} className={`${boton} ring-1 ring-border hover:bg-background`}>Abrir</button>
                </div>
              )}
              {d.personalizaciones.length === 0 ? (
                <p className="text-sm text-muted-foreground">Aún no has aplicado ninguna. Pídele al Constructor, desde el chat, lo que quieras cambiar del panel.</p>
              ) : (
                <ul className="divide-y divide-border">
                  {d.personalizaciones.map((p) => (
                    <li key={p.commit} className="flex flex-wrap items-center gap-3 py-2.5">
                      <div className="min-w-0 flex-1">
                        <div className={`text-sm font-medium ${p.deshecha ? "text-muted-foreground line-through" : ""}`}>{p.titulo}</div>
                        <div className="text-xs text-muted-foreground">{timeAgo(p.fecha)} · {p.n_archivos} archivo{p.n_archivos === 1 ? "" : "s"}{p.deshecha ? " · deshecha" : ""}</div>
                      </div>
                      {!p.deshecha && (
                        <button type="button" disabled={ocupado} className={`${boton} text-muted-foreground ring-1 ring-border hover:bg-muted hover:text-foreground`}
                          onClick={() => void lanzar(`deshacer-${p.commit}`, "/cambios/deshacer", { commit: p.commit },
                            `Se deshará «${p.titulo}» y el panel se reiniciará.\n\nAntes se hace una copia de seguridad y, si algo falla, vuelve solo a como está ahora.\n\n¿Deshacer?`)}>
                          {trabajando === `deshacer-${p.commit}` ? <Loader2 className="size-4 animate-spin" /> : <Undo2 className="size-4" />} Deshacer
                        </button>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2"><ArchiveRestore className="size-4" /> Copias de seguridad</CardTitle>
              <CardDescription>Se hace una antes de cada actualización, personalización o deshacer (se guardan las {5} últimas): la base de datos del panel, tu vault y tu configuración. La copia diaria de la base sigue aparte.</CardDescription>
            </CardHeader>
            <CardContent>
              {d.copias.length === 0 ? (
                <p className="text-sm text-muted-foreground">Aún no hay ninguna.</p>
              ) : (
                <ul className="divide-y divide-border">
                  {d.copias.map((c) => (
                    <li key={c.id} className="py-2.5">
                      <div className="flex flex-wrap items-center gap-3">
                        <div className="min-w-0 flex-1">
                          <div className="text-sm font-medium">{fechaCopia(c.id)} · {OP[c.id.split("-").slice(2).join("-")] ?? "Copia"}</div>
                          <div className="text-xs text-muted-foreground">{bytes(c.tam)} · {[c.base && "base de datos", c.vault && "vault", "configuración"].filter(Boolean).join(", ")}</div>
                        </div>
                        <button type="button" disabled={ocupado} onClick={() => setRestaurar(restaurar?.id === c.id ? null : { id: c.id, vault: false })}
                          className={`${boton} text-muted-foreground ring-1 ring-border hover:bg-muted hover:text-foreground`}>
                          <History className="size-4" /> Restaurar…
                        </button>
                      </div>
                      {restaurar?.id === c.id && (
                        <div className="mt-2 space-y-2 rounded-lg border border-border bg-muted/40 p-3 text-sm">
                          <p>Tus datos del panel volverán a como estaban en esa fecha. Lo de después se pierde, aunque antes se guarda una copia del estado actual.</p>
                          {!c.base && <p className="text-amber-700 dark:text-amber-300">Esta copia no tiene base de datos (aquella operación no la cambió): solo se puede restaurar la vault.</p>}
                          {c.vault && (
                            <label className="flex items-center gap-2">
                              <input type="checkbox" checked={restaurar.vault} onChange={(e) => setRestaurar({ ...restaurar, vault: e.target.checked })} />
                              Restaurar también la vault (la actual se guarda aparte, no se borra)
                            </label>
                          )}
                          <button type="button" disabled={ocupado || (!c.base && !restaurar.vault)} className={`${boton} bg-destructive text-white hover:bg-destructive/90`}
                            onClick={() => void lanzar(`restaurar-${c.id}`, "/cambios/restaurar", { copia: c.id, vault: restaurar.vault },
                              `¿Seguro? Se restaurará la copia del ${fechaCopia(c.id)}${restaurar.vault ? " (también la vault)" : ""} y el panel se reiniciará.`)}>
                            {trabajando === `restaurar-${c.id}` ? <Loader2 className="size-4 animate-spin" /> : <ArchiveRestore className="size-4" />} Restaurar esta copia
                          </button>
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>

          {d.historial.length > 0 && (
            <Card>
              <CardHeader><CardTitle className="flex items-center gap-2"><History className="size-4" /> Historial</CardTitle></CardHeader>
              <CardContent>
                <ul className="divide-y divide-border">
                  {d.historial.map((h) => {
                    const [txt, tono] = ESTADO[h.estado] ?? ESTADO.fallo;
                    return (
                      <li key={h.id} className="flex flex-wrap items-center gap-3 py-2">
                        <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${tono}`}>{txt}</span>
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-sm">{OP[h.op] ?? h.op}: {h.titulo}</div>
                          {h.error && h.estado !== "ok" && <div className="truncate text-xs text-muted-foreground" title={h.error}>{h.error}</div>}
                        </div>
                        <span className="text-xs text-muted-foreground">{timeAgo(h.fin ?? h.inicio)}</span>
                      </li>
                    );
                  })}
                </ul>
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
