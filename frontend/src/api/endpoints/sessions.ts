// Session face (SPEC-500 §4.2 lifecycle routes; the exhaustive transition
// table authority is SPEC-200 §5 — 409 SIM_INVALID_LIFECYCLE_TRANSITION
// carries {current,target,allowed} for the control bar's disable matrix).
import { client, unwrap } from "../client";
import type { components } from "../schema.gen";

export type CreateSessionRequest = components["schemas"]["CreateSessionRequest"];
export type SessionViewDTO = components["schemas"]["SessionViewDTO"];
export type SnapshotDTO = components["schemas"]["SnapshotDTO"];
export type SessionValidationDTO = components["schemas"]["SessionValidationDTO"];
// SPEC-408 §6 read increments (wire by ticket #94; consumed by #95's guidance
// layer). Types come from the generated chain — no hand-written mirrors.
export type SessionListItemDTO = components["schemas"]["SessionListItemDTO"];
export type SessionDetailDTO = components["schemas"]["SessionDetailDTO"];
export type RunListItemDTO = components["schemas"]["RunListItemDTO"];

export function createSession(body: CreateSessionRequest) {
  return unwrap<SessionViewDTO>(client.POST("/api/v1/sessions", { body }));
}

/** GET /sessions — newest-first recent list (server default limit 20, cap 100).
 * The rows answer in contract order; the frontend never re-sorts. */
export function listSessions(limit?: number) {
  return unwrap<SessionListItemDTO[]>(
    client.GET("/api/v1/sessions", {
      params: { query: limit === undefined ? {} : { limit } },
    }),
  );
}

/** GET /sessions/{id} — the detail read-back (provenance pair scenario_id? +
 * created_at_ms; SPEC-408 §6.2). Unknown id → 404 SIM_SESSION_NOT_FOUND. */
export function getSessionDetail(sessionId: string) {
  return unwrap<SessionDetailDTO>(
    client.GET("/api/v1/sessions/{session_id}", {
      params: { path: { session_id: sessionId } },
    }),
  );
}

/** GET /sessions/{id}/runs — submitted_at ASC (the eight-step narrative
 * order, SPEC-408 §6.3); no pagination, frontend never re-sorts. */
export function listSessionRuns(sessionId: string) {
  return unwrap<RunListItemDTO[]>(
    client.GET("/api/v1/sessions/{session_id}/runs", {
      params: { path: { session_id: sessionId } },
    }),
  );
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
