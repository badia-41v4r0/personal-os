"use client";

import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { ArrowUp, Loader2, Mic, Paperclip, Square } from "lucide-react";
import { cn } from "cn";
import { upload } from "@/lib/api";
import { AttachmentChips, DropOverlay, MAX_FILES, pasteFiles, useAttachments } from "../attachments";

export type CompositorRef = { focus: () => void; setTexto: (t: string) => void };

type Props = {
  placeholder: string;
  ocupada: boolean;
  /** Devuelve true si se envió (entonces se vacía el cuadro). */
  onEnviar: (texto: string, archivos: File[]) => Promise<boolean>;
  onParar: () => void;
  onError: (msg: string) => void;
  compacta?: boolean;
  onFocus?: () => void;
};

/** Dictado: graba con el micro y lo transcribe el Whisper local (/voice/transcribe). */
function useVoz(añadir: (t: string) => void, onError: (m: string) => void) {
  const rec = useRef<MediaRecorder | null>(null);
  const [estado, setEstado] = useState<"idle" | "recording" | "transcribing">("idle");
  const alternar = async () => {
    if (estado === "recording") {
      rec.current?.stop();
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const trozos: Blob[] = [];
      const r = new MediaRecorder(stream);
      rec.current = r;
      r.ondataavailable = (e) => trozos.push(e.data);
      r.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        setEstado("transcribing");
        try {
          añadir((await upload<{ text: string }>("/voice/transcribe", new Blob(trozos, { type: r.mimeType }))).text);
        } catch (e) {
          onError(e instanceof Error ? e.message : String(e));
        } finally {
          setEstado("idle");
        }
      };
      r.start();
      setEstado("recording");
    } catch {
      onError("No se pudo usar el micrófono: revisa el permiso.");
    }
  };
  return { estado, alternar };
}

export const Compositor = forwardRef<CompositorRef, Props>(function Compositor({ placeholder, ocupada, onEnviar, onParar, onError, compacta, onFocus }, ref) {
  const [texto, setTexto] = useState("");
  const [enviando, setEnviando] = useState(false);
  const area = useRef<HTMLTextAreaElement>(null);
  const att = useAttachments(onError);
  const voz = useVoz((t) => setTexto((x) => [x.trim(), t].filter(Boolean).join(" ")), onError);
  useImperativeHandle(ref, () => ({ focus: () => area.current?.focus(), setTexto }), []);

  // Crece con el texto hasta un tope; luego hace scroll
  useEffect(() => {
    const el = area.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, compacta ? 120 : 240)}px`;
  }, [texto, compacta]);

  const enviar = async () => {
    const t = texto.trim();
    if ((!t && att.files.length === 0) || enviando || ocupada) return;
    setEnviando(true);
    try {
      if (await onEnviar(t, att.files)) {
        setTexto("");
        att.clear();
      }
    } finally {
      setEnviando(false);
    }
  };

  const vacio = !texto.trim() && att.files.length === 0;
  const icono = "grid size-9 shrink-0 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:pointer-events-none disabled:opacity-40";
  return (
    <form
      className={cn("relative rounded-3xl", compacta ? "px-1 py-1" : "border border-border bg-background px-3 pt-2.5 pb-2 shadow-sm transition-shadow focus-within:border-ring/60 focus-within:shadow-md")}
      {...att.dropProps(false)}
      onSubmit={(e) => {
        e.preventDefault();
        void enviar();
      }}
    >
      <DropOverlay a={att} />
      <div className={cn(att.files.length > 0 && "px-1 pt-1")}><AttachmentChips a={att} disabled={enviando} /></div>
      <div className={cn("flex gap-1", compacta ? "items-end" : "flex-col")}>
        <textarea
          ref={area}
          value={texto}
          onChange={(e) => setTexto(e.target.value)}
          onFocus={onFocus}
          onPaste={pasteFiles(att)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              void enviar();
            }
          }}
          rows={1}
          maxLength={20000}
          placeholder={placeholder}
          aria-label={placeholder}
          className={cn("min-w-0 flex-1 resize-none bg-transparent text-sm leading-6 outline-none placeholder:text-muted-foreground", compacta ? "self-center px-2 py-1.5" : "px-1.5 py-1")}
        />
        <div className={cn("flex items-center gap-0.5", !compacta && "justify-between")}>
          <div className="flex items-center gap-0.5">
            <label title="Adjuntar archivos (también puedes arrastrarlos o pegarlos)" className={cn(icono, "cursor-pointer has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring", att.files.length >= MAX_FILES && "pointer-events-none opacity-40")}>
              <Paperclip className="size-4" />
              <span className="sr-only">Adjuntar archivos</span>
              <input type="file" multiple className="sr-only" disabled={att.files.length >= MAX_FILES} onChange={(e) => { att.add(e.target.files); e.target.value = ""; }} />
            </label>
            <button type="button" className={cn(icono, voz.estado === "recording" && "bg-destructive/15 text-destructive hover:bg-destructive/20")} disabled={voz.estado === "transcribing"}
              aria-pressed={voz.estado === "recording"} aria-label={voz.estado === "recording" ? "Terminar de dictar" : voz.estado === "transcribing" ? "Transcribiendo" : "Dictar"}
              title={voz.estado === "recording" ? "Terminar de dictar" : "Dictar"} onClick={() => void voz.alternar()}>
              {voz.estado === "transcribing" ? <Loader2 className="size-4 animate-spin" /> : <Mic className="size-4" />}
            </button>
          </div>
          {ocupada ? (
            <button type="button" onClick={onParar} aria-label="Parar la respuesta" title="Parar" className="grid size-9 shrink-0 place-items-center rounded-full bg-foreground text-background hover:opacity-85">
              <Square className="size-3.5 fill-current" />
            </button>
          ) : (
            <button type="submit" disabled={vacio || enviando} aria-label="Enviar" title="Enviar (Intro)" className="grid size-9 shrink-0 place-items-center rounded-full bg-primary text-primary-foreground transition-opacity hover:opacity-90 disabled:bg-muted disabled:text-muted-foreground">
              {enviando ? <Loader2 className="size-4 animate-spin" /> : <ArrowUp className="size-4" />}
            </button>
          )}
        </div>
      </div>
    </form>
  );
});
