"use client";

import { useState } from "react";
import { useAct, TextField, selectClass } from "@/components/cc/form";
import { PageHeader } from "@/components/cc/shell";
import { Empty, ErrorState, Loading } from "@/components/cc/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api, post } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { DocumentosCard, PerfilCard, PrepararSolicitud, Revision, useRuns, type Doc } from "@/components/cc/solicitudes";

type App = { id: number; empresa: string; puesto: string; estado: string; enlace: string; proximo_paso: string; follow_up: string | null };
type Oferta = { id: string; titulo: string; empresa: string; lugar: string; enlace: string; puntos: string; visto: string };
type Career = { candidaturas: App[]; ofertas: Oferta[]; estados: string[] };

export default function CarreraPage() {
  const c = useApi<Career>("/me/career");
  const [empresa, setEmpresa] = useState("");
  const [puesto, setPuesto] = useState("");
  const a = useAct(c.reload);
  const seguir = (o: Oferta) => a.run(() => post("/me/career/applications", { empresa: o.empresa, puesto: o.titulo, enlace: o.enlace, proximo_paso: "Aplicar" }));
  const yaSeguidas = new Set(c.data?.candidaturas.map((x) => x.enlace));
  const docs = useApi<Doc[]>("/me/career/documents");
  const runs = useRuns();
  const [abierta, setAbierta] = useState<number | null>(null);
  const ultima = (id: number) => runs.data?.find((r) => r.candidatura === id);
  return (
    <>
      <PageHeader title="Carrera" description="Tus candidaturas, las ofertas del radar y las solicitudes que prepara el agente (nunca se envían sin tu aprobación)." />
      {c.error && <ErrorState message={c.error} />}
      {a.ErrorBox}
      {c.loading && <Loading rows={5} />}
      {c.data && (
        <div className="grid gap-4 xl:grid-cols-2">
          <Card>
            <CardHeader><CardTitle>Candidaturas</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              {c.data.candidaturas.length === 0 && <Empty message="Aún no sigues ninguna candidatura." />}
              <ul className="divide-y divide-border">
                {c.data.candidaturas.map((x) => (
                  <li key={x.id} className="space-y-2 py-2 text-sm">
                    <div className="flex flex-wrap items-center gap-2">
                      <div className="min-w-0 flex-1">
                        <div className="truncate font-medium">{x.empresa}</div>
                        <div className="truncate text-xs text-muted-foreground">{x.puesto}{x.follow_up ? ` · seguimiento ${x.follow_up}` : ""}</div>
                      </div>
                      <select aria-label={`Estado de ${x.empresa}`} className={selectClass} value={x.estado} onChange={(e) => void a.run(() => api(`/me/career/applications/${x.id}`, { method: "PATCH", body: JSON.stringify({ estado: e.target.value }) }))}>
                        {c.data?.estados.map((s) => <option key={s}>{s}</option>)}
                      </select>
                      <Button size="sm" variant="outline" onClick={() => setAbierta(abierta === x.id ? null : x.id)}>Preparar solicitud</Button>
                      <Button size="sm" variant="ghost" aria-label={`Borrar la candidatura de ${x.empresa}`} disabled={a.busy} onClick={() => { if (window.confirm(`¿Borrar la candidatura «${x.empresa} · ${x.puesto}»? No se puede deshacer.`)) void a.run(() => api(`/me/career/applications/${x.id}`, { method: "DELETE" })); }}>Borrar</Button>
                    </div>
                    {abierta === x.id && <PrepararSolicitud app={x} docs={docs.data ?? []} onDone={() => { setAbierta(null); runs.reload(); }} />}
                    {ultima(x.id) && <Revision run={ultima(x.id)!} reload={() => { runs.reload(); c.reload(); }} />}
                  </li>
                ))}
              </ul>
              <form className="grid gap-2 sm:grid-cols-[1fr_1fr_auto]" onSubmit={(e) => { e.preventDefault(); void a.run(() => post("/me/career/applications", { empresa, puesto })).then(() => { setEmpresa(""); setPuesto(""); }); }}>
                <TextField label="Empresa" value={empresa} onChange={setEmpresa} required />
                <TextField label="Puesto" value={puesto} onChange={setPuesto} required />
                <Button type="submit" className="self-end" disabled={a.busy || !empresa.trim() || !puesto.trim()}>Añadir</Button>
              </form>
            </CardContent>
          </Card>
          <DocumentosCard docs={docs.data ?? []} reload={docs.reload} />
          <PerfilCard />
          <Card>
            <CardHeader><CardTitle>Ofertas del radar</CardTitle></CardHeader>
            <CardContent>
              {c.data.ofertas.length === 0 && <Empty message="Sin ofertas relevantes en los últimos 14 días." />}
              <ul className="divide-y divide-border">
                {c.data.ofertas.map((o) => (
                  <li key={o.id} className="flex items-center gap-2 py-2 text-sm">
                    <div className="min-w-0 flex-1">
                      <a href={o.enlace} target="_blank" rel="noreferrer" className="block truncate font-medium hover:underline">{o.titulo}</a>
                      <div className="truncate text-xs text-muted-foreground">{o.empresa} · {o.lugar}</div>
                    </div>
                    <Button size="sm" variant="outline" disabled={yaSeguidas.has(o.enlace)} onClick={() => void seguir(o)}>{yaSeguidas.has(o.enlace) ? "Siguiendo" : "Seguir"}</Button>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        </div>
      )}
    </>
  );
}
