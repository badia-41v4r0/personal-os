"use client";

import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, ChevronUp, Loader2, Menu, Pencil, Search, SquarePen, Trash2, X } from "lucide-react";
import { cn } from "cn";
import { api, post, upload } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { visible } from "@/lib/instancia";
import { ASISTENTES, assistantFor, asistentePorClave, claveChat } from "../assistants";
import { usePanel } from "../shell";
import { Compositor, type CompositorRef } from "./compositor";
import { ocupada, type Conversacion, type EnDirecto } from "./datos";
import { useConversacion } from "./datos";
import { describirLinea } from "./pasos";
import { Vista } from "./vista";
import { AvatarAsistente } from "../avatar-asistente";
import { EN_VISTA_PREVIA } from "@/lib/base";
import { BarraConstructor } from "./constructor";

const GUARDADO = "pos.chat.conversaciones";

/** Abre el chat en una conversación concreta (p. ej. la del Constructor que junta una actualización). */
export function abrirConversacion(asistente: string, id: string) {
  window.dispatchEvent(new CustomEvent("cc:chat-ir", { detail: { asistente, id } }));
}

/** Pídele algo a un asistente desde cualquier pantalla: abre el chat con una conversación nueva y lo envía. */
export function preguntarAlChat(asistente: string, texto: string) {
  window.dispatchEvent(new CustomEvent("cc:chat-preguntar", { detail: { asistente, texto } }));
}

function grupo(iso: string): string {
  const d = new Date(iso);
  const hoy = new Date();
  hoy.setHours(0, 0, 0, 0);
  const dias = Math.floor((hoy.getTime() - new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()) / 86400000);
  if (dias <= 0) return "Hoy";
  if (dias === 1) return "Ayer";
  if (dias < 7) return "Últimos 7 días";
  if (dias < 30) return "Últimos 30 días";
  return new Intl.DateTimeFormat("es-ES", { month: "long", year: "numeric" }).format(d);
}

/** Lo que está haciendo ahora mismo, en una línea (para la barra plegada). */
function estadoCorto(vivo: EnDirecto | null, enCola: boolean): string {
  if (enCola) return "Preparándose…";
  if (vivo?.pasos.length && !vivo.texto) return `${describirLinea(vivo.pasos[vivo.pasos.length - 1])}…`;
  if (vivo?.texto) return "Escribiendo…";
  return "Pensando…";
}

function Elemento({ c, activa, onElegir, onCambiado }: { c: Conversacion; activa: boolean; onElegir: () => void; onCambiado: () => void }) {
  const [editando, setEditando] = useState(false);
  const [titulo, setTitulo] = useState(c.titulo);
  const guardar = async () => {
    setEditando(false);
    if (titulo.trim() && titulo.trim() !== c.titulo) {
      await api(`/conversaciones/${c.id}`, { method: "PATCH", body: JSON.stringify({ titulo: titulo.trim() }) });
      onCambiado();
    }
  };
  if (editando) {
    return (
      <form className="flex items-center gap-1 rounded-lg bg-sidebar-accent px-1.5 py-1" onSubmit={(e) => { e.preventDefault(); void guardar(); }}>
        <input autoFocus value={titulo} onChange={(e) => setTitulo(e.target.value)} onBlur={() => void guardar()} maxLength={120} aria-label="Nuevo título"
          onKeyDown={(e) => { if (e.key === "Escape") { e.stopPropagation(); setTitulo(c.titulo); setEditando(false); } }}
          className="min-w-0 flex-1 rounded bg-background px-1.5 py-1 text-sm outline-none ring-1 ring-ring" />
        <button type="submit" aria-label="Guardar título" className="grid size-7 place-items-center rounded hover:bg-background"><Check className="size-3.5" /></button>
      </form>
    );
  }
  return (
    <div className={cn("group relative flex items-center rounded-lg hover:bg-sidebar-accent", activa && "bg-sidebar-accent")}>
      <button type="button" onClick={onElegir} aria-current={activa ? "true" : undefined} className="min-w-0 flex-1 truncate px-2.5 py-2 text-left text-sm">{c.titulo}</button>
      <div className="absolute right-1 hidden items-center gap-0.5 rounded-md bg-sidebar-accent group-focus-within:flex group-hover:flex">
        <button type="button" onClick={() => setEditando(true)} aria-label={`Renombrar «${c.titulo}»`} title="Renombrar" className="grid size-7 place-items-center rounded text-muted-foreground hover:text-foreground"><Pencil className="size-3.5" /></button>
        <button type="button" title="Quitar del historial" aria-label={`Quitar «${c.titulo}» del historial`} className="grid size-7 place-items-center rounded text-muted-foreground hover:text-destructive"
          onClick={async () => { if (window.confirm(`¿Quitar «${c.titulo}» del historial? Lo que aprendió de ella se queda en su memoria.`)) { await api(`/conversaciones/${c.id}`, { method: "DELETE" }); onCambiado(); } }}>
          <Trash2 className="size-3.5" />
        </button>
      </div>
    </div>
  );
}

