"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronRight, Copy, FileText, Loader2, TriangleAlert } from "lucide-react";
import { cn } from "cn";
import type { Assistant } from "../assistants";
import { Markdown } from "../markdown";
import { sinAdjuntos, turnos, type Detalle, type EnDirecto, type Turno } from "./datos";
import { describirLinea, duracion } from "./pasos";

/** Reloj que avanza cada segundo mientras hace falta (para el «lleva 12 s»). */
function useAhora(activo: boolean) {
  const [ahora, setAhora] = useState(() => Date.now());
  useEffect(() => {
    if (!activo) return;
    const t = setInterval(() => setAhora(Date.now()), 1000);
    return () => clearInterval(t);
  }, [activo]);
  return ahora;
}

function Copiar({ texto }: { texto: string }) {
  const [hecho, setHecho] = useState(false);
  return (
    <button type="button" onClick={() => { void navigator.clipboard?.writeText(texto); setHecho(true); setTimeout(() => setHecho(false), 1500); }}
      className="grid size-7 place-items-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground" aria-label="Copiar la respuesta" title="Copiar">
      {hecho ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
    </button>
  );
}

/** «▸ Ha mirado 3 cosas · 12 s»: plegado por defecto; dentro, cada paso en palabras. */
function Pasos({ pasos, etiqueta, enCurso }: { pasos: string[]; etiqueta: string; enCurso: boolean }) {
  const [abierto, setAbierto] = useState(false);
  if (!pasos.length && !enCurso) return null;
  return (
    <div className="mb-2">
      <button type="button" onClick={() => setAbierto(!abierto)} disabled={!pasos.length} aria-expanded={abierto}
        className="flex max-w-full items-center gap-1.5 rounded-md py-0.5 text-left text-xs text-muted-foreground hover:text-foreground disabled:hover:text-muted-foreground">
        {enCurso ? <Loader2 className="size-3.5 shrink-0 animate-spin text-primary" /> : <ChevronRight className={cn("size-3.5 shrink-0 transition-transform", abierto && "rotate-90")} />}
        <span className={cn("truncate", enCurso && "text-foreground/80")}>{etiqueta}</span>
        {enCurso && pasos.length > 0 && <ChevronRight className={cn("size-3 shrink-0 transition-transform", abierto && "rotate-90")} />}
      </button>
      {abierto && pasos.length > 0 && (
        <ol className="mt-1.5 ml-1.5 space-y-1 border-l border-border pl-3.5">
          {pasos.map((p, i) => <li key={i} className="text-xs text-muted-foreground">{describirLinea(p)}</li>)}
        </ol>
      )}
    </div>
  );
}

function Pregunta({ texto }: { texto: string }) {
  const m = sinAdjuntos(texto);
  return (
    <div className="flex flex-col items-end gap-1.5">
      {m.adjuntos.length > 0 && (
        <ul className="flex flex-wrap justify-end gap-1.5" aria-label="Adjuntos">
          {m.adjuntos.map((a) => <li key={a} className="flex items-center gap-1.5 rounded-lg border border-border px-2 py-1 text-xs"><FileText className="size-3.5 text-muted-foreground" />{a}</li>)}
        </ul>
      )}
      {m.texto && <div className="max-w-[85%] rounded-3xl bg-muted px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap break-words">{m.texto}</div>}
    </div>
  );
}

function TurnoVista({ t, vivo, nombre, onWiki, ahora }: { t: Turno; vivo: EnDirecto | null; nombre: string; onWiki: (n: string) => void; ahora: number }) {
  const estado = t.estado?.estado;
  const enCurso = estado === "queued" || estado === "running";
  const directo = enCurso && vivo?.run === t.run ? vivo : null;
  const pasos = directo ? [...t.pasos, ...directo.pasos.slice(t.pasos.length)] : t.pasos;
  const inicio = t.estado?.inicio ?? t.estado?.creada;
  const ms = inicio ? (t.estado?.fin ? Date.parse(t.estado.fin) : ahora) - Date.parse(inicio) : 0;
  let etiqueta = "";
  if (enCurso) {
    etiqueta = estado === "queued" ? "Preparándose…" : pasos.length ? `${describirLinea(pasos[pasos.length - 1])}…` : directo?.texto ? "Escribiendo…" : "Pensando…";
    if (estado === "running" && ms > 3000) etiqueta += ` · ${duracion(ms)}`;
  } else if (pasos.length) {
    etiqueta = `Ha mirado ${pasos.length} ${pasos.length === 1 ? "cosa" : "cosas"}${ms > 0 ? ` · ${duracion(ms)}` : ""}`;
  }
  const texto = t.respuesta?.texto ?? directo?.texto ?? "";
  return (
    <div className="space-y-4">
      {t.pregunta && <Pregunta texto={t.pregunta.texto} />}
      {(texto || enCurso || pasos.length > 0 || estado === "error" || estado === "interrupted") && (
        <div className="group" aria-live={enCurso ? "polite" : undefined}>
          <div className="mb-1 text-xs font-medium text-muted-foreground">{nombre}</div>
          <Pasos pasos={pasos} etiqueta={etiqueta} enCurso={enCurso} />
          {texto && <div className="text-sm leading-relaxed"><Markdown source={texto} onWiki={onWiki} imageSrc={(n) => n} /></div>}
          {estado === "error" && !t.respuesta && <p className="flex items-start gap-2 rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive"><TriangleAlert className="mt-0.5 size-4 shrink-0" />{t.estado?.error || "No ha podido responder."}</p>}
          {estado === "interrupted" && <p className="text-xs text-muted-foreground italic">Respuesta parada.</p>}
          {t.respuesta && !enCurso && <div className="mt-1 opacity-60 transition-opacity group-hover:opacity-100 focus-within:opacity-100"><Copiar texto={t.respuesta.texto} /></div>}
        </div>
      )}
    </div>
  );
}

export function Vista({ data, vivo, asistente, onWiki, onSugerencia }: {
  data: Detalle | null; vivo: EnDirecto | null; asistente: Assistant; onWiki: (n: string) => void; onSugerencia: (t: string) => void;
}) {
  const lista = useMemo(() => (data ? turnos(data) : []), [data]);
  const enCurso = lista.some((t) => t.estado?.estado === "running" || t.estado?.estado === "queued");
  const ahora = useAhora(enCurso);
  const fin = useRef<HTMLDivElement>(null);
  const caja = useRef<HTMLDivElement>(null);
  const pegado = useRef(true);

  // Baja solo si ya estabas abajo (si has subido a leer algo, no te lo mueve), salvo al abrirla o al preguntar de nuevo
  const previo = useRef({ id: "", n: 0 });
  useEffect(() => {
    const id = data?.conversacion.id ?? "";
    if (id !== previo.current.id || lista.length > previo.current.n) pegado.current = true;
    previo.current = { id, n: lista.length };
    if (pegado.current) fin.current?.scrollIntoView({ block: "end" });
  }, [lista.length, vivo?.texto, vivo?.pasos.length, data?.conversacion.id]);

  const alDesplazar = () => {
    const el = caja.current;
    if (el) pegado.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  };

  return (
    <div ref={caja} onScroll={alDesplazar} className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
      {data ? (
        <div className="mx-auto w-full max-w-3xl space-y-8 px-4 py-6">
          {lista.map((t) => <TurnoVista key={t.run} t={t} vivo={vivo} nombre={asistente.name} onWiki={onWiki} ahora={ahora} />)}
          <div ref={fin} />
        </div>
      ) : (
      <div className="flex min-h-full flex-col items-center justify-center px-4 py-10 text-center">
        <div className="grid size-12 place-items-center rounded-2xl bg-primary/12 font-mono text-lg font-semibold text-primary">{asistente.name[0]}</div>
        <h2 className="mt-4 text-xl font-semibold tracking-tight">¿En qué te ayudo?</h2>
        <p className="mt-1 text-sm text-muted-foreground">{asistente.name} · {asistente.hint}</p>
        {asistente.quick.length > 0 && (
          <div className="mt-6 grid w-full max-w-xl gap-2 sm:grid-cols-2">
            {asistente.quick.map(({ label, icon: Icon, text }) => (
              <button key={label} type="button" onClick={() => onSugerencia(text)}
                className="flex items-start gap-2.5 rounded-2xl border border-border px-3.5 py-3 text-left text-sm transition-colors hover:bg-muted">
                <Icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />{label}
              </button>
            ))}
          </div>
        )}
      </div>
      )}
    </div>
  );
}
