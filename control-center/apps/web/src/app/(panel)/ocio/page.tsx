"use client";

import { useEffect, useMemo, useState } from "react";
import { Clapperboard, Film, Plus, RefreshCw, Search, Star, Trash2, Tv } from "lucide-react";
import { useAct, Field, TextField, selectClass } from "@/components/cc/form";
import { PageHeader } from "@/components/cc/shell";
import { Empty, ErrorState, Loading } from "@/components/cc/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { api, post } from "@/lib/api";
import { useApi } from "@/lib/hooks";

type Tipo = "pelicula" | "serie";
type Estado = "pendiente" | "viendo" | "vista" | "abandonada";
type Item = {
  id: number; tipo: Tipo; tmdb_id: number | null; titulo: string; titulo_original: string; anio: number | null; sinopsis: string;
  generos: string[]; duracion: number | null; temporadas: number | null; capitulos: number | null; capitulos_por_temporada: number[];
  emision: string; poster: string; nota_tmdb: number | null; plataformas: string[]; estado: Estado; valoracion: number | null;
  temporada: number | null; capitulo: number | null; empezada: string | null; terminada: string | null; nota: string;
};
type Hit = { tmdb_id: number; tipo: Tipo; titulo: string; titulo_original: string; anio: number | null; poster: string; sinopsis: string };
type Lista = { tmdb: boolean; items: Item[] };

const ESTADOS: [Estado, string][] = [["viendo", "Viendo"], ["pendiente", "Quiero verla"], ["vista", "Vista"], ["abandonada", "Abandonada"]];
const ESTADO_LABEL = Object.fromEntries(ESTADOS) as Record<Estado, string>;
const ORDEN: Record<Estado, number> = { viendo: 0, pendiente: 1, vista: 2, abandonada: 3 };
const img = (size: "w92" | "w342", name: string) => `/api/v1/me/ocio/imagen/${size}/${name}`;
const progreso = (i: Item) => (i.tipo === "serie" && i.temporada ? `T${i.temporada} · E${i.capitulo ?? 0}` : null);

/** Siguiente capítulo: si se acaba la temporada (y se sabe cuántos tiene), pasa a la siguiente. */
function siguiente(i: Item): { temporada: number; capitulo: number } {
  const t = i.temporada ?? 1;
  const c = (i.capitulo ?? 0) + 1;
  const total = i.capitulos_por_temporada[t - 1];
  if (total && c > total && t < i.capitulos_por_temporada.length) return { temporada: t + 1, capitulo: 1 };
  return { temporada: t, capitulo: c };
}

function Poster({ item, className = "" }: { item: { poster: string; titulo: string; tipo: Tipo }; className?: string }) {
  const [roto, setRoto] = useState(false);
  if (!item.poster || roto) {
    const Icon = item.tipo === "serie" ? Tv : Film;
    return <div className={`flex aspect-[2/3] items-center justify-center rounded-lg bg-muted text-muted-foreground ${className}`}><Icon className="size-8" /></div>;
  }
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={img("w342", item.poster)} alt={`Carátula de ${item.titulo}`} loading="lazy" onError={() => setRoto(true)} className={`aspect-[2/3] w-full rounded-lg bg-muted object-cover ${className}`} />;
}

