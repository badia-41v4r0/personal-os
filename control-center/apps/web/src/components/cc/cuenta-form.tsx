"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ErrorState } from "@/components/cc/states";
import { post } from "@/lib/api";

/** Cambiar usuario y contraseña propios. `obligatorio`: el primer acceso con admin/admin (la contraseña es obligatoria). */
export function CuentaForm({ usuario, obligatorio = false, onHecho }: { usuario: string; obligatorio?: boolean; onHecho: (u: string) => void }) {
  const [nuevoUsuario, setNuevoUsuario] = useState(obligatorio ? "" : usuario);
  const [actual, setActual] = useState("");
  const [nueva, setNueva] = useState("");
  const [repite, setRepite] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState(false);
  const [busy, setBusy] = useState(false);
  const cambiaClave = obligatorio || nueva.length > 0;
  const valido = actual.length > 0 && (!cambiaClave || (nueva.length >= 12 && nueva === repite)) && (cambiaClave || nuevoUsuario.trim() !== usuario);

  const enviar = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setOk(false);
    try {
      const r = await post<{ username: string }>("/auth/cuenta", {
        actual, usuario: nuevoUsuario.trim() || null, nueva: cambiaClave ? nueva : null,
      });
      setActual(""); setNueva(""); setRepite(""); setOk(true);
      onHecho(r.username);
    } catch (x) {
      setError(x instanceof Error ? x.message : String(x));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={enviar} className="space-y-3 text-sm">
      <label className="block space-y-1" htmlFor="c-usuario"><span className="font-medium">Usuario{obligatorio ? " nuevo (opcional)" : ""}</span>
        <Input id="c-usuario" autoComplete="username" value={nuevoUsuario} onChange={(e) => setNuevoUsuario(e.target.value)} placeholder={obligatorio ? `Deja vacío para seguir con «${usuario}»` : ""} /></label>
      <label className="block space-y-1" htmlFor="c-actual"><span className="font-medium">Contraseña actual</span>
        <Input id="c-actual" type="password" autoComplete="current-password" value={actual} onChange={(e) => setActual(e.target.value)} /></label>
      <div className="space-y-1">
        <label className="block font-medium" htmlFor="c-nueva">Contraseña nueva{obligatorio ? "" : " (vacía para no cambiarla)"}</label>
        <Input id="c-nueva" type="password" autoComplete="new-password" aria-describedby="c-nueva-ayuda" value={nueva} onChange={(e) => setNueva(e.target.value)} />
        <p id="c-nueva-ayuda" className="text-xs text-muted-foreground">Al menos 12 caracteres. Una frase de varias palabras es fácil de recordar y difícil de adivinar.</p>
      </div>
      {cambiaClave && (
        <label className="block space-y-1" htmlFor="c-repite"><span className="font-medium">Repite la contraseña nueva</span>
          <Input id="c-repite" type="password" autoComplete="new-password" value={repite} onChange={(e) => setRepite(e.target.value)} />
          {repite.length > 0 && nueva !== repite && <span className="block text-xs text-destructive">No coinciden</span>}</label>
      )}
      {error && <ErrorState message={error} />}
      {ok && !obligatorio && <p className="text-xs text-success">Guardado. Las demás sesiones abiertas se han cerrado.</p>}
      <div className="flex justify-end"><Button type="submit" disabled={busy || !valido}>{obligatorio ? "Guardar y entrar" : "Guardar"}</Button></div>
    </form>
  );
}
