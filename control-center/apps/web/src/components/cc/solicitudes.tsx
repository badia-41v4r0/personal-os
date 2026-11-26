"use client";

// Candidaturas con agente: perfil para rellenar formularios, CV y solicitudes preparadas que el usuario revisa y aprueba.
// Nada se envía desde aquí sin pulsar «Aprobar y enviar», y lo que se envía es exactamente lo que se ve en la revisión.

import { useEffect, useRef, useState } from "react";
import { useAct, TextField, selectClass } from "@/components/cc/form";
import { Empty } from "@/components/cc/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { api, post, upload } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { BASE } from "@/lib/base";

export type Doc = { id: number; nombre: string; tipo: string; sha256: string; idioma: string; tamano: number; activo: boolean; texto: boolean };
type Campo = { ref: string; etiqueta: string; tipo: string; obligatorio: boolean; valor: string | boolean | string[]; rellenado_por_el_agente: boolean };
export type Run = {
  id: string; candidatura: number; empresa: string; puesto: string; url: string; dominios: string[]; estado: string; documento: string;
  error: string; notas: string; capturas: number; creada: string;
  revision: { url: string; titulo: string; campos: Campo[]; boton: { ref: string; texto: string } } | null;
  resultado: { url: string; titulo: string; texto: string } | null;
  accion: { id: string; estado: string; hash: string } | null;
};
type Perfil = {
  nombre: string; email: string; telefono: string; ciudad: string; permiso_trabajo: string; disponibilidad: string; pretension: string;
  enlaces: { tipo: string; url: string }[]; idiomas: { idioma: string; nivel: string }[];
  respuestas: { pregunta: string; respuesta: string; verificada: boolean }[]; nunca_rellenar: string[];
};

const ESTADOS: Record<string, string> = {
  en_cola: "En cola", preparando: "El agente lo está rellenando", verificando: "Comprobando el formulario",
  listo_para_revisar: "Listo para revisar", aprobada: "Enviando", enviada: "Enviada", fallida: "Fallida (pasa a manual)",
  abortada: "Abortada (pasa a manual)", rechazada: "Rechazada", caducada: "Caducada",
};
const ACTIVOS = new Set(["en_cola", "preparando", "verificando", "aprobada"]);

const lineas = (t: string, sep: string) => t.split("\n").map((l) => l.split(sep).map((x) => x.trim())).filter((p) => p[0]);

export function PerfilCard() {
  const p = useApi<Perfil>("/me/career/profile");
  const a = useAct(p.reload);
  const [f, setF] = useState<Perfil | null>(null);
  const [txt, setTxt] = useState({ enlaces: "", idiomas: "", respuestas: "", nunca: "" });
  useEffect(() => {
    if (!p.data || f) return;
    setF(p.data);
    setTxt({
      enlaces: p.data.enlaces.map((e) => `${e.tipo} | ${e.url}`).join("\n"),
      idiomas: p.data.idiomas.map((e) => `${e.idioma} | ${e.nivel}`).join("\n"),
      respuestas: p.data.respuestas.map((e) => `${e.pregunta} | ${e.respuesta}`).join("\n"),
      nunca: p.data.nunca_rellenar.join("\n"),
    });
  }, [p.data, f]);
  if (!f) return null;
  const set = (k: keyof Perfil) => (v: string) => setF({ ...f, [k]: v });
  const guardar = () => a.run(() => api("/me/career/profile", {
    method: "PUT",
    body: JSON.stringify({
      ...f,
      enlaces: lineas(txt.enlaces, "|").map(([tipo, url]) => ({ tipo, url: url ?? "" })),
      idiomas: lineas(txt.idiomas, "|").map(([idioma, nivel]) => ({ idioma, nivel: nivel ?? "" })),
      respuestas: lineas(txt.respuestas, "|").map(([pregunta, respuesta]) => ({ pregunta, respuesta: respuesta ?? "", verificada: true })),
      nunca_rellenar: txt.nunca.split("\n").map((x) => x.trim()).filter(Boolean),
    }),
  }));
  return (
    <Card>
      <CardHeader><CardTitle>Perfil para solicitudes</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        {a.ErrorBox}
        <p className="text-xs text-muted-foreground">Lo único que el agente puede escribir en un formulario. Lo de «nunca rellenar» no se rellena aunque lo pidan.</p>
        <div className="grid gap-2 sm:grid-cols-2">
          <TextField label="Nombre" value={f.nombre} onChange={set("nombre")} />
          <TextField label="Email" value={f.email} onChange={set("email")} type="email" />
          <TextField label="Teléfono" value={f.telefono} onChange={set("telefono")} />
          <TextField label="Ciudad" value={f.ciudad} onChange={set("ciudad")} />
          <TextField label="Permiso de trabajo" value={f.permiso_trabajo} onChange={set("permiso_trabajo")} />
          <TextField label="Disponibilidad" value={f.disponibilidad} onChange={set("disponibilidad")} />
          <TextField label="Pretensión salarial" value={f.pretension} onChange={set("pretension")} />
        </div>
        {([["enlaces", "Enlaces (tipo | url, uno por línea)"], ["idiomas", "Idiomas (idioma | nivel)"],
           ["respuestas", "Respuestas estándar (pregunta | respuesta)"], ["nunca", "Nunca rellenar (uno por línea)"]] as const).map(([k, label]) => (
          <label key={k} className="block space-y-1 text-sm">
            <span className="text-xs font-medium text-muted-foreground">{label}</span>
            <Textarea rows={k === "nunca" ? 4 : 3} value={txt[k]} onChange={(e) => setTxt({ ...txt, [k]: e.target.value })} />
          </label>
        ))}
        <Button onClick={() => void guardar()} disabled={a.busy}>Guardar perfil</Button>
      </CardContent>
    </Card>
  );
}

