"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { Bell, LogOut, Menu, PanelRightClose, PanelRightOpen, Search, X } from "lucide-react";
import { cn } from "cn";
import { api, post, setCsrf } from "@/lib/api";
import { useApi, useEvents, type BusEvent } from "@/lib/hooks";
import { syncPush } from "@/lib/push";
import { visible, moduloDe, type Instancia } from "@/lib/instancia";
import { OnboardingBanner } from "./onboarding-banner";
import { CuentaForm } from "./cuenta-form";
import { Button } from "@/components/ui/button";
import { AGENTS_TABS, NAV, NAV_MOBILE, NAV_SYSTEM, isActive, type NavItem } from "./nav";
import { CommandPalette } from "./command-palette";
import { assistantFor } from "./assistants";
import { JarvisDock } from "./jarvis-dock";
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
    <nav className="flex flex-col gap-0.5" aria-label={label}>
      {items.map(({ href, label: text, icon: Icon }) => {
        const active = isActive(href, path) || (href === "/agents/" && AGENTS_TABS.some((t) => isActive(t.href, path)));
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
    </nav>
  );
}

function AgentTabs({ path }: { path: string }) {
  const { inst } = usePanel();
  if (!AGENTS_TABS.some((t) => isActive(t.href, path))) return null;
  const tabs = AGENTS_TABS.filter((t) => visible(inst, t.href));
  return (
    <nav aria-label="Secciones de Agentes" className="mb-5 flex gap-1 overflow-x-auto border-b border-border">
      {tabs.map(({ href, label }) => (
        <Link key={href} href={href} aria-current={isActive(href, path) ? "page" : undefined}
          className={cn("shrink-0 border-b-2 border-transparent px-3 py-2 text-sm text-muted-foreground hover:text-foreground", isActive(href, path) && "border-primary font-medium text-foreground")}>
          {label}
        </Link>
      ))}
    </nav>
  );
}

function Bell_({ unread }: { unread: number }) {
  return (
    <Link href="/avisos/" aria-label={`Avisos${unread ? `, ${unread} sin leer` : ""}`} className="relative grid size-9 place-items-center rounded-lg hover:bg-muted">
      <Bell className="size-4" />
      {unread > 0 && <span className="absolute top-1.5 right-1.5 size-2 rounded-full bg-primary" />}
    </Link>
  );
}

export function Shell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const path = usePathname();
  const [dock, setDock] = useState(true);
  const [sheet, setSheet] = useState(false);
  const assistant = assistantFor(path);
  const [search, setSearch] = useState(false);
  // Otras pantallas piden abrir el chat del apartado (p. ej. «Estudiar ahora» manda un mensaje al tutor)
  useEffect(() => {
    const open = () => { setDock(true); setSheet(true); };
    window.addEventListener("cc:open-dock", open);
    return () => window.removeEventListener("cc:open-dock", open);
  }, []);
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
  const [open, setOpen] = useState(false);
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

  const isChat = path.startsWith("/chat");
  const unread = useApi<{ unread: number }>(me ? "/notifications/count" : null, 60000);
  const { reload: reloadUnread } = unread;
  useEffect(() => {
    if (lastEvent?.type === "notification.created") {
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
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto">
        <NavList items={NAV} path={path} label="Principal" onNavigate={() => setOpen(false)} />
        <div className="border-t border-sidebar-border pt-3"><NavList items={NAV_SYSTEM} path={path} label="Sistema" onNavigate={() => setOpen(false)} /></div>
      </div>
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
        {open && (
          <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true">
            <div className="absolute inset-0 bg-black/60" onClick={() => setOpen(false)} />
            <aside className="absolute inset-y-0 left-0 w-64 border-r border-sidebar-border bg-sidebar">
              <Button variant="ghost" size="icon-sm" className="absolute top-3 right-3" onClick={() => setOpen(false)} aria-label="Cerrar menú">
                <X />
              </Button>
              {sidebar}
            </aside>
          </div>
        )}
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-30 flex h-12 items-center gap-2 border-b border-border bg-background/85 px-4 backdrop-blur lg:h-14 lg:px-6">
            <Button variant="ghost" size="icon-sm" className="lg:hidden" onClick={() => setOpen(true)} aria-label="Abrir menú">
              <Menu />
            </Button>
            <span className="text-sm font-medium first-letter:uppercase">{new Intl.DateTimeFormat("es-ES", { weekday: "short", day: "numeric", month: "long" }).format(new Date())}</span>
            <span className="flex-1" />
            <button type="button" onClick={() => setSearch(true)} aria-label="Buscar" className="flex h-9 items-center gap-2 rounded-lg px-2 text-sm text-muted-foreground hover:bg-muted lg:w-64 lg:border lg:border-border">
              <Search className="size-4" /><span className="hidden flex-1 text-left lg:block">Buscar…</span><kbd className="hidden font-mono text-[10px] lg:block">⌘K</kbd>
            </button>
            <Bell_ unread={unread.data?.unread ?? 0} />
            {!isChat && (
              <Button variant="ghost" size="icon-sm" className="hidden xl:inline-flex" onClick={() => setDock((d) => !d)} aria-label={dock ? `Ocultar ${assistant.name}` : `Mostrar ${assistant.name}`} aria-pressed={dock}>
                {dock ? <PanelRightClose /> : <PanelRightOpen />}
              </Button>
            )}
          </header>
          <div className="flex min-h-0 flex-1">
            <main className="mx-auto w-full min-w-0 max-w-[1400px] flex-1 p-4 pb-24 md:p-6 lg:pb-6">
              <AgentTabs path={path} />
              {visible(inst, path) ? <>{(() => { const m = moduloDe(inst, path); return m && !path.startsWith("/bienvenida") ? <OnboardingBanner key={m.id} modulo={m} /> : null; })()}{children}</> : <ModuloApagado nombre={moduloDe(inst, path)?.nombre ?? ""} />}
            </main>
            {dock && !isChat && <aside aria-label={assistant.name} className="sticky top-14 hidden h-[calc(100dvh-3.5rem)] w-80 shrink-0 border-l border-border bg-card xl:block"><JarvisDock key={assistant.base} assistant={assistant} /></aside>}
          </div>
          {sheet && <div role="dialog" aria-modal="true" aria-label={assistant.name} className="fixed inset-0 z-50 bg-card pt-[env(safe-area-inset-top)] pb-[env(safe-area-inset-bottom)] xl:hidden"><JarvisDock key={assistant.base} assistant={assistant} onClose={() => setSheet(false)} /></div>}
          <nav aria-label="Accesos rápidos" className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-5 border-t border-border bg-background/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden">
            {NAV_MOBILE.filter((i) => visible(inst, i.href)).map(({ href, label, icon: Icon }) => href === "/chat/" ? (
              <button key={href} type="button" onClick={() => setSheet(true)} className="flex min-h-14 flex-col items-center justify-center gap-0.5 text-[11px] text-muted-foreground"><Icon className="size-5" />{assistant.key ? assistant.name.split(" ")[0] : asistente()}</button>
            ) : (
              <Link key={href} href={href} aria-current={isActive(href, path) ? "page" : undefined} className={cn("flex min-h-14 flex-col items-center justify-center gap-0.5 text-[11px] text-muted-foreground", isActive(href, path) && "text-primary")}>
                <Icon className="size-5" />{label}
              </Link>
            ))}
            <button type="button" onClick={() => setOpen(true)} className="flex min-h-14 flex-col items-center justify-center gap-0.5 text-[11px] text-muted-foreground"><Menu className="size-5" />Más</button>
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
      <p className="mt-2 text-sm text-muted-foreground">Puedes activarlo en <Link className="text-primary underline" href="/settings/modulos/">Configuración → Módulos</Link>.</p>
    </div>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description?: string; actions?: React.ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions}
    </div>
  );
}
