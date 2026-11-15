import { cn } from "cn";

export type Level = "ok" | "warn" | "down" | "unknown";

const COLORS: Record<Level, string> = {
  ok: "bg-success",
  warn: "bg-warning",
  down: "bg-destructive",
  unknown: "bg-muted-foreground/40",
};

export function StatusDot({ level, pulse }: { level: Level; pulse?: boolean }) {
  return (
    <span className="relative inline-flex size-2.5 shrink-0">
      {pulse && level === "ok" && (
        <span className={cn("absolute inline-flex size-full animate-ping rounded-full opacity-40", COLORS[level])} />
      )}
      <span className={cn("relative inline-flex size-2.5 rounded-full", COLORS[level])} />
    </span>
  );
}

export function StatusRow({ label, level, detail }: { label: string; level: Level; detail?: string }) {
  return (
    <div className="flex items-center justify-between gap-3 py-1.5">
      <div className="flex min-w-0 items-center gap-2.5">
        <StatusDot level={level} />
        <span className="truncate text-sm">{label}</span>
      </div>
      {detail && <span className="truncate text-xs text-muted-foreground">{detail}</span>}
    </div>
  );
}
