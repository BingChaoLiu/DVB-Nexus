// Stream Monitor page E2E (SPEC-403 §11): the SPEC-200 §5 table-driven
// control bar against the REAL lifecycle service — badge transitions and the
// disable matrix across a full validate→start→pause→resume→stop→dispose
// chain — plus the overview/alerts presentation and the WS stream badge.
// Data faces (metrics/diagnose/verify/closed-loop chain) live in
// closed-loop.spec.ts; this file pins the control-bar matrix end to end.
import { expect, test } from "@playwright/test";
import { createStartedSession } from "./helpers/backend";

// The SPEC-500 §4.2 create-session body (deterministic clock, topo-1) —
// inlined here so the shared helpers file stays untouched by this ticket.
const CREATE_BODY = {
  topology_id: "topo-1",
  topology_revision: 1,
  seed: 1234567,
  deterministic: true,
  clock_config: {
    mode: "deterministic",
    start_time_ns: 0,
    speed_num: 1,
    speed_den: 1,
    tick_quantum_ns: 1_000_000,
  },
};

async function createBareSession(request: import("@playwright/test").APIRequestContext): Promise<string> {
  const created = await request.post("/api/v1/sessions", { data: CREATE_BODY });
  expect(created.status()).toBe(201);
  const json = (await created.json()) as { session_id: string };
  return json.session_id;
}

const badge = (page: import("@playwright/test").Page) => page.getByTestId("lifecycle-badge");

test("control bar walks the full lifecycle chain with table-driven enablement", async ({ page, request }) => {
  const sessionId = await createBareSession(request);
  await page.goto(`/monitor?session=${sessionId}`);

  // created: only validate is enabled (SPEC-200 §5 row 1; no -> disposed edge)
  await expect(badge(page)).toHaveText("created");
  await expect(page.getByRole("button", { name: "validate" })).toBeEnabled();
  for (const action of ["start", "pause", "resume", "stop", "dispose"]) {
    await expect(page.getByRole("button", { name: action })).toBeDisabled();
  }

  await page.getByRole("button", { name: "validate" }).click();
  await expect(badge(page)).toHaveText("ready", { timeout: 10_000 });
  await expect(page.getByRole("button", { name: "start" })).toBeEnabled();
  await expect(page.getByRole("button", { name: "stop" })).toBeEnabled();
  await expect(page.getByRole("button", { name: "dispose" })).toBeDisabled(); // ready has no -> disposed edge

  await page.getByRole("button", { name: "start" }).click();
  await expect(badge(page)).toHaveText("running", { timeout: 10_000 });
  await expect(page.getByRole("button", { name: "pause" })).toBeEnabled();

  await page.getByRole("button", { name: "pause" }).click();
  await expect(badge(page)).toHaveText("paused", { timeout: 10_000 });
  await expect(page.getByRole("button", { name: "resume" })).toBeEnabled();
  await expect(page.getByRole("button", { name: "pause" })).toBeDisabled();

  await page.getByRole("button", { name: "resume" }).click();
  await expect(badge(page)).toHaveText("running", { timeout: 10_000 });

  await page.getByRole("button", { name: "stop" }).click();
  // STOPPING -> STOPPED lands asynchronously (task cleanup); the badge
  // follows the server truth via the snapshot re-pull.
  await expect(badge(page)).toHaveText("stopped", { timeout: 15_000 });
  await expect(page.getByRole("button", { name: "dispose" })).toBeEnabled();
  await expect(page.getByRole("button", { name: "start" })).toBeDisabled(); // final state: no restart

  await page.getByRole("button", { name: "dispose" }).click();
  // 204 recycles the session: the page returns to the guide scope.
  await expect(page.getByText(/输入 session id/)).toBeVisible({ timeout: 10_000 });
});

test("overview card, alerts merged-in presentation, and the WS stream badge", async ({ page, request }) => {
  const sessionId = await createStartedSession(request);
  await page.goto(`/monitor?session=${sessionId}`);

  // WS stream reaches ready through the same-origin proxy (SPEC-501 §4)
  await expect(page.getByText("ws: ready", { exact: false })).toBeVisible({ timeout: 15_000 });

  // overview: summary five fields + snapshot view field labels, wire names
  await expect(page.getByText(/journal_seq_watermark/)).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText(/virtual_time_ns/)).toBeVisible();
  await expect(page.getByText(/active_alert_count/)).toBeVisible();

  // alerts merged into the page (no standalone alert center): empty state is
  // explicit "no records", never "clean" (无告警 ≠ 干净)
  await expect(page.getByText(/无告警记录/)).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText(/≠ 干净/)).toBeVisible();
});
