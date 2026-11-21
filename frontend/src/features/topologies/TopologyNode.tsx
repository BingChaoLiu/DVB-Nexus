// Custom canvas node (SPEC-401 §5.1/§7.4): the NodeType registry port
// template renders as visible Handles — Handle id = port_id verbatim, input
// on the left / output on the right (ADR-0009 decision 3; no bidirectional
// ports exist in the MVP registry). Violations light the node body and the
// violated Handle in place (the §7.4 mapping application). During a
// connection drag the page hands the §7.6 illegal-end preview set down
// through IllegalEndHandlesContext (review-fix F2: per-handle dimming for
// direction/cardinality/plane/self-loop) — a handle in the set carries
// dvb-topo-handle-illegal-end; outside a drag the context is empty and no
// class is ever applied.
import { useContext } from "react";
import { Handle, Position } from "@xyflow/react";
import type { NodeProps } from "@xyflow/react";

import type { TopologyPortDTO } from "../../api";
import { IllegalEndHandlesContext, illegalHandleKey } from "./connectionFeedback";
import type { TopologyFlowNode } from "./graphMapping";
import { nodeTypeSpec } from "./nodeTypes";
import { renderMetricValue } from "./inspector/nodeStateSummary";

export interface RenderedHandle {
  port_id: string;
  direction: string;
  plane: string;
  max_connections: number;
  handleType: "source" | "target";
  position: "left" | "right";
}

/** Pure geometry mapping (SPEC-401 §5.1): template port → Handle type/position.
 * bidirectional would render target/left (source-capable in prechecks); the
 * MVP registry contains none (ADR-0009 decision-3 open question dormant). */
export function handlesForNode(ports: TopologyPortDTO[]): RenderedHandle[] {
  return ports.map((port) => ({
    port_id: port.port_id,
    direction: port.direction,
    plane: port.plane,
    max_connections: port.max_connections ?? 0,
    handleType: port.direction === "output" || port.direction === "bidirectional" ? "source" : "target",
    position: port.direction === "output" ? "right" : "left",
  }));
}

export function TopologyNode({ data }: NodeProps<TopologyFlowNode>) {
  const spec = nodeTypeSpec(data.node.node_type);
  const violated = data.violationCodes.length > 0;
  // §7.6 illegal-end preview (review-fix F2): empty outside a drag — the
  // idle canvas never dims a handle through this path.
  const illegalEnds = useContext(IllegalEndHandlesContext);
  // §Phase3 card status summary (ticket #169): registry-driven — the rendered
  // keys are exactly the entry's status_metrics list, sourced from the merged
  // state_observed fact set the page hands down. Types without the registry
  // list (and any node without status data) render nothing here.
  const statusMetrics = data.statusMetrics;
  const summaryEntries =
    spec?.status_metrics !== undefined && statusMetrics !== undefined
      ? spec.status_metrics
          .filter((key) => key in statusMetrics)
          .map((key) => [key, statusMetrics[key]] as const)
      : [];
  const hasStatus = spec?.status_metrics !== undefined && (data.health !== undefined || summaryEntries.length > 0);
  return (
    <div className={violated ? "dvb-topo-node dvb-topo-node-violation" : "dvb-topo-node"} data-node-id={data.node.node_id}>
      <div className="dvb-topo-node-title">{spec?.label ?? data.node.node_type}</div>
      <div className="dvb-topo-node-type">{data.node.node_type}</div>
      {spec !== undefined && spec.config_schema !== null && (
        <div className="dvb-topo-node-config-hint">{spec.config_schema}</div>
      )}
      {hasStatus && (
        <div className="dvb-topo-node-status">
          {data.health !== undefined && (
            <span className="dvb-topo-node-health" data-testid="dvb-topo-node-health" data-health={data.health}>
              {data.health}
            </span>
          )}
          {summaryEntries.map(([key, value]) => (
            <span key={key} className="dvb-topo-node-metric" data-testid={`dvb-topo-node-metric-${key}`}>
              <span className="dvb-topo-node-metric-key">{key}</span>
              <span className="dvb-topo-node-metric-value">{renderMetricValue(value)}</span>
            </span>
          ))}
        </div>
      )}
      {handlesForNode(data.node.ports).map((handle) => {
        const portViolated = data.violationPorts.includes(handle.port_id);
        const illegalEnd = illegalEnds.has(illegalHandleKey(data.node.node_id, handle.port_id));
        const className = portViolated
          ? "dvb-topo-handle dvb-topo-handle-violation"
          : illegalEnd
            ? "dvb-topo-handle dvb-topo-handle-illegal-end"
            : "dvb-topo-handle";
        return (
          <Handle
            key={handle.port_id}
            type={handle.handleType}
            position={handle.position === "right" ? Position.Right : Position.Left}
            id={handle.port_id}
            className={className}
            data-testid={`dvb-topo-handle-${handle.port_id}`}
          >
            <span className="dvb-topo-handle-label">{handle.port_id}</span>
          </Handle>
        );
      })}
    </div>
  );
}
