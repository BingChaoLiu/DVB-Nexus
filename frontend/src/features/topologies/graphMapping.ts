// Wire ↔ React Flow mapping (SPEC-401 §5.3) — the pure seam between the
// SPEC-202 §4 graph contract (TopologyDTO wire bodies, ADR-0005 decision-5
// four-tuples) and the canvas draft (ADR-0009 decision-4 controlled mode:
// nodes/edges are application state, React Flow only reports change intents).
//
// Handle id = port_id verbatim (SPEC-401 §5.1: no bidirectional ports in the
// MVP registry, so each port renders exactly one Handle). Draft ids are
// deterministic ordinals (`<prefix>-<n>` / `conn-<n>`) so tests and saved
// revisions stay stable. Layout is the ADR-0009 decision-5 deterministic
// topological-order column walk with node_id lexicographic tie-break — the
// same ordering discipline as SPEC-202 §6.2 — and degrades to a sorted grid
// for cyclic (not-yet-adjudicated) graphs, keeping the function total.
import type { Edge, Node } from "@xyflow/react";

import type {
  TopologyConnectionDTO,
  TopologyCreateRequest,
  TopologyDTO,
  TopologyNodeDTO,
  TopologyPortDTO,
} from "../../api/endpoints/topologies";
import { MVP_ENABLED_PLANES, nodeTypeSpec, type SignalPlane } from "./nodeTypes";

export interface TopologyNodeData extends Record<string, unknown> {
  /** The wire body verbatim — toWire reports it back untouched (immutable
   * revision semantics: stored ports are never re-derived from the registry). */
  node: TopologyNodeDTOWithPorts;
  /** Violation codes addressed to this node (incl. via its ports) —
   * populated by the violations mapper for in-place highlight (§7.4). */
  violationCodes: string[];
  /** port_ids carrying port-addressed violations (Handle highlight). */
  violationPorts: string[];
  /** SPEC-401 §Phase3 card status summary (ticket #169): the node's health
   * from the L0 evaluation products (latest state_observed snapshot health —
   * wire enum value verbatim: ok/warn/error/idle). Absent/undefined = no
   * session face wired → no badge renders (idle canvas unchanged). */
  health?: string;
  /** The node's latest state_observed metrics (NodeEvalResult-shaped payload,
   * JSON-safe). The card renders ONLY the registry entry's status_metrics keys
   * out of this map — registry-driven, zero per-type card logic. */
  statusMetrics?: Record<string, unknown>;
}

/** TopologyNodeDTO with ports normalized to a present array (the wire type
 * leaves `nodes`/`ports` optional; the canvas works on the present form). */
type TopologyNodeDTOWithPorts = Omit<TopologyNodeDTO, "ports"> & { ports: TopologyPortDTO[] };

export interface TopologyEdgeData extends Record<string, unknown> {
  connection: TopologyConnectionDTO;
  violation: boolean;
}

export type TopologyFlowNode = Node<TopologyNodeData, "topology">;
export type TopologyFlowEdge = Edge<TopologyEdgeData>;

/** Layout constants — not frozen by the spec (§13); pinned here with tests. */
export const LAYOUT = { X0: 40, Y0: 40, COLUMN_DX: 240, ROW_DY: 120, GRID_COLS: 4 } as const;

// --- wire ↔ flow -------------------------------------------------------------

export function fromWire(topology: TopologyDTO): {
  nodes: TopologyFlowNode[];
  connections: TopologyFlowEdge[];
} {
  const wireNodes = (topology.nodes ?? []).map((n) => ({ ...n, ports: n.ports ?? [] }));
  const wireConnections = topology.connections ?? [];
  const positions = layoutGraph(
    wireNodes.map((n) => n.node_id),
    wireConnections.map((c) => ({ from: c.from_node, to: c.to_node })),
  );
  const nodes: TopologyFlowNode[] = wireNodes.map((n) => ({
    id: n.node_id,
    type: "topology",
    position: positions.get(n.node_id) ?? { x: LAYOUT.X0, y: LAYOUT.Y0 },
    data: { node: n, violationCodes: [], violationPorts: [] },
  }));
  const connections: TopologyFlowEdge[] = wireConnections.map((c) => ({
    id: c.connection_id,
    source: c.from_node,
    sourceHandle: c.from_port,
    target: c.to_node,
    targetHandle: c.to_port,
    data: { connection: c, violation: false },
  }));
  return { nodes, connections };
}

export function toWire(nodes: TopologyFlowNode[], connections: TopologyFlowEdge[]): TopologyCreateRequest {
  return {
    nodes: nodes.map((n) => n.data.node),
    // data is always present on edges we construct (fromWire/connected) — the
    // RF Edge type merely marks it optional.
    connections: connections.map((e) => e.data!.connection),
  };
}

