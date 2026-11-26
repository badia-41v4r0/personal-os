"use client";

import { BASE } from "./base";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";

/** Petición GET con refresco periódico opcional. */
export function useApi<T>(path: string | null, intervalMs?: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (!path) return;
    try {
      setData(await api<T>(path));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    load();
    if (!intervalMs) return;
    const t = setInterval(load, intervalMs);
    return () => clearInterval(t);
  }, [load, intervalMs]);

  return { data, error, loading, reload: load };
}

export type BusEvent = { id: number; ts: string; type: string; source: string; payload: Record<string, unknown> };

/**
 * Eventos en tiempo real. WebSocket con reanudación por id; si el WebSocket no está disponible
 * (p. ej. en desarrollo), sondeo de /events cada 5 s. Nunca depende solo de la conexión permanente.
 */
export function useEvents(onEvent: (e: BusEvent) => void) {
  const last = useRef(0);
  const handler = useRef(onEvent);
  const [mode, setMode] = useState<"ws" | "poll" | "off">("off");

  useEffect(() => {
    handler.current = onEvent;
  }, [onEvent]);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let poll: ReturnType<typeof setInterval> | null = null;
    let retry: ReturnType<typeof setTimeout> | null = null;
    let closed = false;
    let failures = 0;

    const deliver = (e: BusEvent) => {
      if (e.id === 0) return handler.current(e); // efímero (streaming): sin cursor
      if (e.id > last.current) {
        last.current = e.id;
        handler.current(e);
      }
    };

    const startPoll = () => {
      setMode("poll");
      const tick = async () => {
        try {
          const evs = await api<BusEvent[]>(`/events?after=${last.current}`);
          evs.forEach(deliver);
        } catch {}
      };
      tick();
      poll = setInterval(tick, 5000);
    };

    const connect = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${location.host}${BASE}/api/v1/ws?after=${last.current}`);
      ws.onopen = () => {
        failures = 0;
        setMode("ws");
      };
      ws.onmessage = (m) => {
        const e = JSON.parse(m.data);
        if (e.type !== "ping") deliver(e);
      };
      ws.onclose = () => {
        if (closed) return;
        failures += 1;
        if (failures >= 3 && !poll) startPoll();
        retry = setTimeout(connect, Math.min(30000, 1000 * 2 ** failures));
      };
    };

    // Recuperar el último id antes de conectar, para no recibir todo el historial
    api<{ id: number }>(`/events/cursor`)
      .then((c) => (last.current = c.id))
      .catch(() => {})
      .finally(connect);

    return () => {
      closed = true;
      ws?.close();
      if (poll) clearInterval(poll);
      if (retry) clearTimeout(retry);
    };
  }, []);

  return mode;
}
