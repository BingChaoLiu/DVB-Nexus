// NodeType registry (SPEC-401 §5.1 + §Phase2 修订章, APPROVED 0.5.2 — the
// single declaration point for node types on the canvas). Components consume
// this declaratively and MUST NOT invent node_type strings: every palette
// entry, default-port generation and wire node_type originates here.
//
// The MVP type set is the #62 approval (recorded on milestone ticket #15, "M5
// SPEC 批准记录 #3"): ts_generator / ts_mux / ts_demux / ts_monitor. The Phase
// 2 set adds t2mi_encapsulator / t2mi_demux (SPEC-401 §Phase2 table, the #110
// 细裁; backend mirror = src/domain/topology/node_types.py #121 — labels,
// id prefixes and port templates are verbatim-identical across both sides).
// No bidirectional ports (the ADR-0009 decision-3 open question stays dormant
// for MVP), max_connections always a concrete number ≥ 1 so the client-side
// cardinality precheck is total. Test/example strings seen elsewhere
// (tuner/mux/demux/monitor/generator/gain/muxer/ts_mux) are NOT authoritative.
//
// Downstream consumption: #63 (SPEC-402) follows config_schema for its
// per-node-type field lists — the Phase 2 lists are exported below (hand
// written to the #121 backend config schemas because no generated wire DTO
// exists yet; the fieldInventory lookup consumes them by schema name).
// #67 scenario authoring should follow the frozen node_type strings for
// initial_topology payloads.
import type { FieldDescriptor } from "./inspector/fieldInventory";

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
  /** #63 field-list pointer; null = config stays opaque {} (SPEC-402).
   * Phase 2 extends the pointer set per the SPEC-401 §Phase2 table; the
   * matching field lists are exported below. */
  config_schema: "GeneratorConfigDTO" | "T2miEncapsulatorConfigDTO" | "T2miDemuxConfigDTO" | null;
}

/** Planes enabled for MVP links — mirrors domain.topology.MVP_ENABLED_PLANES
 * (src/domain/topology/model.py, the #121 REPORT §7 final state
 * frozenset({MPEG_TS, T2MI})); the backend validator stays the authority. */
export const MVP_ENABLED_PLANES: readonly ["MPEG_TS", "T2MI"] = ["MPEG_TS", "T2MI"] as const;

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
  // --- Phase 2 (SPEC-401 §Phase2 修订章；label/description 用 CONTEXT.md
  // 「Phase 2 封装层」词条口径——BBFrame 只是节点内部层次，不是独立信号平面) ---
  {
    node_type: "t2mi_encapsulator",
    id_prefix: "enc",
    label: "T2-MI 封装器",
    description: "把 Inner TS 经 BBFrame 封装段包化为 T2-MI 包流（in MPEG_TS / out T2MI）；BBFrame 参数与 PLP 分配表在其 config。",
    ports: [
      { port_id: "inner_in", direction: "input", plane: "MPEG_TS", max_connections: 1 },
      { port_id: "t2mi_out", direction: "output", plane: "T2MI", max_connections: 1 },
    ],
    config_schema: "T2miEncapsulatorConfigDTO",
  },
  {
    node_type: "t2mi_demux",
    id_prefix: "dmx",
    label: "T2-MI 解封装器",
    description: "T2-MI 包流 → BBFrame 解析 → Inner TS 重建的观测侧链（in T2MI / out MPEG_TS）；期望 PLP 过滤在其 config。",
    ports: [
      { port_id: "t2mi_in", direction: "input", plane: "T2MI", max_connections: 1 },
      { port_id: "inner_out", direction: "output", plane: "MPEG_TS", max_connections: 1 },
    ],
    config_schema: "T2miDemuxConfigDTO",
  },
];

/** Registry lookup by the authoritative node_type string. */
export function nodeTypeSpec(nodeType: string): NodeTypeSpec | undefined {
  return MVP_NODE_TYPES.find((entry) => entry.node_type === nodeType);
}

