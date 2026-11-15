import { defineConfig, devices } from "@playwright/test";

// E2E contra un backend ya en marcha que sirve el export (127.0.0.1:8770) con un usuario de prueba.
// Variables: CC_E2E_URL, CC_E2E_USER, CC_E2E_PASS, CC_E2E_SHOTS (carpeta para capturas, opcional).
export default defineConfig({
  testDir: "e2e",
  timeout: 30_000,
  use: { baseURL: process.env.CC_E2E_URL ?? "http://127.0.0.1:8770", browserName: "chromium" },
  projects: [
    { name: "escritorio", use: { viewport: { width: 1440, height: 900 } } },
    { name: "movil", use: { ...devices["iPhone 13"], browserName: "chromium" } },
  ],
});
