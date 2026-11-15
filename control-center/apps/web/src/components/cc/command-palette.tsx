"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { FileText, Search } from "lucide-react";
import { api } from "@/lib/api";
import { NAV, NAV_SYSTEM, AGENTS_TABS } from "./nav";

type Hit = { path: string; name?: string; snippet?: string };
type Row = { key: string; label: string; hint: string; href: string };

/** Buscador global: ⌘K o Ctrl+K. Apartados del panel y notas de la vault. */
export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Hit[]>([]);
  const [i, setI] = useState(0);

  useEffect(() => {
    if (open) {
      input.current?.focus();
    }
  }, [open]);

  useEffect(() => {
    if (q.trim().length < 2) return;
    const t = setTimeout(() => {
      api<{ hits?: Hit[] } | Hit[]>(`/memory/search?q=${encodeURIComponent(q.trim())}`)
        .then((r) => setHits(Array.isArray(r) ? r : (r.hits ?? [])))
        .catch(() => setHits([]));
    }, 200);
    return () => clearTimeout(t);
  }, [q]);

  if (!open) return null;
  const needle = q.trim().toLowerCase();
  const pages: Row[] = [...NAV, ...NAV_SYSTEM, ...AGENTS_TABS]
    .filter((n, idx, all) => all.findIndex((x) => x.href === n.href) === idx)
    .filter((n) => !needle || n.label.toLowerCase().includes(needle))
    .map((n) => ({ key: n.href, label: n.label, hint: "Apartado", href: n.href }));
  const notes: Row[] = needle.length < 2 ? [] : hits.slice(0, 8).map((h) => ({ key: h.path, label: h.name ?? h.path.split("/").pop() ?? h.path, hint: "Nota", href: `/memory/?p=${encodeURIComponent(h.path)}` }));
  const rows = [...pages.slice(0, 8), ...notes];
  const go = (r?: Row) => {
    if (r) {
      router.push(r.href);
      setQ("");
      onClose();
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/40 p-4 pt-[12vh]" role="dialog" aria-modal="true" aria-label="Buscar" onClick={onClose}>
      <div className="mx-auto max-w-xl overflow-hidden rounded-xl border border-border bg-popover shadow-lg" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 border-b border-border px-3">
          <Search className="size-4 text-muted-foreground" />
          <input
            ref={input}
            value={q}
            aria-label="Buscar en el sistema"
            placeholder="Buscar en tu sistema…"
            className="h-11 min-w-0 flex-1 bg-transparent text-base outline-none md:text-sm"
            onChange={(e) => {
              setQ(e.target.value);
              setI(0);
            }}
            onKeyDown={(e) => {
              if (e.key === "Escape") onClose();
              if (e.key === "ArrowDown") {
                e.preventDefault();
                setI((n) => Math.min(n + 1, rows.length - 1));
              }
              if (e.key === "ArrowUp") {
                e.preventDefault();
                setI((n) => Math.max(n - 1, 0));
              }
              if (e.key === "Enter") go(rows[i]);
            }}
          />
        </div>
        <ul className="max-h-80 overflow-y-auto p-1">
          {rows.map((r, n) => (
            <li key={r.key}>
              <button type="button" onClick={() => go(r)} onMouseEnter={() => setI(n)} className={`flex min-h-10 w-full items-center gap-2 rounded-lg px-2.5 text-left text-sm ${n === i ? "bg-accent" : ""}`}>
                <FileText className="size-3.5 shrink-0 text-muted-foreground" />
                <span className="min-w-0 flex-1 truncate">{r.label}</span>
                <span className="text-xs text-muted-foreground">{r.hint}</span>
              </button>
            </li>
          ))}
          {rows.length === 0 && <li className="p-4 text-center text-sm text-muted-foreground">Sin resultados</li>}
        </ul>
      </div>
    </div>
  );
}
