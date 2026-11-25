import { useId } from "react";
import { cn } from "@/lib/utils";

/** Marca de Personal OS: tres módulos y el asistente (el círculo). Misma figura que public/icons/logo.svg. */
export function Logo({ className, title }: { className?: string; title?: string }) {
  const id = useId();
  return (
    <svg viewBox="0 0 64 64" className={cn("size-8 shrink-0", className)} role={title ? "img" : undefined} aria-hidden={title ? undefined : true} aria-label={title}>
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#4f46e5" />
          <stop offset="0.55" stopColor="#2563eb" />
          <stop offset="1" stopColor="#06b6d4" />
        </linearGradient>
      </defs>
      <rect width="64" height="64" rx="15" fill={`url(#${id})`} />
      <rect x="14" y="14" width="15" height="15" rx="4.5" fill="#fff" fillOpacity=".5" />
      <rect x="14" y="35" width="15" height="15" rx="4.5" fill="#fff" fillOpacity=".5" />
      <rect x="35" y="35" width="15" height="15" rx="4.5" fill="#fff" fillOpacity=".5" />
      <circle cx="42.5" cy="21.5" r="8.5" fill="#fff" />
      <circle cx="42.5" cy="21.5" r="3" fill="#2563eb" />
    </svg>
  );
}
