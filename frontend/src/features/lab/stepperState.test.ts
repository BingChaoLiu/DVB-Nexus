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
  return { runId, status, artifacts: kinds.map((kind) => ({ kind })) };
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
