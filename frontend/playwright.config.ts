// E2E smoke config (SPEC-400 §7.3): dual webServer — the backend (uvicorn on
// the tree's bootstrap.asgi entry, started via scripts/start-backend.mjs) and
// the production-built SPA (vite preview with /api + /ws proxying to the
// backend). Tests reach the backend through the SAME-ORIGIN proxy so the
// proxy chain is itself under test.
import { defineConfig } from "@playwright/test";

const backendPort = process.env.DVBNEXUS_PORT ?? "8765";
const backendURL = `http://127.0.0.1:${backendPort}/api/v1/version`;
const frontendURL = "http://localhost:4173";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: frontendURL,
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: "npm run serve:backend",
      url: backendURL,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      command: "npm run preview",
      url: frontendURL,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
  ],
});
