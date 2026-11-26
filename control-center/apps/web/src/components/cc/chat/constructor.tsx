"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, Check, ExternalLink, Loader2, Trash2 } from "lucide-react";
import { post } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { usePanel } from "../shell";
import { avisarCambios, type Operacion } from "../cambios";

export type Personalizacion = {
  conversacion: string; estado: "preparando" | "lista" | "dormida" | "error"; paso?: string; error?: string;
  conflicto?: string[] | null; creada: string; version_objetivo?: string | null;
};
export type EstadoConstructor = {
  personalizacion: Personalizacion | null; url: string | null; vista_previa: boolean; trabajando: boolean;
  preparando: boolean; aplicando: boolean; bwrap: boolean; ultima_operacion: Operacion | null;
};

const boton = "inline-flex h-8 items-center gap-1.5 rounded-lg px-3 text-xs font-medium transition-colors disabled:opacity-50";

/** Encima del compositor, en las conversaciones del Constructor: cómo va la vista previa y los botones para
 *  abrirla, aplicar los cambios al panel real o descartarlos. Solo hay una personalización abierta a la vez. */
export function BarraConstructor({ cid, onIr, onError }: { cid: string | null; onIr: (id: string) => void; onError: (e: string | null) => void }) {
  const est = useApi<EstadoConstructor>("/constructor", 4000);
  const { lastEvent } = usePanel();
  const [enviando, setEnviando] = useState<"aplicar" | "descartar" | null>(null);
  const { reload } = est;
  useEffect(() => {
    if (lastEvent?.type === "run.finished" || lastEvent?.type?.startsWith("cambios.") || lastEvent?.type === "constructor.cerrada") void reload();
  }, [lastEvent, reload]);

  const d = est.data;
  if (!d) return null;
  const p = d.personalizacion;
  const aviso = (texto: React.ReactNode, accion?: React.ReactNode) => (
    <div className="mb-2 flex flex-wrap items-center gap-2 rounded-xl border border-border bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
      <span className="min-w-0 flex-1">{texto}</span>{accion}
    </div>
  );

  if (!d.bwrap) return aviso(<><AlertTriangle className="mr-1 inline size-3.5 text-amber-500" />Falta bubblewrap (bwrap) en este PC: el Constructor lo necesita para trabajar encerrado. Instálalo con tu gestor de paquetes.</>);
  if (!p) {
    return aviso(cid
      ? "Esta personalización ya está cerrada. Si sigues escribiendo, el Constructor empezará otra copia del panel tal como está ahora."
      : "Cuéntale qué quieres cambiar o añadir al panel. Lo verás funcionando en una vista previa, con una copia de tus datos, antes de aplicarlo.");
  }
  if (p.conversacion !== cid) {
    return aviso("Tienes otra personalización abierta. Solo puede haber una a la vez: termínala (aplica o descarta los cambios) antes de empezar otra.",
      <button type="button" onClick={() => onIr(p.conversacion)} className={`${boton} bg-primary text-primary-foreground hover:bg-primary/90`}>Ir a ella</button>);
  }

  const aplicar = async () => {
    if (!window.confirm("Se aplicarán los cambios de la vista previa a tu panel.\n\nAntes se hace una copia de seguridad de tus datos y, si algo sale mal, el panel vuelve solo a como estaba. Se reiniciará (tarda unos minutos).\n\n¿Aplicar?")) return;
    setEnviando("aplicar");
    onError(null);
    try {
      await post("/constructor/aplicar", {});
      avisarCambios();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setEnviando(null);
      void reload();
    }
  };
  const descartar = async () => {
    if (!window.confirm("Se borrará la copia y lo que hayas probado en la vista previa. Tu panel no cambia.\n\n¿Descartar los cambios?")) return;
    setEnviando("descartar");
    onError(null);
    try {
      await post("/constructor/descartar");
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setEnviando(null);
      void reload();
    }
  };

  const ocupado = d.trabajando || d.aplicando || enviando !== null;
  let estado: React.ReactNode;
  if (d.aplicando || enviando === "aplicar") estado = <><Loader2 className="size-3.5 animate-spin" /> Aplicando los cambios a tu panel…</>;
  else if (p.estado === "error") estado = <><AlertTriangle className="size-3.5 text-destructive" /> No se pudo preparar la vista previa: {p.error}</>;
  else if (p.estado === "preparando") estado = <><Loader2 className="size-3.5 animate-spin" /> {p.paso || "Preparando la vista previa"}…</>;
  else if (p.conflicto?.length) estado = <><AlertTriangle className="size-3.5 text-amber-500" /> Juntando la versión {p.version_objetivo} con tus personalizaciones</>;
  else if (d.trabajando) estado = <><Loader2 className="size-3.5 animate-spin" /> El Constructor está trabajando en la copia…</>;
  else estado = <><span className="size-2 rounded-full bg-emerald-500" /> Vista previa {p.estado === "dormida" ? "en pausa (se despierta al abrirla)" : "lista"}</>;

  return (
    <div className="mb-2 rounded-xl border border-border bg-muted/40 px-3 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="flex min-w-0 flex-1 items-center gap-1.5 text-xs text-muted-foreground">{estado}</span>
        <a href="/vista-previa/" target="_blank" rel="noopener"
          aria-disabled={p.estado === "preparando" || p.estado === "error"}
          className={`${boton} ring-1 ring-border hover:bg-background ${p.estado === "preparando" || p.estado === "error" ? "pointer-events-none opacity-50" : ""}`}>
          <ExternalLink className="size-3.5" /> Ver vista previa
        </a>
        <button type="button" onClick={() => void aplicar()} disabled={ocupado || p.estado !== "lista" && p.estado !== "dormida" || !!p.conflicto?.length}
          title={d.trabajando ? "Espera a que el Constructor termine" : "Llevar estos cambios a tu panel"}
          className={`${boton} bg-primary text-primary-foreground hover:bg-primary/90`}>
          {enviando === "aplicar" ? <Loader2 className="size-3.5 animate-spin" /> : <Check className="size-3.5" />} Aplicar cambios
        </button>
        <button type="button" onClick={() => void descartar()} disabled={ocupado} title="Tirar la copia sin tocar tu panel"
          className={`${boton} text-muted-foreground hover:bg-background hover:text-destructive`}>
          {enviando === "descartar" ? <Loader2 className="size-3.5 animate-spin" /> : <Trash2 className="size-3.5" />} Descartar
        </button>
      </div>
    </div>
  );
}
