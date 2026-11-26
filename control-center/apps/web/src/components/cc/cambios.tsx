"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AlertTriangle, Check, CheckCircle2, Eye, Loader2, Undo2, X } from "lucide-react";
import { BASE } from "@/lib/base";
import { usePanel } from "./shell";

/** Operación del supervisor de cambios (data/cambios/estado.json). */
export type Operacion = {
  id: string; op: "aplicar" | "deshacer" | "actualizar" | "restaurar" | "desplegar"; titulo: string;
  estado: "en_curso" | "ok" | "revertido" | "fallo" | "roto"; paso: string; pasos: { texto: string; ts: string }[];
  inicio: string; fin: string | null; error: string; codigo: string; version_antes: string; version_despues: string | null; copia: string | null;
};

const VISTO = "pos.cambios.visto";
/** Para que la pantalla de «Aplicando cambios» empiece a seguir la operación que se acaba de lanzar. */
export const avisarCambios = () => window.dispatchEvent(new Event("cc:cambios"));

async function leerProgreso(): Promise<Operacion | null | "caido"> {
  try {
    const r = await fetch(`${BASE}/api/v1/cambios/progreso`, { credentials: "same-origin", cache: "no-store" });
    if (!r.ok) return "caido";
    return ((await r.json()) as { operacion: Operacion | null }).operacion;
  } catch {
    return "caido";
  }
}

const RESULTADO: Record<string, { titulo: string; texto: string }> = {
  ok: { titulo: "Cambios aplicados", texto: "Tu panel ya tiene los cambios. Recárgalo para verlos." },
  revertido: { titulo: "No se han podido aplicar", texto: "Algo ha fallado, así que el panel ha vuelto solo a como estaba. Tus datos están a salvo y hay una copia de seguridad de antes del intento." },
  fallo: { titulo: "No se ha hecho nada", texto: "No se ha podido empezar, así que no ha cambiado nada." },
  roto: { titulo: "El panel no ha arrancado bien", texto: "Ha fallado el cambio y también la vuelta atrás. Tus datos están a salvo en la copia de seguridad. Prueba a deshacer el último cambio en Ajustes → Versiones." },
};

/** Pantalla que tapa el panel mientras el supervisor aplica, deshace o actualiza (sobrevive al reinicio del panel:
 *  sigue preguntando hasta que vuelve), y el resultado al terminar. */
export function CambiosEnCurso() {
  const { subscribe } = usePanel();
  const [op, setOp] = useState<Operacion | null>(null);
  const [caido, setCaido] = useState(false);
  const [siguiendo, setSiguiendo] = useState(false);
  const [visto, setVisto] = useState<string | null>(null);
  const recargar = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [abierta] = useState(() => Date.now());  // solo se enseña el resultado de lo que terminó hace poco

  useEffect(() => {
    try { setVisto(localStorage.getItem(VISTO)); } catch { /* sin almacenamiento */ }
  }, []);

  const comprobar = useCallback(async () => {
    const r = await leerProgreso();
    if (r === "caido") { setCaido(true); return; }
    setCaido(false);
    setOp(r);
    if (r && r.estado !== "en_curso") setSiguiendo(false);
  }, []);

  useEffect(() => {
    void comprobar();
    const empezar = () => { setSiguiendo(true); void comprobar(); };
    window.addEventListener("cc:cambios", empezar);
    const quitar = subscribe((e) => { if (e.type === "cambios.iniciado" || e.type === "backend.started") empezar(); });
    return () => { window.removeEventListener("cc:cambios", empezar); quitar(); };
  }, [comprobar, subscribe]);

  const enCurso = op?.estado === "en_curso" || (siguiendo && caido);
  useEffect(() => {
    if (!enCurso && !siguiendo) return;
    const t = setInterval(() => void comprobar(), 2000);
    return () => clearInterval(t);
  }, [enCurso, siguiendo, comprobar]);

  const marcarVisto = () => {
    if (!op) return;
    try { localStorage.setItem(VISTO, op.id); } catch { /* sin almacenamiento */ }
    setVisto(op.id);
  };
  const terminado = op && op.estado !== "en_curso" && op.id !== visto && op.fin && abierta - new Date(op.fin).getTime() < 6 * 3600_000;
  // Con la web nueva, hay que recargar: se hace solo a los pocos segundos
  useEffect(() => {
    if (terminado && op?.estado === "ok" && op.op !== "restaurar" && !recargar.current) {
      recargar.current = setTimeout(() => { marcarVisto(); window.location.reload(); }, 6000);
    }
  });

  if (enCurso) {
    const pasos = op?.estado === "en_curso" ? op.pasos : [];
    return (
      <div role="alertdialog" aria-modal="true" aria-label="Aplicando cambios" className="fixed inset-0 z-[70] grid place-items-center bg-background/80 p-4 backdrop-blur-sm">
        <div className="w-full max-w-md rounded-2xl border border-border bg-card p-6 shadow-2xl">
          <div className="flex items-center gap-3">
            <Loader2 className="size-6 shrink-0 animate-spin text-primary" />
            <div className="min-w-0">
              <h2 className="text-base font-semibold">{op?.estado === "en_curso" ? op.titulo : "Aplicando cambios"}</h2>
              <p className="text-sm text-muted-foreground">{caido ? "Reiniciando el panel… vuelve en un momento." : op?.paso ?? "Empezando…"}</p>
            </div>
          </div>
          {pasos.length > 0 && (
            <ol className="mt-4 space-y-1.5 text-sm">
              {pasos.map((p, i) => (
                <li key={`${p.ts}-${i}`} className="flex items-center gap-2">
                  {i < pasos.length - 1 ? <Check className="size-4 text-emerald-500" /> : <Loader2 className="size-4 animate-spin text-muted-foreground" />}
                  <span className={i < pasos.length - 1 ? "text-muted-foreground" : ""}>{p.texto}</span>
                </li>
              ))}
            </ol>
          )}
          <p className="mt-4 text-xs text-muted-foreground">Antes de cambiar nada se ha hecho una copia de seguridad. Si algo falla, el panel vuelve solo a como estaba. Puedes dejar esta página abierta: se actualizará sola.</p>
        </div>
      </div>
    );
  }

  if (!terminado || !op) return null;
  const r = RESULTADO[op.estado] ?? RESULTADO.fallo;
  const ok = op.estado === "ok";
  return (
    <div role="dialog" aria-modal="true" aria-label={r.titulo} className="fixed inset-0 z-[70] grid place-items-center bg-background/70 p-4 backdrop-blur-sm">
      <div className="w-full max-w-md rounded-2xl border border-border bg-card p-6 shadow-2xl">
        <div className="flex items-start gap-3">
          {ok ? <CheckCircle2 className="mt-0.5 size-6 shrink-0 text-emerald-500" /> : op.estado === "revertido" ? <Undo2 className="mt-0.5 size-6 shrink-0 text-amber-500" /> : <AlertTriangle className="mt-0.5 size-6 shrink-0 text-destructive" />}
          <div className="min-w-0 flex-1">
            <h2 className="text-base font-semibold">{r.titulo}</h2>
            <p className="mt-0.5 text-sm text-muted-foreground">{op.titulo}{op.version_despues && op.version_despues !== op.version_antes ? ` · versión ${op.version_despues}` : ""}</p>
            <p className="mt-3 text-sm">{r.texto}</p>
            {!ok && op.error && <p className="mt-2 rounded-lg bg-muted px-3 py-2 text-xs break-words text-muted-foreground">{op.error}</p>}
          </div>
          <button type="button" onClick={marcarVisto} aria-label="Cerrar" className="grid size-8 place-items-center rounded-lg hover:bg-muted"><X className="size-4" /></button>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          {ok ? (
            <button type="button" onClick={() => { marcarVisto(); window.location.reload(); }} className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90">
              Recargar ahora
            </button>
          ) : (
            <button type="button" onClick={marcarVisto} className="inline-flex h-9 items-center rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90">Entendido</button>
          )}
        </div>
      </div>
    </div>
  );
}

