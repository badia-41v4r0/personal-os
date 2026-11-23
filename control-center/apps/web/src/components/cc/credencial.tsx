"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { ErrorState } from "./states";

export type Credenciales = Record<"CLAUDE_CODE_OAUTH_TOKEN" | "TELEGRAM_BOT_TOKEN" | "TELEGRAM_CHAT_ID", boolean>;

/** Qué credenciales del .env están puestas (nunca su valor). */
export const useCredenciales = () => useApi<Credenciales>("/instancia/credenciales");

/**
 * Campo para poner una credencial que guarda el Host Agent en el .env (permisos 600). El valor viaja una vez, no se
 * guarda en el navegador ni en la base y nunca se vuelve a mostrar: el campo solo dice si está puesta.
 */
export function CredencialForm({ clave, etiqueta, placeholder, puesta, secreta = true, onGuardada }: {
  clave: keyof Credenciales; etiqueta: string; placeholder: string; puesta: boolean; secreta?: boolean; onGuardada: () => void;
}) {
  const [valor, setValor] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState(false);
  const id = `cred-${clave}`;
  const guardar = async () => {
    setBusy(true);
    setError(null);
    setOk(false);
    try {
      await api(`/instancia/credenciales/${clave}`, { method: "PUT", body: JSON.stringify({ valor: valor.trim() }) });
      setValor("");
      setOk(true);
      onGuardada();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <form className="space-y-1.5" onSubmit={(e) => { e.preventDefault(); if (valor.trim()) void guardar(); }}>
      <label className="block text-xs font-medium" htmlFor={id}>{etiqueta}</label>
      <div className="flex gap-2">
        <Input id={id} type={secreta ? "password" : "text"} autoComplete="off" spellCheck={false} value={valor} onChange={(e) => setValor(e.target.value)}
          placeholder={puesta ? "Guardado · escribe otro para cambiarlo" : placeholder} />
        <Button type="submit" size="sm" disabled={busy || !valor.trim()}>{busy ? "Guardando…" : "Guardar"}</Button>
      </div>
      {ok && <p role="status" className="text-xs text-success">Guardado.</p>}
      {error && <ErrorState message={error} />}
    </form>
  );
}
