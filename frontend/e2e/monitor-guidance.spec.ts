// Monitor guidance layer E2E (SPEC-408 §4.3/§11.3, ticket #95) against the
// REAL backend: the session-list guide seat (row tracking → ?session=), the
// unknown-session explicit state (disposed/unknown id → the §4.6 row-0 face,
// never an error stack), the source-scenario link (zero state params), and
// the verify editable prefill with its no-auto-guess posture (zero verify
// requests until the user picks both runs). The demo button is asserted as
// a DISABLED placeholder only — its behavior is ticket #99's.
//
// Additive spec file: the existing monitor.spec.ts cases are untouched.
import { expect, test } from "@playwright/test";

// The SPEC-500 §4.2 create-session body (deterministic clock, topo-1) —
// inlined so the shared helpers file stays untouched by this ticket. The
// scenario-session creation passes scenario_id on the same shape (the
// loader branch document-governs; the plain fields are permissive-ignored).
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

const SC01 = {
  scenario_id: "5c010000-0000-4000-8000-000000000001",
  version: "1.0.0",
};

const GOLDEN_RUN_CONFIG = {
  schema_version: 1,
  profile: "analysis_only",
  deterministic: true,
  seed: 1234567,
  initial_media_clock_27mhz: 0,
  target_bitrate_bps: 3008000,
  output_packet_count: 600,
  program: {
    transport_stream_id: 1,
    program_number: 1,
    pmt_pid: 4096,
    pcr_pid: 256,
    version_number: 0,
    program_descriptors: "",
    streams: [
      { pid: 256, stream_type: 27, stream_id: 224, bitrate_bps: 120320, payload_profile: "synthetic_test_data", payload_seed_offset: 0 },
      { pid: 257, stream_type: 3, stream_id: 192, bitrate_bps: 60160, payload_profile: "synthetic_test_data", payload_seed_offset: 1 },
    ],
  },
  pat_period_ms: 101,
  pmt_period_ms: 103,
  pcr_interval_ms: 40,
  pcr_insertion_policy: "payload_packet_first",
};

async function createSession(request: import("@playwright/test").APIRequestContext, scenarioId?: string): Promise<string> {
  const body = scenarioId === undefined ? CREATE_BODY : { ...CREATE_BODY, scenario_id: scenarioId };
  const created = await request.post("/api/v1/sessions", { data: body });
  expect(created.status()).toBe(201);
  const json = (await created.json()) as { session_id: string };
  return json.session_id;
}

