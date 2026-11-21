// SIM_STATE Run 空态三问 (SPEC-404 §Phase3, ticket #169): a state-domain run
// produces no TS stream and no artifact (artifacts == [] — the #165 trigger
// condition), so the packet inspector renders the three-question empty state
// instead of a fake packet face. Copy lives in THIS folder: copy.ts is the
// SPEC-408 §4.6 Monitor-row verbatim authority (out of the #169 footprint) —
// this face is a NEW state, worded to the SPEC-404 §Phase3 line (这是什么 ·
// 为什么空——状态域 Run 不产码流，空 ≠ 干净 · 下一步去哪——按钮跳节点详情面板).
// The `view` param is NOT extended by this ticket.
import { Link } from "react-router";

import "./packet-inspector.css";

/** The §Phase3 empty-state copy (folder-local; the honesty phrase 空 ≠ 干净 is
 * spec-verbatim). */
export const SIM_STATE_EMPTY_COPY = {
  what: "包检查器呈现码流 artifact 的字节切片与结构解析（SPEC-404）",
  why: "当前 Run 是状态域仿真（SIM_STATE）：状态域 Run 不产码流、无 artifact——空 ≠ 干净",
  next: "前往拓扑画布点击 RF/SEC 节点，在节点详情面板查看 state_observed 快照与因果链",
} as const;

/** The SIM_STATE empty state: same dvb-empty-state typography as
 * ThreeQuestionState, plus the jump button (a Router link onto the topology
 * canvas with the tracked session). */
export function SimStateEmptyState({ sessionId }: { sessionId: string }) {
  return (
    <div className="dvb-empty-state" data-testid="dvb-pi-simstate-empty">
      <p className="dvb-empty-title">{SIM_STATE_EMPTY_COPY.what}</p>
      <p className="dvb-empty-note">{SIM_STATE_EMPTY_COPY.why}</p>
      <p className="dvb-empty-note dvb-mon-next">下一步:{SIM_STATE_EMPTY_COPY.next}</p>
      <Link className="dvb-pi-simstate-jump" data-testid="dvb-pi-simstate-jump" to={`/topologies?session=${sessionId}`}>
        前往节点详情面板
      </Link>
    </div>
  );
}
