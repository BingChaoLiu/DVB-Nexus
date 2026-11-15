// Diagnosis face (SPEC-500 §4.5; the report shape authority is SPEC-306 §5,
// ordering SPEC-307 §5, confidence three-tier ban = CONTEXT.md 诊断词条).
import { client, unwrap } from "../client";
import type { components } from "../schema.gen";

export type DiagnosisDTO = components["schemas"]["DiagnosisDTO"];
export type DiagnosisReportDTO = components["schemas"]["DiagnosisReportDTO"];

export function listDiagnoses(sessionId: string) {
  return unwrap<DiagnosisDTO[]>(
    client.GET("/api/v1/sessions/{session_id}/diagnoses", {
      params: { path: { session_id: sessionId } },
    }),
  );
}

// Idempotent re-evaluation (SPEC-306 §5).
export function diagnoseRun(sessionId: string, runId: string) {
  return unwrap<DiagnosisReportDTO>(
    client.POST("/api/v1/sessions/{session_id}/runs/{run_id}/diagnose", {
      params: { path: { session_id: sessionId, run_id: runId } },
    }),
  );
}
