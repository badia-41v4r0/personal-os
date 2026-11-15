import { expect, test, type Page } from "@playwright/test";

// Calendario unificado (Agenda). Marcar tareas solo con CC_E2E_CAL_MUTA=1 y un backend de PRUEBA que tenga un Tareas.md de prueba.
const USER = process.env.CC_E2E_USER ?? "prueba";
const PASS = process.env.CC_E2E_PASS ?? "prueba-prueba-123";
const SHOTS = process.env.CC_E2E_SHOTS;
const MUTA = process.env.CC_E2E_CAL_MUTA === "1";

async function login(page: Page) {
  await page.goto("/login/");
  await page.getByLabel("Usuario").fill(USER);
  await page.getByLabel("Contraseña").fill(PASS);
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page.getByRole("heading", { name: /^Buen(os|as) (días|tardes|noches)/ })).toBeVisible();
}
const sinDesborde = async (page: Page) => expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);

test("agenda: el calendario carga, filtra por capas y no desborda", async ({ page }, info) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("response", (r) => { if (r.url().includes("/api/v1/calendar") && r.status() >= 500) errors.push(`${r.status()} ${r.url()}`); });
  await login(page);
  await page.goto("/agenda/");
  await expect(page.getByRole("tablist", { name: "Vista" })).toBeVisible();
  await expect(page.getByRole("group", { name: "Capas" }).or(page.getByLabel("Capas"))).toBeVisible();
  await expect(page.getByText("Incluir calendario de Canvas")).toBeVisible();
  // Con datos de prueba de las capas locales, algo debe aparecer hoy
  await expect(page.getByText(/Pagar el seguro|Nada en este periodo/).locator("visible=true").first()).toBeVisible();

  // Apagar todas las capas locales deja solo Google (que en el entorno de prueba no está conectado)
  for (const c of ["Uni", "Tareas", "Trabajo", "Gym", "Vida"]) await page.getByRole("button", { name: c, exact: true }).click();
  await expect(page.getByText("Pagar el seguro")).toHaveCount(0);
  for (const c of ["Uni", "Tareas", "Trabajo", "Gym", "Vida"]) await page.getByRole("button", { name: c, exact: true }).click();

  for (const v of ["Semana", "Lista", "Mes"]) {
    await page.getByRole("tab", { name: v }).click();
    await sinDesborde(page);
  }

  // Vista de día: rejilla horaria con el bloque de estudio de hoy (10:30–12:30) y la línea de la hora actual
  await page.getByRole("tab", { name: "Día" }).click();
  await expect(page.getByRole("group", { name: "Horas del día" })).toBeVisible();
  await expect(page.getByRole("group", { name: "Horas del día" }).getByText("FP · Módulo 1")).toBeVisible();
  await expect(page.getByLabel("Sin hora")).toContainText("Pagar el seguro");
  await expect(page.getByLabel("Hora actual")).toBeAttached();
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/calendario-dia-${info.project.name}.png`, fullPage: true });
  await sinDesborde(page);
  await page.getByRole("button", { name: "Siguiente" }).click();
  await expect(page.getByLabel("Hora actual")).toHaveCount(0);  // mañana no hay línea de "ahora"
  await sinDesborde(page);
  await page.getByRole("tab", { name: "Mes" }).click();
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/calendario-${info.project.name}.png`, fullPage: true });
  expect(errors).toEqual([]);
});

test("agenda: marcar y deshacer una tarea desde el calendario", async ({ page }) => {
  test.skip(!MUTA, "Cambia datos: solo con CC_E2E_CAL_MUTA=1 y un backend de prueba con Tareas.md de prueba");
  await login(page);
  await page.goto("/agenda/");
  await page.getByRole("tab", { name: "Día" }).click();
  const sinHora = page.getByLabel("Sin hora");
  await sinHora.getByRole("button", { name: "Marcar «Llamar al banco» como hecha" }).click();
  await expect(sinHora.getByRole("button", { name: "Deshacer «Llamar al banco»" })).toBeVisible();
  await expect(sinHora.getByRole("alert")).toHaveCount(0);
  await sinHora.getByRole("button", { name: "Deshacer «Llamar al banco»" }).click();
  await expect(sinHora.getByRole("button", { name: "Marcar «Llamar al banco» como hecha" })).toBeVisible();
});
