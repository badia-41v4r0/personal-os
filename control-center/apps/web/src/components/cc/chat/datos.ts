"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { usePanel } from "../shell";

export type Conversacion = { id: string; asistente: string; titulo: string; estado: string; creada: string; actividad: string; mensajes: number | null };
export type Mensaje = { id: number; rol: "user" | "assistant" | "tool"; texto: string; run_id: string | null; ts: string };
export type Respuesta = { id: string; estado: "queued" | "running" | "done" | "error" | "interrupted"; inicio: string | null; fin: string | null; creada: string; error: string };
export type Detalle = { conversacion: Conversacion; mensajes: Mensaje[]; respuestas: Respuesta[] };
/** Lo que llega en directo de la respuesta en curso (se pierde al recargar: lo guardado sale de la base). */
export type EnDirecto = { run: string; texto: string; pasos: string[] };

/** Un turno: lo que dijiste, los pasos que dio y lo que respondió. */
export type Turno = { run: string; pregunta: Mensaje | null; pasos: string[]; respuesta: Mensaje | null; estado: Respuesta | null };

export function turnos(d: Detalle): Turno[] {
  const out: Turno[] = [];
  const porRun = new Map<string, Turno>();
  const estados = new Map(d.respuestas.map((r) => [r.id, r]));
  for (const m of d.mensajes) {
    const run = m.run_id ?? `m${m.id}`;
    let t = porRun.get(run);
    if (!t || (m.rol === "user" && t.pregunta)) {
      t = { run, pregunta: null, pasos: [], respuesta: null, estado: estados.get(run) ?? null };
      porRun.set(run, t);
      out.push(t);
    }
    if (m.rol === "user") t.pregunta = m;
    else if (m.rol === "tool") t.pasos.push(m.texto);
    else t.respuesta = t.respuesta ? { ...m, texto: `${t.respuesta.texto}\n\n${m.texto}` } : m;
  }
  return out;
}

/** El mensaje del usuario sin la lista de adjuntos que le añade el backend, y los nombres de esos adjuntos. */
export function sinAdjuntos(texto: string): { texto: string; adjuntos: string[] } {
  const i = texto.indexOf("\n\n📎 Adjuntos");
  if (i < 0) return { texto, adjuntos: [] };
  const adjuntos = texto.slice(i).split("\n").filter((l) => l.startsWith("- ")).map((l) => l.slice(2).split("/").pop() ?? l);
  const t = texto.slice(0, i).trim();
  return { texto: t === "Te adjunto estos archivos." ? "" : t, adjuntos };
}

export const ocupada = (d: Detalle | null) => !!d?.respuestas.some((r) => r.estado === "queued" || r.estado === "running");

/** La conversación abierta, al día: se recarga con cada evento de sus respuestas y acumula el texto en directo. */
export function useConversacion(cid: string | null, onTermina?: (cid: string, estado: string) => void) {
  const { subscribe } = usePanel();
  const [data, setData] = useState<Detalle | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [vivo, setVivo] = useState<EnDirecto | null>(null);

  const load = useCallback(async () => {
    if (!cid) return;
    try {
      const d = await api<Detalle>(`/conversaciones/${cid}`);
      setData((cur) => (cur === null || cur.conversacion.id === cid ? d : cur));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [cid]);

  useEffect(() => {
    setData(null);
    setVivo(null);
    setError(null);
    void load();
  }, [load]);

  useEffect(() => {
    if (!cid) return;
    return subscribe((e) => {
      if (e.payload?.session_id !== cid) return;
      const run = String(e.payload.run_id ?? "");
      if (e.type === "session.delta") {
        setVivo((v) => ({ run, texto: (v?.run === run ? v.texto : "") + String(e.payload.text ?? ""), pasos: v?.run === run ? v.pasos : [] }));
      } else if (e.type === "session.tool") {
        const paso = `${e.payload.tool ?? ""} ${e.payload.input ?? ""}`.trim();
        // el texto previo a una herramienta («voy a mirar…») se queda como paso: la respuesta empieza después
        setVivo((v) => ({ run, texto: "", pasos: [...(v?.run === run ? v.pasos : []), paso] }));
      } else if (e.type.startsWith("run.")) {
        if (e.type === "run.finished" || e.type === "run.interrupted") {
          setVivo(null);
          onTermina?.(cid, String(e.payload.status ?? e.type));
        }
        void load();
      }
    });
  }, [cid, subscribe, load, onTermina]);

  return { data, error, vivo, reload: load, setData };
}
