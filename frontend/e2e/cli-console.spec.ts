// CLI console E2E (SPEC-405 §10, AC-405-01..04).
//
// Test A (real backend): the honest empty state — MVP production makes no
// real TSDuck calls, so a real session answers 200 + [] and the page must
// say so WITHOUT implying "clean".
//
// Test B (MOCK STATE, explicitly labeled): page.route intercepts the §4.8
// route with a nine-field fixture (GBK stderr with CJK + U+FFFD, exit 0) —
// the mock layer exists ONLY because the MVP production stack never calls
// TSDuck; the contract anchor stays in the component tests. Mocked
// interactions pin the wiring end to end: columns, detail gate annotation,
// four-value filter behavior.
import { expect, test, type Page } from "@playwright/test";

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

async function openCliTab(page: Page, sessionId: string): Promise<void> {
  await page.goto(`/monitor?session=${sessionId}`);
  await expect(page.getByRole("tab", { name: "CLI 对照" })).toBeVisible();
  await page.getByRole("tab", { name: "CLI 对照" }).click();
}

const GBK_STDERR = "错误: 未能打开输入文件 'sample.ts'（\uFFFD\uFFFD 无效参数）";

// Nine-field wire fixture (SPEC-308 §7 + run_id), snake_case verbatim.
const MOCK_CALLS = [
  {
    version: "3.40",
    executable_path: "C:\\Program Files\\TSDuck\\bin\\tsduck.exe",
    argv: ["tsduck.exe", "analyze", "--preserve-package-names", "input.ts"],
    started_at_utc_ms: 1_000,
    finished_at_utc_ms: 2_500,
    exit_code: 0,
    stdout_text: "analysis report lines...",
    stderr_text: GBK_STDERR,
    input_artifact_sha256: "a3f1...deadbeef",
    run_id: "run-1",
  },
];

test("honest empty state on a real session (MVP produces no TSDuck calls)", async ({ page, request }) => {
  const sessionId = await createBareSession(request);
  await page.goto(`/monitor?session=${sessionId}`);

  // R1 mount: stream tab is the default — SPEC-403 panels render first.
  await expect(page.getByRole("heading", { name: "运行控制" })).toBeVisible();

  await openCliTab(page, sessionId);
  // §4.6 Monitor 组行 10 逐字文案(SPEC-408 落笔权威表替换后)
  await expect(page.getByText(/TSDuck 调用记录与来源区分（来源标识 ≠ 双解析器 diff）/)).toBeVisible();
  // Clean-refusal sentence is part of the copy contract (CONTEXT.md ban).
  await expect(page.getByText(/不是[「"]?无问题[」"]?信号/)).toBeVisible();
  // The four-value filter vocabulary is fully present even in the empty view.
  for (const value of ["generator", "internal_parser", "tsduck", "hardware"]) {
    await expect(page.getByRole("button", { name: value })).toBeVisible();
  }
  // Stream tab restores the SPEC-403 stack.
  await page.getByRole("tab", { name: "Stream Monitor" }).click();
  await expect(page.getByRole("heading", { name: "运行控制" })).toBeVisible();
});

test("MOCK STATE — nine-field list, gate annotation, and filter behavior over a route-mocked §4.8 face", async ({ page, request }) => {
  const sessionId = await createBareSession(request);

  await page.route(`**/api/v1/sessions/*/tsduck/calls*`, async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(MOCK_CALLS) });
  });

  await openCliTab(page, sessionId);

  // Nine-field wire columns, snake_case verbatim (AC-405-01).
  for (const field of [
    "version",
    "executable_path",
    "argv",
    "started_at_utc_ms",
    "finished_at_utc_ms",
    "exit_code",
    "stdout_text",
    "stderr_text",
    "input_artifact_sha256",
    "run_id",
  ]) {
    await expect(page.getByRole("columnheader", { name: field, exact: true })).toBeVisible();
  }

  // GBK stderr detail: verbatim text with CJK and U+FFFD survives (AC-405-02).
  await page.getByRole("button", { name: /1970-01-01T00:00:01\.000Z/ }).click();
  await expect(page.getByText(GBK_STDERR)).toBeVisible();

  // exit 0 beside the standing gate annotation; no success/failure label (AC-405-03).
  await expect(page.getByText(/退出码 0 不代表报告有效/)).toBeVisible();
  await expect(page.getByText(/ts\.bytes > 0 && ts\.services\.total >= 1/)).toBeVisible();
  await expect(page.getByText(/本页不作有效性判定/)).toBeVisible();

  // Filter behavior: hardware selects the honest empty with the MVP note (AC-405-04).
  await page.getByRole("button", { name: "hardware" }).click();
  await expect(page.getByText(/MVP 阶段 hardware 来源不产生记录/)).toBeVisible();
  await expect(page.getByText(/无记录 ≠ 干净/)).toBeVisible();
  // Back to 全部: the record returns (cell-scoped — the detail stays open).
  await page.getByRole("button", { name: "全部" }).click();
  await expect(page.getByRole("cell", { name: "3.40" })).toBeVisible();
});
