"use client";

import { useEffect, useRef, useState } from "react";
import { Gauge, RefreshCw } from "lucide-react";
import { usePanel } from "./shell";
import { Meter } from "./spark";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { post } from "@/lib/api";
import { timeAgo, until } from "@/lib/format";
import { useApi } from "@/lib/hooks";

type Window = { name: string; utilization: number; resets_at: string | null };
type Item = {
  provider: string;
  model: string;
  available: boolean;
  ts?: string;
  windows: Window[];
  error?: string | null;
};
type Usage = { providers: Record<string, Item> };
type Choice = {
  provider: string;
  model: string;
  emergency: boolean;
  reason: string;
};

const ORDER = ["claude", "antigravity-flash", "antigravity-opus", "codex-terra"] as const;

const LABELS: Record<string, { title: string; subtitle: string }> = {
  claude: { title: "Claude Code", subtitle: "El que trabaja hoy · relevo sugerido desde el 85% semanal" },
  "antigravity-flash": { title: "Antigravity · Gemini 3.8 Flash", subtitle: "Relevo 1" },
  "antigravity-opus": { title: "Antigravity · Opus 4.6", subtitle: "Relevo 2" },
  "codex-terra": { title: "Codex · GPT-5.6 Terra", subtitle: "Relevo 3 · dato de su última sesión en este PC" },
};

function formatWindowName(name: string): string {
  if (name === "seven_day" || name === "weekly") return "Semanal (7 días)";
  if (name === "five_hour") return "Sesión (5 horas)";
  if (name === "daily") return "Diaria";
  if (name === "monthly") return "Mensual (30 días)";
  return name.replaceAll("_", " ");
}

function when(iso: string | null | undefined) {
  return iso ? new Date(iso).toLocaleString("es-ES", { weekday: "short", hour: "2-digit", minute: "2-digit" }) : "";
}

/** Cuotas de cada modelo y relevo sugerido. Solo informa: Jarvis y el orquestador siguen en Claude. */
export function ModelUsageCard() {
  const { lastEvent } = usePanel();
  const u = useApi<Usage>("/models/usage", 60_000);
  const choice = useApi<Choice>("/models/choice", 60_000);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (lastEvent?.type === "models.usage" || lastEvent?.type === "claude.usage") {
      u.reload();
      choice.reload();
    }
  }, [lastEvent]); // eslint-disable-line react-hooks/exhaustive-deps

  // Reloj en el estado (no Date.now() en el render): también refresca la cuenta atrás
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(t);
  }, []);

  // Si ya pasó el reinicio de alguna ventana, el dato es viejo: se pide uno nuevo (una vez por lectura)
  const rows = Object.values(u.data?.providers ?? {});
  const lastRead = rows.map((p) => p.ts ?? "").sort().at(-1);
  const expired = rows.some((p) => p.ts && p.windows.some((w) => {
    const r = w.resets_at ? new Date(w.resets_at).getTime() : 0;
    return r > new Date(p.ts!).getTime() && r < now;
  }));
  const autoTried = useRef<string | null>(null);
  useEffect(() => {
    if (expired && lastRead && autoTried.current !== lastRead) {
      autoTried.current = lastRead;
      post("/models/usage/refresh").then(() => { u.reload(); choice.reload(); }).catch(() => {});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [expired, lastRead]);

  const refresh = async () => {
    setBusy(true);
    setError(null);
    try {
      await post("/models/usage/refresh");
      u.reload();
      choice.reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const providers = u.data?.providers ?? {};
  const suggested = choice.data?.provider;

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-3">
        <div className="space-y-1">
          <CardTitle className="flex items-center gap-2 text-base">
            <Gauge className="size-4 text-primary" /> Uso de modelos y relevo
          </CardTitle>
          <p className="text-xs text-muted-foreground">
            {choice.data && (suggested
              ? <>Relevo sugerido: <span className="font-semibold text-foreground">{LABELS[suggested]?.title ?? suggested}</span>
                  {choice.data.emergency && <span className="text-amber-500 font-medium"> (último recurso)</span>}. </>
              : "Ningún modelo con lectura válida. ")}
            No cambia solo: todo sigue en Claude.
          </p>
        </div>
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={refresh}
          disabled={busy}
          aria-label="Actualizar uso de modelos"
        >
          <RefreshCw className={busy ? "animate-spin" : ""} />
        </Button>
      </CardHeader>

      <CardContent className="space-y-4 pt-1">
        {!u.data && <p className="text-sm text-muted-foreground">Consultando cuotas de modelos…</p>}

        {ORDER.map((key) => {
          const item = providers[key] ?? {
            provider: key,
            model: key,
            available: false,
            windows: [],
          };
          const info = LABELS[key] ?? { title: item.provider, subtitle: item.model };
          const isSuggested = suggested === key;

          return (
            <section
              key={key}
              className={`rounded-lg border p-3 transition-colors ${
                isSuggested
                  ? "border-emerald-500/50 bg-emerald-500/5 dark:bg-emerald-950/20"
                  : "border-border/60 bg-muted/20"
              }`}
            >
              <div className="flex items-center justify-between gap-2 mb-1.5">
                <div className="flex items-center gap-2">
                  <div className="text-sm font-semibold">{info.title}</div>
                  {isSuggested && (
                    <Badge variant="default" className="bg-emerald-600 text-white hover:bg-emerald-600 text-[10px] h-4 px-1.5">
                      Sugerido
                    </Badge>
                  )}
                </div>
                {!item.available && (
                  <Badge variant="destructive" className="text-[10px] h-4 px-1.5">
                    No disponible
                  </Badge>
                )}
              </div>

              <p className="text-xs text-muted-foreground mb-2">{info.subtitle}</p>

              {item.windows && item.windows.length > 0 ? (
                <div className="space-y-2">
                  {item.windows.map((w) => {
                    const isWeekly = w.name === "seven_day" || w.name === "weekly";
                    const reset = !!w.resets_at && new Date(w.resets_at).getTime() < now;
                    const isOver = !reset && w.utilization >= 0.85 && (key !== "claude" || isWeekly);
                    return (
                      <div key={`${w.name}-${w.resets_at}`} className={reset ? "space-y-1 opacity-50" : "space-y-1"}>
                        <Meter
                          label={formatWindowName(w.name)}
                          pct={w.utilization * 100}
                        />
                        <div className="flex items-center justify-between text-[11px] text-muted-foreground">
                          <span>
                            {reset ? "Se reinició" : isOver ? "Por encima del 85%" : `${Math.round(w.utilization * 100)}% consumido`}
                          </span>
                          {w.resets_at && !reset && (
                            <span>
                              Reinicia {until(w.resets_at)} ({when(w.resets_at)})
                            </span>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <p className="text-xs text-destructive">
                  {item.error || "Sin lectura de cuota"}
                </p>
              )}

              {item.ts && (
                <p className="mt-2 text-[10px] text-muted-foreground/70">
                  Actualizado {timeAgo(item.ts)}
                </p>
              )}
            </section>
          );
        })}

        {error && <p className="text-xs text-destructive">{error}</p>}
      </CardContent>
    </Card>
  );
}
