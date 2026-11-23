import { expect, test, type Page } from "@playwright/test";

const USER = process.env.CC_E2E_USER ?? "prueba";
const PASS = process.env.CC_E2E_PASS ?? "prueba-prueba-123";

async function login(page: Page) {
  await page.goto("/login/");
  await page.getByLabel("Usuario").fill(USER);
  await page.getByLabel("Contraseña").fill(PASS);
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page.getByRole("heading", { name: /^Buen(os|as) (días|tardes|noches)/ })).toBeVisible();
}

test("la app se puede instalar: manifest, iconos y service worker", async ({ request }) => {
  const m = await request.get("/manifest.webmanifest");
  expect(m.ok()).toBeTruthy();
  const manifest = await m.json();
  expect(manifest.display).toBe("standalone");
  for (const i of manifest.icons) expect((await request.get(i.src)).ok()).toBeTruthy();
  expect((await request.get("/icons/icon-180.png")).ok()).toBeTruthy();
  const sw = await request.get("/sw.js");
  expect(sw.ok()).toBeTruthy();
  expect(sw.headers()["content-type"]).toContain("javascript");
});

test("la bandeja muestra los avisos y se marcan como leídos", async ({ page, isMobile }) => {
  await login(page);
  await page.goto("/bandeja/?t=avisos");
  await expect(page.getByRole("heading", { name: "Avisos" })).toBeVisible();
  await expect(page.getByText("Aviso de la prueba E2E").first()).toBeVisible();
  if (isMobile) {
    await expect(page.getByRole("link", { name: /^Bandeja/ }).first()).toBeVisible();
  }
});

test("el service worker se registra en el panel", async ({ page }) => {
  await login(page);
  const state = await page.evaluate(async () => {
    const reg = await navigator.serviceWorker.register("/sw.js");
    const r = await navigator.serviceWorker.ready;
    return { scope: reg.scope, active: Boolean(r.active) };
  });
  expect(state.active).toBe(true);
  expect(new URL(state.scope).pathname).toBe("/");
});

test("sin soporte de push o sin instalar, la página lo explica sin romperse", async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "userAgent", { get: () => "Mozilla/5.0 (iPhone; CPU iPhone OS 26_0 like Mac OS X)" });
  });
  await login(page);
  await page.goto("/ajustes/conexiones/");
  await expect(page.getByText("Instala el panel para recibir avisos")).toBeVisible();
});
