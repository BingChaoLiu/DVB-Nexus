// Custom canvas node (SPEC-401 §5.1/§7.4): the NodeType registry port
// template renders as visible Handles — Handle id = port_id verbatim, input
// on the left / output on the right (ADR-0009 decision 3; no bidirectional
// ports exist in the MVP registry). Violations light the node body and the
// violated Handle in place (the §7.4 mapping application).
import { Handle, Position } from "@xyflow/react";
import type { NodeProps } from "@xyflow/react";

import type { TopologyPortDTO } from "../../api";
import type { TopologyFlowNode } from "./graphMapping";
import { nodeTypeSpec } from "./nodeTypes";

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
  return (
    <div className={violated ? "dvb-topo-node dvb-topo-node-violation" : "dvb-topo-node"} data-node-id={data.node.node_id}>
      <div className="dvb-topo-node-title">{spec?.label ?? data.node.node_type}</div>
      <div className="dvb-topo-node-type">{data.node.node_type}</div>
      {spec !== undefined && spec.config_schema !== null && (
        <div className="dvb-topo-node-config-hint">{spec.config_schema}</div>
      )}
      {handlesForNode(data.node.ports).map((handle) => {
        const portViolated = data.violationPorts.includes(handle.port_id);
        return (
          <Handle
            key={handle.port_id}
            type={handle.handleType}
            position={handle.position === "right" ? Position.Right : Position.Left}
            id={handle.port_id}
            className={portViolated ? "dvb-topo-handle dvb-topo-handle-violation" : "dvb-topo-handle"}
            data-testid={`dvb-topo-handle-${handle.port_id}`}
          >
            <span className="dvb-topo-handle-label">{handle.port_id}</span>
          </Handle>
        );
      })}
    </div>
  );
}
