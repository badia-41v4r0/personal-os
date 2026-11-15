"use client";

import { useState } from "react";
import { Moon, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { post, api } from "@/lib/api";
import { useAct } from "./form";

export type Slot = "manana" | "noche";
export type CheckInData = { mood: number | null; energy: number | null; sleep_h: number | null; intention: string; note: string } | null;
export type Habito = { id: number; nombre: string; hoy: boolean; racha: number };
export type CheckInView = { dia: string; manana: CheckInData; noche: CheckInData; sugerido: Slot | null; habitos: Habito[] };

const TITULO: Record<Slot, string> = { manana: "Check-in de la mañana", noche: "Check-in de la noche" };

function Escala({ label, value, onChange }: { label: string; value: number | null; onChange: (n: number | null) => void }) {
  return (
    <div>
      <div className="mb-1 text-xs text-muted-foreground">{label} <span className="opacity-70">(1 mal · 5 muy bien)</span></div>
      <div role="radiogroup" aria-label={label} className="flex gap-1.5">
        {[1, 2, 3, 4, 5].map((n) => (
          <button
            key={n}
            type="button"
            role="radio"
            aria-checked={value === n}
            aria-label={`${label}: ${n}`}
            onClick={() => onChange(value === n ? null : n)}
            className={`size-10 rounded-lg border text-sm font-medium tabular-nums transition-colors ${value === n ? "border-primary bg-primary text-primary-foreground" : "border-border hover:border-primary/50"}`}
          >
            {n}
          </button>
        ))}
      </div>
    </div>
  );
}

function Formulario({ slot, inicial, habitos, onDone }: { slot: Slot; inicial: CheckInData; habitos: Habito[]; onDone: () => void }) {
  const [mood, setMood] = useState<number | null>(inicial?.mood ?? null);
  const [energy, setEnergy] = useState<number | null>(inicial?.energy ?? null);
  const [sleep, setSleep] = useState(inicial?.sleep_h != null ? String(inicial.sleep_h) : "");
  const [intention, setIntention] = useState(inicial?.intention ?? "");
  const [note, setNote] = useState(inicial?.note ?? "");
  const [cerrado, setCerrado] = useState(false);
  const act = useAct(onDone);
  const toggle = useAct(onDone);

  const body = () => ({
    slot, mood, energy,
    sleep_h: slot === "manana" && sleep.trim() !== "" ? Number(sleep.replace(",", ".")) : null,
    intention: slot === "manana" ? intention : "",
    note: slot === "noche" ? note : "",
  });
  const vacio = mood == null && energy == null && sleep.trim() === "" && !intention.trim() && !note.trim();
  const guardar = (cerrar: boolean) =>
    act.run(async () => {
      await api("/me/checkin", { method: "PUT", body: JSON.stringify(body()) });
      if (cerrar) {
        await post("/me/checkin/close");
        setCerrado(true);
      }
    });

  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <Escala label="Ánimo" value={mood} onChange={setMood} />
        <Escala label="Energía" value={energy} onChange={setEnergy} />
      </div>
      {slot === "manana" ? (
        <div className="grid gap-3 sm:grid-cols-[8rem_1fr]">
          <label className="grid gap-1 text-xs text-muted-foreground">
            <span>Horas dormidas</span>
            <Input inputMode="decimal" value={sleep} onChange={(e) => setSleep(e.target.value)} placeholder="7,5" aria-label="Horas dormidas" />
          </label>
          <label className="grid gap-1 text-xs text-muted-foreground">
            <span>Lo más importante de hoy</span>
            <Input value={intention} maxLength={300} onChange={(e) => setIntention(e.target.value)} placeholder="Terminar la PEC de FP" aria-label="Lo más importante de hoy" />
          </label>
        </div>
      ) : (
        <label className="grid gap-1 text-xs text-muted-foreground">
          <span>¿Cómo ha ido el día?</span>
          <Textarea value={note} maxLength={1000} rows={3} onChange={(e) => setNote(e.target.value)} placeholder="Lo que has hecho, lo que se ha quedado atrás, cómo te sientes…" aria-label="Cómo ha ido el día" />
        </label>
      )}
      {habitos.length > 0 && (
        <div>
          <div className="mb-1 text-xs text-muted-foreground">Hábitos de hoy</div>
          <div className="flex flex-wrap gap-2">
            {habitos.map((h) => (
              <button
                key={h.id}
                type="button"
                aria-pressed={h.hoy}
                disabled={toggle.busy}
                onClick={() => void toggle.run(() => post(`/me/habits/${h.id}/toggle`, {}))}
                className={`min-h-10 rounded-lg border px-3 text-sm transition-colors ${h.hoy ? "border-success bg-success/15" : "border-border hover:border-primary/50"}`}
              >
                {h.hoy ? "✓ " : ""}{h.nombre}{h.racha > 1 ? <span className="ml-1 text-xs text-muted-foreground">{h.racha} días</span> : null}
              </button>
            ))}
          </div>
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" disabled={act.busy || vacio} onClick={() => void guardar(false)}>{act.busy ? "Guardando…" : "Guardar"}</Button>
        {slot === "noche" && (
          <Button size="sm" variant="outline" disabled={act.busy || vacio} onClick={() => void guardar(true)}>Guardar y cerrar el día</Button>
        )}
        {cerrado && <span className="text-xs text-success">Cierre encargado: Jarvis escribirá el diario.</span>}
      </div>
      {act.ErrorBox}
      {toggle.ErrorBox}
    </div>
  );
}

export function CheckInCard({ data, onChange }: { data: CheckInView; onChange: () => void }) {
  const [slot, setSlot] = useState<Slot>(data.sugerido ?? "manana");
  const [editar, setEditar] = useState(false);
  const hecho = data[slot] != null;
  const Icono = slot === "manana" ? Sun : Moon;

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <CardTitle className="flex items-center gap-2"><Icono className="size-4 text-primary" />{TITULO[slot]}</CardTitle>
        <div role="tablist" aria-label="Franja" className="flex gap-1 text-xs">
          {(["manana", "noche"] as Slot[]).map((s) => (
            <button
              key={s}
              role="tab"
              aria-selected={slot === s}
              onClick={() => { setSlot(s); setEditar(false); }}
              className={`min-h-9 rounded-md px-3 ${slot === s ? "bg-primary/12 font-medium" : "text-muted-foreground hover:text-foreground"}`}
            >
              {s === "manana" ? "Mañana" : "Noche"}{data[s] ? " ✓" : ""}
            </button>
          ))}
        </div>
      </CardHeader>
      <CardContent>
        {hecho && !editar ? (
          <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
            <span className="text-muted-foreground">
              Hecho{data[slot]?.mood ? ` · ánimo ${data[slot]!.mood}/5` : ""}{data[slot]?.energy ? ` · energía ${data[slot]!.energy}/5` : ""}{data[slot]?.sleep_h != null ? ` · ${data[slot]!.sleep_h} h de sueño` : ""}
              {data[slot]?.intention ? ` · «${data[slot]!.intention}»` : ""}
            </span>
            <Button size="sm" variant="outline" onClick={() => setEditar(true)}>Editar</Button>
          </div>
        ) : (
          <Formulario key={`${slot}-${JSON.stringify(data[slot])}`} slot={slot} inicial={data[slot]} habitos={data.habitos} onDone={() => { setEditar(false); onChange(); }} />
        )}
      </CardContent>
    </Card>
  );
}
