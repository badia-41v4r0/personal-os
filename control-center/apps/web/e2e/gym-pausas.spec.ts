import { expect, test, type Page } from "@playwright/test";

// Periodos sin entrenar (Gym → Recovery). Cambia datos: solo con CC_E2E_GYM_MUTA=1 y contra un backend de PRUEBA.
// Corre en escritorio y en móvil (con --workers=1: comparten la base de prueba y las pausas no pueden solaparse).
const USER = process.env.CC_E2E_USER ?? "prueba";
const PASS = process.env.CC_E2E_PASS ?? "prueba-prueba-123";
const MUTA = process.env.CC_E2E_GYM_MUTA === "1";

const iso = (d: Date) => d.toLocaleDateString("sv-SE");
const add = (d: Date, n: number) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };
const lunes = (d: Date) => add(d, -((d.getDay() + 6) % 7));

async function login(page: Page) {
  await page.goto("/login/");
  await page.getByLabel("Usuario").fill(USER);
  await page.getByLabel("Contraseña").fill(PASS);
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page.getByRole("heading", { name: /^Buen(os|as) (días|tardes|noches)/ })).toBeVisible();
}

test("gym: pausa creada, visible en la lista y en el calendario, y borrada", async ({ page }) => {
  test.skip(!MUTA, "cambia datos: solo en el backend de prueba (CC_E2E_GYM_MUTA=1)");
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("response", (r) => { if (r.url().includes("/api/v1/gym") && r.status() >= 500) errors.push(`${r.status()} ${r.url()}`); });
  await login(page);

  // Lunes a miércoles de esta semana
  const ini = lunes(new Date());
  const desde = iso(ini), hasta = iso(add(ini, 2));
  await page.goto("/entrenamiento/?tab=recovery");
  await expect(page.getByText("Periodos sin entrenar", { exact: true })).toBeVisible();
  await expect(page.getByText("Sin pausas registradas.")).toBeVisible();

  await page.getByLabel("Desde").fill(desde);
  await page.getByLabel("Hasta (vacío = en curso)").fill(hasta);
  await page.getByLabel("Motivo").selectOption("enfermedad");
  await page.getByLabel("Nota", { exact: true }).fill("E2E: pausa de prueba");
  await page.getByRole("button", { name: "Añadir pausa" }).click();
  await expect(page.getByText("Pausa guardada.")).toBeVisible();
  await expect(page.getByText("E2E: pausa de prueba")).toBeVisible();
  await expect(page.getByText("Enfermedad").first()).toBeVisible();
  await expect(page.getByRole("button", { name: `Borrar la pausa del ${desde}` })).toBeVisible();

  // El calendario de Routines marca esos días como pausa (no «perdido»)
  await page.goto("/entrenamiento/?tab=routines");
  await expect(page.getByText("Calendario", { exact: true })).toBeVisible();
  const dias = await page.evaluate(async ([d, h]) => {
    const r = await fetch(`/api/v1/gym/calendar?desde=${d}&hasta=${h}`, { credentials: "same-origin" });
    return (await r.json()).dias as { fecha: string; estado: string; prevista: string | null }[];
  }, [desde, hasta]);
  const previstos = dias.filter((d) => d.prevista);
  expect(previstos.length).toBeGreaterThan(0);
  for (const d of previstos) expect(d.estado).toBe("pausa");
  // En pantalla (vista semana): al menos esos días llevan la etiqueta «pausa»
  await expect(page.getByText("pausa", { exact: true }).first()).toBeVisible();
  expect(await page.getByText("pausa", { exact: true }).count()).toBeGreaterThanOrEqual(previstos.length);

  // Terminar (si no tuviera fin) no aplica: tiene fin. Borrar
  await page.goto("/entrenamiento/?tab=recovery");
  await page.getByRole("button", { name: `Borrar la pausa del ${desde}` }).click();
  await expect(page.getByText("Pausa borrada.")).toBeVisible();
  await expect(page.getByText("Sin pausas registradas.")).toBeVisible();

  // Una pausa en curso se termina con «Terminar»
  await page.getByLabel("Desde").fill(desde);
  await page.getByLabel("Motivo").selectOption("vacaciones");
  await page.getByRole("button", { name: "Añadir pausa" }).click();
  await expect(page.locator("li").filter({ hasText: "en curso" })).toBeVisible();
  await page.getByRole("button", { name: "Terminar", exact: true }).click();
  await expect(page.getByText("Pausa terminada: hoy vuelves.")).toBeVisible();
  await expect(page.locator("li").filter({ hasText: "en curso" })).toHaveCount(0);
  await page.getByRole("button", { name: `Borrar la pausa del ${desde}` }).click();
  await expect(page.getByText("Sin pausas registradas.")).toBeVisible();

  const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(over).toBeLessThanOrEqual(1);
  expect(errors).toEqual([]);
});
