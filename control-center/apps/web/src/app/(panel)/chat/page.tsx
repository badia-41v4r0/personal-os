"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Bot, ChevronRight, CircleStop, FileText, Loader2, Search, Send, Wrench } from "lucide-react";
import { cn } from "cn";
import { usePanel } from "@/components/cc/shell";
import { StatusDot } from "@/components/cc/status";
import { Empty, ErrorState, Loading } from "@/components/cc/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { api, post } from "@/lib/api";
import { clock, timeAgo } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { TranscriptItem } from "@/lib/types";
import { IndependentChat } from "@/components/cc/independent-chat";
import { AttachButton, AttachmentChips, DropOverlay, pasteFiles, useAttachments } from "@/components/cc/attachments";
import { NewSessionDialog, type SessionSummary } from "@/components/cc/new-session";
import { asistente } from "@/lib/asistente";

type Page = { items: TranscriptItem[]; next_offset: number; claude_session_id: string | null };
type Transcript = { claude_session_id: string; mtime: number; size: number };
type Run = { id: string; status: string; created_at: string; started_at: string | null; ended_at: string | null; tools_used: string[]; error: string };
type MainState = { current_run: string | null; queued: number; tmux: boolean | null };

const CHANNEL: Record<string, { label: string; cls: string }> = {
  telegram: { label: "Telegram", cls: "text-sky-300 border-sky-400/30" },
  web: { label: "Panel", cls: "text-primary border-primary/30" },
  voz: { label: "Voz", cls: "text-violet-300 border-violet-400/30" },
  video: { label: "Vídeo", cls: "text-pink-300 border-pink-400/30" },
  sistema: { label: "Sistema", cls: "text-muted-foreground border-border" },
  "sesión": { label: "Sesión", cls: "text-muted-foreground border-border" },
};

const RUN_STATUS: Record<string, string> = {
  queued: "en cola", running: "en curso", done: "hecha", error: "error", interrupted: "interrumpida",
};

function ChannelBadge({ channel }: { channel: string }) {
  const c = CHANNEL[channel] ?? CHANNEL.sistema;
  return <Badge variant="outline" className={cn("h-5 px-1.5 text-[10px] font-normal", c.cls)}>{c.label}</Badge>;
}

