// Lab request-body builders (SPEC-406 §7.1/§7.4) — PURE seams, unit-tested
// against the §11 vectors. No fetch, no state: the console components call
// these and hand the result to the api barrel functions.
//
// - Create body: scenario_id (the document identity — the server's scenario
//   branch is document-governed, 加载即建 SPEC-205 §5; the request's
//   topology/seed/clock fields are permissive-ignored per the DTO contract,
//   orchestrator OQ-6) + the document's OWN projection values, so the plain
//   shape stays self-documenting and a server change cannot strand a
//   half-governed session.
// - Verify body: the detail's pass_criteria pass through VERBATIM (the
//   pass/fail contract is the document's declaration, never rewritten by
//   the UI); scenario identity carries the true scenario_id/version and the
//   declared content_hash marker (SPEC-406 §7.4 申报句: the loader-pinned
//   hash has no REST echo face — the marker declares that honestly; the
//   reveal gate matches on scenario_id). `ui_state` is NEVER sent (the
//   engine provably ignores it; UI state is not evidence — CONTEXT.md
//   通关 ban / AC-206-01).
import type { CreateSessionRequest, ScenarioDetailDTO, VerifyRunRequest } from "../../api";

/** SPEC-406 §7.4: the declared marker for the unobservable pinned hash. */
export const VERIFY_CONTENT_HASH_MARKER = "lab-ui-unpinned";

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

export function buildVerifyBody(detail: ScenarioDetailDTO, baselineRunId: string): VerifyRunRequest {
  return {
    baseline_run_id: baselineRunId,
    scenario: {
      scenario_id: detail.scenario_id,
      version: detail.version,
      content_hash: VERIFY_CONTENT_HASH_MARKER,
    },
    pass_criteria: detail.pass_criteria as VerifyRunRequest["pass_criteria"],
  };
}
