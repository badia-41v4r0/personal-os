"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { ArrowLeft, ExternalLink, FolderGit2, GitBranch, GitPullRequest, RefreshCw, CircleDot } from "lucide-react";
import { cn } from "cn";
import { PageHeader, usePanel } from "@/components/cc/shell";
import { Empty, ErrorState, Loading } from "@/components/cc/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { timeAgo } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { asistente } from "@/lib/asistente";

type Commit = { hash: string; author: string; date: string; subject: string };
type Local = { clonada: boolean; rama_actual?: string; principal?: string; staging?: boolean; staging_por_delante?: number | null; staging_por_detras?: number | null; ultimo_commit?: Commit | null };
type GH = { prs: { titulo: string; url: string; numero: number }[]; issues: { titulo: string; url: string; numero: number; etiquetas: string[] }[]; pr_staging: string | null; error: string | null };
type Project = { nombre: string; area: string; modelo: string; minutos: number; subagentes: boolean; local: Local; github: GH; encargos: number; encargos_pendientes: number };
type Encargo = { id: string; estado: string; path: string; meta: Record<string, string>; titulo: string; resultado: string; mtime: number };
type Detail = { nombre: string; owner: string; config: Record<string, unknown>; local: Local; commits: Record<string, Commit[]>; github: GH; encargos: Encargo[] };

const ESTADO: Record<string, string> = { cola: "en cola", "en-curso": "en curso", hechos: "hecho" };
// Las issues que piden una decisión van primero.
const isDecision = (i: GH["issues"][number]) => i.etiquetas.includes("decision");

