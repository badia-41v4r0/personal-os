import { existsSync } from "node:fs";
import type { NextConfig } from "next";
import { PREFIJOS } from "./src/lib/rutas";

// Producción: export estático (lo sirve el backend FastAPI, mismo origen para cookies y WebSocket).
// Desarrollo: `next dev` en 127.0.0.1:3770 con proxy de /api al backend (127.0.0.1:8770).
const isProd = process.env.NODE_ENV === "production";
// Extensiones locales: src/privado/index.tsx si existe (no se publica); si no, la versión vacía del proyecto público
const EXTENSIONES = existsSync("./src/privado/index.tsx") ? "./src/privado/index.tsx" : "./src/extensiones/vacias.tsx";  // relativo a apps/web

const nextConfig: NextConfig = {
  // Tailwind v4 con Turbopack (lo genera create-next-app 16.4)
  turbopack: {
    resolveAlias: { "@extensiones": EXTENSIONES },
    rules: {
      "*.css": { loaders: ["@tailwindcss/turbopack"], as: "*.css" },
    },
  },
  ...(isProd
    ? {
        output: "export", trailingSlash: true, images: { unoptimized: true },
        // Solo para compilar un entorno de prueba sin tocar el `out` que sirve el panel en marcha
        ...(process.env.CC_WEB_OUT ? { distDir: process.env.CC_WEB_OUT } : {}),
      }
    : {
        // Direcciones antiguas (en producción las redirige el backend: app/rutas_viejas.py)
        async redirects() {
          return PREFIJOS.map(([viejo, nuevo]) => ({ source: `${viejo}:path*`, destination: `${nuevo}:path*`, permanent: false }));
        },
        async rewrites() {
          return [{ source: "/api/:path*", destination: "http://127.0.0.1:8770/api/:path*" }];
        },
      }),
};

export default nextConfig;
