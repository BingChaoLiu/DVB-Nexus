// Node detail panel (SPEC-404 §Phase3 节点详情面板, ticket #169): clicking an
// RF/SEC canvas node opens the state snapshot face — the node's LATEST
// state_observed payload rendered as a FULL generic metrics list (every wire
// key, no skeuomorphic controls, no invented units) + the CauseRef chain with
// canvas-locate jumps. Data arrives via props (the page owns the SPEC-305
// §Phase3 query face + the page-level useSessionStream subscription — zero new
// data channels); the panel narrows client-side by node_id (the events
// endpoint carries no node_id param — the §5 whitelist stays frozen).
//
// Honesty posture: health/source/confidence render the wire values verbatim
// (state_evaluator/simulated stay simulated — never relabeled parsed/measured);
// a missing snapshot is 缺失 ≠ 零, never a clean state; causes without wiring
// render without a jump control instead of a dead button.
import type { StateObservedSnapshot } from "./nodeStateSummary";
import { latestSnapshotFor, renderMetricValue, STATE_OBSERVED_ENVELOPE_KEYS } from "./nodeStateSummary";
import { isStateDomainNodeType } from "../nodeTypes";
import "./inspector.css";

/** The selected-canvas-node reference the panel consumes. */
export interface StateDomainNodeRef {
  node_id: string;
  node_type: string;
}

interface CauseRef {
  node_id: string;
  port_id?: string;
}

function causeList(value: unknown): CauseRef[] {
  if (!Array.isArray(value)) return [];
  return value.filter(
    (entry): entry is CauseRef =>
      typeof entry === "object" && entry !== null && typeof (entry as CauseRef).node_id === "string",
  );
}

export function NodeStateDetailPanel({
  sessionId,
  node,
  snapshots,
  onLocate,
}: {
  sessionId: string | null;
  node: StateDomainNodeRef | null;
  snapshots: readonly StateObservedSnapshot[];
  onLocate?: (nodeId: string) => void;
}) {
  let body: React.ReactNode;
  if (sessionId === null) {
    body = (
      <p className="dvb-state-note" data-testid="dvb-state-panel-empty">
        未携带 session 深链——节点详情面板需要 ?session=&lt;id&gt; 才有状态快照可读（缺失 ≠ 零）。
      </p>
    );
  } else if (node === null) {
    body = (
      <p className="dvb-state-note" data-testid="dvb-state-panel-empty">
        未选中节点：点击画布 RF/SEC 节点查看其 state_observed 快照与因果链。
      </p>
    );
  } else if (!isStateDomainNodeType(node.node_type)) {
    body = (
      <p className="dvb-state-note" data-testid="dvb-state-panel-empty">
        非状态域节点（{node.node_type} 无 state_observed 快照——TS/T2MI 域走码流证据面）。
      </p>
    );
  } else {
    const latest = latestSnapshotFor(snapshots, node.node_id);
    if (latest === undefined) {
      body = (
        <p className="dvb-state-note" data-testid="dvb-state-panel-empty">
          尚无 state_observed 快照（缺失 ≠ 零）——跑一个状态域 Run 后此处呈现 L0 求值产物。
        </p>
      );
    } else {
      const { payload } = latest;
      const health = typeof payload.health === "string" ? payload.health : null;
      const source = typeof payload.source === "string" ? payload.source : null;
      const confidence = typeof payload.confidence === "string" ? payload.confidence : null;
      const causes = causeList(payload.causes);
      const metrics = Object.entries(payload).filter(([key]) => !STATE_OBSERVED_ENVELOPE_KEYS.includes(key));
      body = (
        <>
          <p className="dvb-state-head">
            <span className="dvb-state-node-id">{node.node_id}</span>
            <span className="dvb-state-node-type">{node.node_type}</span>
            {health !== null && (
              <span className="dvb-state-health" data-testid="dvb-state-panel-health" data-health={health}>
                {health}
              </span>
            )}
          </p>
          {(source !== null || confidence !== null) && (
            <p className="dvb-state-honesty" data-testid="dvb-state-panel-honesty">
              {source !== null && <span>source: {source}</span>}
              {confidence !== null && <span>confidence: {confidence}</span>}
            </p>
          )}
          <ul className="dvb-state-metrics">
            {metrics.map(([key, value]) => (
              <li key={key} className="dvb-state-metric" data-testid={`dvb-state-panel-metric-${key}`}>
                <span className="dvb-state-metric-key">{key}</span>
                <span className="dvb-state-metric-value">{renderMetricValue(value)}</span>
              </li>
            ))}
          </ul>
          <div className="dvb-state-causes" data-testid="dvb-state-panel-causes">
            <h5 className="dvb-state-causes-title">CauseRef 因果链</h5>
            {causes.length === 0 ? (
              <p className="dvb-state-note">无 CauseRef 记录（上游链路正常或未产生异常传播）。</p>
            ) : (
              <ul className="dvb-state-cause-list">
                {causes.map((cause, index) => (
                  <li key={`${cause.node_id}:${cause.port_id ?? ""}:${index}`} className="dvb-state-cause" data-testid={`dvb-state-panel-cause-${index}`}>
                    <span className="dvb-state-cause-node">{cause.node_id}</span>
                    {cause.port_id !== undefined && <span className="dvb-state-cause-port">{cause.port_id}</span>}
                    {onLocate !== undefined && (
                      <button
                        type="button"
                        className="dvb-state-locate"
                        data-testid={`dvb-state-panel-locate-${index}`}
                        onClick={() => onLocate(cause.node_id)}
                      >
                        定位
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      );
    }
  }
  return (
    <section className="dvb-state-panel" aria-label="节点状态详情" data-testid="dvb-state-panel">
      <h4 className="dvb-state-title">节点状态详情</h4>
      {body}
    </section>
  );
}
