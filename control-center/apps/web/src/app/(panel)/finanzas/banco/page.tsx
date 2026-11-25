"use client";

import Link from "next/link";
import { Suspense, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { PageHeader } from "@/components/cc/shell";
import { ErrorState, Loading } from "@/components/cc/states";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { post } from "@/lib/api";

type Sync = { nuevos: number; por_revisar: number; ya_en_csv: number; saldo: string | null };

/** Aquí vuelve el banco después de dar el permiso: canjea el código y hace la primera descarga. */
function Vuelta() {
  const q = useSearchParams();
  const hecho = useRef(false);
  const [paso, setPaso] = useState<"conectando" | "descargando" | "listo">("conectando");
  const [sync, setSync] = useState<Sync | null>(null);
  const [error, setError] = useState<string | null>(null);

  const code = q.get("code");
  const state = q.get("state");
  const sinCodigo = !code || !state
    ? q.get("error_description") || q.get("error") || "El banco no ha devuelto ningún código: no se ha dado el permiso."
    : null;

  useEffect(() => {
    if (hecho.current || !code || !state) return;
    hecho.current = true;  // el código es de un solo uso
    void (async () => {
      try {
        await post("/finance/banco/vuelta", { code, state });
        setPaso("descargando");
        setSync(await post<Sync>("/finance/banco/sincronizar"));
        setPaso("listo");
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    })();
  }, [code, state]);

  return (
    <Card>
      <CardContent className="space-y-3 text-sm">
        {sinCodigo || error ? <ErrorState message={(sinCodigo || error)!} /> : paso !== "listo" ? (
          <>
            <p>{paso === "conectando" ? "Guardando el permiso del banco…" : "Conectado. Descargando tus movimientos…"}</p>
            <Loading rows={2} />
          </>
        ) : sync && (
          <>
            <p className="font-medium">Banco conectado.</p>
            <p className="text-muted-foreground">
              {sync.nuevos} movimientos nuevos{sync.por_revisar ? ` (${sync.por_revisar} por revisar)` : ""}
              {sync.ya_en_csv ? `; ${sync.ya_en_csv} ya estaban por tus extractos y no se han duplicado` : ""}.
              {sync.saldo && ` Saldo: ${Number(sync.saldo).toLocaleString("es-ES", { minimumFractionDigits: 2 })} €.`}
            </p>
            <p className="text-muted-foreground">A partir de ahora se descargan solos cada día a las 3:00.</p>
          </>
        )}
        <Link href="/finanzas/" className={buttonVariants({ size: "sm", variant: "outline" })}>Volver a Finanzas</Link>
      </CardContent>
    </Card>
  );
}

export default function BancoVueltaPage() {
  return (
    <>
      <PageHeader title="Conectar el banco" description="Permiso de solo lectura con Enable Banking." />
      <Suspense fallback={<Loading rows={3} />}><Vuelta /></Suspense>
    </>
  );
}
