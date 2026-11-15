// Node palette (SPEC-401 REQ-UI-401-001): the list is a declarative projection
// of the MVP NodeType registry — this component contains zero node_type
// literals, so the registry stays the single type authority. Drag payload =
// the wire node_type string under a namespaced MIME key (§7.1 drop flow).
import { MVP_NODE_TYPES } from "./nodeTypes";

export const NODE_TYPE_MIME = "application/dvb-nexus-node-type";

export function NodePalette({ onAdd }: { onAdd?: (nodeType: string) => void }) {
  return (
    <aside className="dvb-topo-palette" aria-label="节点面板">
      <h4 className="dvb-topo-palette-title">节点类型（MVP 注册表）</h4>
      {MVP_NODE_TYPES.map((spec) => (
        <button
          key={spec.node_type}
          type="button"
          className="dvb-topo-palette-item"
          data-node-type={spec.node_type}
          draggable
          onClick={() => onAdd?.(spec.node_type)}
          onDragStart={(event) => {
            event.dataTransfer.setData(NODE_TYPE_MIME, spec.node_type);
            event.dataTransfer.effectAllowed = "move";
          }}
          title={spec.description}
        >
          <span className="dvb-topo-palette-label">{spec.label}</span>
          <span className="dvb-topo-palette-type">{spec.node_type}</span>
        </button>
      ))}
    </aside>
  );
}
