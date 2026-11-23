"use client";

import Link from "next/link";
import { useState } from "react";
import { ArrowRight, Check, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useApi } from "@/lib/hooks";
import { usePanel } from "./shell";

type Motor = { elegido: string; proveedores: { id: string; nombre: string; conectado: boolean }[] };
type Integracion = { id: string; estado: string; activa: boolean };
type Paso = { id: string; texto: string; detalle: string; href: string; opcional?: boolean; enlaces?: [string, string][] };

const OCULTO = "pos:por-configurar-oculto";
const leer = () => { try { return localStorage.getItem(OCULTO) ?? ""; } catch { return ""; } };
const guardar = (v: string) => { try { localStorage.setItem(OCULTO, v); } catch { /* sin almacenamiento: se vuelve a ver */ } };

/**
 * «Te falta por configurar»: lo que queda para que todo funcione, con un enlace directo a cada sitio. Desaparece
 * cuando no queda nada. Ocultarla vale hasta que aparezca algo nuevo.
 */
export function PorConfigurar() {
  const { inst, me } = usePanel();
  const motor = useApi<Motor>(me.role === "admin" ? "/instancia/motor" : null);
  const integ = useApi<Integracion[]>(me.role === "admin" ? "/home/integraciones" : null);
  const [oculto, setOculto] = useState(leer);
  if (!inst || !motor.data || !integ.data) return null;

  const pasos: Paso[] = [];
  const elegido = motor.data.proveedores.find((p) => p.id === motor.data!.elegido);
  if (elegido && !elegido.conectado) {
    pasos.push({ id: "motor", texto: `Conecta ${elegido.nombre}`, detalle: "Sin motor de IA, los asistentes no pueden responder.", href: "/ajustes/motor/" });
  }
  const sinConectar = (id: string) => integ.data!.some((i) => i.id === id && i.activa && i.estado === "sin_conectar");
  if (sinConectar("google")) pasos.push({ id: "google", texto: "Conecta tu cuenta de Google", detalle: "Para ver tu calendario en la Agenda.", href: "/ajustes/conexiones/" });
  if (sinConectar("telegram")) pasos.push({ id: "telegram", texto: "Pon el bot de Telegram", detalle: "Has activado los avisos por Telegram pero falta el token.", href: "/ajustes/conexiones/" });
  const ap = inst.onboarding.apartados;
  const porConfigurar = inst.modulos.filter((m) => m.activo && !m.nucleo && m.web.length > 0 && ap[m.id] !== "hecho");
  const edu = porConfigurar.find((m) => m.id === "educacion");
  if (edu) pasos.push({ id: "educacion", texto: "Configura Educación con el tutor", detalle: "Tus asignaturas y, si quieres, el acceso a tu campus.", href: edu.web[0] });
  const resto = porConfigurar.filter((x) => x.id !== "educacion");
  if (resto.length) {
    pasos.push({ id: `apartados:${resto.map((m) => m.id).join("+")}`, texto: "Configura tus apartados con su asistente", opcional: true,
      detalle: "Te pregunta lo necesario y te deja una propuesta para aprobar:", href: "/ajustes/modulos/",
      enlaces: resto.map((m) => [m.nombre, m.web[0]]) });
  }
  if (integ.data.some((i) => i.id === "push" && i.estado === "sin_conectar")) {
    pasos.push({ id: "push", texto: "Activa los avisos en el móvil", detalle: "Para enterarte de lo que espera tu aprobación.", href: "/ajustes/conexiones/", opcional: true });
  }
  const firma = pasos.map((p) => p.id).join(",");
  if (pasos.length === 0 || oculto === firma) return null;
  const importantes = pasos.filter((p) => !p.opcional);

  return (
    <section aria-labelledby="por-configurar" className="rounded-xl border border-primary/30 bg-primary/5 p-4">
      <div className="mb-2 flex items-start justify-between gap-2">
        <div>
          <h2 id="por-configurar" className="text-sm font-medium">Te falta por configurar</h2>
          <p className="text-xs text-muted-foreground">
            {importantes.length ? `${importantes.length} ${importantes.length === 1 ? "paso necesario" : "pasos necesarios"}` : "Todo lo necesario está listo"}
            {pasos.length > importantes.length ? ` · ${pasos.length - importantes.length} opcional${pasos.length - importantes.length === 1 ? "" : "es"}` : ""}
          </p>
        </div>
        <Button variant="ghost" size="icon-sm" aria-label="Ocultar hasta que haya algo nuevo" title="Ocultar hasta que haya algo nuevo" onClick={() => { guardar(firma); setOculto(firma); }}><X /></Button>
      </div>
      <ul className="grid gap-1 sm:grid-cols-2">
        {pasos.map((p) => (
          <li key={p.id} className={p.enlaces ? "sm:col-span-2" : undefined}>
            {p.enlaces ? (
              <div className="flex items-start gap-2.5 rounded-lg px-2 py-2">
                <span className="mt-0.5 size-4 shrink-0 rounded-full border border-muted-foreground/40" aria-hidden />
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-medium">{p.texto}<span className="ml-1.5 text-xs font-normal text-muted-foreground">opcional</span></span>
                  <span className="text-xs text-muted-foreground">{p.detalle} </span>
                  {p.enlaces.map(([t, h], n) => <span key={h} className="text-xs">{n > 0 && <span className="text-muted-foreground"> · </span>}<Link href={h} className="text-primary hover:underline">{t}</Link></span>)}
                </span>
              </div>
            ) : (
            <Link href={p.href} className="group flex items-start gap-2.5 rounded-lg px-2 py-2 hover:bg-background/60">
              <span className={`mt-0.5 grid size-4 shrink-0 place-items-center rounded-full border ${p.opcional ? "border-muted-foreground/40" : "border-primary"}`} aria-hidden>
                <Check className="size-2.5 opacity-0" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-medium group-hover:text-primary">{p.texto}{p.opcional && <span className="ml-1.5 text-xs font-normal text-muted-foreground">opcional</span>}</span>
                <span className="block text-xs text-muted-foreground">{p.detalle}</span>
              </span>
              <ArrowRight className="mt-1 size-3.5 shrink-0 text-muted-foreground group-hover:text-primary" />
            </Link>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