// --- Phase 2 #63 field lists (SPEC-402 §5.1 mechanism consumes by name) --------
//
// Hand-written to the backend config schemas (domain.topology.node_types #121,
// wire snake_case) because these configs are still opaque dicts on the wire —
// no generated DTO exists in schema.gen.ts yet (#129 did not land node config
// DTOs). Constraints appear ONLY as hint text (presentation, never
// client-side enforcement — SPEC-402 §2.2; the backend validate stays the
// authority). Key discipline: these lists must never contradict the backend
// schema they mirror.

/** T2miEncapsulatorConfigDTO = plp_assignment + bbframe_params (#121 REPORT
 * §3; SPEC-602 §5 分配表 / SPEC-601 §5 封装参数). */
export const T2MI_ENCAPSULATOR_FIELD_INVENTORY: FieldDescriptor[] = [
  {
    path: "plp_assignment",
    kind: "group",
    required: true,
    label: "plp_assignment（PLP 分配表）",
    hint: "entries 至少 1 行；重复 source_tag / plp_id 由后端拒绝（SPEC-602 §8 分配表冲突）",
    children: [
      {
        path: "plp_assignment.entries",
        kind: "rows",
        required: true,
        label: "entries（业务源 → PLP）",
        hint: "至少 1 行（SPEC-602 §5 min 1，存在性归后端）；plp_id 表内不得重复",
        rowFields: [
          {
            path: "plp_assignment.entries[].plp_id",
            kind: "number",
            required: true,
            label: "plp_id",
            hint: "0..255（8-bit PLP_ID 值域；越界后端拒绝）",
          },
          {
            path: "plp_assignment.entries[].source_tag",
            kind: "text",
            required: true,
            label: "source_tag",
            hint: "非空业务源标签；同表内不得重复（后端拒绝）",
          },
        ],
      },
    ],
  },
  {
    path: "bbframe_params",
    kind: "group",
    required: true,
    label: "bbframe_params（BBFrame 封装参数）",
    hint: "SPEC-601 §5 五键；值域为字段宽钉扎，语义随 golden 渐进钉扎（#123）",
    children: [
      { path: "bbframe_params.matype_value", kind: "number", required: true, label: "matype_value", hint: "0..0xFFFF（MATYPE 16-bit 字段宽）" },
      { path: "bbframe_params.upl", kind: "number", required: true, label: "upl", hint: "≥ 1（UPL 用户包长度，单位 bit；188 字节 UP = 1504）" },
      { path: "bbframe_params.n_ups", kind: "number", required: true, label: "n_ups", hint: "≥ 1（单 BBFrame 携带的 UP 数 N_UPS）" },
      { path: "bbframe_params.issy_mode", kind: "text", required: true, label: "issy_mode", hint: "非空（ISSY 模式词表随 golden 渐进钉扎，#123）" },
      { path: "bbframe_params.npd_enabled", kind: "checkbox", required: true, label: "npd_enabled", hint: "NPD（空包删除）插入开关（bool）" },
    ],
  },
];

/** T2miDemuxConfigDTO = plp_filter + strict_crc (#121 REPORT §3; SPEC-602 §5
 * 过滤器 / SPEC-600 §5 demux config——plp_filter.mode 承载 plp_mode 语义). */
export const T2MI_DEMUX_FIELD_INVENTORY: FieldDescriptor[] = [
  {
    path: "plp_filter",
    kind: "group",
    required: true,
    label: "plp_filter（期望 PLP 过滤）",
    hint: "mode = expected 时必须携带 expected_plp（SPEC-602 §5 交叉约束，后端权威）",
    children: [
      {
        path: "plp_filter.mode",
        kind: "select",
        required: true,
        label: "mode",
        hint: "expected = 按 expected_plp 过滤；all = 全部通过",
        options: ["expected", "all"],
      },
      {
        path: "plp_filter.expected_plp",
        kind: "number",
        required: false,
        label: "expected_plp",
        hint: "mode=expected 时必填（0..255）；mode=all 时留空",
      },
    ],
  },
  { path: "strict_crc", kind: "checkbox", required: false, wireDefault: true, label: "strict_crc", hint: "CRC-32 严格校验（wire 默认 true，SPEC-600 §5）" },
];
