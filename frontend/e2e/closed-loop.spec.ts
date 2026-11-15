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
  diagnoseRun,
  fetchPacket,
  queryEvents,
  submitAndAwaitRun,
  verifyRun,
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

  test("Generate — clean baseline run completes with artifacts (driver: rest, UI owner #64)", async ({ request }) => {
    test.info().annotations.push({ type: "driver", description: 'rest — flips to "ui" at #64' });
    const run = await submitAndAwaitRun(request, sessionId, []);
    baselineRunId = run.runId;
    expect(run.status).toBe("completed");
    const generated = run.artifacts.filter((a) => a.kind === "generated_ts");
    expect(generated.length).toBeGreaterThanOrEqual(1);
    generatedArtifactId = generated[0].artifact_id;
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

  test("Diagnose — idempotent evaluation answers a SPEC-306 report (driver: rest, UI owner #64)", async ({ request }) => {
    test.info().annotations.push({ type: "driver", description: 'rest — flips to "ui" at #64' });
    const { status, json } = await diagnoseRun(request, sessionId, injectedRunId);
    expect(status, `diagnose: ${status} ${JSON.stringify(json)}`).toBe(200);
    // Honest shape assertion: without the Analyze bridge the ruleset sees no
    // ts.* facts — the report may honestly carry zero candidates; the
    // REPORT SHAPE is what this step pins.
    expect(json.session_id).toBe(sessionId);
    expect(json.run_id).toBe(injectedRunId);
    expect(Array.isArray(json.candidates)).toBe(true);
    expect(Array.isArray(json.warnings)).toBe(true);
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

  test("Recover — a second clean run completes (driver: rest, UI owner #64/#67)", async ({ request }) => {
    test.info().annotations.push({ type: "driver", description: 'rest — flips to "ui" at #64/#67' });
    const run = await submitAndAwaitRun(request, sessionId, []);
    recoveryRunId = run.runId;
    expect(run.status).toBe("completed");
  });

  test("Verify — three-state verdict endpoint answers (driver: rest, UI owner #64/#67)", async ({ request }) => {
    test.info().annotations.push({ type: "driver", description: 'rest — flips to "ui" at #64/#67' });
    const { status, json } = await verifyRun(
      request,
      sessionId,
      recoveryRunId,
      baselineRunId,
      CC_DISCONTINUITY_FAULT_PLAN,
    );
    expect(status).toBe(200);
    // The verdict is the SERVER's SPEC-206 three-state answer — the UI never
    // derives one locally (CONTEXT.md 通关 ban; SPEC-400 §8). Any of the
    // three states is an honest answer for this chain shape.
    expect(["PASS", "FAIL", "INCONCLUSIVE"]).toContain(json.verdict);
    expect(json.session_id).toBe(sessionId);
    expect(json.recovery_run_id).toBe(recoveryRunId);
    expect(json.baseline_run_id).toBe(baselineRunId);
    expect(Array.isArray(json.criteria)).toBe(true);
  });
});
