"use client";

import Link from "next/link";
import { ChevronRight, LogOut } from "lucide-react";
import { useRouter } from "next/navigation";
import { AJUSTES_GROUPS, NAV_GROUPS, type NavItem } from "@/components/cc/nav";
import { usePanel } from "@/components/cc/shell";
import { StatusDot } from "@/components/cc/status";
import { Button } from "@/components/ui/button";
import { visible } from "@/lib/instancia";
import { useApi } from "@/lib/hooks";
import { post, setCsrf } from "@/lib/api";
import { asistente } from "@/lib/asistente";

type Resumen = {
  gym: { sesiones: number; planificadas: number };
  estudios: { entregas_semana: number };
  carrera: { ofertas_nuevas: number };
  tareas: { pendientes: number; atrasadas: number };
  objetivos: unknown[] | null;
};

const plural = (n: number, uno: string, varios: string) => `${n} ${n === 1 ? uno : varios}`;

/** Pantalla «Más» del móvil: todos los apartados y los ajustes en una sola lista, con el dato clave de cada uno. */
export default function Mas() {
  const { inst, me, live } = usePanel();
  const router = useRouter();
  const home = useApi<Resumen>("/home", 120000);
  const d = home.data;
  const dato: Record<string, string | undefined> = d ? {
    "/educacion/": d.estudios.entregas_semana ? plural(d.estudios.entregas_semana, "entrega", "entregas") : undefined,
    "/entrenamiento/": d.gym.planificadas ? `${d.gym.sesiones} / ${d.gym.planificadas}` : undefined,
    "/carrera/": d.carrera.ofertas_nuevas ? plural(d.carrera.ofertas_nuevas, "nueva", "nuevas") : undefined,
    "/tareas/": d.tareas.atrasadas ? plural(d.tareas.atrasadas, "atrasada", "atrasadas") : d.tareas.pendientes ? plural(d.tareas.pendientes, "pendiente", "pendientes") : undefined,
    "/objetivos/": d.objetivos ? plural(d.objetivos.length, "activo", "activos") : undefined,
  } : {};
  const ver = (i: NavItem) => i.href !== "/" && visible(inst, i.href);
  const areas = (NAV_GROUPS.find((g) => g.label === "Tus áreas")?.items ?? []).filter(ver);
  const resto = [
    ...(NAV_GROUPS.find((g) => g.label === "Hoy")?.items ?? []).filter((i) => i.href === "/tareas/"),
    ...(NAV_GROUPS.find((g) => g.label === "Conocimiento")?.items ?? []),
  ].filter(ver);
  const logout = async () => {
    try { await post("/auth/logout"); } finally { setCsrf(null); router.replace("/login/"); }
  };

  return (
    <div className="space-y-5">
      <section aria-label="Tus áreas">
        <h2 className="mb-2 px-1 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">Tus áreas</h2>
        <div className="grid grid-cols-3 gap-2">
          {areas.map(({ href, label, icon: Icon }) => (
            <Link key={href} href={href} className="flex min-h-24 min-w-0 flex-col items-center justify-center gap-1.5 rounded-xl border border-border bg-card px-1 py-3 text-center text-xs font-medium transition-colors active:bg-muted">
              <Icon className="size-6 text-primary" strokeWidth={1.7} />
              <span className="w-full truncate">{label}</span>
              {dato[href] && <span className="text-[10px] font-normal text-muted-foreground">{dato[href]}</span>}
            </Link>
          ))}
        </div>
      </section>

      <Lista items={resto} dato={dato} />

      <section aria-label="Ajustes">
        <h2 className="mb-2 px-1 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">Ajustes</h2>
        <div className="space-y-4">
          {AJUSTES_GROUPS.map((g) => (
            <div key={g.label}>
              <div className="mb-1 px-1 text-xs text-muted-foreground">{g.label}</div>
              <Lista items={g.items.filter(ver)} dato={{}} />
            </div>
          ))}
         
        </div>
      </section>

      <div className="flex items-center justify-between rounded-xl border border-border bg-card px-4 py-3 text-sm">
        <div className="min-w-0">
          <div className="truncate font-medium">{me.username}</div>
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <StatusDot level={live === "ws" ? "ok" : live === "poll" ? "warn" : "unknown"} pulse />
            {live === "ws" ? "Tiempo real" : live === "poll" ? "Sondeo cada 5 s" : "Conectando…"} · {asistente()}
          </div>
        </div>
        <Button variant="outline" size="sm" onClick={logout}><LogOut /> Salir</Button>
      </div>
    </div>
  );
}

function Lista({ items, dato }: { items: NavItem[]; dato: Record<string, string | undefined> }) {
  if (items.length === 0) return null;
  return (
    <div className="divide-y divide-border overflow-hidden rounded-xl border border-border bg-card">
      {items.map(({ href, label, icon: Icon, hint }) => (
        <Link key={href} href={href} className="flex min-h-12 items-center gap-3 px-4 py-2 text-sm active:bg-muted">
          <Icon className="size-[18px] shrink-0 text-muted-foreground" />
          <span className="min-w-0 flex-1">
            <span className="block truncate">{label}</span>
            {hint && <span className="block truncate text-[11px] text-muted-foreground">{hint}</span>}
          </span>
          {dato[href] && <span className="shrink-0 text-xs text-muted-foreground">{dato[href]}</span>}
          <ChevronRight className="size-4 shrink-0 text-muted-foreground" />
        </Link>
      ))}
    </div>
  );
}
