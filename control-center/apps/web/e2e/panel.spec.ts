import { expect, test, type Page } from "@playwright/test";

const USER = process.env.CC_E2E_USER ?? "prueba";
const PASS = process.env.CC_E2E_PASS ?? "prueba-prueba-123";
const SHOTS = process.env.CC_E2E_SHOTS;

async function shot(page: Page, name: string, project: string) {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${project}-${name}.png`, fullPage: true });
}

async function login(page: Page) {
  await page.goto("/login/");
  await page.getByLabel("Usuario").fill(USER);
  await page.getByLabel("Contraseña").fill(PASS);
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page.getByRole("heading", { name: /^Buen(os|as) (días|tardes|noches)/ })).toBeVisible();
}

test("sin sesión redirige al login", async ({ page }) => {
  await page.goto("/monitor/");
  await expect(page).toHaveURL(/\/login\/$/);
});

test("contraseña incorrecta", async ({ page }) => {
  await page.goto("/login/");
  await page.getByLabel("Usuario").fill(USER);
  await page.getByLabel("Contraseña").fill("mala-mala-mala");
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page.getByText("Usuario o contraseña incorrectos")).toBeVisible();
});

test("recorrido del panel con datos reales", async ({ page }, info) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await login(page);
  await expect(page.getByText("Host Agent")).toBeVisible();
  await page.waitForTimeout(2500);
  await shot(page, "dashboard", info.project.name);

  await page.goto("/monitor/");
  await expect(page.getByText("Servicios y timers de Jarvis")).toBeVisible();
  await expect(page.getByText("jarvis-collect.timer")).toBeVisible();
  await page.waitForTimeout(6000);
  await shot(page, "monitor", info.project.name);

  await page.goto("/chat/");
  await expect(page.getByLabel("Mensaje para Jarvis")).toBeVisible();
  await page.waitForTimeout(1500);
  await shot(page, "chat", info.project.name);

  await page.goto("/gym/");
  await expect(page.getByText("Series por músculo (7 días)")).toBeVisible();
  await shot(page, "gym", info.project.name);
  await page.goto("/gym/?e=press-de-banca-inclinado-mancuerna");
  await expect(page.getByText("Carga por sesión (kg)")).toBeVisible();
  await shot(page, "gym-ejercicio", info.project.name);

  await page.goto("/memory/?p=Jarvis%2FTareas.md");
  await expect(page.getByRole("button", { name: "Editar" })).toBeVisible();
  await shot(page, "memory", info.project.name);
  await page.goto("/memory/?p=Jarvis%2FPanel.md");
  await expect(page.getByText("Solo lectura")).toBeVisible();

  await page.goto("/agenda/");
  await expect(page.getByText("Próximos 7 días")).toBeVisible({ timeout: 20_000 });
  await shot(page, "agenda", info.project.name);

  await page.goto("/tasks/?t=tasks");
  await expect(page.getByText(/Pendientes \(\d+\)/)).toBeVisible();
  for (const [tab, text] of [["Aprobaciones", "Historial"], ["Colas", "Programador (código en las repos)"], ["Programadas", "Temporizadores"], ["Solicitudes", "Resueltas"]]) {
    await page.getByRole("tab", { name: tab }).click();
    await expect(page.getByText(text).first()).toBeVisible({ timeout: 20_000 });
  }
  await shot(page, "tasks", info.project.name);
  await page.goto("/projects/");
  await expect(page.getByText("MiRepo")).toBeVisible({ timeout: 30_000 });
  await page.getByText("MiRepo").click();
  await expect(page.getByText("Encargos del programador")).toBeVisible();
  await shot(page, "proyecto", info.project.name);

  await page.goto("/settings/");
  await expect(page.getByText("auth.login").first()).toBeVisible();
  await shot(page, "settings", info.project.name);
  expect(errors).toEqual([]);
});

test("conversación independiente: crear y ver historial", async ({ page }, info) => {
  await login(page);
  await page.goto("/chat/");
  await page.getByRole("button", { name: "Nueva conversación" }).filter({ visible: true }).first().click();
  await page.getByLabel("Nombre").fill(`E2E ${info.project.name}`);
  await page.getByRole("button", { name: "Crear" }).click();
  await expect(page.getByText("Escribe el primer mensaje")).toBeVisible();
  await expect(page.getByText("Conversación independiente").first()).toBeVisible();
  if (info.project.name === "escritorio") await page.getByRole("button", { name: "Archivar" }).click(); // la columna derecha solo se ve en escritorio
  if (info.project.name === "movil") await page.getByLabel("Conversación", { exact: true }).selectOption({ label: "Prueba técnica" });
  else await page.getByRole("button", { name: /Prueba técnica/ }).click();
  await expect(page.getByText("prueba ok").or(page.getByText("hecho")).first()).toBeVisible();
  await shot(page, "sesion-independiente", info.project.name);
});

test("agentes: importados del repo y crear un borrador con vista previa", async ({ page }, info) => {
  test.skip(info.project.name !== "escritorio", "solo en escritorio");
  await login(page);
  await page.goto("/agents/");
  await expect(page.getByText("entrenador", { exact: true })).toBeVisible();
  await expect(page.getByText("tutor", { exact: true })).toBeVisible();
  await shot(page, "agentes", info.project.name);
  await page.getByRole("button", { name: "Nuevo agente" }).click();
  await page.getByLabel("Nombre").fill("e2e-borrador");
  await page.getByLabel(/Descripción/).fill("Agente de prueba creado por los tests E2E del panel");
  await page.getByLabel("Instrucciones principales").fill("Resume lo que te pasen en tres puntos.");
  await expect(page.getByText("name: e2e-borrador")).toBeVisible();
  await shot(page, "agente-nuevo", info.project.name);
  await page.getByRole("button", { name: "Guardar borrador" }).click();
  await expect(page.getByText("Borrador").first()).toBeVisible();
  await page.goto("/agents/?a=entrenador");
  await page.getByRole("tab", { name: "Versiones" }).click();
  await expect(page.getByText("Importado de agent/.claude/agents")).toBeVisible();
});

test("ordenador virtual: crear, terminal, escritorio y eliminar", async ({ page }, info) => {
  test.skip(info.project.name !== "escritorio", "solo en escritorio");
  test.setTimeout(120_000);
  await login(page);
  await page.goto("/virtual-computers/");
  await page.getByRole("button", { name: "Nuevo ordenador" }).click();
  await page.getByLabel("Nombre").fill("E2E escritorio");
  await page.getByLabel("Perfil").selectOption("desktop");
  await page.getByRole("button", { name: "Crear" }).click();
  await expect(page.getByText("Desktop · Efímero · sin internet")).toBeVisible({ timeout: 60_000 });
  // Escritorio (noVNC dibuja en un canvas)
  await expect(page.getByLabel("Escritorio remoto").locator("canvas")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("Conectando con el escritorio…")).toBeHidden({ timeout: 20_000 });
  await page.waitForTimeout(2000);
  await shot(page, "vc-escritorio", info.project.name);
  // Terminal
  await page.getByRole("tab", { name: "Terminal" }).click();
  await page.getByLabel("Terminal", { exact: true }).click();
  await page.keyboard.type("echo E2E-$(whoami)-$((6*7))\n");
  await expect(page.getByLabel("Terminal", { exact: true })).toContainText("E2E-vc-42", { timeout: 15_000 });
  await shot(page, "vc-terminal", info.project.name);
  // Eliminar (confirma el diálogo del navegador)
  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "Eliminar" }).click();
  await expect(page.getByRole("heading", { name: "Virtual Computers" })).toBeVisible({ timeout: 30_000 });
});