async function llamarPanelReal(ruta: string): Promise<void> {
  const me = await fetch("/api/v1/auth/me", { credentials: "same-origin", cache: "no-store" });
  if (!me.ok) throw new Error("No has iniciado sesión en el panel");
  const { csrf_token } = (await me.json()) as { csrf_token: string };
  const r = await fetch(`/api/v1${ruta}`, { method: "POST", credentials: "same-origin", headers: { "X-CSRF-Token": csrf_token, "Content-Type": "application/json" }, body: "{}" });
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail ?? msg; } catch { /* sin detalle */ }
    throw new Error(String(msg));
  }
}

/** Arriba del todo en la vista previa: deja claro que no es el panel real y permite aplicar o descartar desde aquí. */
export function FranjaVistaPrevia() {
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const accion = async (ruta: string, pregunta: string) => {
    if (!window.confirm(pregunta)) return;
    setEnviando(true);
    setError(null);
    try {
      await llamarPanelReal(ruta);
      window.location.href = "/";
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setEnviando(false);
    }
  };
  return (
    <div role="region" aria-label="Vista previa" className="relative z-[60] flex flex-wrap items-center gap-2 bg-amber-400 px-4 py-2 text-sm text-amber-950">
      <Eye className="size-4 shrink-0" />
      <span className="min-w-0 flex-1"><strong>Vista previa</strong> · Así quedaría tu panel. Usa una copia de tus datos: lo que hagas aquí no se guarda.{error && <span className="ml-2 font-medium text-red-800">{error}</span>}</span>
      {/* eslint-disable-next-line @next/next/no-html-link-for-pages -- el panel real, fuera de /vista-previa (un <Link> le pondría la ruta base) */}
      <a href="/" className="rounded-md px-2.5 py-1 font-medium hover:bg-amber-300">Volver al panel</a>
      <button type="button" disabled={enviando} onClick={() => void accion("/constructor/descartar", "Se borrará la vista previa y tu panel no cambia. ¿Descartar los cambios?")}
        className="rounded-md px-2.5 py-1 font-medium hover:bg-amber-300 disabled:opacity-50">Descartar</button>
      <button type="button" disabled={enviando} onClick={() => void accion("/constructor/aplicar", "Se aplicarán estos cambios a tu panel. Antes se hace una copia de seguridad y, si algo falla, vuelve solo a como estaba. ¿Aplicar?")}
        className="inline-flex items-center gap-1.5 rounded-md bg-amber-950 px-3 py-1 font-medium text-amber-50 hover:bg-amber-900 disabled:opacity-50">
        {enviando ? <Loader2 className="size-3.5 animate-spin" /> : <Check className="size-3.5" />} Aplicar cambios
      </button>
    </div>
  );
}
