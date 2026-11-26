"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import { Download, File as FileIcon, FileText, Folder, FolderPlus, Image as ImageIcon, Upload } from "lucide-react";
import { cn } from "cn";
import { useAct } from "@/components/cc/form";
import { Markdown } from "@/components/cc/markdown";
import { Empty, ErrorState, Loading } from "@/components/cc/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api, upload } from "@/lib/api";
import { bytes, timeAgo } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { Chip } from "./common";
import { BASE } from "@/lib/base";

type Item = { nombre: string; ruta: string; carpeta: boolean; bytes: number; modificado: string; tipo: string };
type Listado = { ruta: string; nombres: Record<string, string>; items: Item[] };
const raw = (ruta: string, descargar = false) => `${BASE}/api/v1/education/archivos/raw?path=${encodeURIComponent(ruta)}${descargar ? "&descargar=true" : ""}`;
const TEXTO = /\.(md|txt|c|h|py|json|csv|sh|v|sv|ya?ml|java|js|ts|tex|log|xml|sql)$/i;
const href = (ruta: string) => `/educacion/?tab=archivos${ruta ? `&ruta=${encodeURIComponent(ruta)}` : ""}`;

function Vista({ item, onClose }: { item: Item; onClose: () => void }) {
  const esTexto = TEXTO.test(item.nombre);
  const txt = useApi<{ texto: string; recortado: boolean; md: boolean }>(esTexto ? `/education/archivos/texto?path=${encodeURIComponent(item.ruta)}` : null);
  const pdf = item.tipo === "application/pdf", img = item.tipo.startsWith("image/") && !item.tipo.includes("svg");
  return (
    <Card className="min-w-0">
      <CardHeader className="flex-row items-center justify-between gap-2">
        <CardTitle className="min-w-0 truncate">{item.nombre}</CardTitle>
        <div className="flex shrink-0 gap-1.5">
          <a href={raw(item.ruta, true)} download className="inline-flex h-7 items-center gap-1 rounded-lg border border-border px-2.5 text-[0.8rem] hover:bg-muted"><Download className="size-3.5" />Descargar</a>
          <Button size="sm" variant="ghost" onClick={onClose}>Cerrar</Button>
        </div>
      </CardHeader>
      <CardContent>
        {pdf && <iframe title={item.nombre} src={raw(item.ruta)} className="h-[70vh] w-full rounded-lg border border-border" />}
        {img && (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={raw(item.ruta)} alt={item.nombre} className="max-h-[70vh] max-w-full rounded-lg" />
        )}
        {esTexto && txt.loading && <Loading rows={4} />}
        {esTexto && txt.error && <ErrorState message={txt.error} />}
        {txt.data && (txt.data.md ? <Markdown source={txt.data.texto} onWiki={() => {}} imageSrc={(n) => n} /> : <pre className="max-h-[70vh] overflow-auto whitespace-pre-wrap rounded-lg bg-muted/60 p-3 font-mono text-xs">{txt.data.texto}</pre>)}
        {txt.data?.recortado && <p className="mt-2 text-xs text-muted-foreground">Vista recortada: descarga el archivo para verlo entero.</p>}
        {!pdf && !img && !esTexto && <Empty message="No hay vista previa de este tipo de archivo: descárgalo." />}
      </CardContent>
    </Card>
  );
}

