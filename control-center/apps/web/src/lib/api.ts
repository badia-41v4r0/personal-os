// Cliente de la API del backend. Mismo origen: la cookie de sesión (HttpOnly) viaja sola;
// el token CSRF se guarda solo en memoria y se manda en las peticiones con efecto.

let csrf: string | null = null;

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export function setCsrf(token: string | null) {
  csrf = token;
}

export async function api<T = unknown>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (method !== "GET" && csrf) headers.set("X-CSRF-Token", csrf);
  const res = await fetch(`/api/v1${path}`, { ...init, method, headers, credentials: "same-origin", cache: "no-store" });
  if (res.status === 401 && typeof window !== "undefined" && !path.startsWith("/auth/")) {
    window.location.href = "/login/";
  }
  if (!res.ok) {
    let msg = res.statusText;
    try {
      msg = (await res.json()).detail ?? msg;
    } catch {}
    throw new ApiError(res.status, typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return res.json() as Promise<T>;
}

export const post = <T,>(path: string, body?: unknown) =>
  api<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

/** Sube un archivo tal cual (cuerpo binario) con la cookie y el CSRF de siempre. */
export const upload = <T,>(path: string, file: Blob) =>
  api<T>(path, { method: "POST", body: file, headers: { "Content-Type": "application/octet-stream" } });
