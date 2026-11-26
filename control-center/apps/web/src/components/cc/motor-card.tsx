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
import { CredencialForm } from "./credencial";

type Prov = { id: string; nombre: string; conectado: boolean; claves?: Record<string, boolean>; mcp: boolean; subagentes: boolean; web: boolean; contenedor: boolean };
type Config = { proveedor: string; relevo: boolean; modelos: Record<string, Record<string, string>>; limite_mensual_usd: number };
type Estado = { config: Config; elegido: string; gasto_mes_openrouter: number; limite: number; aviso: string; proveedores: Prov[] };

// Las dos claves que puede usar OpenCode: el prefijo del modelo decide cuál entra en cada turno
const CLAVES: { id: string; nombre: string; placeholder: string; ayuda: string }[] = [
  { id: "opencode", nombre: "Clave de OpenCode", placeholder: "Clave de opencode.ai",
    ayuda: "Créala en opencode.ai (Zen o Go). Modelos opencode/… (Zen, por uso) u opencode-go/… (suscripción Go)." },
  { id: "openrouter", nombre: "Clave de OpenRouter (opcional)", placeholder: "sk-or-…",
    ayuda: "Créala en openrouter.ai. Modelos openrouter/proveedor/modelo." },
];

const PERFILES: [string, string][] = [["fast", "Rápido"], ["standard", "Normal"], ["deep", "A fondo"], ["code", "Código"]];
const AYUDA: Record<string, string> = {
  claude: "Tu suscripción de Claude (Pro o Max). Pega el token de «claude setup-token».",
  codex: "Tu cuenta de ChatGPT. Ejecuta «codex login» en el PC y pulsa Conectar.",
  opencode: "Con tu clave de OpenCode (Zen por uso o suscripción Go) o de OpenRouter. Pon un límite de gasto mensual.",
  antigravity: "Solo responde con texto (sin herramientas ni tus datos). Usa la sesión de Antigravity del PC.",
};

function Puede({ p }: { p: Prov }) {
  const no = [!p.mcp && "herramientas", !p.subagentes && "subagentes", !p.web && "búsqueda web"].filter(Boolean);
  return <p className="text-xs text-muted-foreground">{no.length ? `No puede: ${no.join(", ")}.` : "Puede usar todo el sistema."}</p>;
}

/** Elegir y conectar el motor de IA. `onListo` lo usa el onboarding para seguir cuando el motor está conectado. */
export function MotorCard({ onListo }: { onListo?: () => void }) {
  const e = useApi<Estado>("/instancia/motor");
  const [claves, setClaves] = useState<Record<string, string>>({});
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
            {CLAVES.map((k) => {
              const puesta = !!elegido?.claves?.[k.id];
              const v = claves[k.id] ?? "";
              return (
                <div key={k.id} className="space-y-1">
                  <label className="flex items-center gap-2 text-xs font-medium" htmlFor={`clave-${k.id}`}>{k.nombre}
                    <Badge variant={puesta ? "secondary" : "outline"}>{puesta ? "guardada" : "sin poner"}</Badge></label>
                  <div className="flex gap-2">
                    <Input id={`clave-${k.id}`} type="password" autoComplete="off" placeholder={puesta ? "Guardada · escribe otra para cambiarla" : k.placeholder} value={v} onChange={(x) => setClaves({ ...claves, [k.id]: x.target.value })} />
                    <Button size="sm" disabled={busy || v.length < 10} onClick={() => run(async () => { await api(`/instancia/motor/${k.id}/clave`, { method: "PUT", body: JSON.stringify({ clave: v }) }); setClaves({ ...claves, [k.id]: "" }); })}>Guardar</Button>
                    {puesta && <Button size="sm" variant="ghost" disabled={busy} onClick={() => run(() => api(`/instancia/motor/${k.id}/clave`, { method: "DELETE" }))}>Quitar</Button>}
                  </div>
                  <p className="text-xs text-muted-foreground">{k.ayuda}</p>
                </div>
              );
            })}
            <p className="text-xs text-muted-foreground">Se guardan en el PC, en archivos que solo puede leer tu usuario (no en la base ni en el navegador). Cada turno recibe solo la clave que necesita su modelo, y nunca se muestran ni se registran.</p>
            <label className="flex items-center justify-between gap-3 text-xs" htmlFor="or-lim">Límite de gasto al mes (USD; la suscripción Go no cuenta) · llevas {e.data.gasto_mes_openrouter.toFixed(2)} $
              <Input id="or-lim" type="number" min={0} step={1} className="w-24" value={c.limite_mensual_usd} onChange={(x) => setCfg({ ...c, limite_mensual_usd: Number(x.target.value) })} />
            </label>
          </div>
        )}
        {c.proveedor === "claude" && (
          <div className="space-y-2 rounded-lg border border-border p-3">
            <CredencialForm clave="CLAUDE_CODE_OAUTH_TOKEN" etiqueta="Token de Claude" placeholder="sk-ant-…" puesta={!!elegido?.conectado} onGuardada={() => void e.reload()} />
            <p className="text-xs text-muted-foreground">En el PC, ejecuta <code>claude setup-token</code>, inicia sesión y pega aquí lo que te da. Se guarda en el <code>.env</code> del PC (solo lo puede leer tu usuario), no en la base ni en el navegador, y nunca se vuelve a mostrar.</p>
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
                  : <Input className="h-8 flex-1" placeholder={c.proveedor === "opencode" ? "opencode-go/…, opencode/… u openrouter/…" : "modelo"} value={c.modelos[c.proveedor]?.[k] ?? ""} onChange={(x) => setModelo(k, x.target.value)} />}
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
