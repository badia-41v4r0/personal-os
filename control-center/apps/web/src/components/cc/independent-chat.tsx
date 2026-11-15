"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Bot, CircleStop, Download, Folder, Globe, Library, Loader2, Send, Wrench } from "lucide-react";
import { AttachButton, AttachmentChips, DropOverlay, pasteFiles, useAttachments } from "./attachments";
import { cn } from "cn";
import { usePanel } from "./shell";
import { Empty, ErrorState, Loading } from "./states";
import type { SessionSummary } from "./new-session";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { api, post } from "@/lib/api";
import { clock } from "@/lib/format";
import { useApi } from "@/lib/hooks";

type Msg = { id: number; role: "user" | "assistant" | "tool" | "system"; content: string; run_id: string | null; created_at: string };
type WFile = { name: string; path: string; dir: boolean; size: number; mtime: number };
type Run = { id: string; status: string; created_at: string; tools_used: string[]; error: string };

const RUN: Record<string, string> = { queued: "en cola", running: "en curso", done: "hecha", error: "error", interrupted: "interrumpida" };

export function IndependentChat({ session, onChanged }: { session: SessionSummary; onChanged: () => void }) {
  const { subscribe } = usePanel();
  const [msgs, setMsgs] = useState<Msg[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [live, setLive] = useState<{ run: string; text: string; tools: string[] } | null>(null);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const att = useAttachments(setError);
  const runs = useApi<Run[]>(`/agents/runs?session_id=${session.id}&limit=20`);
  const [dir, setDir] = useState("");
  const files = useApi<{ path: string; items: WFile[] }>(`/sessions/${session.id}/files?path=${encodeURIComponent(dir)}`);
  const bottom = useRef<HTMLDivElement>(null);
  const sid = session.id;

  const load = useCallback(async () => {
    try {
      setMsgs(await api<Msg[]>(`/sessions/${sid}/messages`));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [sid]);

  useEffect(() => {
    setMsgs(null);
    setLive(null);
    load();
  }, [load]);

  useEffect(
    () =>
      subscribe((e) => {
        if (e.payload?.session_id !== sid) return;
        const run = String(e.payload.run_id);
        if (e.type === "session.delta") {
          setLive((l) => {
            const same = l !== null && l.run === run;
            return { run, text: (same ? l.text : "") + String(e.payload.text), tools: same ? l.tools : [] };
          });
        } else if (e.type === "session.tool") {
          setLive((l) => {
            const same = l !== null && l.run === run;
            return { run, text: same ? l.text : "", tools: [...(same ? l.tools : []), `${e.payload.tool} ${e.payload.input ?? ""}`] };
          });
        } else if (e.type === "run.finished" || e.type === "run.started" || e.type === "run.queued") {
          if (e.type === "run.finished") {
            setLive(null);
            load();
            onChanged();
            files.reload();
          }
          runs.reload();
        }
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [sid, subscribe, load],
  );

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" });
  }, [msgs?.length, live?.text]);

  const busy = !!live || (runs.data ?? []).some((r) => r.status === "running" || r.status === "queued");
  const archived = session.status === "archived";

  const send = async () => {
    const t = text.trim();
    if (!t && att.files.length === 0) return;
    setSending(true);
    try {
      const names = await att.uploadAll(`/sessions/${sid}/upload`, "name");
      await post(`/sessions/${sid}/messages`, { text: t, attachments: names });
      setText("");
      att.clear();
      setError(null);
      await load();
      files.reload();
      runs.reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSending(false);
    }
  };

  const p = session.permissions;
  return (
    <>
      <section className="relative flex min-h-0 flex-col" {...att.dropProps(archived)}>
        <DropOverlay a={att} />
        <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-2.5">
          <div className="min-w-0">
            <div className="truncate text-sm font-medium">{session.name}</div>
            <div className="truncate text-[11px] text-muted-foreground">{session.description || "Conversación independiente"}</div>
          </div>
          {busy && <Button variant="destructive" size="sm" onClick={() => post(`/sessions/${sid}/interrupt`).then(() => runs.reload())}><CircleStop /> Interrumpir</Button>}
        </div>
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-4">
          {error && <ErrorState message={error} />}
          {!msgs && !error && <Loading rows={4} />}
          {msgs?.length === 0 && !live && <Empty message="Escribe el primer mensaje. Cada respuesta se ejecuta en un contenedor aislado." />}
          {msgs?.map((m) =>
            m.role === "tool" ? (
              <div key={m.id} className="flex items-center gap-1.5 pl-1 font-mono text-[11px] text-muted-foreground"><Wrench className="size-3" /> {m.content.replace(/^\/trabajo\//, "")}</div>
            ) : (
              <div key={m.id} className={cn("flex flex-col gap-1", m.role === "user" ? "items-end" : "items-start")}>
                <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
                  {m.role === "assistant" && <Bot className="size-3" />}{m.role === "user" ? "Tú" : "Asistente"}<span>{clock(m.created_at)}</span>
                </div>
                <div className={cn("max-w-[min(42rem,92%)] rounded-xl px-3.5 py-2.5 text-sm leading-relaxed whitespace-pre-wrap break-words",
                  m.role === "user" ? "bg-primary/12 ring-1 ring-primary/20" : "bg-card ring-1 ring-border")}>{m.content}</div>
              </div>
            ),
          )}
          {live && (
            <div className="flex flex-col items-start gap-1">
              {live.tools.map((t, i) => <div key={i} className="flex items-center gap-1.5 pl-1 font-mono text-[11px] text-muted-foreground"><Wrench className="size-3" /> {t}</div>)}
              <div className="max-w-[min(42rem,92%)] rounded-xl bg-card px-3.5 py-2.5 text-sm leading-relaxed whitespace-pre-wrap ring-1 ring-border">
                {live.text || <span className="flex items-center gap-2 text-muted-foreground"><Loader2 className="size-3.5 animate-spin" /> Pensando…</span>}
              </div>
            </div>
          )}
          {!live && busy && <div className="flex items-center gap-2 pl-1 text-xs text-muted-foreground"><Loader2 className="size-3.5 animate-spin" /> Arrancando el contenedor…</div>}
          <div ref={bottom} />
        </div>
        <form className="border-t border-border p-3" onSubmit={(e) => { e.preventDefault(); send(); }}>
          <AttachmentChips a={att} disabled={sending} />
          <Textarea value={text} onChange={(e) => setText(e.target.value)} disabled={archived}
            onPaste={pasteFiles(att)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
            placeholder={archived ? "Conversación archivada" : "Escribe… (Intro para enviar)"} rows={2} maxLength={20000} className="resize-none" aria-label="Mensaje" />
          <div className="mt-2 flex items-center justify-between gap-2">
            <AttachButton a={att} disabled={archived || sending} />
            <Button type="submit" size="sm" disabled={sending || (!text.trim() && att.files.length === 0) || archived}>
              {sending ? <Loader2 className="animate-spin" /> : <Send />} {sending && att.files.length ? "Subiendo…" : "Enviar"}</Button>
          </div>
        </form>
      </section>

      <aside className="hidden space-y-5 overflow-y-auto border-l border-border p-4 text-sm xl:block">
        <section>
          <h2 className="mb-2 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">Configuración</h2>
          <dl className="space-y-1.5 text-xs">
            <div className="flex justify-between gap-2"><dt className="text-muted-foreground">Modelo</dt><dd>{session.model}</dd></div>
            <div className="flex justify-between gap-2"><dt className="text-muted-foreground">Permisos</dt><dd><Badge variant="outline">{p?.level ?? "read"}</Badge></dd></div>
            <div className="flex justify-between gap-2"><dt className="flex items-center gap-1 text-muted-foreground"><Globe className="size-3" /> Internet</dt><dd>{p?.internet ? "sí" : "no"}</dd></div>
            <div className="flex justify-between gap-2"><dt className="flex items-center gap-1 text-muted-foreground"><Library className="size-3" /> Vault</dt><dd>{p?.vault ? "solo lectura" : "no"}</dd></div>
            <div className="flex justify-between gap-2"><dt className="text-muted-foreground">Tiempo máx.</dt><dd>{p?.minutes ?? 30} min</dd></div>
            <div><dt className="flex items-center gap-1 text-muted-foreground"><Folder className="size-3" /> Carpeta</dt><dd className="truncate font-mono text-[10px]" title={session.workdir}>{session.workdir}</dd></div>
            {session.agent_id && <div className="flex justify-between gap-2"><dt className="text-muted-foreground">Agente</dt><dd>{session.agent_id}</dd></div>}
            <div className="flex justify-between gap-2"><dt className="text-muted-foreground">Subagentes</dt><dd>{session.permissions?.subagents ? "sí" : "no"}</dd></div>
            <div className="flex justify-between gap-2"><dt className="text-muted-foreground">Ordenador virtual</dt><dd>
              {!p?.vc?.enabled ? "ninguno" : p.vc.vc_id ? <a href={`/virtual-computers/?v=${p.vc.vc_id}`} className="text-primary hover:underline">{p.vc.profile} · ver</a> : `a petición (${p.vc.profile})`}
            </dd></div>
          </dl>
          {p?.system_prompt && <details className="mt-2 text-xs"><summary className="cursor-pointer text-muted-foreground">Instrucciones</summary><p className="mt-1 whitespace-pre-wrap">{p.system_prompt}</p></details>}
          <Button variant="ghost" size="xs" className="mt-3" onClick={() => api(`/sessions/${sid}`, { method: "PATCH", body: JSON.stringify({ archived: !archived }) }).then(onChanged)}>
            {archived ? "Desarchivar" : "Archivar"}
          </Button>
        </section>
        <section>
          <h2 className="mb-2 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">Archivos</h2>
          {dir && <button onClick={() => setDir(dir.split("/").slice(0, -1).join("/"))} className="mb-1 text-xs text-primary hover:underline">← {dir}</button>}
          {files.data?.items.length === 0 && <p className="text-xs text-muted-foreground">Su carpeta está vacía.</p>}
          <ul className="space-y-1 text-xs">
            {files.data?.items.map((f) => (
              <li key={f.path} className="flex min-w-0 items-center justify-between gap-2">
                {f.dir ? <button onClick={() => setDir(f.path)} className="flex min-w-0 items-center gap-1.5 py-0.5 hover:text-primary"><Folder className="size-3 shrink-0" /><span className="truncate">{f.name}</span></button>
                  : <a href={`/api/v1/sessions/${sid}/download?path=${encodeURIComponent(f.path)}`} className="flex min-w-0 items-center gap-1.5 py-0.5 hover:text-primary" title="Descargar"><Download className="size-3 shrink-0" /><span className="truncate">{f.name}</span></a>}
                {!f.dir && <span className="shrink-0 text-muted-foreground">{f.size < 1024 ? `${f.size} B` : `${(f.size / 1024).toFixed(0)} KB`}</span>}
              </li>
            ))}
          </ul>
        </section>
        <section>
          <h2 className="mb-2 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">Ejecuciones</h2>
          <ul className="space-y-1.5">
            {runs.data?.map((r) => (
              <li key={r.id} className="text-xs">
                <div className="flex justify-between"><span className="font-mono text-muted-foreground">{r.id.slice(0, 8)}</span>
                  <span className={cn(r.status === "error" && "text-destructive", r.status === "done" && "text-success")}>{RUN[r.status] ?? r.status}</span></div>
                {r.tools_used.length > 0 && <div className="text-muted-foreground">{r.tools_used.join(", ")}</div>}
                {r.error && <div className="truncate text-destructive/80" title={r.error}>{r.error}</div>}
              </li>
            ))}
          </ul>
        </section>
      </aside>
    </>
  );
}
