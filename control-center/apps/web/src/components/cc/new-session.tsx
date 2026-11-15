"use client";

import { useState } from "react";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { post } from "@/lib/api";

export type SessionSummary = {
  id: string; kind: "main" | "independent"; name: string; description: string; agent_id: string | null; model: string;
  status: string; permissions?: { level: string; internet: boolean; vault: boolean; system_prompt?: string; minutes?: number; vc?: { enabled: boolean; profile: string; vc_id: string | null }; subagents?: boolean };
  workdir?: string; claude_session_id?: string | null; created_at: string; last_activity: string;
};

const select = "h-8 w-full rounded-lg border border-input bg-transparent px-2 text-sm dark:bg-input/30";

export function NewSessionDialog({ onCreated, preset }: { onCreated: (s: SessionSummary) => void; preset?: Partial<{ name: string; system_prompt: string; agent_id: string; model: string; level: string; internet: boolean; vault: boolean }> }) {
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ name: "", description: "", model: "sonnet", level: "read", internet: false, vault: false, system_prompt: "", minutes: 30, virtual_computer: false, vc_profile: "terminal", subagents: false, ...preset });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => setF((x) => ({ ...x, [k]: v }));

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const s = await post<SessionSummary>("/sessions", { ...f, agent_id: preset?.agent_id ?? null });
      setOpen(false);
      onCreated(s);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Button size="sm" variant="outline" className="w-full" onClick={() => setOpen(true)}><Plus /> Nueva conversación</Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-lg">
          <form onSubmit={submit} className="space-y-4">
            <DialogHeader>
              <DialogTitle>Nueva conversación independiente</DialogTitle>
              <DialogDescription>No comparte contexto, permisos ni vault con Jarvis. Trabaja en su propia carpeta, en un contenedor aislado sin terminal.</DialogDescription>
            </DialogHeader>
            <div className="space-y-1.5"><Label htmlFor="ns-name">Nombre</Label><Input id="ns-name" required maxLength={120} value={f.name} onChange={(e) => set("name", e.target.value)} /></div>
            <div className="space-y-1.5"><Label htmlFor="ns-desc">Descripción</Label><Input id="ns-desc" maxLength={1000} value={f.description} onChange={(e) => set("description", e.target.value)} /></div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="ns-model">Modelo</Label>
                <select id="ns-model" className={select} value={f.model} onChange={(e) => set("model", e.target.value)}>
                  <option value="sonnet">Sonnet (por defecto)</option><option value="opus">Opus (planificación compleja)</option>
                </select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="ns-level">Permisos</Label>
                <select id="ns-level" className={select} value={f.level} onChange={(e) => set("level", e.target.value)}>
                  <option value="read">Read: leer y buscar</option><option value="propose">Propose: además escribir en su carpeta</option>
                  <option value="execute" disabled={!f.virtual_computer}>Execute: comandos en su ordenador virtual</option>
                </select>
              </div>
            </div>
            <div className="space-y-2 rounded-lg bg-muted/40 p-3">
              <label className="flex items-center justify-between gap-3 text-sm"><span>Acceso a internet <span className="block text-xs text-muted-foreground">Buscar y leer webs (contenido externo = datos)</span></span><Switch checked={f.internet} onCheckedChange={(v) => set("internet", v)} /></label>
              <label className="flex items-center justify-between gap-3 text-sm"><span>Leer la vault <span className="block text-xs text-muted-foreground">Solo lectura; nunca puede escribir en ella</span></span><Switch checked={f.vault} onCheckedChange={(v) => set("vault", v)} /></label>
              <label className="flex items-center justify-between gap-3 text-sm"><span>Subagentes <span className="block text-xs text-muted-foreground">Puede repartir el trabajo en subagentes, con sus mismos permisos</span></span><Switch checked={f.subagents} onCheckedChange={(v) => set("subagents", v)} /></label>
              <label className="flex items-center justify-between gap-3 text-sm"><span>Ordenador virtual <span className="block text-xs text-muted-foreground">Puede pedir uno propio (sin red, caduca a las 2 h) y ejecutar comandos allí, nunca en tu PC</span></span><Switch checked={f.virtual_computer} onCheckedChange={(v) => { set("virtual_computer", v); if (!v && f.level === "execute") set("level", "propose"); }} /></label>
              {f.virtual_computer && (
                <select aria-label="Perfil del ordenador" className={select} value={f.vc_profile} onChange={(e) => set("vc_profile", e.target.value)}>
                  <option value="terminal">Terminal</option><option value="browser">Browser (Chromium + Playwright)</option><option value="desktop">Desktop</option>
                </select>
              )}
            </div>
            <div className="space-y-1.5"><Label htmlFor="ns-sp">Instrucciones (opcional)</Label><Textarea id="ns-sp" rows={3} maxLength={20000} value={f.system_prompt} onChange={(e) => set("system_prompt", e.target.value)} placeholder="Qué debe hacer esta conversación y cómo" /></div>
            {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => setOpen(false)}>Cancelar</Button>
              <Button type="submit" disabled={busy || !f.name.trim()}>{busy ? "Creando…" : "Crear"}</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}
