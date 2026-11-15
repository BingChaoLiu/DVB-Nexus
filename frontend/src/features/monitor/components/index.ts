// SPEC-403 public export barrel (§6, REQ-UI-403-006): the reusable
// diagnosis/verify presentation face for SPEC-404 (locator click entry) and
// SPEC-406 (scenario-context overlay). Signature-frozen additive surface —
// page-internal components (ControlBar/OverviewCard/RunTrigger/MetricsPanel/
// AlertsPanel/JournalTail/useSessionStream) are deliberately NOT exported.
// Controlled presentation only: data in via props, no query/invalidation
// wiring inside the exported components (callers fetch and pass data in).
//
// Frozen signatures (SPEC-403 §6; typecheck against these exports is the
// drift gate):
//   orderDiagnoses<T>(rows: readonly T[]): T[]
//     — SPEC-307 §5 matrix (priority asc → severity desc → code lex; absent
//       priority sorts last; stable, non-mutating, idempotent)
//   DiagnosisList({ diagnoses, onEvidenceSelect?, context? })
//   DiagnosisCandidateList({ candidates, onEvidenceSelect?, context? })
//     — onEvidenceSelect(locator, row) raises {artifact_id,pid,packet_index}
//       verbatim (SPEC-404 entry; locator data exists on candidates only)
//   VerifyResultCard({ result, context? })
//     — read-only VerificationResultDTO rendering, no local derivation
//   VERIFY_CRITERION_KINDS — the six-kind closed set (SPEC-206 §7)
//   monitorKeys.diagnoses / monitorKeys.report — feature query-key factory
//     (canonical-convention keys awaiting the shared keys.ts additive line;
//      see Region.ts header note)
export { DiagnosisCandidateList, DiagnosisList } from "../diagnosis/DiagnosisList";
export type { DiagnosisSharedProps } from "../diagnosis/DiagnosisList";
export { VerifyResultCard, VERIFY_CRITERION_KINDS } from "../verify/VerifyResultCard";
export { orderDiagnoses, SEVERITY_RANK } from "../diagnosis/order";
export { monitorKeys } from "../Region";
