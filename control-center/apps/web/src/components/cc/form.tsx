"use client";

import { useState } from "react";
import type { ReactNode } from "react";
import { Input } from "@/components/ui/input";
import { ErrorState } from "./states";

/** Ejecuta una acción y deja el error a la vista. Sustituye al try/catch repetido en cada formulario. */
export function useAct(onDone?: () => void) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      onDone?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return { busy, error, run, ErrorBox: error ? <ErrorState message={error} /> : null };
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="grid gap-1 text-xs text-muted-foreground"><span>{label}</span>{children}</label>;
}

export function TextField({ label, value, onChange, ...rest }: { label: string; value: string; onChange: (v: string) => void } & Omit<React.ComponentProps<typeof Input>, "value" | "onChange">) {
  return <Field label={label}><Input value={value} onChange={(e) => onChange(e.target.value)} {...rest} /></Field>;
}

export const selectClass = "h-9 rounded-lg border border-input bg-transparent px-2 text-sm dark:bg-input/30";
