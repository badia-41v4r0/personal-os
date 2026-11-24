"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { Bell, LogOut, Menu, Search } from "lucide-react";
import { cn } from "cn";
import { api, post, setCsrf } from "@/lib/api";
import { useApi, useEvents, type BusEvent } from "@/lib/hooks";
import { syncPush } from "@/lib/push";
import { visible, moduloDe, type Instancia } from "@/lib/instancia";
import { OnboardingBanner } from "./onboarding-banner";
import { CuentaForm } from "./cuenta-form";
import { Button } from "@/components/ui/button";
import { NAV_AJUSTES, NAV_GROUPS, NAV_MOBILE, enSeccion, isActive, tituloDe, type NavItem } from "./nav";
import { CommandPalette } from "./command-palette";
import { ChatFlotante } from "./chat/chat-flotante";
import { StatusDot } from "./status";
import { asistente, setAsistente } from "@/lib/asistente";

type Me = { username: string; role: string; csrf_token: string; must_change_password?: boolean };
type Ctx = { me: Me; lastEvent: BusEvent | null; live: "ws" | "poll" | "off"; subscribe: (fn: (e: BusEvent) => void) => () => void; inst: Instancia | null; reloadInst: () => void };
const PanelCtx = createContext<Ctx | null>(null);

export function usePanel() {
  const c = useContext(PanelCtx);
  if (!c) throw new Error("usePanel fuera del panel");
  return c;
}

function NavList({ items, onNavigate, path, label }: { items: NavItem[]; onNavigate?: () => void; path: string; label: string }) {
  const { inst } = usePanel();
  items = items.filter((i) => visible(inst, i.href));
  return (
    <div className="flex flex-col gap-0.5" role="group" aria-label={label}>
      {items.map(({ href, label: text, icon: Icon }) => {
        const active = enSeccion(href, path);
        return (
          <Link
            key={href}
            href={href}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            className={cn(
              "group flex min-h-9 items-center gap-3 rounded-lg px-3 py-1.5 text-sm text-sidebar-foreground/80 transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground",
              active && "bg-sidebar-accent font-medium text-sidebar-foreground",
            )}
          >
            <Icon className={cn("size-4 shrink-0", active ? "text-primary" : "text-muted-foreground group-hover:text-sidebar-foreground")} />
            <span className="flex-1 truncate">{text}</span>
          </Link>
        );
      })}
    </div>
  );
}

/** Campana: lleva a la Bandeja. El número es lo que espera tu decisión; el punto, avisos sin leer. */
function Bell_({ unread, decidir }: { unread: number; decidir: number }) {
  const partes = [decidir && `${decidir} por decidir`, unread && `${unread} sin leer`].filter(Boolean).join(", ");
  return (
    <Link href="/bandeja/" aria-label={`Bandeja${partes ? `: ${partes}` : ""}`} className="relative grid size-9 place-items-center rounded-lg hover:bg-muted">
      <Bell className="size-4" />
      {decidir > 0
        ? <span className="absolute top-0.5 right-0.5 grid h-4 min-w-4 place-items-center rounded-full bg-primary px-1 text-[10px] font-semibold text-primary-foreground">{decidir > 9 ? "9+" : decidir}</span>
        : unread > 0 && <span className="absolute top-1.5 right-1.5 size-2 rounded-full bg-primary" />}
    </Link>
  );
}

