import { expect, test } from "@playwright/test";

const USER = process.env.CC_E2E_USER ?? "prueba";
const PASS = process.env.CC_E2E_PASS ?? "prueba-prueba-123";

// Solo en el proyecto «movil» (iPhone 13): la barra inferior, la pantalla Más y las tarjetas plegables de Inicio.
test("móvil: barra inferior, Más y tarjetas plegables", async ({ page }, info) => {
  test.skip(info.project.name !== "movil", "solo móvil");
  await page.goto("/login/");
  await page.getByLabel("Usuario").fill(USER);
  await page.getByLabel("Contraseña").fill(PASS);
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page.getByRole("heading", { name: /^Buen(os|as) (días|tardes|noches)/ })).toBeVisible();

  const barra = page.getByRole("navigation", { name: "Accesos rápidos" });
  await expect(barra.getByRole("link", { name: "Más" })).toBeVisible();
  // Estado general empieza plegado y se abre con un toque
  const estado = page.getByRole("button", { name: /Estado general/ });
  await expect(estado).toHaveAttribute("aria-expanded", "false");
  await estado.click();
  await expect(estado).toHaveAttribute("aria-expanded", "true");

  await barra.getByRole("link", { name: "Más" }).click();
  await expect(page).toHaveURL(/\/mas\/$/);
  await expect(page.getByRole("heading", { name: "Ajustes" })).toBeVisible();
  await page.getByRole("link", { name: /Motor de IA/ }).click();
  await expect(page).toHaveURL(/\/ajustes\/motor\/$/);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);
});
