// Demo one-click orchestration unit tests (SPEC-408 §7.4, ticket #99): the
// phase machine is the primary seam — mocked at the api barrel boundary, the
// tests walk the SPEC §7.4 phase order (scenario → create → start → generate
// → inject → recover → diagnose → land), the honest per-phase progress
// marking, the failure stops-in-place semantics, and the pre-anchoring
// locator resolution (SC-01 = faulted_ts · PID 0 · packet 202, honest null on
// parse failure). The verify face is deliberately absent: the zero-verify
// assertion pins the §4.3 "verify 判定故意不自动化" discipline.
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../api")>();
  return {
    ...actual,
    listScenarios: vi.fn(),
    getScenario: vi.fn(),
    createSession: vi.fn(),
    startSession: vi.fn(),
    submitRun: vi.fn(),
    getRun: vi.fn(),
    diagnoseRun: vi.fn(),
    verifyRun: vi.fn(),
  };
});

import type { DiagnosisReportDTO, RunStatusDTO, ScenarioDetailDTO, ScenarioSummaryDTO, SessionViewDTO } from "../../../api";
import { ApiError } from "../../../api/client";
import { LAB_RUN_CONFIG } from "../../lab/labGeometry";
import {
  buildDemoLandingPath,
  initialDemoPhases,
  markDemoPhase,
  orchestrateDemoSession,
  resolveInspectLocator,
  runAndWait,
  type DemoProgress,
} from "./demoOrchestrate";

import {
  createSession,
  diagnoseRun,
  getRun,
  getScenario,
  listScenarios,
  startSession,
  submitRun,
  verifyRun,
} from "../../../api";

const listScenariosMock = vi.mocked(listScenarios);
const getScenarioMock = vi.mocked(getScenario);
const createSessionMock = vi.mocked(createSession);
const startSessionMock = vi.mocked(startSession);
const submitRunMock = vi.mocked(submitRun);
const getRunMock = vi.mocked(getRun);
const diagnoseRunMock = vi.mocked(diagnoseRun);
const verifyRunMock = vi.mocked(verifyRun);

const SESSION = "aa990000-0000-4000-8000-000000009901";
const SCENARIO_ID = "5c010000-0000-4000-8000-000000000001";

const SC01_SUMMARY = {
  scenario_id: SCENARIO_ID,
  title: "认识闭环：PAT 缺失",
} as ScenarioSummaryDTO;

/** The SC-01 fault plan shape (scenarios/SC-01-pat-missing.json verbatim
 * fields that matter for pre-anchoring: target hex PID 0, packet slot 202). */
const SC01_FAULT_PLAN = [
  {
    fault_id: "fd000000-0000-4000-8000-00000000f1a1",
    fault_type: "PAT_MISSING",
    target_id: "mux-0:pid:0x0000",
    parameters: {},
    activation: { kind: "packet_index", packet_index: 202 },
    expected_observations: ["ts.psi_section_observed"],
  },
];

const SC01_DETAIL = {
  scenario_id: SCENARIO_ID,
  title: "认识闭环：PAT 缺失",
  version: "1.0.0",
  difficulty: "introductory",
  simulation_config: {
    seed: 1234567,
    mode: "deterministic",
    clock: { mode: "deterministic", start_time_ns: 0, speed_num: 1, speed_den: 1, tick_quantum_ns: 1_000_000 },
  },
  initial_topology: { topology_id: "topo-1", revision: 1 },
  fault_plan: SC01_FAULT_PLAN,
  objectives: [],
  hints: [],
  pass_criteria: [],
} as unknown as ScenarioDetailDTO;

function createdView(): SessionViewDTO {
  return { session_id: SESSION, revision: 1, lifecycle: "ready", virtual_time_ns: 0, topology_revision: 1 } as SessionViewDTO;
}

function completedRun(runId: string, artifacts: RunStatusDTO["artifacts"] = []): RunStatusDTO {
  return {
    run_id: runId,
    status: "completed",
    config_hash: "abc",
    generator_version: "v1",
    packet_count: 600,
    byte_count: 112_800,
    virtual_duration_ns: 1_000_000,
    artifacts: artifacts,
    warnings: [],
  };
}

const FAULTED_ARTIFACT = { artifact_id: "art-faulted-1", kind: "faulted_ts" as const, sha256: "f".repeat(64), byte_size: 112_800, partial: false };
const GENERATED_ARTIFACT = { artifact_id: "art-generated-1", kind: "generated_ts" as const, sha256: "a".repeat(64), byte_size: 112_800, partial: false };

