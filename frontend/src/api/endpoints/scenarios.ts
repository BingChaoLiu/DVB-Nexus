// Scenario face (SPEC-500 §4.7, wired by #80 over the SPEC-205 registry;
// SPEC-406 §6 is the frontend consumer contract). Wire semantics pinned by
// the backend routes:
//
// - GET /scenarios           → filename-ASC summaries (the summary
//   projection only — no document payload, no hidden solution);
// - GET /scenarios/{id}      → the exported document with
//   `hidden_reference_solution` absent by construction
//   (REQ-SIM-205-003: reveal 政策外不泄露); `initial_topology` keeps its
//   authored camelCase keys (nodeId/nodeType/portId/… — the #45
//   canonical-example authority, a wire island inside the snake_case REST);
// - GET /scenarios/{id}/solution?session_id= → the 裁定 F reveal gate:
//   200 {scenario_id, hidden_reference_solution: string|null} iff that
//   (session, scenario) pair carries a verdict=PASS SPEC-206 row; anything
//   else 403 SIM_SCENARIO_SOLUTION_LEAK; missing session_id → 400;
//   unknown scenario → 404 SIM_SCENARIO_NOT_FOUND.
//
// Non-2xx throws ApiError (client core).
import { client, unwrap } from "../client";
import type { components } from "../schema.gen";

export type ScenarioSummaryDTO = components["schemas"]["ScenarioSummaryDTO"];
export type ScenarioDetailDTO = components["schemas"]["ScenarioDetailDTO"];
export type ScenarioSolutionDTO = components["schemas"]["ScenarioSolutionDTO"];

export function listScenarios() {
  return unwrap<ScenarioSummaryDTO[]>(client.GET("/api/v1/scenarios"));
}

export function getScenario(scenarioId: string) {
  return unwrap<ScenarioDetailDTO>(
    client.GET("/api/v1/scenarios/{scenario_id}", {
      params: { path: { scenario_id: scenarioId } },
    }),
  );
}

export function revealScenarioSolution(scenarioId: string, sessionId: string) {
  return unwrap<ScenarioSolutionDTO>(
    client.GET("/api/v1/scenarios/{scenario_id}/solution", {
      params: {
        path: { scenario_id: scenarioId },
        query: { session_id: sessionId },
      },
    }),
  );
}