// --- default ports + deterministic draft ids -----------------------------------

/** Deep-copies the registry port template for a drop (REQ-UI-401-004).
 * Mutating the copy must never reach the registry. Unknown types → [] */
export function defaultPortsFor(nodeType: string): TopologyPortDTO[] {
  return (nodeTypeSpec(nodeType)?.ports ?? []).map((p) => ({ ...p }));
}

/** `<prefix>-<n>` with the smallest unused ordinal across the draft. */
export function nextNodeId(nodes: TopologyFlowNode[], prefix: string): string {
  const used = new Set(nodes.map((n) => n.id));
  let n = 0;
  while (used.has(`${prefix}-${n}`)) n += 1;
  return `${prefix}-${n}`;
}

/** `conn-<n>` with the smallest unused ordinal across the draft. */
export function nextConnectionId(connections: TopologyFlowEdge[]): string {
  const used = new Set(connections.map((e) => e.id));
  let n = 0;
  while (used.has(`conn-${n}`)) n += 1;
  return `conn-${n}`;
}

// --- the four UX prechecks (SPEC-401 §7.2; authority stays with the backend) ----

export interface CanConnectInput {
  source: TopologyFlowNode;
  target: TopologyFlowNode;
  sourceHandle: string | null;
  targetHandle: string | null;
  connections: TopologyFlowEdge[];
}

const SOURCE_CAPABLE = new Set(["output", "bidirectional"]);
const TARGET_CAPABLE = new Set(["input", "bidirectional"]);

export function canConnect({ source, target, sourceHandle, targetHandle, connections }: CanConnectInput): boolean {
  if (!sourceHandle || !targetHandle) return false;
  const sourcePort = source.data.node.ports.find((p) => p.port_id === sourceHandle);
  const targetPort = target.data.node.ports.find((p) => p.port_id === targetHandle);
  if (!sourcePort || !targetPort) return false;
  // (1) direction — the ConnectionMode.Strict companion (SPEC-202 §5 rule)
  if (!SOURCE_CAPABLE.has(sourcePort.direction) || !TARGET_CAPABLE.has(targetPort.direction)) return false;
  // (2) self loop = same node AND same port (the SPEC-202 §5 rule verbatim;
  // same-node different-port links stay legal, as in the backend validator)
  if (source.id === target.id && sourceHandle === targetHandle) return false;
  // (3) cardinality per endpoint port (maxConnections; registry pins numbers,
  // but the wire allows null → treat as unlimited for stored legacy rows)
  const endpointCount = (nodeId: string, portId: string) =>
    connections.filter(
      (e) =>
        (e.source === nodeId && e.sourceHandle === portId) ||
        (e.target === nodeId && e.targetHandle === portId),
    ).length;
  const sourceMax = sourcePort.max_connections ?? Number.POSITIVE_INFINITY;
  const targetMax = targetPort.max_connections ?? Number.POSITIVE_INFINITY;
  if (endpointCount(source.id, sourceHandle) + 1 > sourceMax) return false;
  if (endpointCount(target.id, targetHandle) + 1 > targetMax) return false;
  // (4) single plane (REQ-UI-401-005): endpoints must agree and sit inside
  // MVP_ENABLED_PLANES — the frontend leg of the double-layer rejection.
  if (sourcePort.plane !== targetPort.plane) return false;
  if (!(MVP_ENABLED_PLANES as readonly SignalPlane[]).includes(sourcePort.plane)) return false;
  return true;
}

// --- §7.6 connection-rejection reasons (SPEC-408 §4.5 item 4 / §7.6) -----------
//
// A parallel PURE mapping over the same four prechecks: canConnect keeps its
// boolean signature and behavior untouched; explainConnection only LABELS the
// first failed check with its spec reason line. The two stay consistent by
// construction (same checks, same order) and by a cross-invariant test
// (explainConnection === null ⟺ canConnect === true). Unknown/missing handles
// have no §7.6 enumeration → null (silence), the same defensive posture
// canConnect takes.

const DIRECTION_REASON = "方向不符（需 输出/双向 → 输入/双向）";
const SELF_LOOP_REASON = "不能连回同一端口";
// SPEC-401 §Phase3: the enabled-plane line mirrors MVP_ENABLED_PLANES
// (readonly ["MPEG_TS","T2MI","RF","SEC_CONTROL"] — the #160 domain frozenset,
// 同源纪律).
const PLANE_REASON = "平面不符（当前支持 MPEG_TS / T2MI / RF / SEC_CONTROL）";

