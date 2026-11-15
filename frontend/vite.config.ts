import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// The backend origin is the uvicorn process started by scripts/start-backend.mjs
// (Playwright webServer) or any dev-run backend; the proxy keeps the SPA
// same-origin so the api/ws clients need no CORS handling (SPEC-400 §4.1).
const backendTarget = process.env.DVBNEXUS_BACKEND_ORIGIN ?? "http://127.0.0.1:8765";

const proxy = {
  "/api": { target: backendTarget, changeOrigin: true },
  "/ws": { target: backendTarget, ws: true, changeOrigin: true },
} as const;

export default defineConfig({
  plugins: [react()],
  server: { proxy },
  preview: { port: 4173, strictPort: true, proxy },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
