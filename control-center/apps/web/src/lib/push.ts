// Web Push del panel. En iPhone solo funciona con el panel instalado en la pantalla de inicio y abierto desde ese icono.
import { api, post } from "./api";

export type PushDevice = { id: number; label: string; host: string; created_at: string; last_ok_at: string | null; last_error: string };
export type PushConfig = { public_key: string; subscriptions: PushDevice[] };

export const pushSupported = () =>
  typeof window !== "undefined" && "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;

export const isIOS = () => typeof navigator !== "undefined" && /iPhone|iPad|iPod/.test(navigator.userAgent);

export const isInstalled = () =>
  typeof window !== "undefined" &&
  (window.matchMedia("(display-mode: standalone)").matches || (navigator as Navigator & { standalone?: boolean }).standalone === true);

function deviceLabel() {
  const ua = navigator.userAgent;
  if (/iPhone/.test(ua)) return "iPhone";
  if (/iPad/.test(ua)) return "iPad";
  if (/Macintosh/.test(ua)) return "Mac";
  if (/Android/.test(ua)) return "Android";
  if (/Linux/.test(ua)) return "PC Linux";
  return "Navegador";
}

function keyBytes(key: string) {
  const b64 = key.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (key.length % 4)) % 4);
  return Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
}

async function register(): Promise<ServiceWorkerRegistration> {
  await navigator.serviceWorker.register("/sw.js");
  return navigator.serviceWorker.ready;
}

async function send(sub: PushSubscription) {
  const j = sub.toJSON();
  await post("/push/subscriptions", { endpoint: j.endpoint, keys: j.keys, label: deviceLabel() });
}

/** Activa los avisos en este dispositivo. Debe llamarse desde un toque del usuario (lo exige iOS). */
export async function enablePush() {
  if ((await Notification.requestPermission()) !== "granted") throw new Error("No has dado permiso para las notificaciones.");
  const reg = await register();
  const { public_key } = await api<PushConfig>("/push/config");
  const sub =
    (await reg.pushManager.getSubscription()) ??
    (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(public_key) }));
  await send(sub);
}

/** Al abrir el panel: renueva la suscripción si el sistema la ha cambiado. Sin ruido si no hay nada que hacer. */
export async function syncPush() {
  if (!pushSupported() || Notification.permission !== "granted") return;
  const reg = await register();
  const sub = await reg.pushManager.getSubscription();
  if (sub) await send(sub);
}

export async function currentEndpointActive() {
  if (!pushSupported()) return false;
  const reg = await navigator.serviceWorker.getRegistration();
  return Boolean(await reg?.pushManager.getSubscription());
}

export async function disablePushHere() {
  const reg = await navigator.serviceWorker.getRegistration();
  await (await reg?.pushManager.getSubscription())?.unsubscribe();
}
