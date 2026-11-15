// Verify result card (SPEC-403 §4.6, REQ-UI-403-005): a read-only rendering of
// the server's VerificationResultDTO. There is NO local verdict derivation —
// the card displays exactly the returned verdict string and criterion rows;
// NOT_EVALUATED rows must show their explicit reason (never silent). The
// six-kind closed set is exported for the request form's kind dropdown.
import type { ReactNode } from "react";
import type { VerificationResultDTO } from "../types";
import { Badge, EmptyState } from "../../../components/ui";

/** SPEC-206 §7 frozen criterion-kind closed set (verbatim wire slugs). */
export const VERIFY_CRITERION_KINDS: readonly string[] = [
  "fault_inactive",
  "psi_pat_valid",
  "psi_pmt_valid",
  "pat_pmt_mapping_valid",
  "cc_continuous",
  "no_unexpected_cc_error",
];

const RESULT_TONE: Record<string, "good" | "bad" | "warn" | "neutral"> = {
  PASS: "good",
  FAIL: "bad",
  NOT_EVALUATED: "warn",
};

const VERDICT_TONE: Record<string, "good" | "bad" | "warn"> = {
  PASS: "good",
  FAIL: "bad",
  INCONCLUSIVE: "warn",
};

export function VerifyResultCard({ result, context }: { result: VerificationResultDTO; context?: ReactNode }) {
  return (
    <div className="dvb-mon-verify-card">
      {context !== undefined && <div className="dvb-mon-context">{context}</div>}
      <div className="dvb-mon-row-head">
        <span data-testid="verify-verdict" className="dvb-mon-verdict">
          <Badge tone={VERDICT_TONE[result.verdict] ?? "neutral"}>{result.verdict}</Badge>
        </span>
        <span className="dvb-mon-line">
          recovery {result.recovery_run_id} · baseline {result.baseline_run_id} · scenario{" "}
          {result.scenario.scenario_id}@{result.scenario.version}
        </span>
      </div>
      {result.criteria.length === 0 ? (
        <EmptyState title="无判据明细" note="服务端返回 criteria 为空（原样呈现）。" />
      ) : (
        <ul className="dvb-mon-rows">
          {result.criteria.map((c) => (
            <li key={c.criterion_id} data-testid={`criterion-${c.criterion_id}`} className="dvb-mon-row">
              <div className="dvb-mon-row-head">
                <span className="dvb-mon-code">{c.criterion_id}</span>
                <Badge tone="info">{c.kind}</Badge>
                <Badge tone="neutral">{c.mandatory ? "mandatory" : "optional"}</Badge>
                <Badge tone={RESULT_TONE[c.result] ?? "neutral"}>{c.result}</Badge>
              </div>
              {c.result === "NOT_EVALUATED" && (
                <div className="dvb-mon-line dvb-mon-not-evaluated">
                  {c.reason_code !== null && c.reason_code !== undefined && (
                    <span className="dvb-mon-code">{c.reason_code}</span>
                  )}
                  {c.reason !== null && c.reason !== undefined && <span> · {c.reason}</span>}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      <div className="dvb-mon-line">{result.summary}</div>
      {(result.evidence_refs?.length ?? 0) > 0 && (
        <div className="dvb-mon-line">evidence_refs: {JSON.stringify(result.evidence_refs)}</div>
      )}
      <div className="dvb-mon-line dvb-mon-note">verified_at_utc_ms {result.verified_at_utc_ms}</div>
    </div>
  );
}
