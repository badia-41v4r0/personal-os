"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { AlertTriangle, ChevronRight, Clock, FileText, Folder, Link2, Lock, Pencil, Save, Search, X } from "lucide-react";
import { cn } from "cn";
import { Markdown, splitFrontmatter } from "@/components/cc/markdown";
import { Empty, ErrorState, Loading } from "@/components/cc/states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { api, ApiError } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { asistente } from "@/lib/asistente";

type Entry = { name: string; path: string; dir: boolean; size: number; mtime: number };
type FileData = { path: string; content: string; sha: string; mtime: number; editable: boolean; note: string };
type Hit = { path: string; name: string; snippet: string };
type Ref = { path: string; name: string; mtime?: number };

function TreeNode({ entry, depth, current, open }: { entry: Entry; depth: number; current: string | null; open: (p: string) => void }) {
  const [expanded, setExpanded] = useState(!!current?.startsWith(entry.path + "/"));
  const [items, setItems] = useState<Entry[] | null>(null);
  useEffect(() => {
    if (expanded && entry.dir && !items) api<{ items: Entry[] }>(`/memory/tree?path=${encodeURIComponent(entry.path)}`).then((r) => setItems(r.items)).catch(() => setItems([]));
  }, [expanded, entry, items]);
  const pad = { paddingLeft: `${depth * 12 + 8}px` };
  if (!entry.dir) {
    return (
      <button onClick={() => open(entry.path)} style={pad}
        className={cn("flex w-full items-center gap-1.5 truncate rounded-md py-1 pr-2 text-left text-xs hover:bg-sidebar-accent", current === entry.path && "bg-sidebar-accent text-primary")}>
        <FileText className="size-3 shrink-0 text-muted-foreground" />
        <span className="truncate">{entry.name.replace(/\.md$/, "")}</span>
      </button>
    );
  }
  return (
    <div>
      <button onClick={() => setExpanded(!expanded)} style={pad} aria-expanded={expanded}
        className="flex w-full items-center gap-1.5 truncate rounded-md py-1 pr-2 text-left text-xs hover:bg-sidebar-accent">
        <ChevronRight className={cn("size-3 shrink-0 transition-transform", expanded && "rotate-90")} />
        <Folder className="size-3 shrink-0 text-muted-foreground" />
        <span className="truncate">{entry.name}</span>
      </button>
      {expanded && (items ?? []).map((c) => <TreeNode key={c.path} entry={c} depth={depth + 1} current={current} open={open} />)}
    </div>
  );
}

