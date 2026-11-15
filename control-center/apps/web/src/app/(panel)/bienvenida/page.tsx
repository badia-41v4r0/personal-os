"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Check } from "lucide-react";
import { PageHeader, usePanel } from "@/components/cc/shell";
import { Loading, ErrorState } from "@/components/cc/states";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { MotorCard } from "@/components/cc/motor-card";
import { api } from "@/lib/api";

type Area = { id: string; nombre: string; emoji: string };
const PASOS = ["Tú", "Motor de IA", "Módulos", "Listo"];
const AREAS_DEF: Area[] = [
  { id: "trabajo", nombre: "Trabajo", emoji: "💼" }, { id: "uni", nombre: "Estudios", emoji: "🎓" }, { id: "personal", nombre: "Personal", emoji: "🏠" },
];
const slug = (s: string) => s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40);

export default function Bienvenida() {
  const router = useRouter();
  const { inst, reloadInst } = usePanel();
  const [paso, setPaso] = useState(0);
  const [nombre, setNombre] = useState("");
  const [areas, setAreas] = useState<Area[]>(AREAS_DEF);
  const [nueva, setNueva] = useState("");
  const [activos, setActivos] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (!inst) return <Loading rows={4} />;
  const sel = activos ?? inst.modulos.filter((m) => m.activo).map((m) => m.id);

  const guardar = async (f: () => Promise<unknown>, siguiente: number) => {
    setBusy(true);
    setError(null);
    try {
      await f();
      reloadInst();
      setPaso(siguiente);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader title="Bienvenido al Personal OS" description="Tres pasos y listo. Todo se puede cambiar después en Configuración." />
      <ol className="mb-6 flex flex-wrap gap-2 text-sm" aria-label="Pasos">
        {PASOS.map((p, i) => (
          <li key={p} aria-current={i === paso ? "step" : undefined}
            className={`flex items-center gap-1.5 rounded-full px-3 py-1 ${i === paso ? "bg-primary text-primary-foreground" : i < paso ? "bg-primary/15 text-primary" : "bg-muted text-muted-foreground"}`}>
            {i < paso ? <Check className="size-3.5" /> : <span className="font-mono text-xs">{i + 1}</span>}{p}
          </li>
        ))}
      </ol>
      {error && <div className="mb-4"><ErrorState message={error} /></div>}

      {paso === 0 && (
        <Card>
          <CardHeader><CardTitle>Sobre ti</CardTitle></CardHeader>
          <CardContent className="space-y-4 text-sm">
            <label className="block space-y-1" htmlFor="b-nombre"><span className="font-medium">¿Cómo quieres que te llame?</span>
              <Input id="b-nombre" value={nombre} onChange={(e) => setNombre(e.target.value)} placeholder="Tu nombre" autoFocus /></label>
            <div className="space-y-2">
              <p className="font-medium">Áreas de tu vida (agrupan tus tareas)</p>
              <div className="flex flex-wrap gap-2">
                {areas.map((a) => (
                  <span key={a.id} className="inline-flex items-center gap-1 rounded-full border border-border px-3 py-1">{a.emoji} {a.nombre}
                    {a.id !== "personal" && <button type="button" aria-label={`Quitar ${a.nombre}`} className="ml-1 text-muted-foreground hover:text-foreground" onClick={() => setAreas(areas.filter((x) => x.id !== a.id))}>×</button>}
                  </span>
                ))}
              </div>
              <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); const id = slug(nueva); if (id && !areas.some((a) => a.id === id)) setAreas([...areas, { id, nombre: nueva.trim(), emoji: "•" }]); setNueva(""); }}>
                <Input value={nueva} onChange={(e) => setNueva(e.target.value)} placeholder="Añadir área (p. ej. Casa, Mi proyecto)" aria-label="Nueva área" />
                <Button type="submit" variant="outline" size="sm">Añadir</Button>
              </form>
            </div>
            <div className="flex justify-end">
              <Button disabled={busy || !nombre.trim()} onClick={() => guardar(() => api("/instancia/config/perfil", { method: "PUT", body: JSON.stringify({ nombre: nombre.trim(), areas }) }), 1)}>Siguiente</Button>
            </div>
          </CardContent>
        </Card>
      )}

      {paso === 1 && (
        <div className="space-y-3">
          <MotorCard onListo={() => setPaso(2)} />
          <div className="flex justify-between"><Button variant="ghost" onClick={() => setPaso(0)}>Atrás</Button>
            <Button variant="ghost" onClick={() => setPaso(2)}>Lo configuro después</Button></div>
        </div>
      )}

      {paso === 2 && (
        <Card>
          <CardHeader><CardTitle>¿Qué quieres usar?</CardTitle></CardHeader>
          <CardContent className="space-y-2 text-sm">
            <p className="text-muted-foreground">Activa solo lo que vayas a usar. La primera vez que abras cada apartado, su asistente te ayudará a configurarlo.</p>
            {inst.modulos.filter((m) => !m.nucleo).map((m) => (
              <label key={m.id} className="flex items-start justify-between gap-3 rounded-lg border border-border p-3">
                <span><span className="font-medium">{m.nombre}</span><span className="block text-xs text-muted-foreground">{m.descripcion}</span></span>
                <Switch checked={sel.includes(m.id)} onCheckedChange={(v: boolean) => setActivos(v ? [...sel, m.id] : sel.filter((x) => x !== m.id))} aria-label={`Activar ${m.nombre}`} />
              </label>
            ))}
            <div className="flex justify-between pt-2"><Button variant="ghost" onClick={() => setPaso(1)}>Atrás</Button>
              <Button disabled={busy} onClick={() => guardar(() => api("/instancia/modulos", { method: "PUT", body: JSON.stringify({ activos: sel }) }), 3)}>Siguiente</Button></div>
          </CardContent>
        </Card>
      )}

      {paso === 3 && (
        <Card>
          <CardHeader><CardTitle>¡Listo!</CardTitle></CardHeader>
          <CardContent className="space-y-3 text-sm">
            <p>En Inicio está Jarvis, que lo ve todo. Cada apartado tiene su propio asistente y, la primera vez que lo abras, te ofrecerá configurarlo contigo.</p>
            <p className="text-muted-foreground">Cuentas como Google, GitHub o Telegram se conectan en Configuración cuando las necesites.</p>
            <div className="flex justify-end">
              <Button disabled={busy} onClick={() => guardar(async () => {
                await api("/instancia/config/onboarding", { method: "PUT", body: JSON.stringify({ hecho: true, apartados: { ...inst.onboarding.apartados, inicio: "hecho", sistema: "hecho" } }) });
                router.replace("/");
              }, 3)}>Empezar</Button>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
