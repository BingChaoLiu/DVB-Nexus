// Hints ladder (SPEC-406 §4.4, REQ-UI-406-004): progressive reveal of the
// scenario document's hints[] — PURE frontend. The document array order is
// the reveal order ("下一层" = the next unrevealed hint); the `level` wire
// string renders verbatim as a badge and is NEVER a sort key (no invented
// level semantics). Reveal state is parent-held component state: no
// backend participation, no persistence (refresh resets — honest
// presentation, SPEC-406 §2.2 不做清单 boundary).
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
}: {
  hints: ReadonlyArray<LabHintWire>;
  revealedCount: number;
  onRevealNext: () => void;
}) {
  if (hints.length === 0) {
    return <EmptyState title="本场景未声明提示" note="hints[] 为空（文档事实，非错误）。" />;
  }
  const remaining = hints.length - revealedCount;
  return (
    <div className="dvb-lab-hints">
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
    </div>
  );
}
