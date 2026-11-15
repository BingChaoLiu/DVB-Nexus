// MVP NodeType registry (SPEC-401 §5.1, APPROVED 0.5.0 — the single
// declaration point for node types on the canvas). Components consume this
// declaratively and MUST NOT invent node_type strings: every palette entry,
// default-port generation and wire node_type originates here.
//
// The type set is the #62 approval (recorded on milestone ticket #15, "M5
// SPEC 批准记录 #3"): ts_generator / ts_mux / ts_demux / ts_monitor, no
// bidirectional ports (the ADR-0009 decision-3 open question stays dormant
// for MVP), max_connections always a concrete number ≥ 1 so the client-side
// cardinality precheck is total. Test/example strings seen elsewhere
// (tuner/mux/demux/monitor/generator/gain/muxer/ts_mux) are NOT authoritative.
//
// Downstream consumption: #63 (SPEC-402) follows config_schema for its
// per-node-type field lists; #67 scenario authoring should follow the frozen
// node_type strings for initial_topology payloads.

/** Wire-enumerations mirrored from the generated schema (TopologyPortDTO).
 * Kept as local string-literal unions referencing the same value sets —
 * the generated types stay the single type authority via graphMapping's
 * DTO-typed signatures. */
export type PortDirection = "input" | "output" | "bidirectional";
export type SignalPlane = "RF" | "SEC_CONTROL" | "MPEG_TS" | "T2MI" | "IP";

export interface NodeTypePortSpec {
  /** Unique within the node type; doubles as the React Flow Handle id and
   * the wire port_id (SPEC-401 §5.3 mapping). */
  port_id: string;
  direction: PortDirection;
  plane: SignalPlane;
  /** Registry always pins a concrete number (≥ 1) — no unlimited ports. */
  max_connections: number;
}

export interface NodeTypeSpec {
  /** The authoritative wire string (TopologyNodeDTO.node_type). */
  node_type: string;
  /** node_id semantic-slug prefix for drops: `<prefix>-<n>` (SPEC-401 §7.1). */
  id_prefix: string;
  /** Palette display name (zh). */
  label: string;
  /** Palette hint text. */
  description: string;
  /** Default-port template, deep-copied on drop (REQ-UI-401-004). */
  ports: NodeTypePortSpec[];
  /** #63 field-list pointer; null = config stays opaque {} (SPEC-402). */
  config_schema: "GeneratorConfigDTO" | null;
}

/** Planes enabled for MVP links — mirrors domain.topology.MVP_ENABLED_PLANES
 * (src/domain/topology/model.py); the backend validator stays the authority. */
export const MVP_ENABLED_PLANES: readonly ["MPEG_TS"] = ["MPEG_TS"] as const;

export const MVP_NODE_TYPES: NodeTypeSpec[] = [
  {
    node_type: "ts_generator",
    id_prefix: "gen",
    label: "TS 生成器",
    description: "按 GeneratorConfig 产出 MPEG-TS 码流（八步闭环 Generate 锚）。",
    ports: [{ port_id: "ts_out", direction: "output", plane: "MPEG_TS", max_connections: 1 }],
    config_schema: "GeneratorConfigDTO",
  },
  {
    node_type: "ts_mux",
    id_prefix: "mux",
    label: "TS 复用器",
    description: "多路 TS 输入复用为单路输出（ADR-0005 决策 5 多端口组件）。",
    ports: [
      { port_id: "ts_in_1", direction: "input", plane: "MPEG_TS", max_connections: 1 },
      { port_id: "ts_in_2", direction: "input", plane: "MPEG_TS", max_connections: 1 },
      { port_id: "ts_out", direction: "output", plane: "MPEG_TS", max_connections: 1 },
    ],
    config_schema: null,
  },
  {
    node_type: "ts_demux",
    id_prefix: "demux",
    label: "TS 解复用器",
    description: "将单路 TS 拆分为两路输出（接收侧拆流教学锚）。",
    ports: [
      { port_id: "ts_in", direction: "input", plane: "MPEG_TS", max_connections: 1 },
      { port_id: "ts_out_1", direction: "output", plane: "MPEG_TS", max_connections: 1 },
      { port_id: "ts_out_2", direction: "output", plane: "MPEG_TS", max_connections: 1 },
    ],
    config_schema: null,
  },
  {
    node_type: "ts_monitor",
    id_prefix: "mon",
    label: "TS 监测器",
    description: "被动观测端点（八步 Analyze/Inspect 沉淀端；孤立节点合法 idle）。",
    ports: [{ port_id: "ts_in", direction: "input", plane: "MPEG_TS", max_connections: 1 }],
    config_schema: null,
  },
];

/** Registry lookup by the authoritative node_type string. */
export function nodeTypeSpec(nodeType: string): NodeTypeSpec | undefined {
  return MVP_NODE_TYPES.find((entry) => entry.node_type === nodeType);
}
