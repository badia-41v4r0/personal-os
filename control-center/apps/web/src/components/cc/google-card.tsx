"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { post } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { useAct } from "./form";
import { ErrorState } from "./states";

type Cuenta = {
  cuenta: string;
  email: string;
  autorizada: boolean;
  edad_dias: number | null;
  dias_restantes: number | null;
  caducada: boolean;
};

const NOMBRE: Record<string, string> = { personal: "Personal (calendario y correo)", secundaria: "Segunda cuenta (correo)" };

function estado(c: Cuenta): { texto: string; tono: "ok" | "aviso" | "mal" } {
  if (!c.autorizada) return { texto: "Sin autorizar", tono: "mal" };
  if (c.caducada) return { texto: "Caducado", tono: "mal" };
  const d = c.dias_restantes ?? 0;
  if (d <= 2) return { texto: `Caduca en ${d < 1 ? "menos de 1 día" : `${Math.ceil(d)} días`}`, tono: "aviso" };
  return { texto: `Vigente · ${Math.floor(d)} días`, tono: "ok" };
}

/** Renovación de un permiso: 1) abrir Google, 2) pegar la dirección final (que en el móvil no carga, es normal). */
function Renovar({ c, onDone, autoStart }: { c: Cuenta; onDone: () => void; autoStart?: boolean }) {
  const [url, setUrl] = useState<string | null>(null);
  const [pegado, setPegado] = useState("");
  const [ok, setOk] = useState(false);
  const start = useAct();
  const fin = useAct();

  const empezar = () =>
    start.run(async () => {
      setOk(false);
      setPegado("");
      setUrl((await post<{ url: string }>(`/system/google/${c.cuenta}/renovar`)).url);
    });
  const confirmar = () =>
    fin.run(async () => {
      await post(`/system/google/${c.cuenta}/callback`, { pegado });
      setUrl(null);
      setOk(true);
      onDone();
    });

  useEffect(() => {
    if (autoStart) {
      void empezar();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoStart]);

  return (
    <div className="space-y-2">
      {!url && (
        <Button size="sm" variant={c.caducada || !c.autorizada ? "default" : "outline"} disabled={start.busy} onClick={() => void empezar()}>
          {start.busy ? "Preparando…" : "Renovar"}
        </Button>
      )}
      {ok && <p className="text-xs text-success">Renovado. El calendario y el correo ya funcionan otra vez.</p>}
      {start.ErrorBox}
      {url && (
        <ol className="space-y-2 text-xs text-muted-foreground">
          <li>
            1. Abre Google, elige {c.email} y pulsa Continuar:{" "}
            <a className="inline-flex min-h-9 items-center text-primary underline" href={url} target="_blank" rel="noopener noreferrer">
              Abrir Google
            </a>
          </li>
          <li>
            2. Te llevará a una página que no carga (127.0.0.1). Es lo esperado: copia su dirección completa y pégala aquí.
            <div className="mt-1 flex gap-2">
              <Input value={pegado} onChange={(e) => setPegado(e.target.value)} placeholder="http://127.0.0.1:8765/?state=…&code=…" autoCapitalize="none" autoCorrect="off" spellCheck={false} />
              <Button size="sm" disabled={fin.busy || pegado.trim().length < 10} onClick={() => void confirmar()}>
                {fin.busy ? "Comprobando…" : "Confirmar"}
              </Button>
            </div>
          </li>
          <li>El enlace vale 10 minutos.</li>
        </ol>
      )}
      {fin.ErrorBox}
    </div>
  );
}

export function GoogleCard() {
  const g = useApi<Cuenta[]>("/system/google", 60000);
  const [cola, setCola] = useState<string[]>([]);
  const [activa, setActiva] = useState<string | null>(null);

  const siguiente = (hecha: string) => {
    g.reload();
    const resto = cola.filter((x) => x !== hecha);
    setCola(resto);
    setActiva(resto[0] ?? null);
  };

  return (
    <Card>
      <CardHeader><CardTitle>Permisos de Google</CardTitle></CardHeader>
      <CardContent className="space-y-4 text-sm">
        <p className="text-xs text-muted-foreground">
          La app de Google está en modo Prueba: cada permiso caduca a los 7 días. Renovarlo son dos toques desde el móvil o el Mac.
        </p>
        {g.error && <ErrorState message={g.error} />}
        {g.data?.map((c) => {
          const e = estado(c);
          return (
            <div key={c.cuenta} className="space-y-2 rounded-lg border border-border p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <div className="font-medium">{NOMBRE[c.cuenta] ?? c.cuenta}</div>
                  <div className="text-xs text-muted-foreground">{c.email}</div>
                </div>
                <Badge variant={e.tono === "ok" ? "secondary" : "destructive"} className={e.tono === "aviso" ? "bg-warning text-warning-foreground" : undefined}>{e.texto}</Badge>
              </div>
              <Renovar c={c} onDone={() => siguiente(c.cuenta)} autoStart={activa === c.cuenta} />
            </div>
          );
        })}
        {g.data && g.data.length > 1 && !activa && (
          <Button size="sm" variant="outline" onClick={() => { const todas = g.data!.map((c) => c.cuenta); setCola(todas); setActiva(todas[0]); }}>
            Renovar las dos, una detrás de otra
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
