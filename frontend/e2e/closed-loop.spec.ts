// Eight-step closed-loop E2E skeleton (SPEC-400 §7.3 file 2; REQ-UI-400-004).
//
// 混合驱动收敛制 (approved ruling, #15 批准记录): every step is annotated
// with `driver` ("rest" = driven via in-test REST until the owning ticket's
// UI lands; "ui" = browser-driven) and its OWNING TICKET. Owning tickets
// flip their steps additively as their surfaces land. This file is a SHARED
// face from this merge onward — additive edits only.
//
// Step map mirrors the #58 API harness (tests/e2e/_fault_lab.py):
//   Create   = POST /sessions                    (rest now; UI: #67 Lab 开局)
//   Generate = POST runs with an EMPTY plan      (rest now; UI: #64 Monitor)
//   Inject   = POST runs with the fault plan     (rest now; UI: #67 Lab)
//   Analyze  = in-process bridge                 (SKIPPED — M4 裁定 B: the
//              REST analyze route stays frozen 501; no HTTP face exists)
//   Diagnose = POST diagnose (idempotent)        (rest now; UI: #64)
//   Inspect  = GET events + artifact Range       (rest now; UI: #65 hex view)
//   Recover  = POST runs, empty plan again       (rest now; UI: #64/#67)
//   Verify   = POST verify (three-state verdict) (rest now; UI: #64/#67)
//
// The full chain passing through UI surfaces is an ACCEPTANCE-TIME property
// (ticket #61 acceptance text): backend full-chain availability is the
// precondition, not a launch blocker for this ticket.
import { expect, test } from "@playwright/test";
import {
  CC_DISCONTINUITY_FAULT_PLAN,
  createStartedSession,
  fetchPacket,
  queryEvents,
  submitAndAwaitRun,
} from "./helpers/backend";