export function DocumentosCard({ docs, reload }: { docs: Doc[]; reload: () => void }) {
  const a = useAct(reload);
  const input = useRef<HTMLInputElement>(null);
  const subir = (file: File) => a.run(() => upload(`/me/career/documents?nombre=${encodeURIComponent(file.name)}&tipo=cv`, file));
  return (
    <Card>
      <CardHeader><CardTitle>CV y documentos</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        {a.ErrorBox}
        {docs.filter((d) => d.activo).length === 0 && <Empty message="Sube tu CV (PDF, Word o texto) para poder preparar solicitudes." />}
        <ul className="divide-y divide-border">
          {docs.filter((d) => d.activo).map((d) => (
            <li key={d.id} className="flex items-center gap-2 py-2 text-sm">
              <a className="min-w-0 flex-1 truncate font-medium hover:underline" href={`${BASE}/api/v1/me/career/documents/${d.id}/file`}>{d.nombre}</a>
              <span className="font-mono text-xs text-muted-foreground" title={d.sha256}>{d.sha256.slice(0, 10)}</span>
              <Button size="sm" variant="ghost" onClick={() => void a.run(() => post(`/me/career/documents/${d.id}/archive`))}>Archivar</Button>
            </li>
          ))}
        </ul>
        <input ref={input} type="file" accept=".pdf,.doc,.docx,.odt,.txt,.md" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) void subir(f); e.target.value = ""; }} />
        <Button variant="outline" onClick={() => input.current?.click()} disabled={a.busy}>Subir CV</Button>
      </CardContent>
    </Card>
  );
}

function valor(v: Campo["valor"]) {
  if (typeof v === "boolean") return v ? "✔ marcada" : "sin marcar";
  if (Array.isArray(v)) return v.length ? `📎 ${v.join(", ")}` : "—";
  return v || "—";
}

export function Revision({ run, reload }: { run: Run; reload: () => void }) {
  const a = useAct(reload);
  const r = run.revision;
  const decidir = (aprobar: boolean) => run.accion && a.run(() => post(`/actions/${run.accion!.id}/decide`, { aprobar, hash: run.accion!.hash }));
  return (
    <div className="space-y-3 rounded-lg border border-border p-3 text-sm">
      {a.ErrorBox}
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="font-medium">{ESTADOS[run.estado] ?? run.estado}</span>
        <span className="text-xs text-muted-foreground">{run.dominios[0]}</span>
      </div>
      {run.error && <p className="text-xs text-destructive">{run.error}</p>}
      {run.notas && <p className="whitespace-pre-wrap text-xs text-muted-foreground">Notas del agente: {run.notas}</p>}
      {r && run.estado === "listo_para_revisar" && (
        <>
          <p className="break-all text-xs">Formulario: <a className="underline" href={r.url} target="_blank" rel="noreferrer">{r.url}</a></p>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead><tr className="text-left text-muted-foreground"><th className="py-1 pr-2">Campo</th><th className="py-1">Se enviará</th></tr></thead>
              <tbody>
                {r.campos.map((c) => (
                  <tr key={c.ref} className="border-t border-border align-top">
                    <td className="py-1 pr-2">{c.etiqueta}{c.obligatorio ? " *" : ""}</td>
                    <td className="break-all py-1">{valor(c.valor)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-xs">Botón que se pulsará: <strong>{r.boton.texto || r.boton.ref}</strong> · CV <span className="font-mono">{run.documento.slice(0, 10)}</span></p>
          {run.capturas > 0 && (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={`${BASE}/api/v1/me/career/runs/${run.id}/screenshot/0`} alt="Captura del formulario rellenado" className="w-full rounded border border-border" />
          )}
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => void decidir(true)} disabled={a.busy}>Aprobar y enviar</Button>
            <Button variant="outline" onClick={() => void decidir(false)} disabled={a.busy}>Rechazar</Button>
          </div>
        </>
      )}
      {run.resultado && <p className="text-xs">Respuesta de la web: {run.resultado.titulo} · <span className="break-all">{run.resultado.url}</span></p>}
      {ACTIVOS.has(run.estado) && <Button size="sm" variant="ghost" onClick={() => void a.run(() => post(`/me/career/runs/${run.id}/abort`))}>Descartar</Button>}
    </div>
  );
}

export function PrepararSolicitud({ app, docs, onDone }: { app: { id: number; enlace: string }; docs: Doc[]; onDone: () => void }) {
  const activos = docs.filter((d) => d.activo);
  const [url, setUrl] = useState(app.enlace || "");
  const [doc, setDoc] = useState<number | "">(activos[0]?.id ?? "");
  const a = useAct(onDone);
  if (!activos.length) return <p className="text-xs text-muted-foreground">Sube antes tu CV.</p>;
  return (
    <form className="grid gap-2 sm:grid-cols-[1fr_auto_auto]" onSubmit={(e) => { e.preventDefault(); void a.run(() => post(`/me/career/applications/${app.id}/runs`, { url, documento: doc })); }}>
      {a.ErrorBox}
      <TextField label="URL del formulario o de la oferta" value={url} onChange={setUrl} placeholder="https://…" required />
      <label className="space-y-1 text-sm">
        <span className="block text-xs font-medium text-muted-foreground">CV</span>
        <select className={selectClass} value={doc} onChange={(e) => setDoc(Number(e.target.value))}>
          {activos.map((d) => <option key={d.id} value={d.id}>{d.nombre}</option>)}
        </select>
      </label>
      <Button type="submit" className="self-end" disabled={a.busy || !url.startsWith("https://") || doc === ""}>Preparar</Button>
    </form>
  );
}

export function useRuns() {
  const r = useApi<Run[]>("/me/career/runs", 5000);
  return r;
}
