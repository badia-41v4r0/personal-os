"use client";

import { useState } from "react";
import { useAct, TextField } from "@/components/cc/form";
import { Loading } from "@/components/cc/states";
import { Button } from "@/components/ui/button";
import { post } from "@/lib/api";
import { useApi } from "@/lib/hooks";

export type BancoEstado = {
  app_id: string; clave: boolean; banco: string; conectado: boolean; dias: number | null; valido_hasta: string | null;
  ultima: { fecha: string; hora: string; nuevos: number; por_revisar: number; saldo: string | null } | null;
  error: { fecha: string; hora: string; mensaje: string } | null;
  alias: number;
};

const fecha = (iso: string) => new Date(iso.length === 10 ? `${iso}T12:00:00` : iso).toLocaleDateString("es-ES", { day: "numeric", month: "short", year: "numeric" });

/** Dirección a la que vuelve el banco: tiene que estar en «Allowed redirect URLs» de la aplicación de Enable Banking. */
export const vuelta = () => `${window.location.origin}/finanzas/banco`;

export async function conectarBanco() {
  const r = await post<{ url: string }>("/finance/banco/conectar", { redirect_url: vuelta() });
  window.location.href = r.url;
}

export function Banco({ onDone }: { onDone: () => void }) {
  const e = useApi<BancoEstado>("/finance/banco");
  const [appId, setAppId] = useState("");
  const a = useAct(() => { e.reload(); onDone(); });
  if (e.loading || !e.data) return <Loading rows={2} />;
  const d = e.data;
  const caduca = d.dias !== null && d.dias <= 7;

  if (!d.app_id) {
    return (
      <form className="grid gap-2" onSubmit={(ev) => { ev.preventDefault(); void a.run(() => post("/finance/banco/app", { app_id: appId.trim() })); }}>
        <p className="text-sm text-muted-foreground">Descarga cada noche los movimientos de tu banco con Enable Banking (gratis para uso personal, solo lectura). Crea la aplicación en su panel y pega aquí su Application ID.</p>
        <TextField label="Application ID" value={appId} onChange={setAppId} placeholder="xxxxxxxx-xxxx-…" />
        {a.ErrorBox}
        <Button type="submit" size="sm" variant="outline" disabled={!appId.trim() || a.busy}>Guardar</Button>
      </form>
    );
  }

  return (
    <div className="space-y-3 text-sm">
      {!d.clave && <p className="text-warning">Falta la clave privada: deja el archivo <code>{d.app_id}.pem</code> en la carpeta <code>secrets/</code>.</p>}
      {d.conectado ? (
        <>
          <p>
            <span className="font-medium">{d.banco}</span> conectado. Se descargan los movimientos cada día a las 3:00.
            {d.dias !== null && <span className={caduca ? " text-warning" : " text-muted-foreground"}> {d.dias < 0 ? "El permiso ha caducado." : `Permiso válido ${d.dias} días más (hasta el ${fecha(d.valido_hasta!)}).`}</span>}
          </p>
          {d.ultima && (
            <p className="text-muted-foreground">
              Última descarga: {fecha(d.ultima.fecha)} a las {d.ultima.hora} · {d.ultima.nuevos} nuevos{d.ultima.por_revisar ? `, ${d.ultima.por_revisar} por revisar` : ""}
            </p>
          )}
          {d.error && <p role="alert" className="text-destructive">Falló el {fecha(d.error.fecha)} a las {d.error.hora}: {d.error.mensaje}</p>}
        </>
      ) : (
        <p className="text-muted-foreground">Aún no está conectado. Al pulsar «Conectar» irás a {d.banco} para dar permiso de lectura; dura hasta 180 días.</p>
      )}
      {a.ErrorBox}
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant={d.conectado && !caduca ? "outline" : "default"} disabled={!d.clave || a.busy} onClick={() => void a.run(conectarBanco)}>
          {d.conectado ? "Reconectar" : "Conectar"}
        </Button>
        {d.conectado && <Button size="sm" variant="outline" disabled={a.busy} onClick={() => void a.run(() => post("/finance/banco/sincronizar"))}>{a.busy ? "Descargando…" : "Descargar ahora"}</Button>}
      </div>
    </div>
  );
}
