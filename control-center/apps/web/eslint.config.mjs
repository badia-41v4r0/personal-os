import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    // SPA exportada en estático: cargar datos al montar o al cambiar de nota (fetch → setState en un efecto)
    // es intencionado. Se deja como aviso en lugar de error.
    rules: { "react-hooks/set-state-in-effect": "warn" },
  },
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "out-*/**", // compilaciones aparte: la del supervisor de cambios y la de la vista previa del Constructor
    "build/**",
    "next-env.d.ts",
  ]),
]);

export default eslintConfig;
