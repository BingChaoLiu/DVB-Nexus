// Request-body builders (SPEC-406 §7.1; verify §7.5 per SPEC-408 §4.3/§6.4):
// the pure seams for the two Lab-shaped request bodies. The §11 test vectors
// pin:
// - the create body carries scenario_id (the document value) + the document
//   projection fields (permissive-ignored server-side — self-documenting,
//   never a second governance source);
// - the verify body carries the detail's pass_criteria VERBATIM (no UI
//   rewrite of the pass/fail contract), the scenario identity FROM THE FORM
//   (real pinned content_hash — SPEC-406 §7.4 的 lab-ui-unpinned 声明串口径
//   停用, SPEC-408 §6.4 增量③), and NEVER a ui_state key.
import { describe, expect, it } from "vitest";
import { buildCreateSessionBody, buildVerifyBody } from "./labBodies";
import type { ScenarioDetailDTO } from "../../api";

const detail = {
  schema_version: "1",
  scenario_id: "5c010000-0000-4000-8000-000000000001",
  version: "1.0.0",
  title: "认识闭环：PAT 缺失",
  difficulty: "introductory",
  required_engine_versions: {},
  initial_topology: {
    topology_id: "topo-sc-01",
    revision: 1,
    nodes: [],
    connections: [],
  },
  simulation_config: {
    seed: 1234567,
    mode: "deterministic",
    clock: { mode: "deterministic", start_time_ns: 0, speed_num: 1, speed_den: 1, tick_quantum_ns: 1000000 },
  },
  fault_plan: [{ fault_id: "fd-1", fault_type: "PAT_MISSING" }],
  objectives: ["a", "b"],
  hints: [],
  pass_criteria: [
    { criterion_id: "fault-cleared", kind: "fault_inactive", mandatory: true, fault_id: "fd-1" },
    { criterion_id: "pat-valid", kind: "psi_pat_valid", mandatory: true },
  ],
} as unknown as ScenarioDetailDTO;

describe("buildCreateSessionBody — the scenario_id carrier", () => {
  it("carries scenario_id + the document's own topology/seed/clock projection", () => {
    const body = buildCreateSessionBody(detail);
    expect(body).toEqual({
      scenario_id: "5c010000-0000-4000-8000-000000000001",
      topology_id: "topo-sc-01",
      topology_revision: 1,
      seed: 1234567,
      deterministic: true,
      clock_config: { mode: "deterministic", start_time_ns: 0, speed_num: 1, speed_den: 1, tick_quantum_ns: 1000000 },
    });
  });
});

describe("buildVerifyBody — criteria passthrough + real pinned identity", () => {
  it("passes pass_criteria through verbatim and carries the FORM's identity (real pinned hash, not a declared marker)", () => {
    // recovery_run_id rides the endpoint PATH (verifyRun(sessionId, runId, body));
    // the body carries baseline + scenario identity + criteria only.
    const body = buildVerifyBody(
      {
        baselineRunId: "r-inj",
        scenarioId: "5c010000-0000-4000-8000-000000000001",
        version: "1.0.0",
        contentHash: "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
      },
      detail,
    );
    expect(body.baseline_run_id).toBe("r-inj");
    expect(body.scenario).toEqual({
      scenario_id: "5c010000-0000-4000-8000-000000000001",
      version: "1.0.0",
      content_hash: "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    });
    expect(body.pass_criteria).toBe(detail.pass_criteria);
    expect(Object.keys(body)).not.toContain("ui_state");
  });

  it("the declared marker lab-ui-unpinned is RETIRED: no code path emits it (SPEC-406 §7.4 停用注记)", () => {
    const body = buildVerifyBody(
      { baselineRunId: "r-b", scenarioId: "s", version: "v", contentHash: "real-hash" },
      detail,
    );
    expect(JSON.stringify(body)).not.toContain("lab-ui-unpinned");
    // Whatever the form supplies lands verbatim — the body never substitutes
    // a constant for the caller's hash.
    expect(body.scenario.content_hash).toBe("real-hash");
  });
});
