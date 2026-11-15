// Run face (SPEC-500 §4.3): submit is 202 + run_id (never synchronous);
// status polls the job surface (the #58 POLL_BOUND posture).
import { client, unwrap } from "../client";
import type { components } from "../schema.gen";

export type RunSubmitRequest = components["schemas"]["RunSubmitRequest"];
export type RunAcceptedDTO = components["schemas"]["RunAcceptedDTO"];
export type RunStatusDTO = components["schemas"]["RunStatusDTO"];

export function submitRun(sessionId: string, body: RunSubmitRequest) {
  return unwrap<RunAcceptedDTO>(
    client.POST("/api/v1/sessions/{session_id}/runs", {
      params: { path: { session_id: sessionId } },
      body,
    }),
  );
}

export function getRun(sessionId: string, runId: string) {
  return unwrap<RunStatusDTO>(
    client.GET("/api/v1/sessions/{session_id}/runs/{run_id}", {
      params: { path: { session_id: sessionId, run_id: runId } },
    }),
  );
}
