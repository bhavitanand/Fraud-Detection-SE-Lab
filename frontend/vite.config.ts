/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

// Dev: the Vite server proxies /api to FastAPI so the browser sees one origin (no CORS needed).
// Override the target with VITE_PROXY_TARGET in frontend/.env.local if the API is not on 127.0.0.1:8000.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "");
  return {
    plugins: [react()],
    server: { port: 5173, proxy: { "/api": env.VITE_PROXY_TARGET || "http://127.0.0.1:8000" } },
    build: { outDir: "dist", sourcemap: false },
    test: { environment: "jsdom", globals: true, setupFiles: ["./src/test-setup.ts"], css: false },
  };
});
