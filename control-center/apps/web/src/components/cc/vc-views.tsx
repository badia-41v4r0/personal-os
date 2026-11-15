"use client";

import { useEffect, useRef, useState } from "react";
import "@xterm/xterm/css/xterm.css";
import { ErrorState } from "./states";

function wsUrl(path: string) {
  return `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${path}`;
}

/** Terminal real del ordenador virtual (xterm.js ↔ WebSocket ↔ docker exec -it). */
export function VcTerminal({ id }: { id: string }) {
  const el = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<"connecting" | "open" | "closed">("connecting");
  useEffect(() => {
    let disposed = false;
    let ws: WebSocket | null = null;
    let cleanup = () => {};
    (async () => {
      const { Terminal } = await import("@xterm/xterm");
      const { FitAddon } = await import("@xterm/addon-fit");
      if (disposed || !el.current) return;
      const term = new Terminal({ fontSize: 13, fontFamily: "var(--font-mono), monospace", cursorBlink: true,
        theme: { background: "#0d1014", foreground: "#e6e9ef", cursor: "#7dd3e0" } });
      const fit = new FitAddon();
      term.loadAddon(fit);
      term.open(el.current);
      fit.fit();
      ws = new WebSocket(wsUrl(`/api/v1/virtual-computers/${id}/tty`));
      ws.binaryType = "arraybuffer";
      const sendSize = () => ws?.readyState === 1 && ws.send(JSON.stringify({ type: "resize", cols: term.cols, rows: term.rows }));
      ws.onopen = () => { setState("open"); sendSize(); term.focus(); };
      ws.onclose = () => setState("closed");
      ws.onmessage = (m) => term.write(typeof m.data === "string" ? m.data : new Uint8Array(m.data));
      const d = term.onData((data) => ws?.readyState === 1 && ws.send(data));
      const ro = new ResizeObserver(() => { fit.fit(); sendSize(); });
      ro.observe(el.current);
      cleanup = () => { d.dispose(); ro.disconnect(); term.dispose(); };
    })();
    return () => { disposed = true; ws?.close(); cleanup(); };
  }, [id]);
  return (
    <div className="space-y-2">
      {state === "closed" && <ErrorState message="Terminal desconectada (el ordenador puede estar parado). Recarga para reconectar." />}
      <div ref={el} className="h-[60vh] min-h-80 overflow-hidden rounded-lg bg-[#0d1014] p-2" aria-label="Terminal" />
    </div>
  );
}

/** Escritorio (noVNC ↔ WebSocket ↔ docker exec socat al VNC local). */
export function VcDesktop({ id, viewOnly }: { id: string; viewOnly: boolean }) {
  const el = useRef<HTMLDivElement>(null);
  const rfb = useRef<{ viewOnly: boolean; disconnect(): void } | null>(null);
  const [state, setState] = useState<"connecting" | "open" | "closed">("connecting");
  useEffect(() => {
    let disposed = false;
    (async () => {
      const { default: RFB } = await import("@novnc/novnc");
      if (disposed || !el.current) return;
      const r = new RFB(el.current, wsUrl(`/api/v1/virtual-computers/${id}/vnc`), { wsProtocols: ["binary"], shared: true });
      r.scaleViewport = true;
      r.resizeSession = false;
      r.viewOnly = viewOnly;
      r.addEventListener("connect", () => setState("open"));
      r.addEventListener("disconnect", () => setState("closed"));
      rfb.current = r;
    })();
    return () => { disposed = true; rfb.current?.disconnect(); rfb.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);
  useEffect(() => {
    if (rfb.current) rfb.current.viewOnly = viewOnly;
  }, [viewOnly]);
  return (
    <div className="space-y-2">
      {state === "closed" && <ErrorState message="Escritorio desconectado. Recarga para reconectar." />}
      {state === "connecting" && <p className="text-xs text-muted-foreground">Conectando con el escritorio…</p>}
      <div ref={el} className="aspect-[16/10] w-full overflow-hidden rounded-lg bg-black" aria-label="Escritorio remoto" />
    </div>
  );
}
