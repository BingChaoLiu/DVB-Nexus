// initial_topology readability seam (SPEC-408 §4.4 REQ-UI-408-012 部分 /
// AC-408-07): pure functions turning the scenario document's camelCase
// initial-topology island into human-readable rows. Layout translation ONLY:
// labels are Chinese, but key names and VALUES stay authored-verbatim — no
// key-name semantic translation, no SVG thumbnail. The raw document remains
// available line-by-line (键名原样, the #45 canonical-example authority) for
// the verbatim fold-back <details>.
//
// Any unexpected shape answers null — the caller then shows the raw document
// alone (honest fallback, no invented structure).

export interface InitialTopologyPortSummary {
  portId: string;
  direction: string;
  plane: string;
  maxConnections: number;
  /** 「端口 {portId} · 方向 {direction} · 平面 {plane} · 连接上限 {maxConnections}」 */
  line: string;
}

export interface InitialTopologyNodeSummary {
  nodeId: string;
  nodeType: string;
  /** 「节点 {nodeId}（{nodeType}）」 */
  line: string;
  ports: InitialTopologyPortSummary[];
}

export interface InitialTopologyConnectionSummary {
  connectionId: string;
  /** 「连接 {connectionId}：{fromNodeId}:{fromPortId} → {toNodeId}:{toPortId}」 */
  line: string;
}

export interface InitialTopologySummary {
  /** 「N 节点 · M 连接 · topology_id {id}/revision {rev}」 */
  statsLine: string;
  topologyId: string;
  revision: number;
  nodes: InitialTopologyNodeSummary[];
  connections: InitialTopologyConnectionSummary[];
  /** Raw authored rows in document order: 「{key} {value}」 pairs — 键名原样. */
  rawLines: string[];
}

function asString(value: unknown): string {
  return typeof value === "string" ? value : String(value ?? "");
}

export function summarizeInitialTopology(raw: unknown): InitialTopologySummary | null {
  if (typeof raw !== "object" || raw === null) return null;
  const record = raw as Record<string, unknown>;
  const topologyId = record.topology_id;
  const revision = record.revision;
  const nodesRaw = record.nodes;
  const connectionsRaw = record.connections;
  if (typeof topologyId !== "string" || typeof revision !== "number") return null;
  if (!Array.isArray(nodesRaw) || (connectionsRaw !== undefined && !Array.isArray(connectionsRaw))) return null;

  const nodes: InitialTopologyNodeSummary[] = [];
  const rawLines: string[] = [];
  for (const nodeRaw of nodesRaw) {
    if (typeof nodeRaw !== "object" || nodeRaw === null) return null;
    const node = nodeRaw as Record<string, unknown>;
    const nodeId = node.nodeId;
    const nodeType = node.nodeType;
    if (typeof nodeId !== "string" || typeof nodeType !== "string") return null;
    rawLines.push(`nodeId ${nodeId}`, `nodeType ${nodeType}`);

    const ports: InitialTopologyPortSummary[] = [];
    const portsRaw = Array.isArray(node.ports) ? node.ports : [];
    for (const portRaw of portsRaw) {
      if (typeof portRaw !== "object" || portRaw === null) return null;
      const port = portRaw as Record<string, unknown>;
      const portId = port.portId;
      if (typeof portId !== "string") return null;
      const direction = asString(port.direction);
      const plane = asString(port.plane);
      const maxConnections = typeof port.maxConnections === "number" ? port.maxConnections : 0;
      ports.push({
        portId,
        direction,
        plane,
        maxConnections,
        line: `端口 ${portId} · 方向 ${direction} · 平面 ${plane} · 连接上限 ${maxConnections}`,
      });
      rawLines.push(
        `portId ${portId}`,
        `direction ${direction}`,
        `plane ${plane}`,
        `maxConnections ${maxConnections}`,
      );
    }
    nodes.push({ nodeId, nodeType, line: `节点 ${nodeId}（${nodeType}）`, ports });
  }

  const connections: InitialTopologyConnectionSummary[] = [];
  for (const connectionRaw of Array.isArray(connectionsRaw) ? connectionsRaw : []) {
    if (typeof connectionRaw !== "object" || connectionRaw === null) return null;
    const connection = connectionRaw as Record<string, unknown>;
    const connectionId = connection.connectionId;
    const from = connection.from;
    const to = connection.to;
    if (
      typeof connectionId !== "string" ||
      typeof from !== "object" ||
      from === null ||
      typeof to !== "object" ||
      to === null
    ) {
      return null;
    }
    const fromNode = (from as Record<string, unknown>).nodeId;
    const fromPort = (from as Record<string, unknown>).portId;
    const toNode = (to as Record<string, unknown>).nodeId;
    const toPort = (to as Record<string, unknown>).portId;
    if (
      typeof fromNode !== "string" ||
      typeof fromPort !== "string" ||
      typeof toNode !== "string" ||
      typeof toPort !== "string"
    ) {
      return null;
    }
    connections.push({
      connectionId,
      line: `连接 ${connectionId}：${fromNode}:${fromPort} → ${toNode}:${toPort}`,
    });
    rawLines.push(`connectionId ${connectionId}`, `from ${fromNode}/${fromPort}`, `to ${toNode}/${toPort}`);
  }

  return {
    statsLine: `${nodes.length} 节点 · ${connections.length} 连接 · topology_id ${topologyId}/revision ${revision}`,
    topologyId,
    revision,
    nodes,
    connections,
    rawLines,
  };
}
