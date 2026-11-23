import { expect, test, type Page } from "@playwright/test";

// Ocio → Pelis y series. La prueba con TMDB simula la API en el navegador (no sale a internet ni cambia datos);
// la de alta a mano cambia datos: solo con CC_E2E_OCIO_MUTA=1 y contra un backend de PRUEBA (sin token de TMDB).
const USER = process.env.CC_E2E_USER ?? "prueba";
const PASS = process.env.CC_E2E_PASS ?? "prueba-prueba-123";
const MUTA = process.env.CC_E2E_OCIO_MUTA === "1";
// PNG de 2×3 px
const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAIAAAADCAYAAAC56t6BAAAAEklEQVR4nGNgYGD4z8DAwMAAAAQAAWb5Q2sAAAAASUVORK5CYII=", "base64");

async function login(page: Page) {
  await page.goto("/login/");
  await page.getByLabel("Usuario").fill(USER);
  await page.getByLabel("Contraseña").fill(PASS);
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page.getByRole("heading", { name: /^Buen(os|as) (días|tardes|noches)/ })).toBeVisible();
}

const ITEM = {
  id: 7, tipo: "serie", tmdb_id: 1396, titulo: "Breaking Bad", titulo_original: "Breaking Bad", anio: 2008, sinopsis: "Un profesor de química.",
  generos: ["Drama", "Crimen"], duracion: 47, temporadas: 5, capitulos: 62, capitulos_por_temporada: [7, 13, 13, 13, 16], emision: "Finalizada",
  poster: "ggFHVNu6YYI5L9pCfOacjizRGt.jpg", nota_tmdb: 8.9, plataformas: ["Netflix"], estado: "viendo", valoracion: null,
  temporada: 1, capitulo: 7, empezada: "2026-11-16", terminada: null, nota: "", actualizado: null,
};

test("ocio: buscar en TMDB, añadir con carátula y pasar de temporada", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  let items: typeof ITEM[] = [];
  let patch: unknown = null;
  await page.route("**/api/v1/me/ocio/imagen/**", (r) => r.fulfill({ contentType: "image/png", body: PNG }));
  await page.route("**/api/v1/me/ocio/buscar?**", (r) => r.fulfill({ json: [
    { tmdb_id: 1396, tipo: "serie", titulo: "Breaking Bad", titulo_original: "Breaking Bad", anio: 2008, poster: ITEM.poster, sinopsis: "Un profesor…" },
  ] }));
  await page.route(/\/api\/v1\/me\/ocio(\/7)?$/, async (r) => {
    const m = r.request().method();
    if (m === "POST") { items = [ITEM]; return r.fulfill({ json: ITEM }); }
    if (m === "PATCH") { patch = r.request().postDataJSON(); items = [{ ...ITEM, ...(patch as object) }]; return r.fulfill({ json: items[0] }); }
    return r.fulfill({ json: { tmdb: true, items } });
  });
  await login(page);
  await page.goto("/ocio/");
  await expect(page.getByRole("heading", { name: "Ocio" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "Pelis y series" })).toBeVisible();
  await expect(page.getByText("Aún no has añadido nada.")).toBeVisible();

  await page.getByLabel("Buscar peli o serie").fill("breaking");
  const hit = page.getByRole("list", { name: "Resultados" }).getByRole("button", { name: /Breaking Bad/ });
  await expect(hit).toBeVisible();
  await page.getByLabel("Añadir como").selectOption("viendo");
  await hit.click();

  const portada = page.getByRole("img", { name: "Carátula de Breaking Bad" });
  await expect(portada).toBeVisible();
  expect(await portada.evaluate((i: HTMLImageElement) => i.naturalWidth)).toBeGreaterThan(0);
  await expect(page.getByText("2008 · Serie · T1 · E7")).toBeVisible();
  // La temporada 1 tiene 7 capítulos: el siguiente es el 2×1
  await page.getByRole("button", { name: "Siguiente capítulo de Breaking Bad" }).click();
  await expect(page.getByText("2008 · Serie · T2 · E1")).toBeVisible();
  expect(patch).toEqual({ temporada: 2, capitulo: 1 });

  await page.getByRole("button", { name: "Abrir Breaking Bad" }).click();
  const ficha = page.getByRole("dialog");
  await expect(ficha.getByText("Dónde verla:")).toBeVisible();
  await expect(ficha.getByText("Netflix")).toBeVisible();
  await expect(ficha.getByText("8.9 TMDB")).toBeVisible();
  expect(errors).toEqual([]);
});

test("ocio: sin TMDB se añade a mano, se valora y se quita", async ({ page }) => {
  test.skip(!MUTA, "cambia datos: solo en el backend de prueba (CC_E2E_OCIO_MUTA=1)");
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("response", (r) => { if (r.url().includes("/api/v1/me/ocio") && r.status() >= 500) errors.push(`${r.status()} ${r.url()}`); });
  await login(page);
  await page.goto("/ocio/");
  await expect(page.getByText(/Falta la clave de TMDB/)).toBeVisible();
  const titulo = `E2E ${test.info().project.name}`;
  await page.getByLabel("Título", { exact: true }).fill(titulo);
  await page.getByLabel("Tipo", { exact: true }).first().selectOption("pelicula");
  await page.getByRole("button", { name: "Añadir" }).click();
  await expect(page.getByRole("button", { name: `Abrir ${titulo}` })).toBeVisible();

  await page.getByRole("button", { name: `Abrir ${titulo}` }).click();
  const ficha = page.getByRole("dialog");
  await expect(ficha.getByText("Añadida a mano, sin información de TMDB.")).toBeVisible();
  await ficha.getByLabel("Estado").selectOption("vista");
  await ficha.getByLabel("Tu nota").selectOption("8");
  await ficha.getByRole("button", { name: "Guardar" }).click();
  await expect(ficha).toBeHidden();
  await page.getByRole("button", { name: "Vista" }).first().click();
  await expect(page.getByRole("button", { name: `Abrir ${titulo}` })).toContainText("8");

  await page.getByRole("button", { name: `Abrir ${titulo}` }).click();
  await ficha.getByRole("button", { name: "Quitar" }).click();
  await ficha.getByRole("button", { name: "Sí, quitar" }).click();
  await expect(page.getByRole("button", { name: `Abrir ${titulo}` })).toBeHidden();
  expect(errors).toEqual([]);
});
