import { expect, test, type Page } from "@playwright/test";

// Educación. Las pruebas que cambian datos (tarjetas, archivos, cronómetro) solo corren con CC_E2E_EDU_MUTA=1
// y siempre contra un backend de PRUEBA (CC_E2E_URL), nunca contra el panel real.
const USER = process.env.CC_E2E_USER ?? "prueba";
const PASS = process.env.CC_E2E_PASS ?? "prueba-prueba-123";
const MUTA = process.env.CC_E2E_EDU_MUTA === "1";
const SHOTS = process.env.CC_E2E_SHOTS;

async function login(page: Page) {
  await page.goto("/login/");
  await page.getByLabel("Usuario").fill(USER);
  await page.getByLabel("Contraseña").fill(PASS);
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page.getByRole("heading", { name: /^Buen(os|as) (días|tardes|noches)/ })).toBeVisible();
}
const shot = async (page: Page, name: string, info: { project: { name: string } }) => { if (SHOTS) await page.screenshot({ path: `${SHOTS}/edu-${name}-${info.project.name}.png`, fullPage: true }); };
const sinDesborde = async (page: Page) => expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);

test.describe.configure({ mode: "serial" });

test("educación: las pestañas cargan con datos reales y sin errores", async ({ page }, info) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("response", (r) => { if (r.url().includes("/api/v1/education") && r.status() >= 500) errors.push(`${r.status()} ${r.url()}`); });
  await login(page);
  await page.goto("/educacion/");
  await expect(page.getByText("Cómo vas")).toBeVisible();
  await expect(page.getByText("Carga por semana")).toBeVisible();
  await expect(page.getByRole("button", { name: "Estudiar ahora" })).toBeVisible();
  await expect(page.getByText("Entregas", { exact: true })).toBeVisible();
  await sinDesborde(page);
  await shot(page, "hoy", info);

  const nav = page.getByRole("navigation", { name: "Secciones de Educación" });
  await nav.getByRole("link", { name: "Asignaturas" }).click();
  await expect(page.getByText("Fundamentos de programación").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Generar tarjetas" }).first()).toBeVisible();
  await sinDesborde(page);
  await shot(page, "asignaturas", info);

  await nav.getByRole("link", { name: "Plan" }).click();
  await expect(page.getByRole("button", { name: /^semana$/i })).toBeVisible();
  await page.getByRole("button", { name: /^mes$/i }).click();
  await expect(page.getByRole("grid", { name: "Calendario del mes" })).toBeVisible();
  await sinDesborde(page);
  await shot(page, "plan-mes", info);

  await nav.getByRole("link", { name: "Repaso" }).click();
  await expect(page.getByText("Repaso espaciado")).toBeVisible();
  await sinDesborde(page);
  await shot(page, "repaso", info);

  await nav.getByRole("link", { name: "Cruces" }).click();
  await expect(page.getByText("Coste de la matrícula")).toBeVisible();
  await expect(page.getByText("Energía, sueño y entreno")).toBeVisible();
  await sinDesborde(page);
  await shot(page, "cruces", info);

  await page.getByRole("link", { name: "Ver archivos" }).click();
  await expect(page.getByText("Fundamentos de programación").first()).toBeVisible();
  await expect(page.getByText("Solo se puede ver, descargar y subir")).toBeVisible();
  await sinDesborde(page);
  await shot(page, "archivos", info);
  expect(errors).toEqual([]);
});

test("educación: repaso de una tarjeta y archivo del tutor", async ({ page }, info) => {
  test.skip(!MUTA || info.project.name !== "escritorio", "cambia datos: solo en el entorno de prueba");
  await login(page);
  await page.goto("/educacion/?tab=repaso");
  await page.getByRole("button", { name: /^Repasar/ }).click();
  await expect(page.getByText("1 de")).toBeVisible();
  await page.getByRole("button", { name: /Ver respuesta/ }).click();
  await shot(page, "repaso-respuesta", info);
  await page.getByRole("button", { name: /^Bien/ }).click();
  await page.goto("/educacion/?tab=archivos&ruta=SD");
  await page.locator('input[type="file"]').setInputFiles({ name: "borrador.md", mimeType: "text/markdown", buffer: Buffer.from("# Borrador PR1\n\nTexto de **prueba**.") });
  await expect(page.getByRole("button", { name: /borrador\.md/ })).toBeVisible();
  await page.getByRole("button", { name: /borrador\.md/ }).click();
  await expect(page.getByRole("heading", { name: "Borrador PR1" })).toBeVisible();
  await shot(page, "archivo-vista", info);
});
