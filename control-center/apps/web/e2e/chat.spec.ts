import { expect, test, type Page } from "@playwright/test";

const USER = process.env.CC_E2E_USER ?? "prueba";
const PASS = process.env.CC_E2E_PASS ?? "prueba-prueba-123";
const SHOTS = process.env.CC_E2E_SHOTS;
// Enviar mensajes gasta modelo: solo con CC_E2E_CHAT=1 (p. ej. contra una instancia con el Host Agent simulado)
const ENVIAR = process.env.CC_E2E_CHAT === "1";

async function shot(page: Page, name: string, project: string) {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${project}-chat-${name}.png` });
}

async function login(page: Page) {
  await page.goto("/login/");
  await page.getByLabel("Usuario").fill(USER);
  await page.getByLabel("Contraseña").fill(PASS);
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page.getByRole("heading", { name: /^Buen(os|as) (días|tardes|noches)/ })).toBeVisible();
}

test("chat flotante: plegado, desplegado y agente de cada apartado", async ({ page }, info) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await login(page);
  // En Inicio, la barra es del asistente general
  const barra = page.getByRole("textbox", { name: /^Pregunta a / });
  await expect(barra).toBeVisible();
  await shot(page, "plegado", info.project.name);

  // En Educación, la barra es del tutor
  await page.goto("/educacion/");
  await expect(page.getByRole("textbox", { name: "Pregunta a Tutor…" })).toBeVisible();

  await page.getByRole("button", { name: "Abrir el chat con Tutor" }).click();
  const chat = page.getByRole("dialog", { name: "Chat con Tutor" });
  await expect(chat.getByRole("heading", { name: "¿En qué te ayudo?" })).toBeVisible();
  await shot(page, "desplegado", info.project.name);

  // Se puede cambiar a otro agente desde el selector
  await chat.getByRole("button", { name: "Tutor", exact: false }).first().click();
  await chat.getByRole("option", { name: /Finanzas/ }).click();
  await expect(page.getByRole("dialog", { name: "Chat con Finanzas" })).toBeVisible();

  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("chat flotante: pregunta, pasos en directo e historial", async ({ page }, info) => {
  test.skip(!ENVIAR, "solo con CC_E2E_CHAT=1");
  test.setTimeout(90_000);
  await login(page);
  await page.goto("/educacion/");
  const pregunta = `¿Cuándo entrego la PEC2? ${Date.now()}`;
  await page.getByRole("textbox", { name: "Pregunta a Tutor…" }).fill(pregunta);
  await page.keyboard.press("Enter");
  const chat = page.getByRole("dialog", { name: "Chat con Tutor" });
  await expect(chat.locator("section").getByText(pregunta, { exact: true }).last()).toBeVisible();
  await expect(chat.getByRole("button", { name: "Parar la respuesta" })).toBeVisible();
  await page.waitForTimeout(2500);
  await shot(page, "trabajando", info.project.name);
  // Plegado mientras trabaja: la barra dice qué está haciendo y vuelve a abrir el chat
  await page.keyboard.press("Escape");
  const aviso = page.getByRole("button", { name: /Tutor · .*Ver$/ });
  await expect(aviso).toBeVisible();
  await shot(page, "plegado-trabajando", info.project.name);
  await aviso.click();
  await expect(chat.getByText(/Ha mirado \d+ cosas?/)).toBeVisible({ timeout: 60_000 });
  await shot(page, "respuesta", info.project.name);

  await chat.getByText(/Ha mirado \d+ cosas?/).click();
  await shot(page, "pasos", info.project.name);

  // Sale en el historial y se puede empezar otra
  if (info.project.name === "movil") await chat.getByRole("button", { name: "Ver conversaciones" }).click();
  const historial = chat.getByRole("navigation", { name: "Conversaciones con Tutor" });
  await expect(historial.getByRole("button", { name: pregunta })).toBeVisible();
  await shot(page, "historial", info.project.name);
  await chat.getByRole("button", { name: "Nueva conversación" }).first().click();
  await expect(chat.getByRole("heading", { name: "¿En qué te ayudo?" })).toBeVisible();
});