export function ArchivosTab({ ruta }: { ruta: string }) {
  const l = useApi<Listado>(`/education/archivos?path=${encodeURIComponent(ruta)}`);
  const rec = useApi<Item[]>(ruta ? null : "/education/archivos/recientes?limit=8");
  const [sel, setSel] = useState<Item | null>(null);
  const [nueva, setNueva] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const a = useAct(() => { l.reload(); rec.reload(); });
  const partes = ruta ? ruta.split("/") : [];
  const subir = (files: FileList | null) => {
    if (!files?.length) return;
    void a.run(async () => { for (const f of Array.from(files)) await upload(`/education/archivos?path=${encodeURIComponent(ruta)}&name=${encodeURIComponent(f.name)}`, f); });
  };
  const icono = (i: Item) => (i.carpeta ? <Folder className="size-4 text-primary" /> : i.tipo.startsWith("image/") ? <ImageIcon className="size-4 text-muted-foreground" /> : TEXTO.test(i.nombre) || i.tipo === "application/pdf" ? <FileText className="size-4 text-muted-foreground" /> : <FileIcon className="size-4 text-muted-foreground" />);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-1 text-sm">
        <Link href={href("")} className="rounded px-1.5 py-1 hover:bg-muted">Uni</Link>
        {partes.map((p, i) => (<span key={i} className="flex items-center gap-1"><span className="text-muted-foreground">/</span><Link href={href(partes.slice(0, i + 1).join("/"))} className="rounded px-1.5 py-1 hover:bg-muted">{p}{i === 0 && l.data?.nombres[p] ? ` · ${l.data.nombres[p]}` : ""}</Link></span>))}
        <span className="flex-1" />
        {ruta && <>
          <input ref={input} type="file" multiple className="sr-only" aria-label="Subir archivos" onChange={(e) => { subir(e.target.files); e.target.value = ""; }} />
          <Button size="sm" variant="outline" disabled={a.busy} onClick={() => input.current?.click()}><Upload />Subir aquí</Button>
        </>}
      </div>
      <p className="text-xs text-muted-foreground">Aquí deja el tutor lo que te prepara, ordenado por asignatura. También puedes subir un borrador para que lo revise. Solo se puede ver, descargar y subir: nada se borra desde el panel.</p>
      {l.error && <ErrorState message={l.error} />}
      {a.ErrorBox}
      <div className={cn("grid gap-4", sel && "xl:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]")}>
        <Card className="h-fit min-w-0">
          <CardContent className="py-2">
            {l.loading && !l.data && <Loading rows={5} />}
            {l.data && l.data.items.length === 0 && <Empty message="Carpeta vacía." />}
            <ul className="divide-y divide-border">
              {l.data?.items.map((i) => {
                const nombre = !ruta && l.data?.nombres[i.nombre];
                const contenido = (
                  <>
                    <span className="grid size-8 shrink-0 place-items-center">{icono(i)}</span>
                    <span className="min-w-0 flex-1"><span className="flex items-center gap-2"><span className="truncate text-sm font-medium">{i.nombre}</span>{nombre && <Chip code={i.nombre} />}</span>
                      <span className="block truncate text-xs text-muted-foreground">{nombre ? nombre : i.carpeta ? "Carpeta" : `${bytes(i.bytes)} · ${timeAgo(i.modificado)}`}</span></span>
                  </>
                );
                return (
                  <li key={i.ruta}>
                    {i.carpeta ? <Link href={href(i.ruta)} className="flex min-h-11 items-center gap-2 rounded-md px-1 hover:bg-muted">{contenido}</Link>
                      : <button type="button" onClick={() => setSel(i)} aria-pressed={sel?.ruta === i.ruta} className={cn("flex min-h-11 w-full items-center gap-2 rounded-md px-1 text-left hover:bg-muted", sel?.ruta === i.ruta && "bg-muted")}>{contenido}</button>}
                  </li>
                );
              })}
            </ul>
          </CardContent>
        </Card>
        {sel && <Vista key={sel.ruta} item={sel} onClose={() => setSel(null)} />}
      </div>
      {ruta && (
        <form className="flex max-w-sm gap-2" onSubmit={(e) => { e.preventDefault(); if (nueva.trim()) void a.run(async () => { await api("/education/archivos/carpeta", { method: "POST", body: JSON.stringify({ ruta, nombre: nueva }) }); setNueva(""); }); }}>
          <Input aria-label="Nombre de la carpeta" placeholder="Nueva carpeta (p. ej. PEC4)" value={nueva} onChange={(e) => setNueva(e.target.value)} />
          <Button type="submit" size="sm" variant="outline" disabled={a.busy || !nueva.trim()}><FolderPlus />Crear</Button>
        </form>
      )}
      {!ruta && rec.data && rec.data.length > 0 && (
        <Card>
          <CardHeader><CardTitle>Lo último que ha dejado el tutor</CardTitle></CardHeader>
          <CardContent>
            <ul className="divide-y divide-border">
              {rec.data.map((i) => (
                <li key={i.ruta} className="flex items-center gap-2 py-2 text-sm">
                  <Chip code={i.ruta.split("/")[0]} />
                  <Link href={href(i.ruta.split("/").slice(0, -1).join("/"))} className="min-w-0 flex-1 truncate hover:underline">{i.ruta.split("/").slice(1).join("/")}</Link>
                  <span className="shrink-0 text-xs text-muted-foreground">{timeAgo(i.modificado)}</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
