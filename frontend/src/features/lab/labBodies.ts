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
//   half-governed session.
// - Verify body: the detail's pass_criteria pass through VERBATIM (the
//   pass/fail contract is the document's declaration, never rewritten by
//   the UI); scenario identity comes from the EDITABLE PREFILL FORM —
//   scenario_id/version/content_hash prefilled from the scenario detail's
//   real pinned hash (SPEC-408 §6.4 增量③; the old `lab-ui-unpinned`
//   declared-marker posture is RETIRED per SPEC-406 §7.4 0.5.1 停用注记).
//   `ui_state` is NEVER sent (the engine provably ignores it; UI state is
//   not evidence — CONTEXT.md 通关 ban / AC-206-01).
import type { CreateSessionRequest, ScenarioDetailDTO, VerifyRunRequest } from "../../api";

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
    mode: string;
    clock: CreateSessionRequest["clock_config"];
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
    deterministic: simulation.mode === "deterministic",
    clock_config: simulation.clock,
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