async function submitAndWaitRun(request: import("@playwright/test").APIRequestContext, sessionId: string): Promise<string> {
  const accepted = await request.post(`/api/v1/sessions/${sessionId}/runs`, {
    data: { config: GOLDEN_RUN_CONFIG, fault_plan: [] },
  });
  expect(accepted.status()).toBe(202);
  const { run_id: runId } = (await accepted.json()) as { run_id: string };
  const deadline = Date.now() + 30_000;
  for (;;) {
    const view = await request.get(`/api/v1/sessions/${sessionId}/runs/${runId}`);
    expect(view.status()).toBe(200);
    const json = (await view.json()) as { status: string };
    if (json.status !== "running") {
      expect(json.status).toBe("completed");
      return runId;
    }
    if (Date.now() >= deadline) throw new Error(`run ${runId} never completed within 30s`);
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
}

test("session-list guide seat: entry copy, demo placeholder, list rows, row tracking and the manual-UUID fallback", async ({ page, request }) => {
  const sessionA = await createSession(request);
  const sessionB = await createSession(request);

  await page.goto("/monitor");

  // §4.6 row 1 verbatim anchors (what / why / next)
  const guide = page.getByTestId("monitor-entry-guide");
  await expect(guide).toContainText("Monitor 是自由观测台");
  await expect(guide).toContainText("尚未选择任何 session");
  await expect(guide).toContainText("从 Lab 选场景开始实验后自动进入；或一键演示；或在最近列表选择；或手输 UUID");

  // the demo button holds the primary button position as a disabled
  // placeholder (behavior = ticket #99; no fake clickability)
  await expect(page.getByTestId("monitor-demo-start")).toBeDisabled();

  // the recent list renders both sessions (created_at DESC; lifecycle wire
  // badge verbatim; plain sessions carry the explicit 无场景 marker)
  const rowA = page.getByTestId(`monitor-session-row-${sessionA}`);
  await expect(rowA).toBeVisible();
  await expect(rowA).toContainText("无场景");
  await expect(page.getByTestId(`monitor-session-row-${sessionB}`)).toBeVisible();
  await expect(page.getByText(/创建时间/).first()).toBeVisible();
  // creation wall-clock, deterministic local-format shape
  expect(await rowA.textContent()).toMatch(/\d{4}-\d{2}-\d{2} \d{2}:\d{2}/);

  // row tracking → ?session=<id>
  await page.getByTestId(`monitor-track-${sessionA}`).click();
  await expect(page).toHaveURL(new RegExp(`\\?session=${sessionA}$`));
  await expect(page.getByText(`session: ${sessionA}`)).toBeVisible();

  // manual-UUID fallback: a complete pasted UUID tracks on input (输入即跟踪)
  await page.goto("/monitor");
  await page.getByLabel("session id").fill(sessionB);
  await expect(page.getByText(`session: ${sessionB}`)).toBeVisible();
});

test("unknown-session explicit state for a never-existing id (snapshot 404 route, row-0 copy verbatim)", async ({ page }) => {
  await page.goto("/monitor?session=11111111-2222-4333-8444-555555555555");

  const unknown = page.getByTestId("monitor-unknown-session");
  await expect(unknown).toBeVisible();
  await expect(unknown).toContainText("当前跟踪的 session 在服务端不存在");
  await expect(unknown).toContainText("可能已清理、已过期或 id 输入有误");
  await expect(unknown).toContainText("从下方最近列表重新选择；或回 Lab 开新实验");

  // actions: back to Lab; reselection from the recent list below
  await expect(page.getByRole("link", { name: "回 Lab 开新实验" })).toHaveAttribute("href", "/lab");
  await expect(page.getByTestId("monitor-entry-guide")).toBeVisible();

  // the panel stack is replaced by the explicit state — never an error stack
  await expect(page.getByRole("heading", { name: "运行控制" })).toHaveCount(0);
});

test("disposed session stays observable; the unknown state is reserved for truly absent ids", async ({ page, request }) => {
  const sessionId = await createSession(request);
  // SPEC-200 §5 exhaustive table: disposed is only reachable from stopped
  // (ready allows failed/running/stopping) — walk the real chain.
  expect((await request.post(`/api/v1/sessions/${sessionId}/validate`)).status()).toBe(200);
  expect((await request.post(`/api/v1/sessions/${sessionId}/start`)).status()).toBe(200);
  expect((await request.post(`/api/v1/sessions/${sessionId}/stop`)).status()).toBe(200);
  const deadline = Date.now() + 15_000;
  for (;;) {
    const snap = await request.get(`/api/v1/sessions/${sessionId}/snapshot`);
    const lifecycle = ((await snap.json()) as { lifecycle: string }).lifecycle;
    if (lifecycle === "stopped") break;
    if (Date.now() >= deadline) throw new Error(`never reached stopped (last: ${lifecycle})`);
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  const disposed = await request.delete(`/api/v1/sessions/${sessionId}`);
  if (disposed.status() !== 204) {
    throw new Error(`dispose failed: ${disposed.status()} ${await disposed.text()}`);
  }
  expect(disposed.status()).toBe(204);

  // The disposed RECORD persists server-side (SPEC-200 nine-state mirror):
  // the page keeps the honest observation face (lifecycle badge "disposed",
  // wire verbatim) — the explicit unknown-session state is reserved for ids
  // that truly do not exist (the previous test hits both of its signal
  // routes: snapshot 404 AND the WS 4404 permanent close on subscribe).
  await page.goto(`/monitor?session=${sessionId}`);
  await expect(page.getByTestId("monitor-unknown-session")).toHaveCount(0);
  await expect(page.getByText(`session: ${sessionId}`)).toBeVisible();
  await expect(page.getByTestId("lifecycle-badge")).toHaveText("disposed", { timeout: 15_000 });
  await expect(page.getByRole("heading", { name: "运行控制" })).toBeVisible();
  // and the recycled id no longer appears in the recent list (DELETE 后不出现)
  await expect(page.getByTestId(`monitor-session-row-${sessionId}`)).toHaveCount(0);
});

test("source-scenario link: 来源场景:<id> ↗ back to /lab?scenario=<id> with zero state params", async ({ page, request }) => {
  const sessionId = await createSession(request, SC01.scenario_id);
  await page.goto(`/monitor?session=${sessionId}`);

  const link = page.getByTestId("monitor-source-scenario");
  await expect(link).toBeVisible();
  await expect(link).toContainText(`来源场景:${SC01.scenario_id}`);
  const href = await link.getAttribute("href");
  expect(href).toBe(`/lab?scenario=${SC01.scenario_id}`);
  // 仅来源回跳:no cross-module state rides along (no inspect_* params)
  expect(href).not.toContain("inspect_");
});

test("verify editable prefill: three sources land, run datalist from the run list, and zero auto-guess (no verify request)", async ({ page, request }) => {
  const verifyRequests: string[] = [];
  page.on("request", (req) => {
    if (req.url().includes("/verify")) verifyRequests.push(req.url());
  });

  const sessionId = await createSession(request, SC01.scenario_id);
  // runs need a RUNNING session (SPEC-200 §5 gate) — scenario sessions come
  // out of the loader READY, so start once.
  const started = await request.post(`/api/v1/sessions/${sessionId}/start`);
  expect(started.status()).toBe(200);
  await page.goto(`/monitor?session=${sessionId}`);

  // identity triple prefill (scenario_id ← session detail; version /
  // content_hash ← scenario detail, the real pinned hash)
  const scenarioIdInput = page.getByLabel("scenario_id");
  await expect(scenarioIdInput).toHaveValue(SC01.scenario_id);
  await expect(page.getByLabel("version")).toHaveValue(SC01.version);
  await expect(page.getByLabel("content_hash")).toHaveValue(/^[0-9a-f]{64}$/);

  // run list datalist: submit two runs REST-side, then reload — the datalist
  // carries the server list (submitted_at ASC), inputs stay EMPTY.
  await submitAndWaitRun(request, sessionId);
  await submitAndWaitRun(request, sessionId);
  await page.reload();
  await expect(page.getByLabel("scenario_id")).toHaveValue(SC01.scenario_id);
  const datalist = page.locator("#verify-run-candidates option");
  await expect(datalist).toHaveCount(2);

  // runs are candidates only — the run inputs stay empty and verify stays
  // disabled (never auto-guess); clicking is impossible, so zero verify
  // requests go out even though every identity field is prefilled.
  await expect(page.getByLabel("recovery_run_id")).toHaveValue("");
  await expect(page.getByLabel("baseline_run_id")).toHaveValue("");
  await expect(page.getByRole("button", { name: "verify" })).toBeDisabled();

  // explicit user selection unlocks the submission face (still not pressed)
  await page.getByLabel("recovery_run_id").fill("chosen-recovery");
  await page.getByLabel("baseline_run_id").fill("chosen-baseline");
  await page.getByLabel("criterion_id").fill("fault-cleared");
  await page.getByLabel("kind").selectOption("fault_inactive");
  await page.getByLabel("fault_id").fill("fd000000-0000-4000-8000-00000000f1a1");
  await expect(page.getByRole("button", { name: "verify" })).toBeEnabled();
  expect(verifyRequests).toEqual([]);
});
