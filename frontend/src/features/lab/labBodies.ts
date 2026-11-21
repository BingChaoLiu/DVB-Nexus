// Lab request-body builders (SPEC-406 §7.1/§7.4; verify per SPEC-408 §4.3
// + §7.5) — PURE seams, unit-tested against the §11 vectors. No fetch, no
// state: the console components call these and hand the result to the api
// barrel functions.
//
// - Create body: scenario_id (the document identity — the server's scenario
//   branch is document-governed, 加载即建 SPEC-205 §5; the request's
//   topology/seed/clock fields are permissive-ignored per the DTO contract,
//   orchestrator OQ-6) + the document's OWN projection values, so the plain
//   shape stays self-documenting and a server change cannot strand a
//   half-governed session. A v3 SIM_STATE document (Lab Pack v3 承载, #170)
//   carries {fidelity, seed} — no mode/clock: the sandbox deterministic
//   default applies and the clock key stays ABSENT (never a fabricated
//   realtime declaration).
// - Verify body: the detail's pass_criteria pass through VERBATIM (the
//   pass/fail contract is the document's declaration, never rewritten by
//   the UI); scenario identity comes from the EDITABLE PREFILL FORM —
//   scenario_id/version/content_hash prefilled from the scenario detail's
//   real pinned hash (SPEC-408 §6.4 增量③; the old `lab-ui-unpinned`
//   declared-marker posture is RETIRED per SPEC-406 §7.4 0.5.1 停用注记).
//   `ui_state` is NEVER sent (the engine provably ignores it; UI state is
//   not evidence — CONTEXT.md 通关 ban / AC-206-01).
// - Run submit body (#170, the #165 fidelity contract): SIM_TS carries the
//   FROZEN golden geometry config; SIM_STATE submits with the config key
//   ABSENT — the backend model 双向钉 (SIM_TS requires config, SIM_STATE
//   refuses one; carrying a dummy/null config would be the dishonest form).
import type { CreateSessionRequest, RunSubmitRequest, ScenarioDetailDTO, VerifyRunRequest } from "../../api";
import { LAB_RUN_CONFIG } from "./labGeometry";

/** The run-form discriminator (RunSubmitRequest.fidelity wire vocabulary). */
export type ScenarioFidelity = RunSubmitRequest["fidelity"];

/**
 * Read the scenario document's run form: `simulation_config.fidelity` is a
 * loose `{[key: string]: unknown}` projection — only the exact wire string
 * "SIM_STATE" selects the state form; everything else (v1 documents without
 * the field, malformed values) reads the wire default SIM_TS. No case
 * folding, no aliasing.
 */
export function readScenarioFidelity(detail: ScenarioDetailDTO): ScenarioFidelity {
  const fidelity = (detail.simulation_config as { fidelity?: unknown } | undefined)?.fidelity;
  return fidelity === "SIM_STATE" ? "SIM_STATE" : "SIM_TS";
}

/**
 * The run-submit body for the Lab's fidelity split (#170; #165 contract):
 * SIM_TS rides the FROZEN golden geometry (LAB_RUN_CONFIG — declaration-frozen,
 * never re-copied); SIM_STATE carries `fidelity` + the plan and NO config key
 * (缺省 — a state run has no generator; `config: null` would still be a
 * carried key, so the key is absent on the wire).
 */
export function buildRunSubmitBody(
  fidelity: ScenarioFidelity,
  faultPlan: ReadonlyArray<unknown>,
): RunSubmitRequest {
  if (fidelity === "SIM_STATE") {
    return {
      fidelity,
      fault_plan: faultPlan as RunSubmitRequest["fault_plan"],
    };
  }
  return {
    config: LAB_RUN_CONFIG as unknown as RunSubmitRequest["config"],
    fault_plan: faultPlan as RunSubmitRequest["fault_plan"],
    fidelity: "SIM_TS",
  };
}

/** The form-supplied scenario identity + run choice for a verify body.
 * Runs are NEVER derived automatically (SPEC-408 §7.5: run 不自动猜) —
 * both run ids arrive from explicit user selection in the console's
 * editable verify form; baseline rides the body, recovery the endpoint path
 * (the caller passes it to verifyRun separately). */
export interface VerifyIdentityInput {
  baselineRunId: string;
  scenarioId: string;
  version: string;
  contentHash: string;
}

export function buildCreateSessionBody(detail: ScenarioDetailDTO): CreateSessionRequest {
  const simulation = detail.simulation_config as {
    seed: number;
    mode?: string;
    clock?: CreateSessionRequest["clock_config"];
  };
  const topology = detail.initial_topology as {
    topology_id: string;
    revision: number;
  };
  return {
    scenario_id: detail.scenario_id,
    topology_id: topology.topology_id,
    topology_revision: topology.revision,
    seed: simulation.seed,
    // v1 mode ∈ {deterministic, realtime} (unchanged reading); a v3 SIM_STATE
    // document carries no mode — the sandbox deterministic DEFAULT applies,
    // never a fabricated realtime declaration (#170 Lab Pack v3 承载).
    deterministic: simulation.mode !== "realtime",
    ...(simulation.clock !== undefined ? { clock_config: simulation.clock } : {}),
  };
}

export function buildVerifyBody(identity: VerifyIdentityInput, detail: ScenarioDetailDTO): VerifyRunRequest {
  return {
    baseline_run_id: identity.baselineRunId,
    scenario: {
      scenario_id: identity.scenarioId,
      version: identity.version,
      content_hash: identity.contentHash,
    },
    pass_criteria: detail.pass_criteria as VerifyRunRequest["pass_criteria"],
  };
}