export function ChatFlotante() {
  const path = usePathname();
  const router = useRouter();
  const { inst, lastEvent } = usePanel();
  // El Constructor, solo si su módulo está activo, y nunca dentro de su propia vista previa
  const disponibles = useMemo(() => ASISTENTES.filter((x) => (x.modulo ? !EN_VISTA_PREVIA && !!inst?.modulos.find((m) => m.id === x.modulo)?.activo : visible(inst, x.ruta)))
    .map((x) => x.asistente), [inst]);
  const [clave, setClave] = useState(() => claveChat(assistantFor(path)));
  const [abierto, setAbierto] = useState(false);
  const [lado, setLado] = useState(false); // historial en el móvil
  const [selector, setSelector] = useState(false);
  const [convs, setConvs] = useState<Record<string, string | null>>({});
  const [error, setError] = useState<string | null>(null);
  const [respondida, setRespondida] = useState<string | null>(null); // respuesta que llegó con el chat plegado
  const [q, setQ] = useState("");
  const [qDef, setQDef] = useState("");
  const panel = useRef<CompositorRef>(null);
  const abiertoRef = useRef(abierto);
  useEffect(() => {
    abiertoRef.current = abierto;
  }, [abierto]);
  const abrir = useCallback(() => {
    setAbierto(true);
    setRespondida(null);
  }, []);

  const asistente = asistentePorClave(clave);
  const cid = convs[clave] ?? null;

  // La conversación de cada asistente se recuerda mientras dure la pestaña
  useEffect(() => {
    try { setConvs(JSON.parse(sessionStorage.getItem(GUARDADO) ?? "{}")); } catch { /* nada guardado */ }
  }, []);
  const elegir = useCallback((k: string, id: string | null) => {
    setConvs((c) => {
      const n = { ...c, [k]: id };
      try { sessionStorage.setItem(GUARDADO, JSON.stringify(n)); } catch { /* sin almacenamiento */ }
      return n;
    });
    setRespondida(null);
    setLado(false);
  }, []);

  // Plegado, el chat sigue al apartado en el que estás
  useEffect(() => {
    if (!abiertoRef.current) setClave(claveChat(assistantFor(path)));
  }, [path]);
  useEffect(() => {
    if (inst && !disponibles.some((a) => claveChat(a) === clave)) setClave("jarvis");
  }, [inst, disponibles, clave]);

  const onTermina = useCallback((id: string) => {
    if (!abiertoRef.current) setRespondida(id);
  }, []);
  const conv = useConversacion(cid, onTermina);
  const enCurso = ocupada(conv.data);
  const enCola = !!conv.data?.respuestas.some((r) => r.estado === "queued");
  // La conversación ya no existe (quitada desde otro sitio): se empieza otra
  useEffect(() => {
    if (cid && conv.error) elegir(clave, null);
  }, [cid, conv.error, clave, elegir]);

  useEffect(() => {
    const t = setTimeout(() => setQDef(q.trim()), 250);
    return () => clearTimeout(t);
  }, [q]);
  const lista = useApi<Conversacion[]>(abierto ? `/conversaciones?asistente=${clave}${qDef ? `&q=${encodeURIComponent(qDef)}` : ""}` : null);
  const { reload: recargarLista } = lista;
  useEffect(() => {
    if (abierto && (lastEvent?.type === "run.finished" || lastEvent?.type === "run.queued")) recargarLista();
  }, [lastEvent, abierto, recargarLista]);

  const enviarA = useCallback(async (k: string, id: string | null, texto: string, archivos: File[]): Promise<boolean> => {
    setError(null);
    try {
      if (!id) {
        id = (await post<Conversacion>("/conversaciones", { asistente: k, texto })).id;
        elegir(k, id);
      }
      const adjuntos: string[] = [];
      for (const f of archivos) {
        adjuntos.push((await upload<{ name: string }>(`/conversaciones/${id}/adjuntos?name=${encodeURIComponent(f.name || "archivo")}`, f)).name);
      }
      await post(`/conversaciones/${id}/mensajes`, { texto, adjuntos });
      abrir();
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return false;
    }
  }, [elegir, abrir]);
  const { reload: recargarConv } = conv;
  const enviar = async (texto: string, archivos: File[]) => {
    const ok = await enviarA(clave, cid, texto, archivos);
    if (ok) { void recargarConv(); recargarLista(); }
    return ok;
  };
  const parar = () => { if (cid) void post(`/conversaciones/${cid}/interrumpir`).catch((e) => setError(String(e?.message ?? e))); };

  // Otras pantallas abren el chat o le piden algo a un asistente (p. ej. «Pedir tarjetas al tutor»)
  useEffect(() => {
    const preguntar = (e: Event) => {
      const { asistente: k, texto } = (e as CustomEvent<{ asistente: string; texto: string }>).detail;
      setClave(k);
      void enviarA(k, null, texto, []);
    };
    const ir = (e: Event) => {
      const { asistente: k, id } = (e as CustomEvent<{ asistente: string; id: string }>).detail;
      setClave(k);
      elegir(k, id);
      abrir();
    };
    window.addEventListener("cc:open-dock", abrir);
    window.addEventListener("cc:chat-preguntar", preguntar);
    window.addEventListener("cc:chat-ir", ir);
    return () => {
      window.removeEventListener("cc:open-dock", abrir);
      window.removeEventListener("cc:chat-preguntar", preguntar);
      window.removeEventListener("cc:chat-ir", ir);
    };
  }, [enviarA, abrir, elegir]);

  // Esc pliega; Ctrl/⌘ + J abre y pliega
  useEffect(() => {
    const tecla = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "j") {
        e.preventDefault();
        setAbierto((a) => !a);
        setRespondida(null);
      } else if (e.key === "Escape" && abiertoRef.current) {
        if (selector) setSelector(false);
        else if (lado) setLado(false);
        else setAbierto(false);
      }
    };
    window.addEventListener("keydown", tecla);
    return () => window.removeEventListener("keydown", tecla);
  }, [selector, lado]);

  useEffect(() => {
    if (abierto) {
      setTimeout(() => panel.current?.focus(), 50);
      document.body.style.overflow = "hidden";
      return () => { document.body.style.overflow = ""; };
    }
  }, [abierto]);

  const wiki = async (nombre: string) => {
    try {
      const r = await api<{ path: string }>(`/memory/resolve?name=${encodeURIComponent(nombre)}&from_path=`);
      setAbierto(false);
      router.push(`/conocimiento/?p=${encodeURIComponent(r.path)}`);
    } catch {
      setError(`No encuentro la nota «${nombre}»`);
    }
  };

  const cambiarAsistente = (k: string) => {
    setSelector(false);
    setClave(k);
    setQ("");
  };

  const grupos = useMemo(() => {
    const g: [string, Conversacion[]][] = [];
    for (const c of lista.data ?? []) {
      const n = grupo(c.actividad);
      const ultimo = g[g.length - 1];
      if (ultimo?.[0] === n) ultimo[1].push(c);
      else g.push([n, [c]]);
    }
    return g;
  }, [lista.data]);

  const titulo = conv.data?.conversacion.titulo;

  // ---------- plegado: la barra flotante ----------
  const barra = !abierto && (
    <div className="pointer-events-none fixed inset-x-0 bottom-[calc(3.5rem+env(safe-area-inset-bottom)+0.5rem)] z-30 flex justify-center px-3 lg:bottom-4 lg:left-60 lg:px-6">
      <div className="pointer-events-auto w-full max-w-2xl">
        {(enCurso || respondida === cid && cid) && (
          <button type="button" onClick={abrir}
            className="mx-auto mb-1.5 flex max-w-full items-center gap-2 rounded-full border border-border bg-card/95 px-3 py-1 text-xs shadow-sm backdrop-blur">
            {enCurso ? <Loader2 className="size-3.5 shrink-0 animate-spin text-primary" /> : <span className="size-2 shrink-0 rounded-full bg-primary" />}
            <span className="truncate"><span className="font-medium">{asistente.name}</span> · {enCurso ? estadoCorto(conv.vivo, enCola) : "ha respondido"}</span>
            <span className="shrink-0 text-primary">Ver</span>
          </button>
        )}
        {error && <p role="alert" className="mx-auto mb-1.5 w-fit max-w-full rounded-full bg-destructive/90 px-3 py-1 text-xs text-white shadow-sm">{error}</p>}
        <div className="flex items-end gap-1 rounded-[1.75rem] bg-background/90 p-1 shadow-lg ring-1 ring-border backdrop-blur transition-shadow focus-within:ring-ring/60">
          <button type="button" onClick={abrir} title={`Abrir el chat (Ctrl+J)${titulo ? ` · ${titulo}` : ""}`} aria-label={`Abrir el chat con ${asistente.name}`}
            className="mb-1 ml-1 flex h-9 shrink-0 items-center gap-1 rounded-full px-1.5 hover:bg-muted">
            <AvatarAsistente asistente={asistente} tam="sm" redondo />
            <ChevronUp className="size-4 text-muted-foreground" />
          </button>
          <div className="min-w-0 flex-1">
            <Compositor compacta placeholder={cid && titulo ? `Sigue con ${asistente.name}…` : `Pregunta a ${asistente.name}…`} ocupada={enCurso}
              onEnviar={enviar} onParar={parar} onError={setError} />
          </div>
        </div>
      </div>
    </div>
  );

  if (!abierto) return barra;

  // ---------- desplegado: la ventana de chat ----------
  const historial = (
    <div className="flex h-full flex-col gap-2 p-2">
      <button type="button" onClick={() => { elegir(clave, null); setTimeout(() => panel.current?.focus(), 50); }}
        className="flex items-center gap-2 rounded-lg px-2.5 py-2 text-sm font-medium hover:bg-sidebar-accent">
        <SquarePen className="size-4" /> Nueva conversación
      </button>
      <div className="relative px-0.5">
        <Search className="absolute top-2.5 left-3 size-3.5 text-muted-foreground" />
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Buscar" aria-label="Buscar en las conversaciones"
          className="h-9 w-full rounded-lg border border-input bg-transparent pr-2 pl-8 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring" />
      </div>
      <nav aria-label={`Conversaciones con ${asistente.name}`} className="-mx-0.5 min-h-0 flex-1 space-y-4 overflow-y-auto px-0.5 pt-1">
        {lista.loading && !lista.data && <p className="px-2.5 text-xs text-muted-foreground">Cargando…</p>}
        {lista.data?.length === 0 && <p className="px-2.5 text-xs text-muted-foreground">{qDef ? "Nada coincide con la búsqueda." : `Aún no has hablado con ${asistente.name}.`}</p>}
        {grupos.map(([g, cs]) => (
          <div key={g}>
            <div className="mb-1 px-2.5 text-[11px] font-medium text-muted-foreground first-letter:uppercase">{g}</div>
            <div className="space-y-0.5">
              {cs.map((c) => <Elemento key={c.id} c={c} activa={c.id === cid} onElegir={() => elegir(clave, c.id)} onCambiado={() => { recargarLista(); if (c.id === cid) void recargarConv(); }} />)}
            </div>
          </div>
        ))}
      </nav>
    </div>
  );

  return (
    <div role="dialog" aria-modal="true" aria-label={`Chat con ${asistente.name}`} className="fixed inset-0 z-50">
      <div className="absolute inset-0 hidden bg-background/55 backdrop-blur-[2px] lg:block" onClick={() => setAbierto(false)} />
      <div className="pointer-events-none absolute inset-0 flex justify-center lg:left-60 lg:px-6 lg:pt-6">
        <div className="pointer-events-auto relative flex w-full max-w-6xl overflow-hidden bg-card pt-[env(safe-area-inset-top)] pb-[env(safe-area-inset-bottom)] shadow-2xl duration-200 animate-in fade-in slide-in-from-bottom-6 lg:rounded-t-2xl lg:border lg:border-b-0 lg:border-border lg:pt-0 lg:pb-0">
          <aside className={cn("w-64 shrink-0 flex-col border-r border-border bg-sidebar", lado ? "absolute inset-y-0 left-0 z-20 flex pt-[env(safe-area-inset-top)] shadow-xl" : "hidden lg:flex")}>
            {historial}
          </aside>
          {lado && <div className="absolute inset-0 z-10 bg-background/50 lg:hidden" onClick={() => setLado(false)} />}
          <section className="flex min-w-0 flex-1 flex-col">
            <header className="flex h-13 shrink-0 items-center gap-1 border-b border-border px-2 lg:px-3">
              <button type="button" onClick={() => setLado(true)} aria-label="Ver conversaciones" className="grid size-9 place-items-center rounded-lg hover:bg-muted lg:hidden"><Menu className="size-4" /></button>
              <div className="relative">
                <button type="button" onClick={() => setSelector(!selector)} aria-expanded={selector} aria-haspopup="listbox"
                  className="flex h-9 items-center gap-2 rounded-lg px-2 text-sm font-semibold hover:bg-muted">
                  <AvatarAsistente asistente={asistente} tam="xs" />
                  {asistente.name}
                  <ChevronDown className="size-4 text-muted-foreground" />
                </button>
                {selector && (
                  <>
                    <div className="fixed inset-0 z-30" onClick={() => setSelector(false)} />
                    <ul role="listbox" aria-label="Asistente" className="absolute top-full left-0 z-40 mt-1 max-h-[60vh] w-72 overflow-y-auto rounded-xl border border-border bg-popover p-1 shadow-lg">
                      {disponibles.map((a) => {
                        const k = claveChat(a);
                        return (
                          <li key={k} role="option" aria-selected={k === clave}>
                            <button type="button" onClick={() => cambiarAsistente(k)} className="flex w-full items-center gap-2.5 rounded-lg px-2 py-2 text-left hover:bg-muted">
                              <AvatarAsistente asistente={a} tam="sm" />
                              <span className="min-w-0 flex-1 leading-tight"><span className="block text-sm font-medium">{a.name}</span><span className="block truncate text-xs text-muted-foreground">{a.hint}</span></span>
                              {k === clave && <Check className="size-4 text-primary" />}
                            </button>
                          </li>
                        );
                      })}
                    </ul>
                  </>
                )}
              </div>
              <span className="min-w-0 flex-1 truncate px-1 text-sm text-muted-foreground">{titulo}</span>
              {cid && <button type="button" onClick={() => elegir(clave, null)} aria-label="Nueva conversación" title="Nueva conversación" className="grid size-9 place-items-center rounded-lg hover:bg-muted"><SquarePen className="size-4" /></button>}
              <button type="button" onClick={() => setAbierto(false)} aria-label="Plegar el chat" title="Plegar (Esc)" className="grid size-9 place-items-center rounded-lg hover:bg-muted">
                <ChevronDown className="hidden size-5 lg:block" /><X className="size-5 lg:hidden" />
              </button>
            </header>
            {cid && !conv.data && !conv.error ? (
              <div className="grid flex-1 place-items-center"><Loader2 className="size-5 animate-spin text-muted-foreground" /></div>
            ) : (
              <Vista data={cid ? conv.data : null} vivo={conv.vivo} asistente={asistente} onWiki={(n) => void wiki(n)}
                onSugerencia={(t) => void enviar(t, [])} />
            )}
            <div className="mx-auto w-full max-w-3xl shrink-0 px-3 pb-3 lg:px-4 lg:pb-4">
              {clave === "constructor" && <BarraConstructor cid={cid} onIr={(id) => elegir(clave, id)} onError={setError} />}
              {error && <p role="alert" className="mb-2 text-xs text-destructive">{error}</p>}
              <Compositor ref={panel} placeholder={`Escribe a ${asistente.name}…`} ocupada={enCurso} onEnviar={enviar} onParar={parar} onError={setError} />
              <p className="mt-1.5 hidden text-center text-[11px] text-muted-foreground lg:block">Intro para enviar · Mayús+Intro, salto de línea · Esc para plegar</p>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