export function Shell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const path = usePathname();
  const [search, setSearch] = useState(false);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setSearch(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  const [me, setMe] = useState<Me | null>(null);
  const [lastEvent, setLastEvent] = useState<BusEvent | null>(null);
  // Suscriptores directos: el streaming no puede pasar por el estado de React (agruparía los trozos)
  const listeners = useRef(new Set<(e: BusEvent) => void>());
  const live = useEvents((e) => {
    listeners.current.forEach((f) => f(e));
    if (e.id !== 0) setLastEvent(e);
  });
  const subscribe = useCallback((fn: (e: BusEvent) => void) => {
    listeners.current.add(fn);
    return () => {
      listeners.current.delete(fn);
    };
  }, []);

  useEffect(() => {
    api<Me>("/auth/me")
      .then((m) => {
        setCsrf(m.csrf_token);
        setMe(m);
      })
      .catch(() => router.replace("/login/"));
  }, [router]);

  const logout = async () => {
    try {
      await post("/auth/logout");
    } finally {
      setCsrf(null);
      router.replace("/login/");
    }
  };

  // El chat flotante está en todas las pantallas salvo la bienvenida y la de sesiones (que tiene su propio cuadro)
  const chat = !path.startsWith("/conversaciones") && !path.startsWith("/bienvenida");
  const unread = useApi<{ unread: number; por_decidir: number }>(me ? "/notifications/count" : null, 60000);
  const { reload: reloadUnread } = unread;
  useEffect(() => {
    if (lastEvent?.type === "notification.created" || lastEvent?.type === "action.changed" || lastEvent?.type === "approval.decided") {
      reloadUnread();
    }
  }, [lastEvent, reloadUnread]);
  // Configuración de la instancia: qué módulos se ven. Se recarga cuando cambia (p. ej. desde Ajustes o el onboarding)
  const instancia = useApi<Instancia>(me ? "/instancia" : null);
  const { reload: reloadInst } = instancia;
  const inst = instancia.data;
  if (inst) setAsistente(inst.asistente);  // antes de pintar nada: todos los textos salen con su nombre
  useEffect(() => {
    if (lastEvent?.type === "config.changed") {
      reloadInst();
    }
  }, [lastEvent, reloadInst]);
  // Primera vez: el asistente de bienvenida antes que nada (solo el administrador puede configurar)
  useEffect(() => {
    if (inst && !inst.onboarding.hecho && me?.role === "admin" && !path.startsWith("/bienvenida")) {
      router.replace("/bienvenida/");
    }
  }, [inst, me, path, router]);
  useEffect(() => {
    if (me) {
      syncPush().catch(() => {});
    }
  }, [me]);

  if (me?.must_change_password) {
    // Primer acceso con el usuario de la instalación (admin/admin): nada más hasta cambiarlo
    return (
      <div className="grid min-h-dvh place-items-center p-4">
        <div className="w-full max-w-sm space-y-4 rounded-xl border border-border bg-card p-6">
          <div>
            <h1 className="text-lg font-semibold tracking-tight">Antes de empezar, protege tu panel</h1>
            <p className="mt-1 text-sm text-muted-foreground">Has entrado con el usuario de la instalación (admin / admin), que conoce todo el mundo. Elige una contraseña tuya; si quieres, también otro usuario.</p>
          </div>
          <CuentaForm usuario={me.username} obligatorio onHecho={(u) => { setMe({ ...me, username: u, must_change_password: false }); reloadInst(); }} />
        </div>
      </div>
    );
  }
  if (!me || (!inst && !instancia.error)) {
    return <div className="grid min-h-dvh place-items-center text-sm text-muted-foreground">Conectando…</div>;
  }

  const sidebar = (
    <div className="flex h-full flex-col gap-4 p-3">
      <div className="flex items-center gap-2.5 px-3 pt-2">
        <div className="grid size-8 place-items-center rounded-lg bg-primary/15 font-mono text-sm font-semibold text-primary">{asistente().charAt(0).toUpperCase()}</div>
        <div className="leading-tight">
          <div className="text-sm font-semibold tracking-tight">{asistente()}</div>
          <div className="text-[11px] text-muted-foreground">Personal OS</div>
        </div>
      </div>
      <nav aria-label="Principal" className="flex min-h-0 flex-1 flex-col gap-4">
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto">
        {NAV_GROUPS.map((g) => g.items.some((i) => visible(inst, i.href)) && (
          <div key={g.label}>
            {g.label !== "Conocimiento" && <div className="mb-1 px-3 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">{g.label}</div>}
            <NavList items={g.items} path={path} label={g.label} />
          </div>
        ))}
      </div>
      <NavList items={[NAV_AJUSTES]} path={path} label="Ajustes" />
      </nav>
      <div className="space-y-2 border-t border-sidebar-border px-3 pt-3 text-xs text-muted-foreground">
        <div className="flex items-center gap-2">
          <StatusDot level={live === "ws" ? "ok" : live === "poll" ? "warn" : "unknown"} pulse />
          {live === "ws" ? "Tiempo real" : live === "poll" ? "Sondeo cada 5 s" : "Conectando…"}
        </div>
        <div className="flex items-center justify-between">
          <span className="truncate">{me.username}</span>
          <Button variant="ghost" size="icon-sm" onClick={logout} aria-label="Cerrar sesión">
            <LogOut />
          </Button>
        </div>
      </div>
    </div>
  );

  return (
    <PanelCtx.Provider value={{ me, lastEvent, live, subscribe, inst, reloadInst }}>
      <CommandPalette open={search} onClose={() => setSearch(false)} />
      <div className="flex min-h-dvh">
        <aside className="sticky top-0 hidden h-dvh w-60 shrink-0 border-r border-sidebar-border bg-sidebar lg:block">{sidebar}</aside>
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-30 flex h-12 items-center gap-2 border-b border-border bg-background/85 px-4 backdrop-blur lg:h-14 lg:px-6">
            <span className="min-w-0 truncate text-base font-semibold tracking-tight lg:hidden">{tituloDe(path) ?? new Intl.DateTimeFormat("es-ES", { weekday: "short", day: "numeric", month: "long" }).format(new Date())}</span>
            <span className="hidden text-sm font-medium first-letter:uppercase lg:inline">{new Intl.DateTimeFormat("es-ES", { weekday: "short", day: "numeric", month: "long" }).format(new Date())}</span>
            <span className="flex-1" />
            <button type="button" onClick={() => setSearch(true)} aria-label="Buscar" className="flex h-9 items-center gap-2 rounded-lg px-2 text-sm text-muted-foreground hover:bg-muted lg:w-64 lg:border lg:border-border">
              <Search className="size-4" /><span className="hidden flex-1 text-left lg:block">Buscar…</span><kbd className="hidden font-mono text-[10px] lg:block">⌘K</kbd>
            </button>
            <Bell_ unread={unread.data?.unread ?? 0} decidir={unread.data?.por_decidir ?? 0} />
          </header>
          <div className="flex min-h-0 flex-1">
            <main className={cn("mx-auto w-full min-w-0 max-w-[1400px] flex-1 p-4 md:p-6", chat ? "pb-40 md:pb-40 lg:pb-28" : "pb-24 lg:pb-6")}>
              {visible(inst, path) ? <>{(() => { const m = moduloDe(inst, path); return m && !path.startsWith("/bienvenida") ? <OnboardingBanner key={m.id} modulo={m} /> : null; })()}{children}</> : <ModuloApagado nombre={moduloDe(inst, path)?.nombre ?? ""} />}
            </main>
          </div>
          {chat && <ChatFlotante />}
          <nav aria-label="Accesos rápidos" className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-4 border-t border-border bg-background/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden">
            {NAV_MOBILE.filter((i) => visible(inst, i.href)).map(({ href, label, icon: Icon }) => (
              <Link key={href} href={href} aria-current={isActive(href, path) ? "page" : undefined} className={cn("relative flex min-h-14 flex-col items-center justify-center gap-0.5 text-[11px] text-muted-foreground", isActive(href, path) && "text-primary")}>
                <Icon className="size-5" />{label}
                {href === "/bandeja/" && (unread.data?.por_decidir ?? 0) > 0 && <span className="absolute top-2 left-1/2 ml-2 size-2 rounded-full bg-primary" aria-label="Hay cosas por decidir" />}
              </Link>
            ))}
            <Link href="/mas/" aria-current={path.startsWith("/mas") ? "page" : undefined} className={cn("flex min-h-14 flex-col items-center justify-center gap-0.5 text-[11px] text-muted-foreground", (path.startsWith("/mas") || !NAV_MOBILE.some((i) => isActive(i.href, path))) && "text-primary")}><Menu className="size-5" />Más</Link>
          </nav>
        </div>
      </div>
    </PanelCtx.Provider>
  );
}

function ModuloApagado({ nombre }: { nombre: string }) {
  return (
    <div className="mx-auto max-w-md py-16 text-center">
      <h1 className="text-lg font-semibold">{nombre ? `${nombre} está desactivado` : "Apartado desactivado"}</h1>
      <p className="mt-2 text-sm text-muted-foreground">Puedes activarlo en <Link className="text-primary underline" href="/ajustes/modulos/">Ajustes → Módulos</Link>.</p>
    </div>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description?: string; actions?: React.ReactNode }) {
  const path = usePathname();
  // En el móvil la cabecera ya dice el nombre de la sección: no se repite como título de la página
  const repetido = tituloDe(path) === title;
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3 lg:mb-6">
      <div>
        <h1 className={cn("text-xl font-semibold tracking-tight", repetido && "sr-only lg:not-sr-only")}>{title}</h1>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions}
    </div>
  );
}
