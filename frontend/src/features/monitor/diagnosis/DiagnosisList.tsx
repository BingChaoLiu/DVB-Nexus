// Diagnosis presentation components (SPEC-403 §4.5/§6, REQ-UI-403-004/006):
// the reusable exported face for SPEC-404 (locator click entry) and SPEC-406
// (scenario-context overlay). Controlled presentation only — data comes in
// via props, no query/invalidation wiring inside the export surface.
// Ordering is the SPEC-307 §5 matrix via orderDiagnoses (no other sort key).
// The confidence tier renders as its static rule-declared enum string —
// never a probability/score (CONTEXT.md 诊断 ban).
import type { ReactNode } from "react";
import type { DiagnosisCandidateDTO, DiagnosisDTO, DiagnosisEvidenceDTO } from "../types";
import { Badge, EmptyState } from "../../../components/ui";
import { orderDiagnoses } from "./order";

export interface DiagnosisSharedProps {
  /**
   * SPEC-404 click entry: the locator triple is raised verbatim; the
   * component never navigates or decodes. Only rows that carry locator data
   * (report candidates — the wire DiagnosisDTO has no evidence field) render
   * the clickable slot.
   */
  onEvidenceSelect?: (locator: DiagnosisEvidenceDTO, row: DiagnosisDTO | DiagnosisCandidateDTO) => void;
  /** SPEC-406 scenario-context overlay slot (header area; fact rows untouched). */
  context?: ReactNode;
}

const SEVERITY_TONE: Record<string, "bad" | "warn" | "info" | "neutral"> = {
  critical: "bad",
  error: "bad",
  warning: "warn",
  info: "info",
};

function LocatorButton({
  evidence,
  onSelect,
  row,
}: {
  evidence: DiagnosisEvidenceDTO;
  onSelect?: DiagnosisSharedProps["onEvidenceSelect"];
  row: DiagnosisDTO | DiagnosisCandidateDTO;
}) {
  return (
    <button
      type="button"
      className="dvb-mon-locator"
      onClick={() => onSelect?.(evidence, row)}
      title={`artifact ${evidence.artifact_id} · pid ${evidence.pid} · packet ${evidence.packet_index}`}
    >
      evidence: {evidence.artifact_id} / pid {evidence.pid} / packet {evidence.packet_index}
    </button>
  );
}

function ObservationRefs({ refs }: { refs: { journal_seq: number; event_type: string }[] }) {
  return (
    <span className="dvb-mon-refs">
      {refs.map((ref) => (
        <span key={ref.journal_seq} className="dvb-mon-ref-chip" title="observation ref（journal 事实引用）">
          seq {ref.journal_seq} · {ref.event_type}
        </span>
      ))}
    </span>
  );
}

export function DiagnosisList({ diagnoses, onEvidenceSelect, context }: DiagnosisSharedProps & {
  diagnoses: readonly DiagnosisDTO[];
}) {
  const ordered = orderDiagnoses(diagnoses);
  return (
    <div className="dvb-mon-diagnosis-list">
      {context !== undefined && <div className="dvb-mon-context">{context}</div>}
      {ordered.length === 0 ? (
        <EmptyState title="无诊断记录" note="该 session 尚无 diagnoses 表行（不代表码流干净）。" />
      ) : (
        <ul className="dvb-mon-rows">
          {ordered.map((d) => (
            <li
              key={d.diagnosis_id}
              data-testid={`diagnosis-row-${d.diagnosis_id}`}
              className={`dvb-mon-row${d.state === "cleared" ? " dvb-mon-row-cleared" : ""}`}
            >
              <div className="dvb-mon-row-head">
                <span className="dvb-mon-code">{d.code}</span>
                <Badge tone={SEVERITY_TONE[d.severity] ?? "neutral"}>{d.severity}</Badge>
                <Badge tone="neutral">confidence: {d.confidence}</Badge>
                <Badge tone={d.state === "raised" ? "warn" : "neutral"}>{d.state}</Badge>
                <span className="dvb-mon-rule">
                  {d.rule_id} @ {d.rule_version}
                </span>
              </div>
              <ObservationRefs refs={d.observation_refs} />
              {d.affected_node_ids.length > 0 && (
                <div className="dvb-mon-line">affected: {d.affected_node_ids.join(", ")}</div>
              )}
              {d.suggested_actions.length > 0 && (
                <ul className="dvb-mon-actions">
                  {d.suggested_actions.map((action) => (
                    <li key={action}>{action}</li>
                  ))}
                </ul>
              )}
              <div className="dvb-mon-line">
                raised_at {d.raised_at}
                {d.cleared_at !== null && d.cleared_at !== undefined ? ` · cleared_at ${d.cleared_at}` : ""}
              </div>
              {onEvidenceSelect !== undefined && d.state === "raised" && (
                <div className="dvb-mon-line dvb-mon-note">
                  locator 呈现位在诊断候选（diagnose 报告）行上——diagnoses 表行不含 evidence 字段。
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function DiagnosisCandidateList({
  candidates,
  onEvidenceSelect,
  context,
}: DiagnosisSharedProps & { candidates: readonly DiagnosisCandidateDTO[] }) {
  const ordered = orderDiagnoses(candidates);
  return (
    <div className="dvb-mon-candidate-list">
      {context !== undefined && <div className="dvb-mon-context">{context}</div>}
      {ordered.length === 0 ? (
        <EmptyState title="无诊断候选" note="评估报告 candidates 为空（诚实结果，非错误）。" />
      ) : (
        <ul className="dvb-mon-rows">
          {ordered.map((c) => (
            <li key={c.diagnosis_id} data-testid={`candidate-row-${c.diagnosis_id}`} className="dvb-mon-row">
              <div className="dvb-mon-row-head">
                <span className="dvb-mon-code">{c.code}</span>
                <Badge tone="info">priority {c.priority}</Badge>
                <Badge tone={SEVERITY_TONE[c.severity] ?? "neutral"}>{c.severity}</Badge>
                <Badge tone="neutral">confidence: {c.confidence}</Badge>
              </div>
              <div className="dvb-mon-title">{c.title}</div>
              <div className="dvb-mon-line">{c.summary}</div>
              <ObservationRefs refs={c.observation_refs} />
              <div className="dvb-mon-line">
                <LocatorButton evidence={c.evidence} onSelect={onEvidenceSelect} row={c} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
