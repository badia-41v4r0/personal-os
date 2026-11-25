import { Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Assistant } from "./assistants";
import { Logo } from "./logo";

const TAM = {
  xs: { caja: "size-6 rounded-md", icono: "size-3.5" },
  sm: { caja: "size-7 rounded-lg", icono: "size-4" },
  md: { caja: "size-8 rounded-lg", icono: "size-[18px]" },
  lg: { caja: "size-12 rounded-2xl", icono: "size-6" },
} as const;

/** Avatar de un asistente: el logo para el general; para los de cada apartado, su icono y su color. */
export function AvatarAsistente({ asistente, tam = "sm", redondo, className }: {
  asistente: Assistant; tam?: keyof typeof TAM; redondo?: boolean; className?: string;
}) {
  const t = TAM[tam];
  const forma = redondo ? "rounded-full" : "";
  if (!asistente.key) return <Logo className={cn(t.caja, forma, "overflow-hidden", className)} />;
  const Icono = asistente.icon ?? Sparkles;
  return (
    <span aria-hidden className={cn("grid shrink-0 place-items-center", t.caja, forma, asistente.tono ?? "bg-primary/12 text-primary", className)}>
      <Icono className={t.icono} strokeWidth={2} />
    </span>
  );
}
