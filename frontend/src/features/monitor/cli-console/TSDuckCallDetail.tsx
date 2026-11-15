// Call detail (SPEC-405 §4.3, REQ-UI-405-002 / AC-405-02/03). Display-text
// discipline (§7.3): stdout/stderr are pre-decoded display text from the
// backend (GBK → UTF-8 errors="replace" upstream) — rendered verbatim in
// monospace <pre> blocks: no trim, no line-splitting, no re-decode, no error
// keyword extraction, no ANSI parsing. U+FFFD is part of the honest display.
// exit 0 ≠ valid (§7.4, #3/#13): the standing content-gate annotation sits in
// the same view as the raw exit_code for EVERY record (never conditionally
// hidden); no success/failure decoration is ever attached to an exit code —
// validity evidence lives in AnalysisReport artifacts and the verify verdict,
// not here (CONTEXT.md UI-judgment ban).
import type { SourceTaggedCall } from "./sources";
import { isoUtcMs } from "./TSDuckCallList";

const NULL_ABSENT = "null（失败路径字段显式缺省）";
const NULL_EXIT = "—（进程未退到可回收码）";

const GATE_ANNOTATION =
  "退出码 0 不代表报告有效 —— JSON 内容门（ts.bytes > 0 && ts.services.total >= 1）" +
  "失败时调用仍以 0 退出（SPEC-308 §9）。有效性以 AnalysisReport 与 verify 判定为准，本页不作有效性判定。";

function Field({ name, children }: { name: string; children: React.ReactNode }) {
  return (
    <div className="dvb-cli-field">
      <span className="dvb-cli-field-name">{name}</span>
      <span className="dvb-cli-field-value">{children}</span>
    </div>
  );
}

export function TSDuckCallDetail({ row }: { row: SourceTaggedCall }) {
  const call = row.call;
  return (
    <div className="dvb-cli-detail">
      <Field name="version">{call.version ?? NULL_ABSENT}</Field>
      <Field name="executable_path">{call.executable_path ?? NULL_ABSENT}</Field>
      <Field name="argv">
        {(() => {
          const argv = call.argv ?? [];
          return argv.length === 0 ? (
            NULL_ABSENT
          ) : (
            <ul className="dvb-cli-argv">
              {argv.map((arg, i) => (
                <li key={`${i}-${arg}`}>{arg}</li>
              ))}
            </ul>
          );
        })()}
      </Field>
      <Field name="started_at_utc_ms">{isoUtcMs(call.started_at_utc_ms)}</Field>
      <Field name="finished_at_utc_ms">{isoUtcMs(call.finished_at_utc_ms)}</Field>
      <Field name="exit_code">
        <span className="dvb-cli-exitcode">{call.exit_code ?? NULL_EXIT}</span>
      </Field>
      <Field name="input_artifact_sha256">{call.input_artifact_sha256 ?? NULL_ABSENT}</Field>
      <Field name="run_id">{call.run_id ?? NULL_ABSENT}</Field>

      <Field name="stdout_text">
        {call.stdout_text === null || call.stdout_text === undefined ? (
          NULL_ABSENT
        ) : (
          <pre className="dvb-cli-text">{call.stdout_text}</pre>
        )}
      </Field>
      <Field name="stderr_text">
        {call.stderr_text === null || call.stderr_text === undefined ? (
          NULL_ABSENT
        ) : (
          <pre className="dvb-cli-text dvb-cli-stderr">{call.stderr_text}</pre>
        )}
      </Field>

      {/* Standing content-gate annotation: same view as exit_code, every record (§7.4). */}
      <div className="dvb-cli-gate" role="note" aria-label="exit 0 ≠ 有效报告内容门标注">
        {GATE_ANNOTATION}
      </div>
    </div>
  );
}
