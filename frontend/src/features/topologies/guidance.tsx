// Guidance-layer components (SPEC-408 §4.5, five faces — REQ-UI-408-013).
// Every literal here is the spec's 定稿 copy byte-exact (fullwidth
// punctuation included): the banner/overlay/save-note sentences, the three
// gate states and the four §7.6 connection reasons. Vocabulary discipline
// (CONTEXT.md): 「已保存拓扑」 (what this module saves) and 「场景初始拓扑」
// (what Lab scenarios carry) are kept distinct — no bare 拓扑 mixing.
// Static signage only: no modals, no tours, no dismiss controls (§4.5 item 1
// 可关闭性不做; the AC-401-06 negative surface stays untouched).
import { useEffect, useState } from "react";
import { Link } from "react-router";

import type { GateReason } from "./inspector/inspectorGate";
import { CONNECTION_HINT_VISIBLE_MS } from "./connectionFeedback";

/** §4.5 item 1 — 页内常驻说明条 (page top; static wayfinding; closability is
 * explicitly NOT built). Links carry plain path strings only (the parallel
 * shell ticket owns the shell; this module imports no shell component). */
export function TopologyGuidanceBanner() {
  return (
    <section className="dvb-topo-guidance" data-testid="dvb-topo-guidance" aria-label="Topologies 使用说明">
      <p>
        <strong>进阶工具</strong> —— 这里用于手工搭建和校验 MPEG-TS 拓扑（节点 + 连线）。主干旅程（Lab 八步闭环）使用
        <strong>场景自带的初始拓扑</strong>，不会读取这里保存的拓扑；拿到第一次 PASS 之后再回来探索不迟。
        <Link className="dvb-topo-guidance-link" to="/lab">[去 Lab →]</Link> <Link className="dvb-topo-guidance-link" to="/">[回主页 →]</Link>
      </p>
    </section>
  );
}

/** §4.5 item 2 — 画布空态三问覆盖层. Shown by the page only while
 * nodes.length === 0; the first dropped node removes it. pointer-events stay
 * off the overlay (the link re-enables them) so drops pass through to the
 * canvas beneath. */
export function CanvasEmptyOverlay() {
  return (
    <div className="dvb-topo-empty-overlay" data-testid="dvb-topo-empty-overlay">
      <p>
        <strong>这是什么</strong>：拓扑画布——搭建 MPEG-TS 链路结构的进阶工具。
        <strong>为什么是空的</strong>：你刚新建了草稿（或拓扑库还是空的），画布上还没有节点。
        <strong>下一步</strong>：从左侧『节点类型』面板拖一个『TS 生成器』进画布开始搭建；或在上方『拓扑』下拉打开已有拓扑。
        也可以跳过这里，直接<Link to="/lab">[去 Lab 开始主干旅程 →]</Link>。
      </p>
    </div>
  );
}

export interface SaveGateNoteProps {
  /** true while a save request is in flight → 正在保存… */
  saving: boolean;
  /** false = nothing to save → 没有待保存的修改 (wins over gate reasons:
   * the save entry itself is inert when not dirty). */
  dirty: boolean;
  /** Honest pending count: incomplete config nodes + validation entries +
   * displayed field errors (derived by the page from computeInspectorGate). */
  pendingCount: number;
  /** The gate's G1/G2/G3 reasons — only present kinds get their line. */
  reasons: GateReason[];
}

/** §4.5 item 3 — 保存 gate 说明区 (next to the save button, always mounted
 * while states apply). States: gate → 暂不能保存：{N} 处待处理 + per-kind
 * lines; 无修改 → 没有待保存的修改; saving → 正在保存…; saveable → NOTHING
 * (零噪音). Replaces the old hover-only title (撤除, hover-only feedback is
 * not honest — invisible on touch). */
export function SaveGateNote({ saving, dirty, pendingCount, reasons }: SaveGateNoteProps) {
  if (saving) {
    return (
      <div className="dvb-topo-gate-note" data-testid="dvb-topo-gate-note">
        正在保存…
      </div>
    );
  }
  if (!dirty) {
    return (
      <div className="dvb-topo-gate-note" data-testid="dvb-topo-gate-note">
        没有待保存的修改
      </div>
    );
  }
  if (reasons.length === 0) return null; // saveable → zero noise
  return (
    <div className="dvb-topo-gate-note" data-testid="dvb-topo-gate-note">
      <p>暂不能保存：{pendingCount} 处待处理</p>
      <ul>
        {reasons.some((reason) => reason.kind === "config_incomplete") && (
          <li>配置待填 → 右侧「节点属性」补全</li>
        )}
        {reasons.some((reason) => reason.kind === "structural_violations") && (
          <li>校验违规 → 见下方「校验」面板</li>
        )}
        {reasons.some((reason) => reason.kind === "field_errors") && <li>表单字段有误</li>}
      </ul>
    </div>
  );
}

/** §4.5 item 4 display half — the one-line inline rejection reason for a
 * failed connection attempt. The 4 s auto-dismiss window restarts for every
 * new rejection (the page remounts via key={attempt}; within one mount a
 * changed rejection string re-arms the timer while `dismissed` resets only on
 * remount — the page contract guarantees that pairing). The preview half
 * (拖拽中非法把手降透明度) is pure CSS over the canvas wrapper's
 * data-connecting hook in topologyEditor.css. */
export function ConnectionHint({ rejection }: { rejection: string | null }) {
  const [dismissed, setDismissed] = useState(false);
  useEffect(() => {
    if (rejection === null) return;
    const timer = window.setTimeout(() => setDismissed(true), CONNECTION_HINT_VISIBLE_MS);
    return () => window.clearTimeout(timer);
  }, [rejection]);
  if (rejection === null || dismissed) return null;
  return (
    <span className="dvb-topo-connection-hint" role="status" data-testid="dvb-topo-connection-hint">
      {rejection}
    </span>
  );
}

/** §4.5 item 5 — 保存成功声明, shown after EVERY successful save (one line):
 * what this module saved is a 已保存拓扑 for THIS module only; Lab 场景使用
 * 场景自带初始拓扑. */
export function SaveSuccessNote({ revision }: { revision: number }) {
  return (
    <p className="dvb-topo-save-note" role="status" data-testid="dvb-topo-save-note">
      已保存为 revision {revision}。（此处保存的拓扑仅供本模块载入与校验；Lab 场景使用场景自带初始拓扑，不会自动使用它。）
    </p>
  );
}
