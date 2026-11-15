import type { Level } from "@/components/cc/status";
import type { Unit } from "./types";

/** Estado de una unidad systemd según su tipo: un .service oneshot inactivo y con Result=success está bien. */
export function unitLevel(u: Unit): Level {
  if (u.ActiveState === "failed" || (u.Result && u.Result !== "success")) return "down";
  if (u.ActiveState === "activating") return "warn";
  if (u.Id.endsWith(".service") && u.ActiveState === "inactive") return "ok";
  if (u.ActiveState === "active") return "ok";
  return "unknown";
}

export function unitDetail(u: Unit): string {
  if (u.ActiveState === "activating") return "en curso";
  if (u.Result && u.Result !== "success") return `falló (${u.Result})`;
  if (u.Id.endsWith(".service") && u.ActiveState === "inactive") return "en espera";
  return u.SubState;
}
