// Shell smoke (SPEC-400 §7.3 file 1) — REAL AND GREEN AT THIS TICKET: SPA
// loads, three route regions navigable, and a session WebSocket reaches its
// ready frame through the same-origin proxy. This one test proves the full
// transport chain (uvicorn asgi entry + pump + preview proxy + WS hub).
import { expect, test } from "@playwright/test";
import { createStartedSession, subscribeAndWaitReady } from "./helpers/backend";

test("three route regions are navigable (AC-400-01)", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("link", { name: "Topologies" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Monitor" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Lab" })).toBeVisible();

  await page.getByRole("link", { name: "Topologies" }).click();
  await expect(page.getByRole("heading", { name: "Topologies" })).toBeVisible();

  await page.getByRole("link", { name: "Monitor" }).click();
  await expect(page.getByRole("heading", { name: "Monitor" })).toBeVisible();

  await page.getByRole("link", { name: "Lab" }).click();
  await expect(page.getByRole("heading", { name: "Lab" })).toBeVisible();
});

test("session WS subscribe reaches the ready frame through the proxy (SPEC-501 §4)", async ({ page, request }) => {
  // Navigate first: the WS URL derives from the page's location (same-origin
  // posture) — on about:blank there is no host and the URL would be malformed.
  await page.goto("/");
  const sessionId = await createStartedSession(request);
  const frame = await subscribeAndWaitReady(page, sessionId);
  expect(frame.type).toBe("ready");
  expect(typeof frame.replayed_from).toBe("number");
});
