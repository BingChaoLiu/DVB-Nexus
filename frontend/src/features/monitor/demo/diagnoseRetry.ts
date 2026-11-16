// Diagnose 404-until-drained retrier — the ONE shared implementation
// (review-fix F4 收拢: the demo orchestration and the Monitor page's
// diagnose trigger previously carried two byte-identical inline loops with
// same-named constants). The report becomes answerable once the pump has
// committed the run's terminal journal events (SPEC-306 §5 idempotent), so
// a fresh 404 is retried inside a short window instead of surfacing as an
// error. diagnoseRun stays the only authority call — this wrapper adds
// timing, never semantics.
import { diagnoseRun, type DiagnosisReportDTO } from "../../../api";
import { ApiError } from "../../../api/client";

/** Retry pacing (the #99 window/stride, kept identical for both consumers). */
export const DIAGNOSE_404_RETRY_WINDOW_MS = 10_000;
export const DIAGNOSE_404_RETRY_INTERVAL_MS = 100;

/** diagnoseRun with the 404-until-drained retry window: a fresh 404 is
 * retried every DIAGNOSE_404_RETRY_INTERVAL_MS until
 * DIAGNOSE_404_RETRY_WINDOW_MS elapses; any other failure (and any 404 past
 * the window) surfaces unchanged. */
export async function diagnoseWith404Retry(sessionId: string, runId: string): Promise<DiagnosisReportDTO> {
  const deadline = Date.now() + DIAGNOSE_404_RETRY_WINDOW_MS;
  for (;;) {
    try {
      return await diagnoseRun(sessionId, runId);
    } catch (error) {
      if (error instanceof ApiError && error.status === 404 && Date.now() < deadline) {
        await new Promise((resolve) => setTimeout(resolve, DIAGNOSE_404_RETRY_INTERVAL_MS));
        continue;
      }
      throw error;
    }
  }
}
