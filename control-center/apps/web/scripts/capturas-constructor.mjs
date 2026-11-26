// Capturas de la interfaz del Constructor contra una instancia de prueba (no forma parte de la web).
// Uso: CC_URL=http://127.0.0.1:8791 CC_USER=admin CC_PW=... SALIDA=/carpeta node scripts/capturas-constructor.mjs
import { chromium } from "@playwright/test";

const URL = process.env.CC_URL ?? "http://127.0.0.1:8791";
const SALIDA = process.env.SALIDA ?? ".";
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1360, height: 860 } });
p.on("dialog", (d) => d.accept());
await p.goto(`${URL}/login/`);
await p.getByLabel(/usuario/i).fill(process.env.CC_USER ?? "admin");
await p.getByLabel(/contraseña/i).fill(process.env.CC_PW ?? "");
await p.getByRole("button", { name: /entrar/i }).click();
await p.waitForURL((u) => !u.pathname.startsWith("/login"));
await p.goto(`${URL}/ajustes/versiones/`);
await p.getByText("Tus personalizaciones", { exact: true }).waitFor();
await p.screenshot({ path: `${SALIDA}/1-versiones.png`, fullPage: true });
const cerrar = p.getByRole("dialog").getByRole("button", { name: "Cerrar" });
if (await cerrar.count()) await cerrar.click();
// Chat con el Constructor
await p.keyboard.press("Control+j");
await p.locator("[aria-haspopup=listbox]").first().click();
const opcion = p.getByRole("option", { name: /Constructor/ });
if (await opcion.count()) await opcion.click();
await p.waitForTimeout(1500);
await p.screenshot({ path: `${SALIDA}/2-chat-constructor.png` });
// Vista previa
await p.goto(`${URL}/vista-previa/`);
await p.waitForTimeout(2500);
await p.screenshot({ path: `${SALIDA}/3-vista-previa.png` });
await b.close();
