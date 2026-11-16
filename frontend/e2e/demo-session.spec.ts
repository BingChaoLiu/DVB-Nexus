// Demo one-click full-chain E2E (SPEC-408 §4.3/§7.4/§8, ticket #99) against
// the REAL backend: entry buttons (home Monitor card + Monitor guide seat)
// drive the §7.4 phase machine (SC-01 → create → start → generate → inject
// → recover → diagnose → land), the landing carries the pre-anchored deep
// link (faulted_ts · PID 0 · packet 202) into the packet inspector, the
// header demo session bar carries its three elements, 「再跑一个 Run」 adds
// one more real run, 「结束演示并清理」 disposes the session and clears the
// local demo state — and the whole orchestration submits ZERO verify
// requests (§4.3: verify 判定故意不自动化, PASS is the user's own walk).
//
// Ticket-owned new file (additive; existing specs untouched except the two
// disabled→enabled assertion flips in shell.spec.ts / monitor-guidance.spec.ts).
// The full chain runs real backend runs (3 + 1 rerun), so per-test timeouts
// are raised well above the 60s default.
import { expect, test, type APIRequestContext } from "@playwright/test";

test.setTimeout(240_000);

/** GET /sessions/{id}/runs row count (real server facts for rerun counting). */
async function runCount(request: APIRequestContext, sessionId: string): Promise<number> {
  const response = await request.get(`/api/v1/sessions/${sessionId}/runs`);
  expect(response.status()).toBe(200);
  return ((await response.json()) as { run_id: string }[]).length;
}

test("home entry: full orchestration lands pre-anchored on Monitor, rerun adds a run, cleanup disposes (zero verify)", async ({ page, request }) => {
  // §4.3: the orchestration NEVER submits verify — watch every request.
  const verifyRequests: string[] = [];
  page.on("request", (req) => {
    if (req.url().includes("/verify")) verifyRequests.push(req.url());
  });

  await page.goto("/");
  // no demo period before the gate: no bar anywhere
  await expect(page.getByTestId("demo-session-bar")).toHaveCount(0);
  const entry = page.getByTestId("home-monitor-demo-start");
  await expect(entry).toBeEnabled();
  await entry.click();

  // The bar appears and walks the §7.4 phase machine to the landed face.
  const bar = page.getByTestId("demo-session-bar");
  await expect(bar).toBeVisible();
  await expect(bar).toHaveAttribute("data-demo-status", "landed", { timeout: 180_000 });

  // Frozen §4.3 declaration, verbatim.
  await expect(page.getByTestId("demo-declaration")).toHaveText("数据 = 沙盘真实生成；与真实会话唯一差别是入口");

  // Landing navigation = /monitor?session=<uuid> + the pre-anchored triple
  // resolved from SC-01's fault_plan (target 0x0000 → PID 0, packet 202).
  const url = new URL(page.url());
  expect(url.pathname).toBe("/monitor");
  const sessionId = url.searchParams.get("session");
  expect(sessionId).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/);
  // artifact ids are opaque uuid4 (ADR-0006 item 3) — shape, not value.
  expect(url.searchParams.get("inspect_artifact")).toMatch(
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/,
  );
  expect(url.searchParams.get("inspect_pid")).toBe("0");
  expect(url.searchParams.get("inspect_packet")).toBe("202");

  // The Monitor page tracks the demo session; the packet inspector is
  // pre-anchored on the REAL injected bytes (Range fetch of packet 202).
  await expect(page.getByText(`session: ${sessionId}`)).toBeVisible();
  const inspector = page.getByTestId("packet-inspector");
  await expect(inspector).toBeVisible();
  await expect(page.getByTestId("inspect-locator-pid")).toHaveText("pid 0");
  await expect(page.getByTestId("inspect-packet-index")).toHaveText("packet 202");
  await expect(page.getByTestId("inspect-content-range")).toContainText("206");

  // Bar slot contract: journey-bar → demo-session-bar → main (DOM order).
  const order = await page.evaluate(() => {
    const shell = document.querySelector(".dvb-shell");
    if (shell === null) return [];
    return Array.from(shell.children).map(
      (el) => `${el.tagName.toLowerCase()}:${el.getAttribute("data-testid") ?? el.className.split(" ")[0]}`,
    );
  });
  const journeyIndex = order.indexOf("div:journey-bar");
  const barIndex = order.indexOf("section:demo-session-bar");
  const mainIndex = order.indexOf("main");
  expect(journeyIndex).toBeGreaterThanOrEqual(0);
  expect(barIndex).toBeGreaterThan(journeyIndex);
  expect(mainIndex).toBeGreaterThan(barIndex);

  // 「再跑一个 Run」: one more real empty-plan run on the frozen geometry —
  // run count 3 → 4, and the button comes back enabled (poll finished).
  expect(await runCount(request, sessionId!)).toBe(3);
  const rerun = page.getByTestId("demo-rerun-run");
  await expect(rerun).toBeEnabled();
  await rerun.click();
  await expect.poll(() => runCount(request, sessionId!), { timeout: 60_000 }).toBe(4);
  await expect(rerun).toBeEnabled();

  // §4.3 discipline held across the whole period so far: zero verify.
  expect(verifyRequests).toEqual([]);

  // 「结束演示并清理」: stop (→stopped) + DELETE session (204) + local demo
  // state clear — the bar disappears, the page leaves the disposed session's
  // scope, and the server records lifecycle "disposed" (the runtime keeps
  // the session registered in the absorbing DISPOSED state — it does not 404).
  await page.getByTestId("demo-cleanup").click();
  await expect(page.getByTestId("demo-session-bar")).toHaveCount(0);
  await expect(page).not.toHaveURL(/session=/);
  const disposed = await request.get(`/api/v1/sessions/${sessionId}`);
  expect(disposed.status()).toBe(200);
  expect(((await disposed.json()) as { lifecycle: string }).lifecycle).toBe("disposed");
  expect(verifyRequests).toEqual([]);
});

test("monitor entry: the guide-seat button drives the same orchestration and lands", async ({ page }) => {
  await page.goto("/monitor");
  const entry = page.getByTestId("monitor-demo-start");
  await expect(entry).toBeEnabled();
  await entry.click();

  const bar = page.getByTestId("demo-session-bar");
  await expect(bar).toHaveAttribute("data-demo-status", "landed", { timeout: 180_000 });

  const url = new URL(page.url());
  expect(url.pathname).toBe("/monitor");
  const sessionId = url.searchParams.get("session");
  expect(sessionId).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/);
  // SC-01 pre-anchor triple present from this entry too.
  expect(url.searchParams.get("inspect_pid")).toBe("0");
  expect(url.searchParams.get("inspect_packet")).toBe("202");

  // cleanup: same semantics from this entry (bar gone, session disposed).
  await page.getByTestId("demo-cleanup").click();
  await expect(page.getByTestId("demo-session-bar")).toHaveCount(0);
  const disposed = await page.request.get(`/api/v1/sessions/${sessionId}`);
  expect(disposed.status()).toBe(200);
  expect(((await disposed.json()) as { lifecycle: string }).lifecycle).toBe("disposed");
});
