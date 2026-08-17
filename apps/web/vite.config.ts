import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

// In dev, /api is proxied to the local backend so no CORS setup is needed.
// For any other deployment set VITE_API_BASE_URL (see .env.example) — the client
// then calls that origin directly and the proxy is unused.
export default defineConfig(({ mode }) => {
  // "." keeps this free of @types/node; Vite resolves envDir against the project
  // root, which is apps/web both locally and with Vercel's root directory set.
  const env = loadEnv(mode, ".", "VITE_");
  const base = (env.VITE_API_BASE_URL ?? "").trim();

  if (mode === "production" && base) {
    // A development origin baked into a deployed bundle is broken for every user
    // and cannot be fixed without a rebuild, so fail the build instead.
    if (/^https?:\/\/(localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])(:|\/|$)/i.test(base)) {
      throw new Error(
        `VITE_API_BASE_URL points at a local address (${base}). Set it to the deployed API origin.`,
      );
    }
    if (!/^https:\/\//i.test(base)) {
      throw new Error(
        `VITE_API_BASE_URL must be an https:// origin for a production build (got ${base}).`,
      );
    }
  }
  if (mode === "production" && !base) {
    // Not fatal: `npm run build` must keep working locally and in CI, where the
    // bundle is only being type- and size-checked. The app reports it at runtime.
    console.warn(
      "\n[build] VITE_API_BASE_URL is not set. This bundle has no API origin and " +
        "is only suitable for local verification, not for deployment.\n",
    );
  }

  return {
    plugins: [react(), tailwindcss()],
    server: {
      port: 5173,
      proxy: {
        "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
      },
    },
    build: { outDir: "dist", sourcemap: false },
  };
});
