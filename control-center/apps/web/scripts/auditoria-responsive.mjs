// Auditoría responsive del panel: todas las páginas en varios anchos.
// Detecta desbordamiento horizontal (y qué elemento lo causa), errores de JS y objetivos táctiles < 24 px.
// Uso: CC_E2E_URL=https://… CC_E2E_USER=… CC_E2E_PASS=… node scripts/auditoria-responsive.mjs
//      [W=390,768] [ONLY=/,/gym/] [SHOTS=1 → capturas en rwd-results/]
import { mkdirSync } from "node:fs";
import { chromium } from "@playwright/test";

const U = process.env.CC_E2E_URL ?? "http://127.0.0.1:8770";
const WIDTHS = process.env.W ? process.env.W.split(",").map(Number) : [360, 390, 768, 1024, 1280, 1920];
const OUT = "rwd-results";
if (process.env.SHOTS) mkdirSync(OUT, { recursive: true });

const b = await chromium.launch();
const ctx = await b.newContext();
const p0 = await ctx.newPage();
await p0.goto(U + "/login/");
await p0.getByLabel("Usuario").fill(process.env.CC_E2E_USER);
await p0.getByLabel("Contraseña").fill(process.env.CC_E2E_PASS);
await p0.getByRole("button", { name: "Entrar" }).click();
await p0.waitForURL(U + "/");
const api = async (path) => (await p0.request.get(U + "/api/v1" + path)).json();
const sess = (await api("/sessions")).find((s) => s.kind === "independent");
const ex = (await api("/gym/exercises"))[0];
const wo = (await api("/gym/workouts"))[0];
const PAGES = ["/login/", "/", "/conversaciones/", sess && `/conversaciones/?s=${sess.id}`, "/ajustes/agentes/", "/ajustes/agentes/?a=entrenador", "/ajustes/agentes/?new=1",
  "/ajustes/ordenadores/", "/ajustes/monitor/", "/conocimiento/", "/conocimiento/?p=Jarvis%2FTareas.md", "/bandeja/", "/ajustes/colas/",
  "/tareas/", "/ajustes/colas/", "/bandeja/?t=solicitudes", "/proyectos/", "/agenda/",
  "/bandeja/", "/ajustes/sistema/", "/salud/", "/finanzas/", "/carrera/", "/educacion/", "/objetivos/", "/estilo-de-vida/", "/ajustes/automatizaciones/", "/ajustes/conexiones/",
  "/entrenamiento/", ...["training", "progress", "recovery", "history", "routines", "coach"].map((t) => `/entrenamiento/?tab=${t}`),
  ex && `/entrenamiento/?e=${ex.id}`, wo && `/entrenamiento/?w=${wo.id}`, "/ajustes/"]
  .filter(Boolean).filter((p) => !process.env.ONLY || process.env.ONLY.split(",").includes(p));

const results = [];
for (const w of WIDTHS) {
  const page = await ctx.newPage();
  await page.setViewportSize({ width: w, height: w < 800 ? 844 : 900 });
  for (const path of PAGES) {
    const errs = [];
    page.removeAllListeners("pageerror");
    page.on("pageerror", (e) => errs.push(e.message));
    await page.goto(U + path, { waitUntil: "networkidle" }).catch(() => {});
    await page.waitForTimeout(1200);
    const r = await page.evaluate(() => {
      const vw = window.innerWidth;
      const over = [];
      for (const el of document.querySelectorAll("body *")) {
        const rc = el.getBoundingClientRect();
        if (!rc.width || !rc.height || (rc.right <= vw + 1 && rc.left >= -1)) continue;
        let a = el.parentElement, clipped = false;
        while (a && a !== document.body) {
          if (/(auto|scroll|hidden|clip)/.test(getComputedStyle(a).overflowX)) { clipped = true; break; }
          a = a.parentElement;
        }
        if (!clipped) over.push(`${el.tagName.toLowerCase()}.${String(el.className).split(" ").slice(0, 3).join(".")} [${Math.round(rc.left)}→${Math.round(rc.right)}] "${(el.textContent || "").trim().slice(0, 40)}"`);
      }
      const small = [];
      if (vw < 800) for (const el of document.querySelectorAll("button, a, [role=tab], select")) {
        const rc = el.getBoundingClientRect();
        // los enlaces dentro de un párrafo están exentos (WCAG 2.5.8)
        if (el.tagName === "A" && el.closest("p, .prose-cc")) continue;
        // área táctil ampliada con ::before (p. ej. las casillas de tareas)
        const before = getComputedStyle(el, "::before");
        if (before.content !== "none" && before.position === "absolute") continue;
        if (rc.width && rc.height && (rc.height < 24 || rc.width < 24))
          small.push(`${el.tagName.toLowerCase()} ${Math.round(rc.width)}x${Math.round(rc.height)} "${(el.textContent || el.getAttribute("aria-label") || "").trim().slice(0, 25)}"`);
      }
      return { scroll: document.documentElement.scrollWidth, vw, over: over.slice(0, 6), small: small.slice(0, 8) };
    });
    if (process.env.SHOTS) {
      const name = `${w}-${path.replace(/[^a-z0-9]+/gi, "_").replace(/^_|_$/g, "") || "dashboard"}`;
      await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true }).catch(() => {});
    }
    results.push({ w, path, overflow: r.scroll > r.vw + 1, scroll: r.scroll, over: r.over, small: r.small, errs });
  }
  await page.close();
}
await b.close();

let bad = 0;
for (const r of results) {
  if (r.overflow || r.over.length || r.errs.length) {
    bad++;
    console.log(`✘ ${r.w}px ${r.path} ancho=${r.scroll}${r.errs.length ? " ERROR " + r.errs[0] : ""}\n   ${r.over.join("\n   ")}`);
  }
}
const small = new Map();
for (const r of results.filter((x) => x.w < 800)) for (const s of r.small) small.set(s, r.path);
if (small.size) {
  console.log("\nObjetivos táctiles < 24 px (móvil):");
  for (const [s, p] of small) console.log("  ", p, s);
}
console.log(`\n${results.length} combinaciones revisadas, ${bad} con desbordamiento o errores, ${small.size} objetivos pequeños`);
process.exit(bad ? 1 : 0);
