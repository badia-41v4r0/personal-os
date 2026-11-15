export function bytes(n: number | undefined | null): string {
  if (n == null) return "—";
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < u.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(v < 10 && i > 0 ? 1 : 0)} ${u[i]}`;
}

export function duration(s: number): string {
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  return d ? `${d} d ${h} h` : h ? `${h} h ${m} min` : `${m} min`;
}

export function timeAgo(iso: string | undefined | null): string {
  if (!iso) return "—";
  const t = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z").getTime();
  const s = Math.round((Date.now() - t) / 1000);
  if (Number.isNaN(s)) return "—";
  if (s < 60) return "ahora";
  if (s < 3600) return `hace ${Math.floor(s / 60)} min`;
  if (s < 86400) return `hace ${Math.floor(s / 3600)} h`;
  return `hace ${Math.floor(s / 86400)} d`;
}

export function clock(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString("es-ES", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

/** "en 2 h 10 min" / "en 3 d 4 h" hasta una fecha ISO. */
export function until(iso: string | null | undefined): string {
  if (!iso) return "—";
  const s = Math.round((new Date(iso).getTime() - Date.now()) / 1000);
  if (Number.isNaN(s)) return "—";
  if (s <= 0) return "ya";
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  return d ? `en ${d} d ${h} h` : h ? `en ${h} h ${m} min` : `en ${m} min`;
}
