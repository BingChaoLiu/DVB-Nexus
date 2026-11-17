// SPEC-404 §Phase2 — the BISS 加扰态标注 face (#132). Renders the evidence
// REFERENCES only: mode wire value verbatim ("1"/"E"/"2" — 禁改写), the key
// FINGERPRINT reference verbatim (sha256: prefix preserved — the key material
// itself NEVER renders, SPEC-610 §9), and the mutation-log summary fetched
// from the `mutation_log_ref` artifact. The biss.descramble_failed evidence
// link rides the same fingerprint symbol (事件与 mutation log 互链面).
import { FieldRow } from "./fields";
import { useMutationLogSummary } from "./useMutationLogSummary";
import type { BissEvidenceAnnotation } from "./viewTypes";

export function BissAnnotation({ evidence }: { evidence: BissEvidenceAnnotation }) {
  const log = useMutationLogSummary(evidence.mutation_log_ref ?? null);

  return (
    <div className="dvb-pi-biss" data-testid="biss-annotation">
      <h4 className="dvb-pi-section">BISS 加扰态标注（SPEC-404 §Phase2）</h4>
      {evidence.mode !== undefined && (
        <FieldRow name="mode" testid="biss-mode" value={evidence.mode} note={'wire 枚举原样（"1" | "E" | "2"）'} />
      )}
      {evidence.key_fingerprint_ref !== undefined && (
        <FieldRow
          name="key_fingerprint_ref"
          testid="biss-fingerprint"
          value={evidence.key_fingerprint_ref}
          note="密钥指纹引用（sha256: 前缀原样）——密钥本体永不渲染"
        />
      )}
      {evidence.key_fingerprint_ref !== undefined && (
        <p className="dvb-pi-note" data-testid="biss-evidence-link">
          证据互链：biss.descramble_failed 证据以同一 key_fingerprint_ref 符号关联 mutation log。
        </p>
      )}
      {evidence.mutation_log_ref ? (
        log.phase === "loading" ? (
          <p className="dvb-pi-line" data-testid="biss-mutation-log-loading">
            读取 mutation log artifact…
          </p>
        ) : log.phase === "error" ? (
          <p className="dvb-pi-error" data-testid="biss-mutation-log-error">
            mutation log 读取失败：HTTP {log.status} · {log.errorCode} · {log.message}
          </p>
        ) : log.phase === "ready" ? (
          <div data-testid="biss-mutation-log">
            <FieldRow name="mutation_log_ref" value={evidence.mutation_log_ref} note="LOG-kind artifact（内容寻址）" />
            {log.summary.log_kind !== null && <FieldRow name="log_kind" value={log.summary.log_kind} />}
            {log.summary.run_id !== null && <FieldRow name="run_id" value={log.summary.run_id} />}
            {log.summary.layer_record_counts !== null &&
              log.summary.layer_record_counts.map((entry) => (
                <FieldRow
                  key={entry.layer}
                  name={`layer ${entry.layer}`}
                  value={`${entry.records} 条记录`}
                  note="§8.2 分层文档记录数（摘要）"
                />
              ))}
            {log.summary.fault_count !== null && (
              <FieldRow name="faults" value={String(log.summary.fault_count)} note="§8.2 fault 记录数（摘要）" />
            )}
            {log.summary.record_count !== null && (
              <FieldRow name="mutations" value={String(log.summary.record_count)} note="§8.2 逐槽记录数（摘要）" />
            )}
          </div>
        ) : null
      ) : null}
    </div>
  );
}
