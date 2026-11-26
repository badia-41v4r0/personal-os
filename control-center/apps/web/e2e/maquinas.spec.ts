import { execSync } from "node:child_process";
import { expect, test, type Page } from "@playwright/test";

/**
 * Máquinas locales (Ajustes → Ordenadores). Sin variables, solo comprueba que la sección se ve (con o sin VirtualBox).
 * Recorrido completo del asistente contra una VM real (no usar con la instalación de verdad, sino con una de prueba):
 *   CC_E2E_VM="Nombre en VirtualBox" CC_E2E_VM_USER=usuario CC_E2E_VM_AUTORIZAR="comando que añade la clave (stdin)"
 * CC_E2E_VM_AUTORIZAR sustituye a pegar los comandos dentro de la VM: recibe la clave pública por la entrada estándar.
 * No pulsa «Dejar de usarla» (borraría la redirección de puerto, que puede compartir con otra instalación).
 */
const USER = process.env.CC_E2E_USER ?? "prueba";
const PASS = process.env.CC_E2E_PASS ?? "prueba-prueba-123";
const VM = process.env.CC_E2E_VM;
const VM_USER = process.env.CC_E2E_VM_USER ?? "";
const AUTORIZAR = process.env.CC_E2E_VM_AUTORIZAR;
const SHOTS = process.env.CC_E2E_SHOTS;

async function login(page: Page) {
  await page.goto("/login/");
  await page.getByLabel("Usuario").fill(USER);
  await page.getByLabel("Contraseña").fill(PASS);
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page.getByRole("heading", { name: /^Buen(os|as) (días|tardes|noches)/ })).toBeVisible();
}

test("la sección de máquinas locales se ve", async ({ page }) => {
  await login(page);
  await page.goto("/ajustes/ordenadores/");
  await expect(page.getByRole("heading", { name: "Máquinas locales" })).toBeVisible();
  await expect(page.getByText(/VirtualBox (no está instalado|\d)|Tienes \d+ máquina|VirtualBox no tiene ninguna|No se pudo consultar/).first()).toBeVisible();
});

test("asistente completo con una VM real", async ({ page }, info) => {
  test.skip(!VM || !AUTORIZAR || info.project.name !== "escritorio", "Solo con CC_E2E_VM y CC_E2E_VM_AUTORIZAR, en escritorio");
  test.setTimeout(240_000);
  await login(page);
  await page.goto("/ajustes/ordenadores/");
  await page.getByRole("button", { name: "Conectar una máquina" }).click();
  const dlg = page.getByRole("dialog");
  await dlg.getByLabel("Máquina de VirtualBox").selectOption(VM!);
  await dlg.getByLabel("Nombre para el panel (opcional)").fill("Máquina de prueba E2E");
  await dlg.getByRole("button", { name: "Preparar" }).click();
  // Paso 2: comandos con la clave pública de esta instalación
  const cmds = dlg.locator("pre").first();
  await expect(cmds).toContainText("ssh-ed25519", { timeout: 120_000 });
  await expect(cmds).toContainText("PasswordAuthentication no");
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/maquinas-paso2.png`, fullPage: true });
  const pub = (await cmds.innerText()).match(/ssh-ed25519 \S+ \S+/)![0];
  execSync(AUTORIZAR!, { input: pub + "\n", timeout: 30_000 });
  // Paso 3: probar
  await dlg.getByLabel("Tu usuario en la máquina").fill(VM_USER);
  await dlg.getByRole("button", { name: "Probar" }).click();
  await expect(dlg.getByText("Entrar por SSH")).toBeVisible({ timeout: 60_000 });
  await expect(dlg.getByText(/Pantalla \d+x\d+/)).toBeVisible();
  // Paso 4: agentes y notas
  await dlg.getByRole("checkbox").first().check();
  await dlg.getByLabel(/Notas para el agente/).fill("Prueba E2E");
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/maquinas-paso4.png`, fullPage: true });
  await dlg.getByRole("button", { name: "Guardar" }).click();
  await expect(dlg).toBeHidden();
  // Tarjeta: conectada, con su agente y su pantalla
  const tarjeta = page.locator("div.rounded-xl", { hasText: "Máquina de prueba E2E" });
  await expect(tarjeta.getByText(/^agente /)).toBeVisible();
  await expect(tarjeta.getByText(`internet · usuario ${VM_USER}`)).toBeVisible();
  await tarjeta.getByRole("button", { name: "Ver pantalla" }).click();
  await expect(tarjeta.getByRole("img", { name: "Pantalla de la máquina" })).toBeVisible();
  await expect.poll(() => tarjeta.getByRole("img", { name: "Pantalla de la máquina" }).evaluate((i: HTMLImageElement) => i.naturalWidth), { timeout: 30_000 }).toBeGreaterThan(100);
  // Editar
  await tarjeta.getByRole("button", { name: "Editar" }).click();
  await expect(page.getByRole("dialog").getByLabel("Notas para el agente")).toHaveValue("Prueba E2E");
  await page.getByRole("dialog").getByRole("button", { name: "Cancelar" }).click();
  // «Dejar de usarla»: solo se abre y se cancela
  await tarjeta.getByRole("button", { name: /Dejar de usar/ }).click();
  await expect(page.getByRole("dialog").getByText("La máquina, sus datos y su instantánea no se tocan.", { exact: false })).toBeVisible();
  await page.getByRole("dialog").getByRole("button", { name: "Cancelar" }).click();
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/maquinas-tarjeta.png`, fullPage: true });
});
