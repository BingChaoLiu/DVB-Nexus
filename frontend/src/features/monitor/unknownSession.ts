// Unknown-session explicit state predicate (SPEC-408 §4.3/§4.6 Monitor row 0,
// ticket #95). A deep-linked or currently tracked session may not exist
// server-side (cleaned up, expired, mistyped id). The two signal routes are:
//   1. a session-scoped REST read answering HTTP 404 (SIM_SESSION_NOT_FOUND);
//   2. the WS stream's permanent close 4404 (CLOSE_SESSION_UNKNOWN —
//      session unknown/DISPOSED, never reconnected; SPEC-501 §5).
// Both are server facts; this predicate is the single judgment both render
// paths share (the page shows the explicit unknown-session state, never an
// error stack). Transient WS closes (reconnectable network-class codes) and
// "no signal yet" are NOT unknown — absence of evidence stays honest.
import { CLOSE_SESSION_UNKNOWN } from "../../ws/closeCodes";

export interface UnknownSessionSignals {
  /** True iff the session-scoped REST reads (snapshot / detail) answered 404. */
  sessionHttpNotFound: boolean;
  /** The latest WS close code observed on this page scope (null = none yet). */
  wsCloseCode: number | null;
}

export function isUnknownSessionState(signals: UnknownSessionSignals): boolean {
  if (signals.sessionHttpNotFound) return true;
  return signals.wsCloseCode === CLOSE_SESSION_UNKNOWN;
}