function Buscador({ tmdb, onAdded }: { tmdb: boolean; onAdded: () => void }) {
  const [q, setQ] = useState("");
  const [tipo, setTipo] = useState<"" | Tipo>("");
  const [estado, setEstado] = useState<Estado>("pendiente");
  const [hits, setHits] = useState<Hit[] | null>(null);
  const [buscando, setBuscando] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const a = useAct(onAdded);

  useEffect(() => {
    if (!tmdb) return;
    const texto = q.trim();
    if (texto.length < 2) return;
    const t = setTimeout(() => {
      setBuscando(true);
      api<Hit[]>(`/me/ocio/buscar?${new URLSearchParams({ q: texto, ...(tipo ? { tipo } : {}) })}`)
        .then((r) => { setHits(r); setErr(null); })
        .catch((e) => setErr(e instanceof Error ? e.message : String(e)))
        .finally(() => setBuscando(false));
    }, 350);
    return () => clearTimeout(t);
  }, [q, tipo, tmdb]);

  const activo = tmdb && q.trim().length >= 2;
  const anadir = (body: Record<string, unknown>) => a.run(() => post("/me/ocio", { estado, ...body })).then(() => { setQ(""); setHits(null); });

  return (
    <Card>
      <CardContent className="grid gap-3">
        {!tmdb && <p className="text-sm text-muted-foreground">Falta la clave de TMDB: de momento se añaden a mano, sin carátula ni información.</p>}
        <div className="grid gap-2 sm:grid-cols-[1fr_auto_auto]">
          <div className="relative">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input aria-label={tmdb ? "Buscar peli o serie" : "Título"} placeholder={tmdb ? "Busca una peli o serie…" : "Título"} value={q} onChange={(e) => setQ(e.target.value)} maxLength={200} className="pl-8" />
          </div>
          <select aria-label="Tipo" className={selectClass} value={tipo} onChange={(e) => setTipo(e.target.value as "" | Tipo)}>
            <option value="">{tmdb ? "Pelis y series" : "Tipo…"}</option><option value="pelicula">Pelis</option><option value="serie">Series</option>
          </select>
          <select aria-label="Añadir como" className={selectClass} value={estado} onChange={(e) => setEstado(e.target.value as Estado)}>
            {ESTADOS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
        </div>
        {a.ErrorBox}
        {err && <ErrorState message={err} />}
        {!tmdb && <Button disabled={a.busy || !q.trim() || !tipo} onClick={() => void anadir({ tipo, titulo: q.trim() })}><Plus /> Añadir</Button>}
        {activo && buscando && !hits && <Loading rows={2} />}
        {activo && !buscando && hits?.length === 0 && <p className="text-sm text-muted-foreground">Sin resultados.</p>}
        {activo && !!hits?.length && (
          <ul className="grid gap-1" aria-label="Resultados">
            {hits.map((h) => (
              <li key={`${h.tipo}-${h.tmdb_id}`}>
                <button type="button" disabled={a.busy} onClick={() => void anadir({ tipo: h.tipo, tmdb_id: h.tmdb_id })}
                  className="flex w-full items-center gap-3 rounded-lg p-1.5 text-left hover:bg-muted disabled:opacity-50">
                  {h.poster
                    // eslint-disable-next-line @next/next/no-img-element
                    ? <img src={img("w92", h.poster)} alt="" loading="lazy" className="h-14 w-[37px] shrink-0 rounded bg-muted object-cover" />
                    : <span className="flex h-14 w-[37px] shrink-0 items-center justify-center rounded bg-muted text-muted-foreground">{h.tipo === "serie" ? <Tv className="size-4" /> : <Film className="size-4" />}</span>}
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium">{h.titulo}{h.anio && <span className="font-normal text-muted-foreground"> ({h.anio})</span>}</span>
                    <span className="block truncate text-xs text-muted-foreground">{h.tipo === "serie" ? "Serie" : "Peli"}{h.titulo_original && h.titulo_original !== h.titulo ? ` · ${h.titulo_original}` : ""}{h.sinopsis ? ` · ${h.sinopsis}` : ""}</span>
                  </span>
                  <Plus className="size-4 shrink-0 text-muted-foreground" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function Ficha({ item, onClose, onChange }: { item: Item; onClose: () => void; onChange: () => void }) {
  const [estado, setEstado] = useState<Estado>(item.estado);
  const [valoracion, setValoracion] = useState(item.valoracion ? String(item.valoracion) : "");
  const [temporada, setTemporada] = useState(String(item.temporada ?? ""));
  const [capitulo, setCapitulo] = useState(String(item.capitulo ?? ""));
  const [nota, setNota] = useState(item.nota);
  const [borrar, setBorrar] = useState(false);
  const a = useAct(onChange);
  const num = (v: string) => (v.trim() === "" ? null : Number(v));

  const guardar = () => a.run(async () => {
    const body: Record<string, unknown> = { nota, valoracion: num(valoracion) };
    if (estado !== item.estado) body.estado = estado;
    if (item.tipo === "serie") Object.assign(body, { temporada: num(temporada), capitulo: num(capitulo) });
    await api(`/me/ocio/${item.id}`, { method: "PATCH", body: JSON.stringify(body) });
    onClose();
  });
  const datos = [
    item.anio && String(item.anio),
    item.tipo === "serie" ? (item.temporadas ? `${item.temporadas} temporada${item.temporadas === 1 ? "" : "s"}` : null) : item.duracion ? `${item.duracion} min` : null,
    item.tipo === "serie" && item.capitulos ? `${item.capitulos} capítulos` : null,
    item.tipo === "serie" && item.duracion ? `~${item.duracion} min/cap.` : null,
    item.emision || null,
  ].filter(Boolean);

  return (
    <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-2xl">
      <DialogHeader>
        <DialogTitle>{item.titulo}</DialogTitle>
        <DialogDescription>{[item.tipo === "serie" ? "Serie" : "Peli", item.titulo_original !== item.titulo ? item.titulo_original : null, ...datos].filter(Boolean).join(" · ")}</DialogDescription>
      </DialogHeader>
      <div className="grid gap-4 sm:grid-cols-[160px_1fr]">
        <Poster item={item} className="mx-auto w-40 sm:w-full" />
        <div className="grid content-start gap-3 text-sm">
          {(item.generos.length > 0 || item.nota_tmdb) && (
            <div className="flex flex-wrap items-center gap-1.5">
              {item.nota_tmdb != null && <Badge variant="outline"><Star className="fill-current" /> {item.nota_tmdb.toFixed(1)} TMDB</Badge>}
              {item.generos.map((g) => <Badge key={g} variant="secondary">{g}</Badge>)}
            </div>
          )}
          {item.plataformas.length > 0 && <p><span className="text-muted-foreground">Dónde verla: </span>{item.plataformas.join(", ")}</p>}
          {item.sinopsis ? <p className="leading-relaxed text-muted-foreground">{item.sinopsis}</p> : item.tmdb_id == null && <p className="text-muted-foreground">Añadida a mano, sin información de TMDB.</p>}
          {(item.empezada || item.terminada) && <p className="text-xs text-muted-foreground">{item.empezada && `Empezada el ${item.empezada}`}{item.empezada && item.terminada && " · "}{item.terminada && `terminada el ${item.terminada}`}</p>}
        </div>
      </div>
      <form className="grid gap-3" onSubmit={(e) => { e.preventDefault(); void guardar(); }}>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Field label="Estado"><select className={selectClass} value={estado} onChange={(e) => setEstado(e.target.value as Estado)}>{ESTADOS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>
          <Field label="Tu nota"><select className={selectClass} value={valoracion} onChange={(e) => setValoracion(e.target.value)}><option value="">—</option>{Array.from({ length: 10 }, (_, n) => 10 - n).map((n) => <option key={n} value={n}>{n}</option>)}</select></Field>
          {item.tipo === "serie" && <>
            <TextField label="Temporada" type="number" min={0} max={200} inputMode="numeric" value={temporada} onChange={setTemporada} />
            <TextField label="Capítulo" type="number" min={0} max={5000} inputMode="numeric" value={capitulo} onChange={setCapitulo} />
          </>}
        </div>
        <Field label="Notas"><Textarea value={nota} onChange={(e) => setNota(e.target.value)} maxLength={4000} rows={3} placeholder="Qué te pareció, quién te la recomendó…" /></Field>
        {a.ErrorBox}
        <div className="flex flex-wrap items-center gap-2">
          <Button type="submit" disabled={a.busy}>Guardar</Button>
          {item.tmdb_id != null && <Button type="button" variant="outline" disabled={a.busy} onClick={() => void a.run(() => post(`/me/ocio/${item.id}/actualizar`))}><RefreshCw /> Actualizar info</Button>}
          <span className="flex-1" />
          {borrar
            ? <Button type="button" variant="destructive" disabled={a.busy} onClick={() => void a.run(async () => { await api(`/me/ocio/${item.id}`, { method: "DELETE" }); onClose(); })}>Sí, quitar</Button>
            : <Button type="button" variant="ghost" onClick={() => setBorrar(true)}><Trash2 /> Quitar</Button>}
        </div>
      </form>
    </DialogContent>
  );
}

function Tarjeta({ item, onOpen, onNext, busy }: { item: Item; onOpen: () => void; onNext: () => void; busy: boolean }) {
  const p = progreso(item);
  return (
    <li className="group grid content-start gap-1.5">
      <button type="button" onClick={onOpen} className="relative rounded-lg text-left focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none" aria-label={`Abrir ${item.titulo}`}>
        <Poster item={item} className="transition-opacity group-hover:opacity-90" />
        {item.valoracion != null && <span className="absolute top-1.5 right-1.5 flex items-center gap-0.5 rounded-md bg-black/70 px-1.5 py-0.5 text-xs font-semibold text-white tabular-nums"><Star className="size-3 fill-current" />{item.valoracion}</span>}
        {item.estado !== "viendo" && <span className="absolute bottom-1.5 left-1.5 rounded-md bg-black/70 px-1.5 py-0.5 text-[11px] text-white">{ESTADO_LABEL[item.estado]}</span>}
      </button>
      <div className="min-w-0">
        <p className="truncate text-sm font-medium" title={item.titulo}>{item.titulo}</p>
        <p className="truncate text-xs text-muted-foreground">{[item.anio, item.tipo === "serie" ? "Serie" : "Peli", p].filter(Boolean).join(" · ")}</p>
      </div>
      {item.estado === "viendo" && item.tipo === "serie" && (
        <Button size="sm" variant="outline" disabled={busy} onClick={onNext} aria-label={`Siguiente capítulo de ${item.titulo}`}><Plus /> Capítulo</Button>
      )}
    </li>
  );
}

function PelisYSeries() {
  const list = useApi<Lista>("/me/ocio");
  const [filtro, setFiltro] = useState<Estado | "todo">("todo");
  const [tipo, setTipo] = useState<"" | Tipo>("");
  const [abierta, setAbierta] = useState<number | null>(null);
  const a = useAct(list.reload);
  const items = list.data?.items;

  const visibles = useMemo(() => (items ?? [])
    .filter((i) => (filtro === "todo" || i.estado === filtro) && (!tipo || i.tipo === tipo))
    .sort((x, y) => ORDEN[x.estado] - ORDEN[y.estado]), [items, filtro, tipo]);
  const cuenta = (e: Estado) => items?.filter((i) => i.estado === e && (!tipo || i.tipo === tipo)).length ?? 0;
  const actual = items?.find((i) => i.id === abierta) ?? null;

  return (
    <div className="grid gap-4">
      {list.error && <ErrorState message={list.error} />}
      {list.data && <Buscador tmdb={list.data.tmdb} onAdded={list.reload} />}
      {a.ErrorBox}
      <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Filtrar">
        {([["todo", "Todo"], ...ESTADOS] as [Estado | "todo", string][]).map(([k, l]) => (
          <Button key={k} size="sm" variant={filtro === k ? "default" : "outline"} aria-pressed={filtro === k} onClick={() => setFiltro(k)}>
            {l}{k !== "todo" && <span className="tabular-nums opacity-70">{cuenta(k)}</span>}
          </Button>
        ))}
        <span className="flex-1" />
        <select aria-label="Tipo" className={selectClass} value={tipo} onChange={(e) => setTipo(e.target.value as "" | Tipo)}>
          <option value="">Pelis y series</option><option value="pelicula">Solo pelis</option><option value="serie">Solo series</option>
        </select>
      </div>
      {!list.data && !list.error && <Loading rows={4} />}
      {items?.length === 0 && <Card><CardContent><Empty message="Aún no has añadido nada. Busca arriba una peli o serie." /></CardContent></Card>}
      {!!items?.length && visibles.length === 0 && <p className="text-sm text-muted-foreground">Nada con este filtro.</p>}
      {visibles.length > 0 && (
        <ul className="grid grid-cols-2 gap-x-3 gap-y-5 sm:grid-cols-[repeat(auto-fill,minmax(150px,1fr))]">
          {visibles.map((i) => (
            <Tarjeta key={i.id} item={i} busy={a.busy} onOpen={() => setAbierta(i.id)}
              onNext={() => void a.run(() => api(`/me/ocio/${i.id}`, { method: "PATCH", body: JSON.stringify(siguiente(i)) }))} />
          ))}
        </ul>
      )}
      <Dialog open={actual != null} onOpenChange={(o) => { if (!o) setAbierta(null); }}>
        {actual && <Ficha key={`${actual.id}-${actual.estado}-${actual.temporada}-${actual.capitulo}`} item={actual} onClose={() => setAbierta(null)} onChange={list.reload} />}
      </Dialog>
    </div>
  );
}

export default function OcioPage() {
  return (
    <>
      <PageHeader title="Ocio" description="Lo que ves, lo que quieres ver y lo que te ha gustado." />
      <Tabs defaultValue="pantalla">
        <TabsList>
          <TabsTrigger value="pantalla"><Clapperboard /> Pelis y series</TabsTrigger>
        </TabsList>
        <TabsContent value="pantalla" className="pt-2"><PelisYSeries /></TabsContent>
      </Tabs>
    </>
  );
}