function shortInput(i: TranscriptItem): string {
  const v = i.tool_input.file_path ?? i.tool_input.command ?? i.tool_input.pattern ?? i.tool_input.description ?? "";
  return v.replace(/^\/vault\//, "").slice(0, 90);
}

/** Agrupa llamadas a herramientas seguidas en una sola línea plegable. */
type Block = { type: "msg"; item: TranscriptItem } | { type: "tools"; items: TranscriptItem[] } | { type: "thinking"; ts: string };

function toBlocks(items: TranscriptItem[]): Block[] {
  const out: Block[] = [];
  for (const it of items) {
    if (it.kind === "tool_result" || it.kind === "turn_end") continue;
    if (it.kind === "tool_call") {
      const last = out.at(-1);
      if (last?.type === "tools") last.items.push(it);
      else out.push({ type: "tools", items: [it] });
    } else if (it.kind === "thinking") {
      if (out.at(-1)?.type !== "thinking") out.push({ type: "thinking", ts: it.ts });
    } else {
      out.push({ type: "msg", item: it });
    }
  }
  return out;
}

function ToolsBlock({ items }: { items: TranscriptItem[] }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="pl-1">
      <button onClick={() => setOpen(!open)} className="flex items-center gap-1.5 py-1 text-xs text-muted-foreground hover:text-foreground" aria-expanded={open}>
        <ChevronRight className={cn("size-3 transition-transform", open && "rotate-90")} />
        <Wrench className="size-3" />
        {items.length === 1 ? `${items[0].tool.replace(/^mcp__plugin_\w+__/, "")} ${shortInput(items[0])}` : `${items.length} herramientas`}
      </button>
      {open && (
        <ul className="mt-1.5 space-y-1 border-l border-border pl-3">
          {items.map((t) => (
            <li key={t.uuid} className="font-mono text-[11px] text-muted-foreground">
              <span className="text-foreground/80">{t.tool.replace(/^mcp__plugin_\w+__/, "")}</span> {shortInput(t)}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Bubble({ item }: { item: TranscriptItem }) {
  const mine = item.role === "user";
  const system = item.role === "system";
  return (
    <div className={cn("flex flex-col gap-1", mine ? "items-end" : "items-start")}>
      <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
        {!mine && !system && <Bot className="size-3" />}
        <span>{mine ? "Tú" : system ? "Orden programada" : `${asistente()}`}</span>
        <ChannelBadge channel={item.channel} />
        <span>{clock(item.ts)}</span>
      </div>
      <div
        className={cn(
          "max-w-[min(42rem,92%)] rounded-xl px-3.5 py-2.5 text-sm leading-relaxed whitespace-pre-wrap break-words",
          mine && "bg-primary/12 ring-1 ring-primary/20",
          system && "bg-muted/50 text-muted-foreground text-xs",
          !mine && !system && "bg-card ring-1 ring-border",
        )}
      >
        {item.text}
      </div>
    </div>
  );
}

export default function ChatPage() {
  const { lastEvent } = usePanel();
  const sessionsList = useApi<SessionSummary[]>("/sessions");
  const [active, setActive] = useState<string>("main");
  useEffect(() => {
    const s = new URLSearchParams(window.location.search).get("s");
    if (s) setActive(s);
  }, []);
  const choose = (id: string) => {
    setActive(id);
    window.history.replaceState(null, "", id === "main" ? "/chat/" : `/chat/?s=${id}`);
  };
  const independent = (sessionsList.data ?? []).filter((x) => x.kind === "independent");
  const current = independent.find((x) => x.id === active);
  const transcripts = useApi<Transcript[]>("/sessions/main/transcripts");
  const [selected, setSelected] = useState<string | null>(null);
  const [page, setPage] = useState<Page | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [tg, setTg] = useState(false);
  const [sending, setSending] = useState(false);
  const att = useAttachments(setError);
  const [filter, setFilter] = useState("");
  const state = useApi<MainState>("/sessions/main/state", 5000);
  const runs = useApi<Run[]>("/agents/runs?session_id=main&limit=15");
  const bottom = useRef<HTMLDivElement>(null);
  const following = selected === null;

  const load = useCallback(async () => {
    try {
      const q = selected ? `?claude_session_id=${selected}&limit=1000` : "?limit=1000";
      setPage(await api<Page>(`/sessions/main/messages${q}`));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [selected]);

  useEffect(() => {
    setPage(null);
    load();
  }, [load]);

  // Tiempo real: el backend avisa cuando el JSONL crece; pedimos solo lo nuevo
  useEffect(() => {
    if (!lastEvent) return;
    if (lastEvent.type.startsWith("run.")) {
      runs.reload();
      state.reload();
    }
    if (lastEvent.type !== "chat.updated" || !following) return;
    const sid = lastEvent.payload.claude_session_id as string;
    if (!page || sid !== page.claude_session_id) {
      load();
      transcripts.reload();
      return;
    }
    api<Page>(`/sessions/main/messages?claude_session_id=${sid}&offset=${page.next_offset}&limit=1000`).then((p) =>
      setPage((cur) => (cur && cur.claude_session_id === sid ? { ...p, items: [...cur.items, ...p.items] } : cur)),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastEvent]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" });
  }, [page?.items.length]);

  const blocks = useMemo(() => {
    const items = page?.items ?? [];
    const f = filter.trim().toLowerCase();
    return toBlocks(f ? items.filter((i) => i.text.toLowerCase().includes(f)) : items);
  }, [page, filter]);

  const toolStats = useMemo(() => {
    const m = new Map<string, number>();
    page?.items.filter((i) => i.kind === "tool_call").forEach((i) => {
      const k = i.tool.replace(/^mcp__plugin_\w+__/, "");
      m.set(k, (m.get(k) ?? 0) + 1);
    });
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  }, [page]);

  const files = useMemo(
    () => [...new Set(page?.items.filter((i) => i.tool_input.file_path).map((i) => i.tool_input.file_path.replace(/^\/vault\//, "")) ?? [])].slice(-12).reverse(),
    [page],
  );

  const send = async () => {
    const t = text.trim();
    if (!t && att.files.length === 0) return;
    setSending(true);
    try {
      const paths = await att.uploadAll("/sessions/main/upload", "path");
      await post("/sessions/main/messages", { text: t, telegram: tg, attachments: paths });
      setText("");
      att.clear();
      runs.reload();
      state.reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSending(false);
    }
  };

  const interrupt = async () => {
    try {
      await post("/sessions/main/interrupt");
      runs.reload();
      state.reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const busy = !!state.data?.current_run || (state.data?.queued ?? 0) > 0;

  return (
    <div className="-m-4 grid h-[calc(100dvh-3rem)] grid-cols-1 grid-rows-[auto_1fr] md:-m-6 lg:h-dvh lg:grid-cols-[15rem_1fr] lg:grid-rows-1 xl:grid-cols-[15rem_1fr_18rem]">
      {/* Móvil: selector de conversación (la columna izquierda solo se ve en pantallas grandes) */}
      <div className="flex items-center gap-2 border-b border-border p-2 lg:hidden">
        <select value={active} onChange={(e) => choose(e.target.value)} aria-label="Conversación"
          className="h-8 min-w-0 flex-1 rounded-lg border border-input bg-transparent px-2 text-sm dark:bg-input/30">
          <option value="main">{asistente()} · compartida</option>
          {independent.filter((x) => x.status !== "archived" || x.id === active).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
        </select>
        <div className="w-44 shrink-0"><NewSessionDialog onCreated={(x) => { sessionsList.reload(); choose(x.id); }} /></div>
      </div>

      {/* Izquierda: sesiones e historial */}
      <aside className="hidden flex-col gap-4 overflow-y-auto border-r border-border p-3 lg:flex">
        <div className="relative">
          <Search className="absolute top-2 left-2.5 size-3.5 text-muted-foreground" />
          <Input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Buscar en la conversación" className="h-8 pl-8 text-xs" aria-label="Buscar en la conversación" />
        </div>
        <div>
          <div className="mb-1.5 px-1 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">Sesiones</div>
          <button onClick={() => choose("main")} className={cn("flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-sm hover:bg-sidebar-accent", active === "main" && "bg-sidebar-accent")}>
            <StatusDot level={state.data?.tmux ? "ok" : state.data?.tmux === false ? "down" : "unknown"} pulse />
            <span className="truncate">{asistente()} · compartida</span>
          </button>
          <div className="mt-1 space-y-0.5">
            {independent.filter((x) => x.status !== "archived" || x.id === active).map((x) => (
              <button key={x.id} onClick={() => choose(x.id)} className={cn("flex w-full items-center justify-between gap-2 rounded-lg px-2.5 py-1.5 text-left text-sm hover:bg-sidebar-accent", active === x.id && "bg-sidebar-accent")}>
                <span className="flex min-w-0 items-center gap-2">
                  <StatusDot level={x.status === "running" ? "warn" : x.status === "archived" ? "unknown" : "ok"} />
                  <span className="truncate">{x.name}</span>
                </span>
                <span className="shrink-0 text-[10px] text-muted-foreground">{timeAgo(x.last_activity)}</span>
              </button>
            ))}
          </div>
          <div className="mt-2"><NewSessionDialog onCreated={(x) => { sessionsList.reload(); choose(x.id); }} /></div>
          {independent.some((x) => x.status === "archived") && <p className="mt-1 px-1 text-[10px] text-muted-foreground">{independent.filter((x) => x.status === "archived").length} archivadas</p>}
        </div>
        {!current && <div>
          <div className="mb-1.5 px-1 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">Historial</div>
          {transcripts.loading && <Loading rows={4} />}
          <div className="space-y-0.5">
            {transcripts.data?.slice(0, 30).map((t, i) => {
              const active = selected === t.claude_session_id || (selected === null && i === 0);
              return (
                <button
                  key={t.claude_session_id}
                  onClick={() => setSelected(i === 0 ? null : t.claude_session_id)}
                  className={cn("flex w-full items-center justify-between rounded-md px-2.5 py-1.5 text-left text-xs hover:bg-sidebar-accent", active && "bg-sidebar-accent")}
                >
                  <span>{i === 0 ? "Actual" : new Date(t.mtime * 1000).toLocaleDateString("es-ES", { weekday: "short", day: "2-digit", month: "2-digit" })}</span>
                  <span className="text-muted-foreground">{timeAgo(new Date(t.mtime * 1000).toISOString())}</span>
                </button>
              );
            })}
          </div>
        </div>}
      </aside>

      {current ? <IndependentChat key={current.id} session={current} onChanged={() => sessionsList.reload()} /> : <>
      {/* Centro: conversación */}
      <section className="flex min-h-0 flex-col">
        <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-2.5">
          <div className="min-w-0">
            <div className="truncate text-sm font-medium">{asistente()} · sesión compartida con Telegram</div>
            <div className="text-[11px] text-muted-foreground">
              {following ? "En directo" : "Historial (solo lectura)"} · {page?.items.filter((i) => i.kind === "message").length ?? 0} mensajes
            </div>
          </div>
          {busy && (
            <Button variant="destructive" size="sm" onClick={interrupt}>
              <CircleStop /> Interrumpir
            </Button>
          )}
        </div>
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-4">
          {error && <ErrorState message={error} />}
          {!page && !error && <Loading rows={6} />}
          {page && blocks.length === 0 && <Empty message={filter ? "Nada coincide con la búsqueda" : "Conversación vacía"} />}
          {blocks.map((b, i) =>
            b.type === "msg" ? (
              <Bubble key={b.item.uuid} item={b.item} />
            ) : b.type === "tools" ? (
              <ToolsBlock key={b.items[0].uuid} items={b.items} />
            ) : (
              <div key={`th-${i}`} className="pl-1 text-[11px] text-muted-foreground/70 italic">{asistente()} está pensando (el razonamiento interno no se muestra)</div>
            ),
          )}
          {state.data?.current_run && (
            <div className="flex items-center gap-2 pl-1 text-xs text-muted-foreground">
              <Loader2 className="size-3.5 animate-spin" /> {asistente()} está trabajando…
            </div>
          )}
          <div ref={bottom} />
        </div>
        <form
          className="relative border-t border-border p-3"
          {...att.dropProps(!following)}
          onSubmit={(e) => {
            e.preventDefault();
            send();
          }}
        >
          <DropOverlay a={att} />
          <AttachmentChips a={att} disabled={sending} />
          <Textarea
            onPaste={pasteFiles(att)}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            placeholder={following ? `Escribe a ${asistente()}… (Intro para enviar, Mayús+Intro para salto de línea)` : "Vuelve a «Actual» para escribir"}
            disabled={!following || state.data?.tmux === false}
            maxLength={4000}
            rows={2}
            className="resize-none"
            aria-label={`Mensaje para ${asistente()}`}
          />
          <div className="mt-2 flex items-center justify-between gap-2">
            <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
            <AttachButton a={att} disabled={!following || sending} />
            <label className="flex items-center gap-2 text-xs text-muted-foreground">
              <Switch checked={tg} onCheckedChange={setTg} aria-label="Responder también por Telegram" /> Respuesta también por Telegram
            </label>
            </div>
            <div className="flex items-center gap-2">
              {(state.data?.queued ?? 0) > 0 && <span className="text-xs text-muted-foreground">{state.data?.queued} en cola</span>}
              <Button type="submit" size="sm" disabled={sending || (!text.trim() && att.files.length === 0) || !following}>
                {sending ? <Loader2 className="animate-spin" /> : <Send />} {sending && att.files.length ? "Subiendo…" : "Enviar"}
              </Button>
            </div>
          </div>
        </form>
      </section>

      {/* Derecha: contexto de ejecución */}
      <aside className="hidden space-y-5 overflow-y-auto border-l border-border p-4 text-sm xl:block">
        <section>
          <h2 className="mb-2 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">Agente</h2>
          <div className="flex items-center gap-2"><Bot className="size-4 text-primary" /> {asistente()}</div>
          <dl className="mt-2 space-y-1 text-xs text-muted-foreground">
            <div className="flex justify-between"><dt>Modelo</dt><dd>Sonnet (por defecto)</dd></div>
            <div className="flex justify-between"><dt>Sesión tmux</dt><dd>{state.data?.tmux ? "activa" : state.data?.tmux === false ? "caída" : "—"}</dd></div>
            <div className="flex justify-between"><dt>Ordenador virtual</dt><dd>ninguno</dd></div>
          </dl>
        </section>
        <section>
          <h2 className="mb-2 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">Ejecuciones del panel</h2>
          {runs.data?.length === 0 && <p className="text-xs text-muted-foreground">Aún no has escrito desde el panel.</p>}
          <ul className="space-y-1.5">
            {runs.data?.map((r) => (
              <li key={r.id} className="text-xs">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-muted-foreground">{r.id.slice(0, 8)}</span>
                  <span className={cn(r.status === "error" && "text-destructive", r.status === "done" && "text-success")}>{RUN_STATUS[r.status] ?? r.status}</span>
                </div>
                {r.error && <div className="truncate text-destructive/80" title={r.error}>{r.error}</div>}
                {r.tools_used.length > 0 && <div className="truncate text-muted-foreground">{r.tools_used.length} herramientas</div>}
              </li>
            ))}
          </ul>
        </section>
        <section>
          <h2 className="mb-2 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">Herramientas usadas</h2>
          <ul className="space-y-1 text-xs">
            {toolStats.slice(0, 10).map(([k, n]) => (
              <li key={k} className="flex justify-between gap-2"><span className="truncate font-mono">{k}</span><span className="text-muted-foreground">{n}</span></li>
            ))}
          </ul>
        </section>
        <section>
          <h2 className="mb-2 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">Archivos tocados</h2>
          <ul className="space-y-1 text-xs">
            {files.map((f) => (
              <li key={f} className="flex items-center gap-1.5 truncate text-muted-foreground"><FileText className="size-3 shrink-0" /><span className="truncate">{f}</span></li>
            ))}
          </ul>
        </section>
      </aside>
      </>}
    </div>
  );
}
