import { expect, test, type Page } from "@playwright/test";

// Gym 2.0. Las pruebas que cambian datos (aceptar, editar, rutinas, sensaciones) solo corren en el proyecto
// «escritorio» y deben ir contra un backend de PRUEBA (CC_E2E_URL), nunca contra el panel real.
const USER = process.env.CC_E2E_USER ?? "prueba";
const PASS = process.env.CC_E2E_PASS ?? "prueba-prueba-123";
const MUTA = process.env.CC_E2E_GYM_MUTA === "1";

async function login(page: Page) {
  await page.goto("/login/");
  await page.getByLabel("Usuario").fill(USER);
  await page.getByLabel("Contraseña").fill(PASS);
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page.getByRole("heading", { name: /^Buen(os|as) (días|tardes|noches)/ })).toBeVisible();
}

test.describe.configure({ mode: "serial" });

test("gym: navegación por las 7 pestañas sin errores", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("response", (r) => { if (r.url().includes("/api/v1/gym") && r.status() >= 500) errors.push(`${r.status()} ${r.url()}`); });
  await login(page);
  await page.goto("/entrenamiento/");
  await expect(page.getByText("Próximo entrenamiento")).toBeVisible();
  await expect(page.getByText("Análisis de Jarvis")).toBeVisible();
  await expect(page.locator(".recharts-surface").first()).toBeVisible();
  for (const [tab, texto] of [["Entreno de hoy", /Entrenamiento recomendado|Sesión planificada/], ["Progreso", "Récords personales (90 días)"],
    ["Recuperación", "Carga reciente por músculo"], ["Historial", "Importar de Hevy"], ["Rutinas", "Calendario"], ["Coach", "Propuestas por revisar"]] as const) {
    await page.getByRole("navigation", { name: "Secciones del gym" }).getByRole("link", { name: tab }).click();
    await expect(page.getByText(texto).first()).toBeVisible();
  }
  const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(over).toBeLessThanOrEqual(1);
  expect(errors).toEqual([]);
});

test("gym: filtros del historial, detalle y comparación", async ({ page }) => {
  await login(page);
  await page.goto("/entrenamiento/?tab=history");
  const filas = page.locator('a[href*="tab=history&w="]');
  await expect(filas.first()).toBeVisible();
  const total = await filas.count();
  await page.getByLabel("Rutina").selectOption("Push");
  await expect.poll(async () => filas.count()).toBeLessThan(total);
  await page.getByRole("checkbox").nth(0).check();
  await page.getByRole("checkbox").nth(1).check();
  await page.getByRole("link", { name: "Comparar", exact: true }).click();
  await expect(page.getByText(/frente a/).first()).toBeVisible();
  await filas.first().click();
  await expect(page.getByText("Comparación con lo planificado")).toBeVisible();
});

test("gym: detalle de ejercicio con periodos y gráficos", async ({ page }) => {
  await login(page);
  await page.goto("/entrenamiento/?tab=progress");
  await page.locator('a[href*="tab=progress&e="]').first().click();
  await expect(page.getByText("Siguiente objetivo")).toBeVisible();
  await expect(page.getByText("Carga por sesión (kg)")).toBeVisible();
  await page.getByRole("button", { name: "3 meses" }).click();
  await expect(page.getByRole("button", { name: "3 meses" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".recharts-surface").first()).toBeVisible();
  await expect(page.getByText("estimación").first()).toBeVisible(); // e1RM marcado como estimación
});

test("gym: aceptar, modificar y comparar el entrenamiento recomendado", async ({ page }, info) => {
  test.skip(!MUTA || info.project.name !== "escritorio", "cambia datos: solo en el backend de prueba y en escritorio");
  await login(page);
  await page.goto("/entrenamiento/?tab=training");
  await page.getByRole("button", { name: "Aceptar planificación" }).click();
  await expect(page.getByText("Sesión planificada")).toBeVisible();
  await page.getByRole("link", { name: "Modificar" }).first().click();
  await page.getByRole("button", { name: "Añadir ejercicio" }).click();
  await page.getByLabel(/Ejercicio \d+/).last().fill("Fondos");
  await page.getByLabel("Motivo del cambio").fill("prueba e2e");
  await page.getByRole("button", { name: "Guardar" }).click();
  await expect(page.getByLabel("Motivo del cambio")).toBeHidden(); // guardado: se cierra el editor
  await page.locator('a[href*="tab=training&plan="]').first().click();
  await expect(page.getByText("Previsto frente a realizado")).toBeVisible();
  await expect(page.getByText(/v2 · /).first()).toBeVisible();
});

test("gym: editor de rutinas con versiones y sensaciones", async ({ page }, info) => {
  test.skip(!MUTA || info.project.name !== "escritorio", "cambia datos: solo en el backend de prueba y en escritorio");
  await login(page);
  await page.goto("/entrenamiento/?tab=routines");
  await page.getByLabel("Nombre de la rutina nueva").fill(`E2E ${Date.now()}`);
  await page.getByRole("button", { name: "Crear desde mi historial" }).click();
  await expect(page.getByText("Versiones")).toBeVisible();
  await page.getByText("Editar", { exact: true }).click();
  await page.getByRole("button", { name: "Ejercicio" }).last().click();
  await page.getByLabel("Ejercicio", { exact: true }).last().fill("Curl de Bíceps (Cable)");
  await page.getByLabel("Motivo").fill("añado curl");
  await page.getByRole("button", { name: "Guardar", exact: true }).click();
  await expect(page.getByText("v2").first()).toBeVisible();

  await page.goto("/entrenamiento/?tab=recovery");
  await page.getByRole("group", { name: "Energía" }).getByRole("button", { name: "4" }).click();
  await page.getByRole("button", { name: "Guardar sensaciones" }).click();
  await expect(page.getByText(/Guardado el/)).toBeVisible();
});

test("gym: Coach con su conversación y el historial de decisiones", async ({ page }) => {
  await login(page);
  await page.goto("/entrenamiento/?tab=coach");
  await expect(page.getByText("Coach del gym", { exact: true })).toBeVisible();
  await expect(page.getByText("Historial de decisiones")).toBeVisible();
  await expect(page.getByText("Informes")).toBeVisible();
});
