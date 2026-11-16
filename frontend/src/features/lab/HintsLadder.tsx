// Hints ladder (SPEC-406 §4.4, REQ-UI-406-004): progressive reveal of the
// scenario document's hints[] — PURE frontend. The document array order is
// the reveal order ("下一层" = the next unrevealed hint); the `level` wire
// string renders verbatim as a badge and is NEVER a sort key (no invented
// level semantics). Reveal state is parent-held (localStorage-backed per
// SPEC-408 §4.4 REQ-UI-408-011 via hintsStorage.ts): no backend
// participation; the disclosure line states 本地记录，非服务端事实 verbatim
// and the reset control clears the per-scenario record. When storage is
// unavailable the ladder says so honestly (「本地记录不可用，刷新将复位」)
// instead of faking persistence (SPEC-408 §8).
import { Badge, EmptyState } from "../../components/ui";

/** Structural wire shape of one ScenarioDetailDTO.hints[] entry
 * (list[dict[str, Any]] on the wire — field names verbatim, SPEC-205 §6). */
export interface LabHintWire {
  hint_id: string;
  trigger: string;
  level: string;
  content: string;
  requirement_ids: ReadonlyArray<string>;
  standard_ref: string | null;
}

export function HintsLadder({
  hints,
  revealedCount,
  onRevealNext,
  onResetHints,
  storageAvailable,
}: {
  hints: ReadonlyArray<LabHintWire>;
  revealedCount: number;
  onRevealNext: () => void;
  /** 重置提示 control: clears the per-scenario record (parent wipes the
   * storage key + memory count); the ladder only emits the intent. */
  onResetHints: () => void;
  /** false = localStorage unusable (SPEC-408 §8): keep page-memory counts,
   * disclose 「本地记录不可用，刷新将复位」, drop the 本地记录 claim. */
  storageAvailable: boolean;
}) {
  if (hints.length === 0) {
    return <EmptyState title="本场景未声明提示" note="hints[] 为空（文档事实，非错误）。" />;
  }
  const remaining = hints.length - revealedCount;
  const shownCount = Math.min(Math.max(revealedCount, 0), hints.length);
  return (
    <div className="dvb-lab-hints">
      <div className="dvb-lab-hints-status-line">
        <span data-testid="lab-hints-status" className="dvb-lab-hints-status">
          {storageAvailable
            ? `已揭示 ${shownCount}/${hints.length}（本地记录，非服务端事实）`
            : `已揭示 ${shownCount}/${hints.length}`}
        </span>
        {!storageAvailable && (
          <span data-testid="lab-hints-storage-unavailable" className="dvb-lab-hints-storage-warn">
            本地记录不可用，刷新将复位
          </span>
        )}
      </div>
      <ul className="dvb-lab-hint-list">
        {hints.map((hint, index) => {
          const revealed = index < revealedCount;
          return (
            <li
              key={hint.hint_id}
              data-testid={`lab-hint-${hint.hint_id}`}
              className={`dvb-lab-hint${revealed ? "" : " dvb-lab-hint-locked"}`}
            >
              {revealed ? (
                <>
                  <div className="dvb-lab-hint-head">
                    <Badge tone="info">{hint.level}</Badge>
                    <span className="dvb-lab-hint-trigger">{hint.trigger}</span>
                  </div>
                  <div className="dvb-lab-hint-content">{hint.content}</div>
                  {hint.requirement_ids.length > 0 && (
                    <div className="dvb-lab-hint-reqs">
                      {hint.requirement_ids.map((req) => (
                        <span key={req} className="dvb-lab-ref-chip">
                          {req}
                        </span>
                      ))}
                    </div>
                  )}
                  <div className="dvb-lab-hint-ref">
                    standard_ref:{" "}
                    <span className="dvb-lab-hint-ref-value">
                      {hint.standard_ref === null ? "无" : hint.standard_ref}
                    </span>
                  </div>
                </>
              ) : (
                <span className="dvb-lab-hint-locked-note">未揭示（第 {index + 1} 层）</span>
              )}
            </li>
          );
        })}
      </ul>
      <div className="dvb-lab-hints-controls">
        {remaining > 0 ? (
          <button type="button" className="dvb-lab-reveal" onClick={onRevealNext}>
            揭示下一条提示
            <span data-testid="lab-hints-remaining" className="dvb-lab-hints-remaining">
              （未揭示 {remaining} 条）
            </span>
          </button>
        ) : (
          <button type="button" className="dvb-lab-reveal" disabled>
            本场景提示已全部揭示
          </button>
        )}
        <button type="button" className="dvb-lab-reveal" data-testid="lab-hints-reset" onClick={onResetHints}>
          重置提示
        </button>
      </div>
    </div>
  );
}