/** The one-line reason for the first failed precheck (§7.6 verbatim), or null
 * when the connection passes all four. Cardinality names the FULL port and
 * its registry limit; the source endpoint is reported first, matching the
 * canConnect check order. */
export function explainConnection({
  source,
  target,
  sourceHandle,
  targetHandle,
  connections,
}: CanConnectInput): string | null {
  if (!sourceHandle || !targetHandle) return null;
  const sourcePort = source.data.node.ports.find((p) => p.port_id === sourceHandle);
  const targetPort = target.data.node.ports.find((p) => p.port_id === targetHandle);
  if (!sourcePort || !targetPort) return null;
  // (1) direction — the ConnectionMode.Strict companion (SPEC-202 §5 rule)
  if (!SOURCE_CAPABLE.has(sourcePort.direction) || !TARGET_CAPABLE.has(targetPort.direction)) {
    return DIRECTION_REASON;
  }
  // (2) self loop = same node AND same port (SPEC-202 §5, canConnect order)
  if (source.id === target.id && sourceHandle === targetHandle) return SELF_LOOP_REASON;
  // (3) cardinality — same counting as canConnect
  const endpointCount = (nodeId: string, portId: string) =>
    connections.filter(
      (e) =>
        (e.source === nodeId && e.sourceHandle === portId) ||
        (e.target === nodeId && e.targetHandle === portId),
    ).length;
  const sourceMax = sourcePort.max_connections ?? Number.POSITIVE_INFINITY;
  const targetMax = targetPort.max_connections ?? Number.POSITIVE_INFINITY;
  if (endpointCount(source.id, sourceHandle) + 1 > sourceMax) {
    return `“${sourceHandle}”连接数已满（上限 ${sourceMax}）`;
  }
  if (endpointCount(target.id, targetHandle) + 1 > targetMax) {
    return `“${targetHandle}”连接数已满（上限 ${targetMax}）`;
  }
  // (4) single plane — mismatch OR non-enabled plane share one §7.6 line
  if (sourcePort.plane !== targetPort.plane) return PLANE_REASON;
  if (!(MVP_ENABLED_PLANES as readonly SignalPlane[]).includes(sourcePort.plane)) return PLANE_REASON;
  return null;
}

// --- deterministic layout (ADR-0009 decision 5) ----------------------------------

export interface LayoutLink {
  from: string;
  to: string;
}

/** Column = longest-path depth over the link set; peers share a column sorted
 * by node_id lexicographically (SPEC-202 §6.2 tie-break discipline). Cyclic
 * graphs degrade to a node_id grid — the function is total so the canvas can
 * render stored graphs awaiting the backend cycle adjudication (§7.4). */
export function layoutGraph(nodeIds: string[], links: LayoutLink[]): Map<string, { x: number; y: number }> {
  const known = new Set(nodeIds);
  const incoming = new Map<string, string[]>(nodeIds.map((id) => [id, []]));
  for (const link of links) {
    if (known.has(link.from) && known.has(link.to)) {
      incoming.get(link.to)!.push(link.from);
    }
  }

  const depth = new Map<string, number>();
  const visiting = new Set<string>();
  let cyclic = false;
  const depthOf = (id: string): number => {
    const memo = depth.get(id);
    if (memo !== undefined) return memo;
    if (visiting.has(id)) {
      cyclic = true;
      return 0;
    }
    visiting.add(id);
    const parents = incoming.get(id)!;
    const d = parents.length === 0 ? 0 : 1 + Math.max(...parents.map(depthOf));
    visiting.delete(id);
    depth.set(id, d);
    return d;
  };
  for (const id of nodeIds) depthOf(id);

  const positions = new Map<string, { x: number; y: number }>();
  if (cyclic) {
    const sorted = [...nodeIds].sort();
    sorted.forEach((id, i) => {
      positions.set(id, {
        x: LAYOUT.X0 + (i % LAYOUT.GRID_COLS) * LAYOUT.COLUMN_DX,
        y: LAYOUT.Y0 + Math.floor(i / LAYOUT.GRID_COLS) * LAYOUT.ROW_DY,
      });
    });
    return positions;
  }

  const byColumn = new Map<number, string[]>();
  for (const id of [...nodeIds].sort()) {
    const column = depthOf(id);
    const bucket = byColumn.get(column);
    if (bucket) {
      bucket.push(id);
    } else {
      byColumn.set(column, [id]);
    }
  }
  for (const [column, ids] of byColumn) {
    ids.forEach((id, row) => {
      positions.set(id, {
        x: LAYOUT.X0 + column * LAYOUT.COLUMN_DX,
        y: LAYOUT.Y0 + row * LAYOUT.ROW_DY,
      });
    });
  }
  return positions;
}