function reportFor(runId: string): DiagnosisReportDTO {
  return { session_id: SESSION, run_id: runId, evaluated_at_utc_ms: 1, candidates: [], warnings: [] };
}

/** Wire the three-run chain: submit assigns ids in call order; every poll
 * answers completed immediately (no real polling wait in unit tests). */
function mockHappyRuns(): string[] {
  const ids = ["run-generate", "run-inject", "run-recover"];
  let call = 0;
  submitRunMock.mockImplementation(async () => {
    const runId = ids[call]!;
    call += 1;
    return { run_id: runId, status: "running", config_hash: "abc" };
  });
  getRunMock.mockImplementation(async (_sessionId, runId) => {
    if (runId === "run-inject") return completedRun(runId, [FAULTED_ARTIFACT]);
    return completedRun(runId, [GENERATED_ARTIFACT]);
  });
  return ids;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("orchestrateDemoSession — §7.4 happy path", () => {
  it("walks the full phase order with honest progress and returns the demo session + SC-01 locator", async () => {
    listScenariosMock.mockResolvedValue([SC01_SUMMARY]);
    getScenarioMock.mockResolvedValue(SC01_DETAIL);
    createSessionMock.mockResolvedValue(createdView());
    startSessionMock.mockResolvedValue({ ...createdView(), lifecycle: "running" });
    mockHappyRuns();
    diagnoseRunMock.mockResolvedValue(reportFor("run-inject"));

    const updates: DemoProgress[] = [];
    const result = await orchestrateDemoSession((progress) => updates.push(progress));

    // Endpoint call facts: scenario by filename-ASC first row, the two-hop
    // body straight from the document, start before any run.
    expect(listScenariosMock).toHaveBeenCalledTimes(1);
    expect(getScenarioMock).toHaveBeenCalledWith(SCENARIO_ID);
    expect(createSessionMock).toHaveBeenCalledTimes(1);
    expect(startSessionMock).toHaveBeenCalledWith(SESSION);

    // Three runs on the frozen golden geometry (imported, not re-copied):
    // generate/recover ride empty plans, inject rides the SC-01 fault plan.
    expect(submitRunMock).toHaveBeenCalledTimes(3);
    const plans = submitRunMock.mock.calls.map(([, body]) => body.fault_plan);
    expect(plans).toEqual([[], SC01_FAULT_PLAN, []]);
    for (const [, body] of submitRunMock.mock.calls) {
      expect(body.config).toEqual(LAB_RUN_CONFIG);
    }

    // Diagnose rides the injected run only.
    expect(diagnoseRunMock).toHaveBeenCalledTimes(1);
    expect(diagnoseRunMock).toHaveBeenCalledWith(SESSION, "run-inject");

    // Progress: every phase reaches done except land, which stays "active"
    // until the caller actually navigates (the honest hand-off).
    const final = updates[updates.length - 1]!;
    const states = Object.fromEntries(final.phases.map((p) => [p.key, p.state]));
    expect(Object.keys(states)).toEqual([
      "scenario", "create", "start", "generate", "inject", "recover", "diagnose", "land",
    ]);
    for (const key of ["scenario", "create", "start", "generate", "inject", "recover", "diagnose"]) {
      expect(states[key]).toBe("done");
    }
    expect(states["land"]).toBe("active");

    // The created session id is visible mid-flight (kept on failure for
    // manual cleanup) as soon as create answers.
    const afterCreate = updates.find((u) => u.phases.find((p) => p.key === "create")?.state === "done");
    expect(afterCreate?.sessionId).toBe(SESSION);

    // Result: real ids + the resolved SC-01 pre-anchor (PID 0 · packet 202).
    expect(result.sessionId).toBe(SESSION);
    expect(result.scenarioTitle).toBe("认识闭环：PAT 缺失");
    expect(result.inspectLocator).toEqual({ artifact_id: "art-faulted-1", pid: 0, packet_index: 202 });

    // §4.3: verify 判定故意不自动化 — the orchestration NEVER touches verify.
    expect(verifyRunMock).not.toHaveBeenCalled();
  });
});

describe("orchestrateDemoSession — failure stops in place (§8 row 1)", () => {
  // AC-408-09: the stale「需 Lab Pack 落位」sentence is RETIRED — the honest
  // face speaks the §4.6 library-empty semantics (registry empty + start.cmd
  // guidance), review-fix F3.
  it("empty scenario registry: scenario phase fails with the honest §4.6-aligned reason, nothing else runs", async () => {
    listScenariosMock.mockResolvedValue([]);
    const updates: DemoProgress[] = [];
    await expect(orchestrateDemoSession((p) => updates.push(p))).rejects.toThrow(/场景注册表为空/);

    const final = updates[updates.length - 1]!;
    const scenario = final.phases.find((p) => p.key === "scenario")!;
    expect(scenario.state).toBe("failed");
    expect(scenario.detail).toContain("场景注册表为空");
    // The stale sentence is gone; the §4.6 start.cmd guidance style is in.
    expect(scenario.detail).not.toContain("Lab Pack");
    expect(scenario.detail).toContain("start.cmd");
    expect(createSessionMock).not.toHaveBeenCalled();
    expect(submitRunMock).not.toHaveBeenCalled();
  });

  it("backend unreachable (create rejects): the failed phase carries the envelope reason", async () => {
    listScenariosMock.mockResolvedValue([SC01_SUMMARY]);
    getScenarioMock.mockResolvedValue(SC01_DETAIL);
    createSessionMock.mockRejectedValue(new ApiError({ status: 503, errorCode: "SIM_BACKEND_UNAVAILABLE", message: "backend down" }));

    const updates: DemoProgress[] = [];
    await expect(orchestrateDemoSession((p) => updates.push(p))).rejects.toThrow(/backend down/);

    const create = updates[updates.length - 1]!.phases.find((p) => p.key === "create")!;
    expect(create.state).toBe("failed");
    // the display row carries the full envelope reason (errorCode: message)
    expect(create.detail).toContain("SIM_BACKEND_UNAVAILABLE: backend down");
    expect(startSessionMock).not.toHaveBeenCalled();
  });

  it("create lifecycle not ready: explicit assertion failure, no start", async () => {
    listScenariosMock.mockResolvedValue([SC01_SUMMARY]);
    getScenarioMock.mockResolvedValue(SC01_DETAIL);
    createSessionMock.mockResolvedValue({ ...createdView(), lifecycle: "created" } as SessionViewDTO);

    const updates: DemoProgress[] = [];
    await expect(orchestrateDemoSession((p) => updates.push(p))).rejects.toThrow(/期望 ready/);
    expect(startSessionMock).not.toHaveBeenCalled();
  });

  it("start lifecycle not running: explicit assertion failure", async () => {
    listScenariosMock.mockResolvedValue([SC01_SUMMARY]);
    getScenarioMock.mockResolvedValue(SC01_DETAIL);
    createSessionMock.mockResolvedValue(createdView());
    startSessionMock.mockResolvedValue({ ...createdView(), lifecycle: "paused" } as SessionViewDTO);

    const updates: DemoProgress[] = [];
    await expect(orchestrateDemoSession((p) => updates.push(p))).rejects.toThrow(/期望 running/);
    expect(submitRunMock).not.toHaveBeenCalled();
  });

  it("a run reaching a non-completed terminal: that phase fails, later phases never run", async () => {
    listScenariosMock.mockResolvedValue([SC01_SUMMARY]);
    getScenarioMock.mockResolvedValue(SC01_DETAIL);
    createSessionMock.mockResolvedValue(createdView());
    startSessionMock.mockResolvedValue({ ...createdView(), lifecycle: "running" });
    submitRunMock.mockResolvedValue({ run_id: "run-x", status: "running", config_hash: "abc" });
    getRunMock.mockResolvedValue(completedRun("run-x", []));
    getRunMock.mockResolvedValue({ ...completedRun("run-x"), status: "failed" });

    const updates: DemoProgress[] = [];
    await expect(orchestrateDemoSession((p) => updates.push(p))).rejects.toThrow(/终态 failed/);

    const final = updates[updates.length - 1]!;
    const generate = final.phases.find((p) => p.key === "generate")!;
    expect(generate.state).toBe("failed");
    expect(generate.detail).toContain("failed");
    const inject = final.phases.find((p) => p.key === "inject")!;
    expect(inject.state).toBe("pending");
    expect(diagnoseRunMock).not.toHaveBeenCalled();
  });

  it("diagnose 404-until-drained: retries inside the window and lands done", async () => {
    listScenariosMock.mockResolvedValue([SC01_SUMMARY]);
    getScenarioMock.mockResolvedValue(SC01_DETAIL);
    createSessionMock.mockResolvedValue(createdView());
    startSessionMock.mockResolvedValue({ ...createdView(), lifecycle: "running" });
    mockHappyRuns();
    diagnoseRunMock
      .mockRejectedValueOnce(new ApiError({ status: 404, errorCode: "SIM_NO_DIAGNOSIS", message: "not drained yet" }))
      .mockResolvedValue(reportFor("run-inject"));

    const updates: DemoProgress[] = [];
    const result = await orchestrateDemoSession((p) => updates.push(p));
    const diagnose = updates[updates.length - 1]!.phases.find((p) => p.key === "diagnose")!;
    expect(diagnose.state).toBe("done");
    expect(result.inspectLocator).toEqual({ artifact_id: "art-faulted-1", pid: 0, packet_index: 202 });
  });
});

describe("resolveInspectLocator — pre-anchor resolution (positive + honest negatives)", () => {
  const faultedRun = completedRun("run-inject", [FAULTED_ARTIFACT]);

  it("resolves the SC-01 triple: faulted_ts artifact + target hex PID + activation packet", () => {
    expect(resolveInspectLocator(SC01_DETAIL, faultedRun)).toEqual({
      artifact_id: "art-faulted-1",
      pid: 0,
      packet_index: 202,
    });
  });

  it("no faulted_ts artifact (plain completed run): null — no fabricated locator", () => {
    const plain = completedRun("run-inject", [GENERATED_ARTIFACT]);
    expect(resolveInspectLocator(SC01_DETAIL, plain)).toBeNull();
  });

  it("empty fault_plan: null", () => {
    const empty = { ...SC01_DETAIL, fault_plan: [] } as ScenarioDetailDTO;
    expect(resolveInspectLocator(empty, faultedRun)).toBeNull();
  });

  it("missing fault_plan: null", () => {
    const missing = { ...SC01_DETAIL, fault_plan: undefined } as unknown as ScenarioDetailDTO;
    expect(resolveInspectLocator(missing, faultedRun)).toBeNull();
  });

  it("target_id without a 0x hex pid: null", () => {
    const odd = {
      ...SC01_DETAIL,
      fault_plan: [{ ...SC01_FAULT_PLAN[0]!, target_id: "mux-0:pid:plain" }],
    } as unknown as ScenarioDetailDTO;
    expect(resolveInspectLocator(odd, faultedRun)).toBeNull();
  });

  it("activation without a numeric packet_index (session_start kind): null", () => {
    const odd = {
      ...SC01_DETAIL,
      fault_plan: [{ ...SC01_FAULT_PLAN[0]!, activation: { kind: "session_start", packet_index: null } }],
    } as unknown as ScenarioDetailDTO;
    expect(resolveInspectLocator(odd, faultedRun)).toBeNull();
  });
});

describe("buildDemoLandingPath — deep link carries the triple only when resolved", () => {
  it("with a locator: /monitor?session=… + inspect_artifact/inspect_pid/inspect_packet", () => {
    expect(buildDemoLandingPath(SESSION, { artifact_id: "art-faulted-1", pid: 0, packet_index: 202 })).toBe(
      `/monitor?session=${SESSION}&inspect_artifact=art-faulted-1&inspect_pid=0&inspect_packet=202`,
    );
  });

  it("parse failure (null locator): session param only — honest absence, no fabricated params", () => {
    expect(buildDemoLandingPath(SESSION, null)).toBe(`/monitor?session=${SESSION}`);
  });
});

describe("runAndWait — the rerun-button building block", () => {
  it("polls to completed and returns the status view (empty plan, golden geometry)", async () => {
    submitRunMock.mockResolvedValue({ run_id: "run-r", status: "running", config_hash: "abc" });
    getRunMock.mockResolvedValue(completedRun("run-r", []));

    const status = await runAndWait(SESSION, []);
    expect(status.run_id).toBe("run-r");
    expect(submitRunMock).toHaveBeenCalledWith(SESSION, { config: expect.objectContaining({ seed: 1234567 }), fault_plan: [] });
    expect(getRunMock).toHaveBeenCalledWith(SESSION, "run-r");
  });

  it("non-completed terminal rejects with the explicit reason", async () => {
    submitRunMock.mockResolvedValue({ run_id: "run-c", status: "running", config_hash: "abc" });
    getRunMock.mockResolvedValue({ ...completedRun("run-c"), status: "cancelled" });
    await expect(runAndWait(SESSION, [])).rejects.toThrow(/cancelled/);
  });
});

describe("phase table helpers", () => {
  it("initialDemoPhases lists the §7.4 order all pending", () => {
    expect(initialDemoPhases().map((p) => p.key)).toEqual([
      "scenario", "create", "start", "generate", "inject", "recover", "diagnose", "land",
    ]);
    expect(initialDemoPhases().every((p) => p.state === "pending")).toBe(true);
  });

  it("markDemoPhase replaces one row immutably", () => {
    const phases = markDemoPhase(initialDemoPhases(), "create", "done", SESSION);
    expect(phases.find((p) => p.key === "create")).toMatchObject({ state: "done", detail: SESSION });
    expect(phases.find((p) => p.key === "start")?.state).toBe("pending");
  });
});
