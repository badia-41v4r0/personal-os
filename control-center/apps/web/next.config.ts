import type { NextConfig } from "next";

// Producción: export estático (lo sirve el backend FastAPI, mismo origen para cookies y WebSocket).
// Desarrollo: `next dev` en 127.0.0.1:3770 con proxy de /api al backend (127.0.0.1:8770).
const isProd = process.env.NODE_ENV === "production";

const nextConfig: NextConfig = {
  // Tailwind v4 con Turbopack (lo genera create-next-app 16.4)
  turbopack: {
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
        async rewrites() {
          return [{ source: "/api/:path*", destination: "http://127.0.0.1:8770/api/:path*" }];
        },
      }),
};

export default nextConfig;
