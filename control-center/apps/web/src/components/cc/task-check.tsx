"use client";

// Casilla para marcar una tarea de Tareas.md como hecha (o deshacerlo) desde el panel.
// El backend la marca en Tareas.md y en su casilla del Panel de hoy, así la regeneración no la deshace.

import { useState } from "react";
import { AlertTriangle, Check, Loader2, Undo2 } from "lucide-react";
import { cn } from "cn";
import { post } from "@/lib/api";

export function TaskCheck({ texto, hecho = false, onDone, className }: { texto: string; hecho?: boolean; onDone?: () => void; className?: string }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function toggle() {
    setBusy(true);
    setError(null);
    try {
      await post("/tasks/done", { texto, hecho: !hecho });
      onDone?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      onDone?.();  // si falló porque la tarea ya había cambiado (409), recarga para enseñar el estado real
    } finally {
      setBusy(false);
    }
  }
  const aviso = error ? (
    <span role="alert" className="inline-flex max-w-48 items-center gap-1 text-[11px] leading-tight text-destructive"><AlertTriangle className="size-3 shrink-0" />{error}</span>
  ) : null;
  if (hecho) {
    return (
      <>
      <button type="button" onClick={toggle} disabled={busy} title={error ?? "Deshacer: volver a pendiente"} aria-label={`Deshacer «${texto}»`}
        className={cn("relative inline-flex size-6 shrink-0 before:absolute before:-inset-1 before:content-[''] items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-50", error && "text-destructive", className)}>
        {busy ? <Loader2 className="size-3.5 animate-spin" /> : <Undo2 className="size-3.5" />}
      </button>
      {aviso}
      </>
    );
  }
  return (
    <>
    <button type="button" onClick={toggle} disabled={busy} title={error ?? "Marcar como hecha"} aria-label={`Marcar «${texto}» como hecha`}
      className={cn("group/check relative inline-flex size-[18px] shrink-0 before:absolute before:-inset-2 before:content-[''] items-center justify-center rounded-[5px] ring-1 ring-border transition-colors hover:bg-success/15 hover:ring-success disabled:opacity-50",
        error && "ring-destructive", className)}>
      {busy ? <Loader2 className="size-3 animate-spin" /> : <Check className="size-3 text-success opacity-0 group-hover/check:opacity-100" />}
    </button>
    {aviso}
    </>
  );
}
