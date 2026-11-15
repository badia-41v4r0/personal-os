"use client";

import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { ErrorState, Loading } from "@/components/cc/states";
import { api, post } from "@/lib/api";
import { useApi } from "@/lib/hooks";

type Prov = { id: string; nombre: string; conectado: boolean; mcp: boolean; subagentes: boolean; web: boolean; contenedor: boolean };
type Config = { proveedor: string; relevo: boolean; modelos: Record<string, Record<string, string>>; limite_mensual_usd: number };
type Estado = { config: Config; elegido: string; gasto_mes_openrouter: number; limite: number; aviso: string; proveedores: Prov[] };

const PERFILES: [string, string][] = [["fast", "Rápido"], ["standard", "Normal"], ["deep", "A fondo"], ["code", "Código"]];
const AYUDA: Record<string, string> = {
  claude: "Tu suscripción de Claude (Pro o Max). El token se configura en la instalación (claude setup-token).",
  codex: "Tu cuenta de ChatGPT. Ejecuta «codex login» en el PC y pulsa Conectar.",
  opencode: "Pago por uso con tu clave de OpenRouter. Pon un límite de gasto mensual.",
  antigravity: "Solo responde con texto (sin herramientas ni tus datos). Usa la sesión de Antigravity del PC.",
};

function Puede({ p }: { p: Prov }) {
  const no = [!p.mcp && "herramientas", !p.subagentes && "subagentes", !p.web && "búsqueda web"].filter(Boolean);
  return <p className="text-xs text-muted-foreground">{no.length ? `No puede: ${no.join(", ")}.` : "Puede usar todo el sistema."}</p>;
}

/** Elegir y conectar el motor de IA. `onListo` lo usa el onboarding para seguir cuando el motor está conectado. */
export function MotorCard({ onListo }: { onListo?: () => void }) {
  const e = useApi<Estado>("/instancia/motor");
  const [clave, setClave] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cfg, setCfg] = useState<Config | null>(null);

  if (e.error) return <ErrorState message={e.error} />;
  if (!e.data) return <Loading rows={4} />;
  const c = cfg ?? e.data.config;
  const elegido = e.data.proveedores.find((p) => p.id === c.proveedor);

  const run = async (f: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await f();
      await e.reload();
    } catch (x) {
      setError(x instanceof Error ? x.message : String(x));
    } finally {
      setBusy(false);
    }
  };
  const guardar = () => run(async () => {
    await api("/instancia/config/ia", { method: "PUT", body: JSON.stringify(c) });
    setCfg(null);
    if (elegido?.conectado) onListo?.();
  });
  const setModelo = (perfil: string, v: string) =>
    setCfg({ ...c, modelos: { ...c.modelos, [c.proveedor]: { ...(c.modelos[c.proveedor] ?? {}), [perfil]: v } } });

  return (
    <Card>
      <CardHeader><CardTitle>Motor de IA</CardTitle></CardHeader>
      <CardContent className="space-y-4 text-sm">
        {e.data.aviso && <p className="text-xs text-muted-foreground">{e.data.aviso}</p>}
        <div className="grid gap-2 sm:grid-cols-2" role="radiogroup" aria-label="Motor de IA">
          {e.data.proveedores.map((p) => (
            <button key={p.id} type="button" role="radio" aria-checked={c.proveedor === p.id} onClick={() => setCfg({ ...c, proveedor: p.id })}
              className={`rounded-lg border p-3 text-left ${c.proveedor === p.id ? "border-primary bg-primary/5" : "border-border hover:bg-muted"}`}>
              <div className="flex items-center gap-2"><span className="font-medium">{p.nombre}</span>
                <Badge variant={p.conectado ? "secondary" : "outline"}>{p.conectado ? "conectado" : "sin conectar"}</Badge></div>
              <p className="mt-1 text-xs text-muted-foreground">{AYUDA[p.id]}</p>
              <Puede p={p} />
            </button>
          ))}
        </div>

        {c.proveedor === "opencode" && (
          <div className="space-y-2 rounded-lg border border-border p-3">
            <label className="block text-xs font-medium" htmlFor="or-key">Clave de OpenRouter</label>
            <div className="flex gap-2">
              <Input id="or-key" type="password" autoComplete="off" placeholder={elegido?.conectado ? "Guardada · escribe otra para cambiarla" : "sk-or-…"} value={clave} onChange={(x) => setClave(x.target.value)} />
              <Button size="sm" disabled={busy || clave.length < 10} onClick={() => run(async () => { await api("/instancia/motor/openrouter/clave", { method: "PUT", body: JSON.stringify({ clave }) }); setClave(""); })}>Guardar</Button>
            </div>
            <p className="text-xs text-muted-foreground">Se guarda en el PC en un archivo que solo puede leer tu usuario (no en la base ni en el navegador). Solo la recibe el turno en curso y nunca se muestra ni se registra.</p>
            <label className="flex items-center justify-between gap-3 text-xs" htmlFor="or-lim">Límite de gasto al mes (USD) · llevas {e.data.gasto_mes_openrouter.toFixed(2)} $
              <Input id="or-lim" type="number" min={0} step={1} className="w-24" value={c.limite_mensual_usd} onChange={(x) => setCfg({ ...c, limite_mensual_usd: Number(x.target.value) })} />
            </label>
          </div>
        )}
        {c.proveedor === "codex" && (
          <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border p-3">
            <p className="flex-1 text-xs text-muted-foreground">En el PC: <code>codex login</code>. Después:</p>
            <Button size="sm" variant="outline" disabled={busy} onClick={() => run(() => post("/instancia/motor/codex/importar"))}>{elegido?.conectado ? "Volver a conectar" : "Conectar Codex"}</Button>
          </div>
        )}

        {c.proveedor !== "antigravity" && (
          <fieldset className="grid gap-2 sm:grid-cols-2">
            <legend className="mb-1 text-xs font-medium">Modelos{c.proveedor === "codex" ? " (vacío = el de Codex por defecto)" : ""}</legend>
            {PERFILES.map(([k, label]) => (
              <label key={k} className="flex items-center gap-2 text-xs">{label}
                {c.proveedor === "claude"
                  ? <select className="h-8 flex-1 rounded-md border border-border bg-background px-2" value={c.modelos.claude?.[k] ?? "sonnet"} onChange={(x) => setModelo(k, x.target.value)}>
                      <option value="sonnet">Sonnet</option><option value="opus">Opus</option></select>
                  : <Input className="h-8 flex-1" placeholder={c.proveedor === "opencode" ? "openrouter/proveedor/modelo" : "modelo"} value={c.modelos[c.proveedor]?.[k] ?? ""} onChange={(x) => setModelo(k, x.target.value)} />}
              </label>
            ))}
          </fieldset>
        )}
        <label className="flex items-center justify-between gap-3 text-xs">Relevo: si Claude se queda sin cuota, otro motor responde solo con texto
          <Switch checked={c.relevo} onCheckedChange={(v: boolean) => setCfg({ ...c, relevo: v })} /></label>
        {error && <ErrorState message={error} />}
        <div className="flex justify-end gap-2">
          {cfg && <Button variant="ghost" size="sm" onClick={() => setCfg(null)}>Descartar</Button>}
          <Button size="sm" disabled={busy || (!cfg && !onListo)} onClick={guardar}>{onListo ? "Usar este motor" : "Guardar"}</Button>
        </div>
      </CardContent>
    </Card>
  );
}
