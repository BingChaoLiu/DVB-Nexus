// Eight-step stepper state derivation (SPEC-406 §7.3, REQ-UI-406-006).
// PURE mapping from observable server facts to the eight CONTEXT.md closed
// loop steps (Create → Generate → Inject → Analyze → Diagnose → Inspect →
// Recover → Verify). Every input arrives from a server answer the page
// holds (SessionViewDTO lifecycle / the page run registry's RunStatusDTO /
// the fetched DiagnosisReportDTO / the events query answer / the fetched
// VerificationResultDTO) — there is NO local business inference here, no
// timers, no button-click flags. "Stepper progress ≠ 通关 evidence" is a
// rendering obligation of the consumer (SPEC-406 §7.3 note), not this
// function's concern.
//
// Wire-fact anchors:
// - "clean run" = a COMPLETED run whose artifacts[] carry `generated_ts`
//   and NOT `faulted_ts` (the prepare-bound plan produces `faulted_ts`
//   artifacts only for non-empty plans — a server-side artifact-kind fact,
//   not a UI guess about plan contents);
// - "faulted run" = a COMPLETED run carrying `faulted_ts`;
// - §6.3 list-reconstructed rows (review-fix F1) hold NO artifact list —
//   their clean/faulted facts ride the server's fault_plan_present boolean
//   verbatim (never a fabricated artifact);
// - Recover = a SECOND distinct clean run (run registry keys are unique
//   run_ids, so counting ≥ 2 IS the distinctness fact);
// - Analyze = the declared gap: the analysis bridge is in-process (M4
//   裁定 B; REST analyze frozen 501) — this step is ALWAYS false and the
//   UI renders it as 不可用, never as progress.

export interface LabRunFact {
  runId: string;
  status: "running" | "completed" | "cancelled" | "failed";
  artifacts: ReadonlyArray<{ kind: string }>;
  /** The §6.3 run-list fact (SPEC-408 §7.5 同口径; review-fix F1): rows
   * reconstructed from GET /sessions/{id}/runs carry NO artifact list — the
   * clean/faulted facts ride the server's own fault_plan_present boolean.
   * null = a page-memory run (facts stay on the artifact-kind path). */
  faultPlanPresent: boolean | null;
}

export interface LabFacts {
  /** SessionViewDTO.lifecycle (wire lowercase string); null = not held. */
  sessionLifecycle: string | null;
  /** The page run registry (unique run_id keys), each entry's latest poll. */
  runs: ReadonlyArray<LabRunFact>;
  /** A DiagnosisReportDTO has been fetched for the chosen run. */
  reportFetched: boolean;
  /** items length of the answered GET .../events query. */
  eventsSeen: number;
  /** A VerificationResultDTO has been fetched (any verdict). */
  verdictFetched: boolean;
}

export interface EightStepBooleans {
  create: boolean;
  generate: boolean;
  inject: boolean;
  analyze: boolean;
  diagnose: boolean;
  inspect: boolean;
  recover: boolean;
  verify: boolean;
}

const CREATE_LIFECYCLES = new Set(["running", "paused"]);

function isCompletedCleanRun(entry: LabRunFact): boolean {
  if (entry.status !== "completed") return false;
  // §6.3 list fact wins when held (review-fix F1): fault_plan_present=true
  // is never clean; false + no artifact face IS clean (the list answers
  // plan presence directly — no artifact fabrication).
  if (entry.faultPlanPresent !== null) return !entry.faultPlanPresent;
  const kinds = entry.artifacts.map((artifact) => artifact.kind);
  return kinds.includes("generated_ts") && !kinds.includes("faulted_ts");
}

function isCompletedFaultedRun(entry: LabRunFact): boolean {
  if (entry.status !== "completed") return false;
  // §6.3 list fact wins when held (review-fix F1) — the server's
  // fault_plan_present boolean replaces the faulted_ts artifact detection
  // for list-reconstructed rows (artifact chips stay unrendered there).
  if (entry.faultPlanPresent !== null) return entry.faultPlanPresent;
  return entry.artifacts.some((artifact) => artifact.kind === "faulted_ts");
}

/** The §7.3 mapping table as a pure function (exhaustively unit-tested). */
export function deriveStepState(facts: LabFacts): EightStepBooleans {
  const cleanRuns = facts.runs.filter(isCompletedCleanRun);
  return {
    create: facts.sessionLifecycle !== null && CREATE_LIFECYCLES.has(facts.sessionLifecycle),
    generate: cleanRuns.length >= 1,
    inject: facts.runs.some(isCompletedFaultedRun),
    // Declared gap (M4 裁定 B): no HTTP analysis face — never done.
    analyze: false,
    diagnose: facts.reportFetched,
    inspect: facts.eventsSeen >= 1,
    recover: cleanRuns.length >= 2,
    verify: facts.verdictFetched,
  };
}
