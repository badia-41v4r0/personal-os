"use client";

// Adjuntos del chat (Jarvis y conversaciones independientes): clip, arrastrar y pegar.
// Se suben uno a uno al enviar; el backend los guarda en la carpeta común del PC (archivos/Entrada/<día>).

import { useState, type DragEvent } from "react";
import { FileText, Paperclip, X } from "lucide-react";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "cn";
import { upload } from "@/lib/api";

export const MAX_FILE = 20 * 1024 * 1024; // como Telegram
export const MAX_FILES = 10;

const size = (n: number) => (n < 1024 * 1024 ? `${Math.max(1, Math.round(n / 1024))} KB` : `${(n / 1024 / 1024).toFixed(1)} MB`);

export function useAttachments(onError: (msg: string) => void) {
  const [files, setFiles] = useState<File[]>([]);
  const [dragging, setDragging] = useState(false);

  const add = (list: FileList | File[] | null) => {
    if (!list) return;
    const nuevos = Array.from(list);
    const grandes = nuevos.filter((f) => f.size > MAX_FILE).map((f) => f.name);
    const vacios = nuevos.filter((f) => f.size === 0).map((f) => f.name);
    const ok = nuevos.filter((f) => f.size > 0 && f.size <= MAX_FILE);
    if (grandes.length) onError(`Pasan de 20 MB: ${grandes.join(", ")}`);
    else if (vacios.length) onError(`Vacíos: ${vacios.join(", ")}`);
    else if (files.length + ok.length > MAX_FILES) onError(`Como mucho ${MAX_FILES} archivos por mensaje`);
    setFiles((p) => [...p, ...ok].slice(0, MAX_FILES));
  };

  /** Sube los pendientes a `url` y devuelve lo que el backend espera en `attachments`. */
  const uploadAll = async (url: string, field: "name" | "path") => {
    const out: string[] = [];
    for (const f of files) {
      const r = await upload<{ name: string; path: string }>(`${url}?name=${encodeURIComponent(f.name || "archivo")}`, f);
      out.push(r[field]);
    }
    return out;
  };

  const dropProps = (disabled: boolean) => ({
    onDragOver: (e: DragEvent) => {
      if (!disabled && e.dataTransfer.types.includes("Files")) {
        e.preventDefault();
        setDragging(true);
      }
    },
    onDragLeave: (e: DragEvent) => {
      if (e.currentTarget === e.target) setDragging(false);
    },
    onDrop: (e: DragEvent) => {
      if (disabled || !e.dataTransfer.files.length) return;
      e.preventDefault();
      setDragging(false);
      add(e.dataTransfer.files);
    },
  });

  return {
    files,
    dragging,
    add,
    uploadAll,
    dropProps,
    remove: (i: number) => setFiles((p) => p.filter((_, j) => j !== i)),
    clear: () => setFiles([]),
  };
}

export type Attachments = ReturnType<typeof useAttachments>;

export function DropOverlay({ a }: { a: Attachments }) {
  if (!a.dragging) return null;
  return (
    <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center bg-background/75 text-sm font-medium text-primary ring-2 ring-primary/50 ring-inset">
      Suelta para adjuntar
    </div>
  );
}

export function AttachmentChips({ a, disabled }: { a: Attachments; disabled?: boolean }) {
  return (
    <>
      {a.files.length > 0 && (
        <ul className="mb-2 flex flex-wrap gap-1.5" aria-label="Adjuntos">
          {a.files.map((f, i) => (
            <li key={`${f.name}-${i}`} className="flex max-w-full min-w-0 items-center gap-1.5 rounded-md bg-muted py-1 pr-1 pl-2 text-xs">
              <FileText className="size-3 shrink-0 text-muted-foreground" />
              <span className="truncate">{f.name || "archivo"}</span>
              <span className="shrink-0 text-muted-foreground">{size(f.size)}</span>
              <button type="button" disabled={disabled} onClick={() => a.remove(i)} aria-label={`Quitar ${f.name}`}
                className="flex size-6 shrink-0 items-center justify-center rounded hover:bg-background">
                <X className="size-3" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

export function AttachButton({ a, disabled }: { a: Attachments; disabled?: boolean }) {
  const off = disabled || a.files.length >= MAX_FILES;
  return (
    <label title="Adjuntar archivos (también puedes arrastrarlos o pegarlos)"
      className={cn(buttonVariants({ variant: "ghost", size: "sm" }), off ? "pointer-events-none opacity-50" : "cursor-pointer",
        "has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring")}>
      <Paperclip /> Adjuntar
      <input type="file" multiple disabled={off} className="sr-only"
        onChange={(e) => { a.add(e.target.files); e.target.value = ""; }} />
    </label>
  );
}

/** Para el onPaste del cuadro de texto: si se pegan archivos (p. ej. una captura), se adjuntan. */
export const pasteFiles = (a: Attachments) => (e: React.ClipboardEvent) => {
  if (e.clipboardData.files.length) {
    e.preventDefault();
    a.add(e.clipboardData.files);
  }
};
