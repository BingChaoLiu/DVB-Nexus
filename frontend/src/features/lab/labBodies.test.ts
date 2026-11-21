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
//
// #170 fidelity 语义钉(SPEC-406 §Phase3 承载): run 提交按场景 fidelity 分叉 —
// SIM_TS 提交冻结几何 config;SIM_STATE 提交 config 键缺省(#165 模型双向钉:
// 携带任何 config 都是「假」形态),fidelity 字段 wire 串原样。
import { describe, expect, it } from "vitest";
import { buildCreateSessionBody, buildRunSubmitBody, buildVerifyBody, readScenarioFidelity } from "./labBodies";
import { LAB_RUN_CONFIG } from "./labGeometry";
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

  it("v1 realtime declaration passes through unchanged (mode === realtime → deterministic false)", () => {
    const realtimeDetail = {
      ...detail,
      simulation_config: { ...detail.simulation_config, mode: "realtime" },
    } as unknown as ScenarioDetailDTO;
    const body = buildCreateSessionBody(realtimeDetail);
    expect(body.deterministic).toBe(false);
    expect(body.clock_config).toBeDefined();
  });

  it("a v3 SIM_STATE document (simulation_config {fidelity, seed}, no mode/clock) opens honestly on the sandbox default", () => {
    // Lab Pack v3 承载(可开性): no mode → deterministic default (never a fake
    // realtime declaration); no clock → the key is ABSENT (backend default).
    const v3Detail = {
      ...detail,
      schema_version: "3",
      simulation_config: { fidelity: "SIM_STATE", seed: 1234567 },
    } as unknown as ScenarioDetailDTO;
    const body = buildCreateSessionBody(v3Detail);
    expect(body.seed).toBe(1234567);
    expect(body.deterministic).toBe(true);
    expect("clock_config" in body).toBe(false);
  });
});

describe("readScenarioFidelity — the wire-string fidelity read (#170)", () => {
  it("a v1 document (no fidelity field) reads SIM_TS (the wire default)", () => {
    expect(readScenarioFidelity(detail)).toBe("SIM_TS");
  });

  it("a v3 SIM_STATE document reads SIM_STATE (wire string verbatim)", () => {
    const v3Detail = {
      ...detail,
      simulation_config: { fidelity: "SIM_STATE", seed: 1 },
    } as unknown as ScenarioDetailDTO;
    expect(readScenarioFidelity(v3Detail)).toBe("SIM_STATE");
  });

  it("anything but the exact wire string falls back to SIM_TS (no case folding, no aliasing)", () => {
    for (const bad of ["sim_state", "SIMSTATE", 3, null, undefined]) {
      const malformed = {
        ...detail,
        simulation_config: { ...detail.simulation_config, fidelity: bad },
      } as unknown as ScenarioDetailDTO;
      expect(readScenarioFidelity(malformed)).toBe("SIM_TS");
    }
  });
});

describe("buildRunSubmitBody — the #165 fidelity contract (#170)", () => {
  const plan = [{ fault_id: "fd-9", fault_type: "UB_SLOT_CONFLICT" }];

  it("SIM_TS carries the frozen golden geometry config + the plan + explicit SIM_TS", () => {
    const body = buildRunSubmitBody("SIM_TS", plan);
    // identity: the FROZEN geometry passes through untouched (never re-copied).
    expect(body.config).toBe(LAB_RUN_CONFIG as unknown as typeof body.config);
    expect(body.fault_plan).toBe(plan as unknown as typeof body.fault_plan);
    expect(body.fidelity).toBe("SIM_TS");
  });

  it("SIM_STATE submits with the config key ABSENT (#165 模型双向钉: SIM_STATE 必须无 config)", () => {
    const body = buildRunSubmitBody("SIM_STATE", plan);
    expect(body.fidelity).toBe("SIM_STATE");
    expect(body.fault_plan).toBe(plan as unknown as typeof body.fault_plan);
    // 缺省, not null — carrying any config (even a dummy/null shape) is the
    // dishonest form the backend validator refuses.
    expect("config" in body).toBe(false);
  });

  it("an empty SIM_STATE plan (the auto-baseline / recovery form) also omits config", () => {
    const body = buildRunSubmitBody("SIM_STATE", []);
    expect(body.fidelity).toBe("SIM_STATE");
    expect("config" in body).toBe(false);
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
