"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ExternalLink, Mic, SendHorizontal, Square, X, Zap } from "lucide-react";
import { api, post, upload } from "@/lib/api";
import type { TranscriptItem } from "@/lib/types";
import { Button } from "@/components/ui/button";
import type { Assistant } from "./assistants";
import { Markdown } from "./markdown";
import { usePanel } from "./shell";
import { AvatarAsistente } from "./avatar-asistente";

type Page = { items: TranscriptItem[] };
type MainState = { current_run: string | null; queued: number; tmux: boolean | null };

/** El asistente del apartado en el que estás. Cada uno tiene su conversación; en Inicio, Jarvis general. */
export function JarvisDock({ assistant, onClose }: { assistant: Assistant; onClose?: () => void }) {
  const { lastEvent } = usePanel();
  const [items, setItems] = useState<TranscriptItem[]>([]);
  const [state, setState] = useState<MainState | null>(null);
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const end = useRef<HTMLDivElement>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const [voice, setVoice] = useState<"idle" | "recording" | "transcribing">("idle");

  const toggleVoice = async () => {
    if (voice === "recording") {
      recorder.current?.stop();
      return;
    }
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const chunks: Blob[] = [];
      const rec = new MediaRecorder(stream);
      recorder.current = rec;
      rec.ondataavailable = (e) => chunks.push(e.data);
      rec.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        setVoice("transcribing");
        try {
          const r = await upload<{ text: string }>("/voice/transcribe", new Blob(chunks, { type: rec.mimeType }));
          setText((t) => [t, r.text].filter(Boolean).join(" "));
        } catch (e) {
          setError(e instanceof Error ? e.message : String(e));
        } finally {
          setVoice("idle");
        }
      };
      rec.start();
      setVoice("recording");
    } catch {
      setError("No se pudo usar el micrófono: revisa el permiso.");
    }
  };

  const load = useCallback(async () => {
    try {
      const [p, s] = await Promise.all([api<Page>(`${assistant.base}/messages`), api<MainState>(`${assistant.base}/state`)]);
      setItems(p.items);
      setState(s);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [assistant.base]);

  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    if (lastEvent?.type === "chat.updated" || lastEvent?.type.startsWith("run.")) {
      void load();
    }
  }, [lastEvent, load]);

  const messages = useMemo(() => items.filter((i) => i.kind === "message" && i.role !== "system").slice(-12), [items]);
  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
  }, [messages.length]);

  const busy = Boolean(state?.current_run);
  const send = async (t: string) => {
    if (!t.trim()) return;
    setText("");
    setError(null);
    try {
      await post(`${assistant.base}/messages`, { text: t.trim() });
      await load();
    } catch (e) {
      setText(t);
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-2 border-b border-border px-4 py-3">
        <AvatarAsistente asistente={assistant} tam="md" />
        <div className="min-w-0 flex-1 leading-tight">
          <div className="text-sm font-semibold">{assistant.name}</div>
          <div className="text-[11px] text-muted-foreground">{busy ? "Trabajando…" : state?.tmux === false ? "Sin conexión" : assistant.hint}</div>
        </div>
        {!assistant.key && <Link href="/conversaciones/" aria-label="Pantalla completa e historial de conversaciones" title="Pantalla completa e historial" className="grid size-8 place-items-center rounded-lg text-muted-foreground hover:bg-muted"><ExternalLink className="size-4" /></Link>}
        {onClose && <Button variant="ghost" size="icon-sm" aria-label="Cerrar" onClick={onClose}><X /></Button>}
      </div>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
        {messages.map((m) => (
          <div key={m.uuid} className={m.role === "user" ? "ml-6 rounded-xl bg-primary/10 px-3 py-2 text-sm" : "mr-2 rounded-xl bg-muted px-3 py-2 text-sm"}>
            <Markdown source={m.text} onWiki={() => {}} imageSrc={(name) => name} />
          </div>
        ))}
        {messages.length === 0 && !error && <p className="text-sm text-muted-foreground">{assistant.key ? `Pregúntame lo que necesites sobre ${assistant.name.toLowerCase()}.` : "Aún no hay mensajes en esta sesión."}</p>}
        <div ref={end} />
      </div>

      <div className="border-t border-border p-3">
        <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-muted-foreground"><Zap className="size-3.5" />Acciones rápidas</div>
        <div className="mb-3 grid gap-1.5">
          {assistant.quick.map(({ label, icon: Icon, text: t }) => (
            <button key={label} type="button" disabled={busy} onClick={() => void send(t)} className="flex min-h-9 items-center gap-2 rounded-lg border border-border px-2.5 text-left text-xs hover:bg-muted disabled:opacity-50">
              <Icon className="size-3.5 shrink-0 text-muted-foreground" />{label}
            </button>
          ))}
        </div>
        {error && <p role="alert" className="mb-2 text-xs text-destructive">{error}</p>}
        <form
          className="flex items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            void send(text);
          }}
        >
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send(text);
              }
            }}
            rows={2}
            maxLength={4000}
            aria-label={`Mensaje para ${assistant.name}`}
            placeholder={`Escribe a ${assistant.name}…`}
            className="min-w-0 flex-1 resize-none rounded-lg border border-input bg-transparent px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
          <Button type="button" variant={voice === "recording" ? "destructive" : "outline"} size="icon" disabled={voice === "transcribing"} aria-pressed={voice === "recording"} aria-label={voice === "recording" ? "Terminar de grabar" : voice === "transcribing" ? "Transcribiendo" : "Dictar"} onClick={() => void toggleVoice()}><Mic /></Button>
          {busy ? (
            <Button type="button" variant="outline" size="icon" aria-label="Interrumpir" onClick={() => void post(`${assistant.base}/interrupt`)}><Square /></Button>
          ) : (
            <Button type="submit" size="icon" aria-label="Enviar" disabled={!text.trim()}><SendHorizontal /></Button>
          )}
        </form>
      </div>
    </div>
  );
}
