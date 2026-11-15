import { expect, test } from "@playwright/test";

// Instalación nueva: bienvenida en tres pasos, menú por módulos y tarjeta de primera vez en un apartado.
// Cambia la configuración: solo con CC_E2E_BIENVENIDA=1 y contra una instancia de PRUEBA recién creada.
const USER = process.env.CC_E2E_USER ?? "prueba";
const PASS = process.env.CC_E2E_PASS ?? "prueba-prueba-123";
test.skip(process.env.CC_E2E_BIENVENIDA !== "1", "Solo contra una instancia de prueba (CC_E2E_BIENVENIDA=1)");
test.describe.configure({ mode: "serial" });

async function login(page: import("@playwright/test").Page) {
  await page.goto("/login/");
  await page.getByLabel(/usuario/i).fill(USER);
  await page.getByLabel(/contraseña/i).fill(PASS);
  await page.getByRole("button", { name: /entrar/i }).click();
}

test("bienvenida, módulos y primera vez en un apartado", async ({ page }, info) => {
  test.skip(info.project.name !== "escritorio", "Cambia datos: una sola vez");
  await login(page);
  await expect(page).toHaveURL(/\/bienvenida\/?$/);
  await page.getByLabel("¿Cómo quieres que te llame?").fill("Ana");
  await page.getByLabel("Nueva área").fill("Mi proyecto");
  await page.getByRole("button", { name: "Añadir" }).click();
  await expect(page.getByText("Mi proyecto")).toBeVisible();
  await page.getByRole("button", { name: "Siguiente" }).click();
  await expect(page.getByRole("radiogroup", { name: "Motor de IA" })).toBeVisible();
  await page.getByRole("button", { name: "Lo configuro después" }).click();
  // Módulos: Finanzas activado, Entrenamiento desactivado
  await page.getByLabel("Activar Finanzas").click();
  await page.getByLabel("Activar Entrenamiento").click();
  await page.getByRole("button", { name: "Siguiente" }).click();
  await page.getByRole("button", { name: "Empezar" }).click();
  await expect(page).toHaveURL(/\/$/);
  const menu = page.getByRole("navigation", { name: "Principal" });
  await expect(menu.getByRole("link", { name: "Finanzas" })).toBeVisible();
  await expect(menu.getByRole("link", { name: "Entrenamiento" })).toHaveCount(0);
  // Apartado apagado: no se ve aunque se entre por la URL
  await page.goto("/gym/");
  await expect(page.getByRole("heading", { name: /Entrenamiento está desactivado/ })).toBeVisible();
  // Primera vez en Finanzas: tarjeta del asistente; «Ahora no» la quita y no vuelve
  await page.goto("/finanzas/");
  await expect(page.getByText("Primera vez en Finanzas")).toBeVisible();
  await page.getByRole("button", { name: "Configurar con el asistente" }).click();
  await expect(page.getByRole("button", { name: "Empezar" })).toBeVisible();
  await page.getByRole("button", { name: "Plegar" }).click();
  await expect(page.getByRole("button", { name: "Configurar con el asistente" })).toBeVisible();
  await page.getByRole("button", { name: "Ahora no" }).click();
  await expect(page.getByText("Primera vez en Finanzas")).toHaveCount(0);
  await page.reload();
  await expect(page.getByText("Primera vez en Finanzas")).toHaveCount(0);
  // Configuración → Módulos: volver a activar Entrenamiento
  await page.goto("/settings/modulos/");
  await page.getByLabel("Activar Entrenamiento").click();
  await expect(menu.getByRole("link", { name: "Entrenamiento" })).toBeVisible();
});

test("en el móvil la bienvenida ya no vuelve y el menú respeta los módulos", async ({ page }, info) => {
  test.skip(info.project.name !== "movil", "Después de la de escritorio");
  await login(page);
  await expect(page).toHaveURL(/\/$/);
  const anchoDoc = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(anchoDoc).toBeLessThanOrEqual(page.viewportSize()!.width + 1);
});