function Viewer({ path, open }: { path: string; open: (p: string) => void }) {
  const [file, setFile] = useState<FileData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [conflict, setConflict] = useState<string | null>(null);
  const backlinks = useApi<Ref[]>(`/memory/backlinks?path=${encodeURIComponent(path)}`);

  const load = useCallback(() => {
    setFile(null);
    setError(null);
    setConflict(null);
    api<FileData>(`/memory/file?path=${encodeURIComponent(path)}`)
      .then((f) => { setFile(f); setDraft(f.content); })
      .catch((e) => setError(e.message));
  }, [path]);

  useEffect(() => {
    setEditing(false);
    load();
  }, [load]);

  const save = async () => {
    if (!file) return;
    setSaving(true);
    setConflict(null);
    try {
      const r = await api<{ sha: string; mtime: number }>("/memory/file", {
        method: "PUT", body: JSON.stringify({ path: file.path, content: draft, base_sha: file.sha }),
      });
      setFile({ ...file, content: draft, sha: r.sha, mtime: r.mtime });
      setEditing(false);
    } catch (e) {
      setConflict(e instanceof ApiError && e.status === 409 ? e.message : e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const wiki = async (target: string) => {
    try {
      const r = await api<{ path: string }>(`/memory/resolve?name=${encodeURIComponent(target)}&from_path=${encodeURIComponent(path)}`);
      open(r.path);
    } catch {
      setError(`No existe la nota «${target}»`);
    }
  };

  if (error) return <ErrorState message={error} />;
  if (!file) return <Loading rows={8} />;
  const { meta, body } = splitFrontmatter(file.content);
  const dir = file.path.split("/").slice(0, -1).join("/");
  const dirty = editing && draft !== file.content;

  return (
    <div className="grid gap-6 xl:grid-cols-[1fr_14rem]">
      <article className="min-w-0">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2 border-b border-border pb-3">
          <div className="min-w-0">
            <div className="truncate font-mono text-[11px] text-muted-foreground">{file.path}</div>
            <div className="text-[11px] text-muted-foreground">Modificada {timeAgo(new Date(file.mtime * 1000).toISOString())}</div>
          </div>
          <div className="flex items-center gap-2">
            {!file.editable && <span className="flex items-center gap-1 text-xs text-muted-foreground" title={file.note}><Lock className="size-3" /> Solo lectura</span>}
            {file.editable && !editing && <Button size="sm" variant="outline" onClick={() => setEditing(true)}><Pencil /> Editar</Button>}
            {editing && (
              <>
                <Button size="sm" variant="ghost" onClick={() => { setEditing(false); setDraft(file.content); setConflict(null); }}><X /> Cancelar</Button>
                <Button size="sm" onClick={save} disabled={saving || !dirty}><Save /> {saving ? "Guardando…" : "Guardar"}</Button>
              </>
            )}
          </div>
        </div>
        {file.note && (
          <p className={cn("mb-3 flex items-start gap-1.5 rounded-lg px-3 py-2 text-xs", file.editable ? "bg-warning/10 text-warning" : "bg-muted text-muted-foreground")}>
            <AlertTriangle className="mt-0.5 size-3.5 shrink-0" /> {file.note}
          </p>
        )}
        {conflict && (
          <div role="alert" className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {conflict}
            <Button size="xs" variant="outline" onClick={load}>Recargar (perderás tus cambios)</Button>
          </div>
        )}
        {editing ? (
          <Textarea value={draft} onChange={(e) => setDraft(e.target.value)} className="min-h-[60vh] font-mono text-xs leading-relaxed" aria-label="Contenido de la nota" spellCheck={false} />
        ) : (
          <>
            {meta.length > 0 && (
              <dl className="mb-4 grid grid-cols-[auto_1fr] gap-x-4 gap-y-0.5 rounded-lg bg-muted/40 px-3 py-2 text-xs">
                {meta.map(([k, v]) => <div key={k} className="contents"><dt className="text-muted-foreground">{k}</dt><dd className="truncate">{v}</dd></div>)}
              </dl>
            )}
            {file.path.endsWith(".md") ? (
              <Markdown source={body} onWiki={wiki} imageSrc={(n) => `/api/v1/memory/raw?path=${encodeURIComponent(n.includes("/") ? n : dir ? `${dir}/${n}` : n)}`} />
            ) : (
              <pre className="overflow-x-auto rounded-lg bg-muted p-3 font-mono text-xs">{file.content}</pre>
            )}
          </>
        )}
      </article>
      <aside className="space-y-2 text-sm">
        <h2 className="flex items-center gap-1.5 text-[11px] font-medium tracking-wide text-muted-foreground uppercase"><Link2 className="size-3" /> Enlazan aquí</h2>
        {backlinks.loading && <Loading rows={2} />}
        {backlinks.data?.length === 0 && <p className="text-xs text-muted-foreground">Ninguna nota</p>}
        <ul className="space-y-1">
          {backlinks.data?.map((b) => <li key={b.path} className="min-w-0"><button onClick={() => open(b.path)} className="block w-full truncate py-1.5 text-left text-xs hover:text-primary lg:py-0.5" title={b.path}>{b.name}</button></li>)}
        </ul>
      </aside>
    </div>
  );
}

function MemoryInner() {
  const params = useSearchParams();
  const router = useRouter();
  const current = params.get("p");
  const rootTree = useApi<{ items: Entry[] }>("/memory/tree");
  const recent = useApi<Ref[]>("/memory/recent?limit=12");
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Hit[] | null>(null);
  const [searchErr, setSearchErr] = useState<string | null>(null);
  const [explore, setExplore] = useState(false); // móvil: explorador plegado mientras se lee una nota

  const open = (p: string) => {
    setExplore(false);
    router.push(`/conocimiento/?p=${encodeURIComponent(p)}`);
  };

  const search = async (e: React.FormEvent) => {
    e.preventDefault();
    setSearchErr(null);
    try {
      setHits(await api<Hit[]>(`/memory/search?q=${encodeURIComponent(q)}`));
    } catch (err) {
      setSearchErr(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <div className="-m-4 grid min-h-[calc(100dvh-3rem)] grid-cols-1 content-start md:-m-6 lg:min-h-dvh lg:grid-cols-[17rem_1fr] lg:content-stretch">
      <div className="border-b border-border p-2 lg:hidden">
        {current && (
          <Button variant="outline" size="sm" className="w-full" onClick={() => setExplore(!explore)} aria-expanded={explore}>
            <Search /> {explore ? "Cerrar el explorador" : "Explorar la vault"}
          </Button>
        )}
      </div>
      <aside className={cn("space-y-4 border-b border-border p-3 lg:sticky lg:top-0 lg:block lg:h-dvh lg:overflow-y-auto lg:border-r lg:border-b-0", current && !explore && "hidden")}>
        <form onSubmit={search} className="relative">
          <Search className="absolute top-2 left-2.5 size-3.5 text-muted-foreground" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Buscar en la vault" className="h-8 pl-8 text-xs" aria-label="Buscar en la vault" />
        </form>
        {searchErr && <p className="text-xs text-destructive">{searchErr}</p>}
        {hits && (
          <div>
            <div className="mb-1 flex items-center justify-between px-1 text-[11px] text-muted-foreground">
              <span>{hits.length} resultados</span>
              <button onClick={() => setHits(null)} className="hover:text-foreground">Cerrar</button>
            </div>
            <ul className="space-y-1">
              {hits.map((h) => (
                <li key={h.path}>
                  <button onClick={() => open(h.path)} className="w-full rounded-md px-2 py-1.5 text-left hover:bg-sidebar-accent">
                    <div className="truncate text-xs font-medium">{h.name}</div>
                    <div className="truncate text-[11px] text-muted-foreground">{h.path}</div>
                    {h.snippet && <div className="line-clamp-2 text-[11px] text-muted-foreground">{h.snippet}</div>}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
        {!hits && (
          <>
            <div>
              <div className="mb-1 px-1 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">Vault</div>
              {rootTree.loading && <Loading rows={4} />}
              {rootTree.error && <ErrorState message={rootTree.error} />}
              {rootTree.data?.items.map((e) => <TreeNode key={e.path} entry={e} depth={0} current={current} open={open} />)}
            </div>
            <div>
              <div className="mb-1 flex items-center gap-1 px-1 text-[11px] font-medium tracking-wide text-muted-foreground uppercase"><Clock className="size-3" /> Recientes</div>
              {recent.data?.map((r) => (
                <button key={r.path} onClick={() => open(r.path)} className="flex w-full items-center justify-between gap-2 rounded-md px-2 py-1 text-left text-xs hover:bg-sidebar-accent">
                  <span className="truncate">{r.name}</span>
                  <span className="shrink-0 text-[10px] text-muted-foreground">{timeAgo(new Date((r.mtime ?? 0) * 1000).toISOString())}</span>
                </button>
              ))}
            </div>
          </>
        )}
      </aside>
      <section className="min-w-0 p-4 md:p-6">
        {current ? <Viewer path={current} open={open} /> : (
          <div className="space-y-4">
            <h1 className="text-xl font-semibold tracking-tight">Tu vault</h1>
            <p className="max-w-xl text-sm text-muted-foreground">
              Tu vault de Obsidian, leída en directo (no se copia a la base del panel). Las notas que genera un script se muestran en solo lectura;
              si una nota cambia en Obsidian o la toca {asistente()} mientras la editas, el panel no la pisa.
            </p>
            <div className="flex flex-wrap gap-2">
              {["Jarvis/Panel.md", "Jarvis/Tareas.md", "Jarvis/Areas/Trabajo.md", "Jarvis/Areas/Gym.md", "Jarvis/Areas/Uni.md"].map((p) => (
                <Button key={p} variant="outline" size="sm" onClick={() => open(p)}>{p.split("/").pop()!.replace(".md", "")}</Button>
              ))}
            </div>
            {!recent.data && <Empty message="Cargando…" />}
          </div>
        )}
      </section>
    </div>
  );
}

export default function MemoryPage() {
  return (
    <Suspense fallback={<Loading rows={6} />}>
      <MemoryInner />
    </Suspense>
  );
}
