// Service worker del panel: solo notificaciones. No guarda nada en caché: los datos siempre llegan del backend.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));

self.addEventListener("push", (e) => {
  let d = {};
  try {
    d = e.data ? e.data.json() : {};
  } catch {}
  e.waitUntil(
    self.registration.showNotification(d.title || "Jarvis", {
      body: d.body || "",
      icon: "/icons/icon-192.png",
      tag: d.id ? `aviso-${d.id}` : undefined,
      data: { url: d.url || "/avisos/" },
    }),
  );
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  // Solo rutas del propio panel
  const url = new URL(e.notification.data?.url || "/avisos/", self.location.origin);
  const target = url.origin === self.location.origin ? url.href : `${self.location.origin}/avisos/`;
  e.waitUntil(
    (async () => {
      const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
      for (const w of windows) {
        await w.focus();
        if ("navigate" in w) await w.navigate(target);
        return;
      }
      await self.clients.openWindow(target);
    })(),
  );
});
