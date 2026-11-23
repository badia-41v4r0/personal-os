"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { cn } from "cn";
import { visible } from "@/lib/instancia";
import { AJUSTES, AJUSTES_GROUPS, isActive, type NavItem } from "./nav";
import { usePanel } from "./shell";

/** Menú de Ajustes: columna en el PC, desplegable en el móvil. */
export function AjustesNav() {
  const path = usePathname();
  const router = useRouter();
  const { inst } = usePanel();
  const ver = (i: NavItem) => visible(inst, i.href);
  const actual = AJUSTES.find((i) => isActive(i.href, path));
  return (
    <>
      <label className="mb-4 block lg:hidden">
        <span className="sr-only">Sección de Ajustes</span>
        <select value={actual?.href ?? "/ajustes/"} onChange={(e) => router.push(e.target.value)}
          className="h-10 w-full rounded-lg border border-border bg-background px-3 text-sm">
          {AJUSTES_GROUPS.map((g) => (
            <optgroup key={g.label} label={g.label}>
              {g.items.filter(ver).map((i) => <option key={i.href} value={i.href}>{i.label}</option>)}
            </optgroup>
          ))}
        </select>
      </label>
      <nav aria-label="Ajustes" className="hidden w-52 shrink-0 space-y-4 lg:block">
        {AJUSTES_GROUPS.map((g) => (
          <div key={g.label}>
            <div className="mb-1 px-3 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">{g.label}</div>
            <ul className="space-y-0.5">
              {g.items.filter(ver).map(({ href, label, icon: Icon, hint }) => {
                const on = isActive(href, path);
                return (
                  <li key={href}>
                    <Link href={href} title={hint} aria-current={on ? "page" : undefined}
                      className={cn("flex min-h-8 items-center gap-2.5 rounded-lg px-3 py-1.5 text-sm text-muted-foreground hover:bg-muted hover:text-foreground", on && "bg-muted font-medium text-foreground")}>
                      <Icon className={cn("size-4 shrink-0", on && "text-primary")} />{label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>
    </>
  );
}

/** Pestañas enlazadas (cada una es una página). */
export function Pestanas({ items, label }: { items: NavItem[]; label: string }) {
  const path = usePathname();
  return (
    <nav aria-label={label} className="mb-5 flex gap-1 overflow-x-auto border-b border-border">
      {items.map(({ href, label: l }) => (
        <Link key={href} href={href} aria-current={isActive(href, path) ? "page" : undefined}
          className={cn("shrink-0 border-b-2 border-transparent px-3 py-2 text-sm text-muted-foreground hover:text-foreground", isActive(href, path) && "border-primary font-medium text-foreground")}>
          {l}
        </Link>
      ))}
    </nav>
  );
}
