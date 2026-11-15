// Verification face (SPEC-206 three-state via SPEC-500 §4.6). The verdict and
// criterion kinds are the CONTEXT.md 通关 authority — the UI only renders what
// this returns, never derives a verdict locally (SPEC-400 §8 bans).
// `ui_state` in the request is accepted by the engine and NEVER consulted.
import { client, unwrap } from "../client";
import type { components } from "../schema.gen";

export type VerifyRunRequest = components["schemas"]["VerifyRunRequest"];
export type VerificationResultDTO = components["schemas"]["VerificationResultDTO"];

export function verifyRun(sessionId: string, runId: string, body: VerifyRunRequest) {
  return unwrap<VerificationResultDTO>(
    client.POST("/api/v1/sessions/{session_id}/runs/{run_id}/verify", {
      params: { path: { session_id: sessionId, run_id: runId } },
      body,
    }),
  );
}