test.describe.serial("eight-step closed loop (SPEC-400 §7.3 skeleton)", () => {
  let sessionId = "";
  let baselineRunId = "";
  let injectedRunId = "";
  let recoveryRunId = "";
  let generatedArtifactId = "";

  test("Create — session over topo-1 validates and starts (driver: rest, UI owner #67)", async ({ request }) => {
    test.info().annotations.push({ type: "driver", description: 'rest — flips to "ui" at #67' });
    sessionId = await createStartedSession(request);
    expect(sessionId).toBeTruthy();
  });

  test("Generate — clean baseline run completes with artifacts (driver: ui, #64 Monitor)", async ({ page }) => {
    test.info().annotations.push({ type: "driver", description: 'ui — #64 Monitor run trigger (flipped)' });
    await page.goto(`/monitor?session=${sessionId}`);
    await page.getByRole("button", { name: /提交 Run/ }).click();
    // the page polls getRun and renders the status row when terminal
    const row = page.getByTestId(/^run-row-/).first();
    await expect(row).toHaveText(/completed/, { timeout: 30_000 });
    baselineRunId = (await row.getAttribute("data-testid"))!.replace("run-row-", "");
    expect(baselineRunId).toBeTruthy();
    // artifact refs render with per-artifact test ids — no DOM text parsing
    const artifact = page.getByTestId(/^run-artifact-/).first();
    await expect(artifact).toContainText("generated_ts", { timeout: 10_000 });
    generatedArtifactId = (await artifact.getAttribute("data-testid"))!.replace("run-artifact-", "");
    expect(generatedArtifactId).toBeTruthy();
  });

  test("Inject — fault-plan run completes (driver: rest, UI owner #67)", async ({ request }) => {
    test.info().annotations.push({ type: "driver", description: 'rest — flips to "ui" at #67' });
    const run = await submitAndAwaitRun(request, sessionId, CC_DISCONTINUITY_FAULT_PLAN);
    injectedRunId = run.runId;
    expect(run.status).toBe("completed");
    const faulted = run.artifacts.filter((a) => a.kind === "faulted_ts");
    expect(faulted.length).toBeGreaterThanOrEqual(1);
  });

  test("Analyze — SKIPPED: in-process bridge only (M4 裁定 B, no HTTP face)", async () => {
    // M4 裁定 B keeps the REST analyze route frozen at 501; the analysis
    // bridge is in-process (stack.analysis_service) with no HTTP surface.
    // This step flips only when a backend decision adds an HTTP face —
    // recorded here as an explicit, annotated gap (never a silent pass).
    test.info().annotations.push({
      type: "skipped-step",
      description:
        "Analyze: REST analyze frozen 501 (M4 裁定 B); in-process bridge has no HTTP face. " +
        "Completes when the backend surface decision lands or the acceptance口径 changes.",
    });
  });

  test("Diagnose — idempotent evaluation answers a SPEC-306 report (driver: ui, #64 Monitor)", async ({ page }) => {
    test.info().annotations.push({ type: "driver", description: 'ui — #64 Monitor diagnose trigger (flipped)' });
    await page.goto(`/monitor?session=${sessionId}`);
    // 404-until-drained tolerance rides the page's bounded retry; the assert
    // polls past it. Report SHAPE remains the pinned object — without the
    // Analyze bridge zero candidates is an honest answer.
    await page.getByLabel("diagnose run id").fill(injectedRunId);
    await page.getByRole("button", { name: "diagnose" }).click();
    // the report line pins the REPORT SHAPE (run id + candidates/warnings
    // counts); zero candidates stays an honest answer (no Analyze bridge).
    await expect(
      page.getByText(new RegExp(`report: run ${injectedRunId} · \\d+ candidates · \\d+ warnings`)),
    ).toBeVisible({ timeout: 15_000 });
  });

  test("Inspect — events queryable + single packet via 188-byte Range (driver: rest, UI owner #65)", async ({ request }) => {
    test.info().annotations.push({ type: "driver", description: 'rest — flips to "ui" at #65' });
    const events = await queryEvents(request, sessionId, { limit: 50 });
    expect(events.status).toBe(200);
    expect(events.json.data.items.length).toBeGreaterThanOrEqual(1);

    const packet = await fetchPacket(request, generatedArtifactId, 0);
    expect(packet.status()).toBe(206); // single-range hit
    const contentRange = packet.headers()["content-range"];
    expect(contentRange).toContain("bytes 0-187/");
    const body = await packet.body();
    expect(body.length).toBe(188);
  });

  test("Recover — a second clean run completes (driver: ui, #64 Monitor / #67 scenario context)", async ({ page }) => {
    test.info().annotations.push({ type: "driver", description: 'ui — #64 Monitor run trigger (flipped; #67 layers scenario)' });
    await page.goto(`/monitor?session=${sessionId}`);
    await page.getByRole("button", { name: /提交 Run/ }).click();
    // the run registry is per-mount (in-memory page state) — after this fresh
    // navigation there is exactly one row, and it must not be the baseline run
    const row = page.getByTestId(/^run-row-/).first();
    await expect(row).toHaveText(/completed/, { timeout: 30_000 });
    recoveryRunId = (await row.getAttribute("data-testid"))!.replace("run-row-", "");
    expect(recoveryRunId).not.toBe(baselineRunId);
  });

  test("Verify — three-state verdict rendered from the server answer (driver: ui, #64 Monitor / #67)", async ({ page }) => {
    test.info().annotations.push({ type: "driver", description: 'ui — #64 Monitor verify form + result card (flipped; #67 layers scenario)' });
    await page.goto(`/monitor?session=${sessionId}`);
    const faultId = (CC_DISCONTINUITY_FAULT_PLAN[0] as { fault_id: string }).fault_id;
    await page.getByLabel("recovery_run_id").fill(recoveryRunId);
    await page.getByLabel("baseline_run_id").fill(baselineRunId);
    await page.getByLabel("scenario_id").fill("cc-discontinuity-lab");
    await page.getByLabel("version").fill("1.0.0");
    await page.getByLabel("content_hash").fill("e2e-smoke");
    await page.getByLabel("criterion_id").fill("cc-ok");
    await page.getByLabel("kind").selectOption("cc_continuous");
    await page.getByLabel("fault_id").fill(faultId);
    await page.getByRole("button", { name: "verify" }).click();
    // The verdict is the SERVER's SPEC-206 three-state answer rendered
    // verbatim — the UI never derives one locally (CONTEXT.md 通关 ban).
    const verdict = page.getByTestId("verify-verdict");
    await expect(verdict).toBeVisible({ timeout: 15_000 });
    const verdictText = await verdict.textContent();
    expect(["PASS", "FAIL", "INCONCLUSIVE"].some((v) => verdictText?.includes(v))).toBe(true);
    const card = page.locator(".dvb-mon-verify-card");
    await expect(card).toContainText(recoveryRunId);
    await expect(card).toContainText(baselineRunId);
    await expect(card).toContainText("cc_continuous");
  });
});
