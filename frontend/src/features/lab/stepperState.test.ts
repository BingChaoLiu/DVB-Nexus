// Eight-step stepper derivation — the §7.3 mapping-table exhaustive unit
// test (SPEC-406 REQ-UI-406-006 / AC-406-06). The seam is the pure function
// `deriveStepState`: every boolean MUST trace to an observable server fact
// (held SessionViewDTO / RunStatusDTO registry / fetched report / events
// answer / fetched verdict) — never to timers, button clicks, or local
// business inference. Analyze is the declared-gap step: it is ALWAYS false
// (in-process bridge, no HTTP face — M4 裁定 B), and the stepper renders it
// as "不可用", never as pending progress.
import { describe, expect, it } from "vitest";
import { deriveStepState, type LabFacts } from "./stepperState";

function run(
  runId: string,
  status: LabFacts["runs"][number]["status"],
  kinds: string[],
): LabFacts["runs"][number] {
  // Page-memory run: no §6.3 list fact — the artifact-kind path decides.
  return { runId, status, artifacts: kinds.map((kind) => ({ kind })), faultPlanPresent: null };
}

const DONE: LabFacts = {
  sessionLifecycle: "running",
  runs: [
    run("r-base", "completed", ["generated_ts", "log"]),
    run("r-inject", "completed", ["generated_ts", "faulted_ts", "log"]),
    run("r-recover", "completed", ["generated_ts", "log"]),
  ],
  reportFetched: true,
  eventsSeen: 5,
  verdictFetched: true,
};

describe("deriveStepState — the §7.3 mapping table", () => {
  it("every step is done when its server fact holds (Analyze never)", () => {
    expect(deriveStepState(DONE)).toEqual({
      create: true,
      generate: true,
      inject: true,
      analyze: false, // declared gap — never done, rendered 不可用
      diagnose: true,
      inspect: true,
      recover: true,
      verify: true,
    });
  });

  it("empty facts → all false (nothing inferred)", () => {
    const empty: LabFacts = {
      sessionLifecycle: null,
      runs: [],
      reportFetched: false,
      eventsSeen: 0,
      verdictFetched: false,
    };
    expect(deriveStepState(empty)).toEqual({
      create: false,
      generate: false,
      inject: false,
      analyze: false,
      diagnose: false,
      inspect: false,
      recover: false,
      verify: false,
    });
  });

  it("Create: only a RUNNING (or paused) session counts — ready/failed/unknown don't", () => {
    for (const lifecycle of ["running", "paused"]) {
      expect(deriveStepState({ ...DONE, sessionLifecycle: lifecycle }).create).toBe(true);
    }
    for (const lifecycle of ["ready", "created", "failed", "stopped", null]) {
      expect(deriveStepState({ ...DONE, sessionLifecycle: lifecycle }).create).toBe(false);
    }
  });

  it("Generate/Recover: completed generated_ts-only runs; a faulted run is NOT one", () => {
    const noGenerate: LabFacts = {
      ...DONE,
      runs: [run("r-inject", "completed", ["generated_ts", "faulted_ts", "log"])],
    };
    const state = deriveStepState(noGenerate);
    expect(state.generate).toBe(false);
    expect(state.recover).toBe(false);
    expect(state.inject).toBe(true);
  });

  it("running/failed/cancelled runs never advance Generate/Inject/Recover", () => {
    const pending: LabFacts = {
      ...DONE,
      runs: [
        run("r-1", "running", ["generated_ts", "log"]),
        run("r-2", "failed", ["generated_ts", "faulted_ts"]),
        run("r-3", "cancelled", ["faulted_ts"]),
      ],
    };
    const state = deriveStepState(pending);
    expect(state.generate).toBe(false);
    expect(state.inject).toBe(false);
    expect(state.recover).toBe(false);
  });

  it("Recover needs a SECOND distinct completed generated-only run", () => {
    const oneClean: LabFacts = { ...DONE, runs: [run("r-base", "completed", ["generated_ts"])] };
    const state = deriveStepState(oneClean);
    expect(state.generate).toBe(true);
    expect(state.recover).toBe(false);

    const twoClean: LabFacts = {
      ...DONE,
      runs: [run("r-base", "completed", ["generated_ts"]), run("r-rec", "completed", ["generated_ts"])],
    };
    expect(deriveStepState(twoClean).recover).toBe(true);
  });

  it("Diagnose/Inspect/Verify ride their fetched server answers only", () => {
    expect(deriveStepState({ ...DONE, reportFetched: false }).diagnose).toBe(false);
    expect(deriveStepState({ ...DONE, eventsSeen: 0 }).inspect).toBe(false);
    expect(deriveStepState({ ...DONE, verdictFetched: false }).verify).toBe(false);
  });
});

// §6.3 run-list reconstruction (SPEC-408 §7.5 同口径; review-fix F1): runs
// rebuilt from GET /sessions/{id}/rows carry NO artifact list (the list face
// answers fault_plan_present instead), so the clean/faulted facts ride the
// server's own boolean — never a fabricated artifact. faultPlanPresent=null
// keeps the page-memory artifact path byte-identical.
describe("deriveStepState — §6.3 list-reconstructed runs (fault_plan_present fact)", () => {
  const listRun = (
    runId: string,
    status: LabFacts["runs"][number]["status"],
    faultPlanPresent: boolean | null,
  ): LabFacts["runs"][number] => ({ runId, status, artifacts: [], faultPlanPresent });

  it("completed + fault_plan_present=true → the inject fact (no artifact needed, no clean count)", () => {
    const state = deriveStepState({
      ...DONE,
      runs: [listRun("r-inject", "completed", true)],
    });
    expect(state.inject).toBe(true);
    expect(state.generate).toBe(false);
    expect(state.recover).toBe(false);
  });

  it("completed + fault_plan_present=false → a clean run (Generate/Recover light from the list fact)", () => {
    const state = deriveStepState({
      ...DONE,
      runs: [listRun("r-base", "completed", false), listRun("r-rec", "completed", false)],
    });
    expect(state.generate).toBe(true);
    expect(state.recover).toBe(true);
    expect(state.inject).toBe(false);
  });

  it("one list-clean + one list-faulted → generate AND inject lit independently", () => {
    const state = deriveStepState({
      ...DONE,
      runs: [listRun("r-base", "completed", false), listRun("r-inject", "completed", true)],
    });
    expect(state.generate).toBe(true);
    expect(state.inject).toBe(true);
    expect(state.recover).toBe(false);
  });

  it("faultPlanPresent=null keeps the artifact-kind path (page-memory runs unchanged)", () => {
    expect(
      deriveStepState({ ...DONE, runs: [listRun("r-1", "completed", null)] }).generate,
    ).toBe(false);
    expect(
      deriveStepState({ ...DONE, runs: [{ runId: "r-2", status: "completed", artifacts: [{ kind: "generated_ts" }], faultPlanPresent: null }] })
        .generate,
    ).toBe(true);
  });

  it("running list rows advance nothing (same as page-memory running rows)", () => {
    const state = deriveStepState({
      ...DONE,
      runs: [listRun("r-1", "running", false), listRun("r-2", "running", true)],
    });
    expect(state.generate).toBe(false);
    expect(state.inject).toBe(false);
    expect(state.recover).toBe(false);
  });
});
