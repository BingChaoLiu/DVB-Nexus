// Session face (SPEC-500 §4.2 lifecycle routes; the exhaustive transition
// table authority is SPEC-200 §5 — 409 SIM_INVALID_LIFECYCLE_TRANSITION
// carries {current,target,allowed} for the control bar's disable matrix).
import { client, unwrap } from "../client";
import type { components } from "../schema.gen";

export type CreateSessionRequest = components["schemas"]["CreateSessionRequest"];
export type SessionViewDTO = components["schemas"]["SessionViewDTO"];
export type SnapshotDTO = components["schemas"]["SnapshotDTO"];
export type SessionValidationDTO = components["schemas"]["SessionValidationDTO"];

export function createSession(body: CreateSessionRequest) {
  return unwrap<SessionViewDTO>(client.POST("/api/v1/sessions", { body }));
}

export function validateSession(sessionId: string) {
  return unwrap<SessionValidationDTO>(
    client.POST("/api/v1/sessions/{session_id}/validate", {
      params: { path: { session_id: sessionId } },
    }),
  );
}

export function startSession(sessionId: string) {
  return unwrap<SessionViewDTO>(
    client.POST("/api/v1/sessions/{session_id}/start", {
      params: { path: { session_id: sessionId } },
    }),
  );
}

export function pauseSession(sessionId: string) {
  return unwrap<SessionViewDTO>(
    client.POST("/api/v1/sessions/{session_id}/pause", {
      params: { path: { session_id: sessionId } },
    }),
  );
}

export function resumeSession(sessionId: string) {
  return unwrap<SessionViewDTO>(
    client.POST("/api/v1/sessions/{session_id}/resume", {
      params: { path: { session_id: sessionId } },
    }),
  );
}

export function stopSession(sessionId: string) {
  return unwrap<SessionViewDTO>(
    client.POST("/api/v1/sessions/{session_id}/stop", {
      params: { path: { session_id: sessionId } },
    }),
  );
}

export function disposeSession(sessionId: string) {
  return unwrap<void>(
    client.DELETE("/api/v1/sessions/{session_id}", {
      params: { path: { session_id: sessionId } },
    }),
  );
}

export function getSnapshot(sessionId: string, journalSeqCursor?: number) {
  return unwrap<SnapshotDTO>(
    client.GET("/api/v1/sessions/{session_id}/snapshot", {
      params: {
        path: { session_id: sessionId },
        query: journalSeqCursor === undefined ? {} : { journal_seq_cursor: journalSeqCursor },
      },
    }),
  );
}