function Detail({ name }: { name: string }) {
  const areas = usePanel().inst?.areas ?? {};
  const router = useRouter();
  const d = useApi<Detail>(`/projects/${encodeURIComponent(name)}`);
  if (d.error) return <ErrorState message={d.error} />;
  if (!d.data) return <Loading rows={6} />;
  const p = d.data;
  const issues = [...p.github.issues].sort((a, b) => Number(isDecision(b)) - Number(isDecision(a)));
  return (
    <>
      <PageHeader title={p.nombre} description={`${areas[String(p.config.area)] ?? p.config.area} · programador con ${p.config.modelo}, ${p.config.minutos} min${p.config.subagentes ? ", con subagentes" : ""}`}
        actions={<div className="flex gap-2">
          <Button variant="ghost" size="sm" onClick={() => router.push("/projects/")}><ArrowLeft /> Proyectos</Button>
          <a href={`https://github.com/${p.owner}/${p.nombre}`} target="_blank" rel="noopener noreferrer" className="inline-flex h-7 items-center gap-1 rounded-lg px-2.5 text-[0.8rem] ring-1 ring-border hover:bg-muted"><ExternalLink className="size-3.5" /> GitHub</a>
        </div>} />
      <div className="grid gap-4 xl:grid-cols-3">
        <div className="space-y-4 xl:col-span-2">
          {Object.entries(p.commits).map(([branch, commits]) => (
            <Card key={branch}>
              <CardHeader><CardTitle className="flex items-center gap-2"><GitBranch className="size-4" /> {branch}</CardTitle></CardHeader>
              <CardContent><ul className="divide-y divide-border">
                {commits.map((c) => <li key={c.hash} className="grid grid-cols-[4.5rem_1fr_auto] gap-2 py-1.5 text-sm"><span className="font-mono text-xs text-muted-foreground">{c.hash}</span><span className="truncate">{c.subject}</span><span className="text-xs text-muted-foreground">{timeAgo(c.date)}</span></li>)}
              </ul></CardContent>
            </Card>
          ))}
          {!p.local.clonada && <Empty message="La repo no está clonada en repos/." />}
          <Card>
            <CardHeader><CardTitle>Encargos del programador</CardTitle></CardHeader>
            <CardContent>
              {p.encargos.length === 0 && <p className="text-sm text-muted-foreground">Ninguno todavía. Se los pides a {asistente()} desde el chat.</p>}
              <ul className="divide-y divide-border">
                {p.encargos.map((e) => (
                  <li key={e.path} className="py-2 text-sm">
                    <div className="flex justify-between gap-2"><Link href={`/memory/?p=${encodeURIComponent(e.path)}`} className="truncate hover:text-primary">{e.titulo}</Link><Badge variant="outline">{ESTADO[e.estado]}</Badge></div>
                    <div className="text-xs text-muted-foreground">{e.meta.tipo} · {timeAgo(new Date(e.mtime * 1000).toISOString())}</div>
                    {e.resultado && <p className="mt-1 line-clamp-3 text-xs text-muted-foreground">{e.resultado}</p>}
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        </div>
        <div className="space-y-4">
          <Card>
            <CardHeader><CardTitle>Estado</CardTitle></CardHeader>
            <CardContent className="space-y-1.5 text-sm">
              <div className="flex justify-between"><span className="text-muted-foreground">Rama principal</span><span>{p.local.principal ?? "—"}</span></div>
              <div className="flex justify-between"><span className="text-muted-foreground">staging</span><span>{p.local.staging ? `${p.local.staging_por_delante ?? 0} commits por delante` : "no existe aún"}</span></div>
              {p.github.pr_staging && <a href={p.github.pr_staging} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-primary hover:underline"><GitPullRequest className="size-3.5" /> PR de staging pendiente de revisar</a>}
              <p className="pt-2 text-xs text-muted-foreground">Datos locales de repos/ (el espacio de trabajo del programador) y de GitHub (cada 10 min).</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Pull requests ({p.github.prs.length})</CardTitle></CardHeader>
            <CardContent>
              {p.github.error && <ErrorState message={p.github.error} />}
              <ul className="space-y-1 text-sm">{p.github.prs.map((x) => <li key={x.numero}><a href={x.url} target="_blank" rel="noopener noreferrer" className="inline-block py-1 hover:text-primary">#{x.numero} {x.titulo}</a></li>)}</ul>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Issues ({p.github.issues.length})</CardTitle></CardHeader>
            <CardContent><ul className="space-y-1.5 text-sm">{issues.map((x) => <li key={x.numero}><a href={x.url} target="_blank" rel="noopener noreferrer" className="inline-block py-1 hover:text-primary">#{x.numero} {x.titulo}</a>{x.etiquetas.map((l) => <Badge key={l} variant={l === "decision" ? "secondary" : "outline"} className="ml-1 align-middle text-[10px]">{l}</Badge>)}</li>)}</ul></CardContent>
          </Card>
        </div>
      </div>
    </>
  );
}

function List() {
  const areas = usePanel().inst?.areas ?? {};
  const [refresh, setRefresh] = useState(0);
  const p = useApi<Project[]>(`/projects${refresh ? `?refresh=true&n=${refresh}` : ""}`);
  return (
    <>
      <PageHeader title="Projects" description="Repos del programador (programador/repos.json), su estado y los encargos."
        actions={<Button variant="outline" size="sm" onClick={() => setRefresh((n) => n + 1)}><RefreshCw /> Actualizar GitHub</Button>} />
      {p.error && <ErrorState message={p.error} />}
      {p.loading && <Loading rows={5} />}
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {p.data?.map((x) => (
          <Link key={x.nombre} href={`/projects/?r=${encodeURIComponent(x.nombre)}`} className="rounded-xl border border-border bg-card p-4 transition-colors hover:border-primary/40">
            <div className="flex items-start justify-between gap-2">
              <span className="flex min-w-0 items-center gap-2"><FolderGit2 className="size-4 shrink-0 text-primary" /><span className="truncate font-medium">{x.nombre}</span></span>
              <Badge variant="secondary">{areas[x.area] ?? x.area}</Badge>
            </div>
            <div className="mt-2 truncate text-xs text-muted-foreground">{x.local.ultimo_commit ? `${x.local.ultimo_commit.subject} · ${timeAgo(x.local.ultimo_commit.date)}` : "Sin clonar"}</div>
            <div className="mt-3 flex flex-wrap gap-3 text-xs">
              <span className={cn(x.github.pr_staging && "text-primary")}><GitPullRequest className="mr-1 inline size-3.5" />{x.github.prs.length} PR{x.github.pr_staging ? " (staging)" : ""}</span>
              <span><CircleDot className="mr-1 inline size-3.5" />{x.github.issues.length} issues</span>
              <span className="text-muted-foreground">{x.encargos} encargos{x.encargos_pendientes ? ` · ${x.encargos_pendientes} en marcha` : ""}</span>
              {x.local.staging && (x.local.staging_por_delante ?? 0) > 0 && <span className="text-warning">staging +{x.local.staging_por_delante}</span>}
            </div>
            {x.github.error && <p className="mt-2 truncate text-xs text-destructive">GitHub: {x.github.error}</p>}
          </Link>
        ))}
      </div>
    </>
  );
}

function Inner() {
  const params = useSearchParams();
  const r = params.get("r");
  return r ? <Detail name={r} /> : <List />;
}

export default function ProjectsPage() {
  return <Suspense fallback={<Loading rows={6} />}><Inner /></Suspense>;
}
