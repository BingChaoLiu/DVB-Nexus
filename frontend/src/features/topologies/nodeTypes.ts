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
   * Phase 2 extends the pointer set per the SPEC-401 §Phase2 table and Phase 3
   * (SPEC-401 §Phase3, #169) adds the #160 config DTO pointers; the matching
   * field lists are exported below. */
  config_schema:
    | "GeneratorConfigDTO"
    | "T2miEncapsulatorConfigDTO"
    | "T2miDemuxConfigDTO"
    | "LnbConfigDTO"
    | "TunerConfigDTO"
    | "SwitchConfigDTO"
    | null;
  /** SPEC-401 §Phase3 card status-summary keys (health badge + key metrics):
   * the card renders exactly these keys from the node's latest state_observed
   * snapshot — registry-declared, zero per-type card logic. Absent on the
   * pre-Phase3 types (no status summary section renders). */
  status_metrics?: readonly string[];
}

/** Planes enabled for links — mirrors domain.topology.MVP_ENABLED_PLANES
 * (src/domain/topology/model.py; #160 expanded the frozenset to the Phase 3
 * set {MPEG_TS, T2MI, RF, SEC_CONTROL}, mirrored here per SPEC-401 §Phase3);
 * the backend validator stays the authority. */
export const MVP_ENABLED_PLANES: readonly ["MPEG_TS", "T2MI", "RF", "SEC_CONTROL"] = [
  "MPEG_TS",
  "T2MI",
  "RF",
  "SEC_CONTROL",
] as const;

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
  // --- Phase 3 (SPEC-401 §Phase3 修订章 + ADR-0012；labels/id_prefixes/端口
  // 模板与 #160 后端 PHASE3_NODE_TYPES 逐字一致——lnb coax_out max=2 承载
  // A1 双 tuner 共享同轴 1:N 扇出，机制零扩展；「至多一条 DC 通路」=
  // switch coax_in max=1) ---
  {
    node_type: "lnb",
    id_prefix: "lnb",
    label: "LNB",
    description: "低噪声下变频器（SEC_CONTROL 域）：供电/tone/band 求值在其 config（SPEC-621）；coax_out 1:N 扇出共享同轴。",
    ports: [{ port_id: "coax_out", direction: "output", plane: "SEC_CONTROL", max_connections: 2 }],
    config_schema: "LnbConfigDTO",
    status_metrics: ["voltage", "tone_actual", "band_selected"],
  },
  {
    node_type: "tuner",
    id_prefix: "tuner",
    label: "卫星调谐器",
    description: "卫星调谐器（SEC_CONTROL 域）：锁定四分支与 ber_state 档位在其 config（SPEC-620）；rf_in 消费上游 L0 快照。",
    ports: [{ port_id: "rf_in", direction: "input", plane: "SEC_CONTROL", max_connections: 1 }],
    config_schema: "TunerConfigDTO",
    status_metrics: ["lock_state", "ber_state"],
  },
  {
    node_type: "diseqc_switch",
    id_prefix: "sw",
    label: "DiSEqC 开关",
    description: "DiSEqC 开关（SEC_CONTROL 域）：命令寄存器终态与 port_selected 派生在其 config（SPEC-622）；coax_in 承载至多一条 DC 通路。",
    ports: [
      { port_id: "coax_in", direction: "input", plane: "SEC_CONTROL", max_connections: 1 },
      { port_id: "coax_out", direction: "output", plane: "SEC_CONTROL", max_connections: 4 },
    ],
    config_schema: "SwitchConfigDTO",
    status_metrics: ["port_selected"],
  },
];

// --- Phase 3 state-domain faces (SPEC-404 §Phase3; registry-derived) ----------

/** The state_observed event types (SPEC-303 §Phase3 wire strings; the #164
 * registration + payloadKeys.gen.ts mirror is the same-source authority).
 * Consumed by the node detail panel's query (namespace rf/sec face). */
export const STATE_OBSERVED_EVENT_TYPES = ["rf.state_observed", "sec.state_observed"] as const;

/** The query namespaces for the state_observed snapshot read path
 * (SPEC-305 §Phase3 query face; the values are registry prefix families). */
export const STATE_OBSERVED_NAMESPACES = ["rf", "sec"] as const;

/** Node types whose ports live on an RF/SEC_CONTROL plane — derived from the
 * registry (never hand-listed), so a future state-domain type joins the set by
 * declaring its planes. SPEC-404 §Phase3: clicking one of these opens the node
 * detail panel. */
export const STATE_DOMAIN_NODE_TYPES: readonly string[] = MVP_NODE_TYPES.filter((entry) =>
  entry.ports.some((port) => port.plane === "RF" || port.plane === "SEC_CONTROL"),
).map((entry) => entry.node_type);

/** Registry-driven state-domain check for one node_type string. */
export function isStateDomainNodeType(nodeType: string): boolean {
  return STATE_DOMAIN_NODE_TYPES.includes(nodeType);
}

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

// --- Phase 3 #169 field lists (hand-written to the #160 backend config DTOs) ---
//
// Same discipline as the Phase 2 lists above: the backend config schemas
// (domain.topology.node_types #160 — LnbConfigDTO / TunerConfigDTO /
// SwitchConfigDTO, wire snake_case) are the authority; constraints surface as
// hint text ONLY (never client-side enforcement). The form mechanism renders
// groups/scalars/rows at one nesting level — the tuner's two-level
// `target_register` object rides dotted paths (NodeInspector's group
// serializer nests dotted child paths; see the #169 REPORT deviation note).

/** LnbConfigDTO = lnb_kind + lo_frequencies + scr? (SPEC-621 §5; scr structure
 * = SPEC-623 §5 ScrConfigDTO). */
export const LNB_FIELD_INVENTORY: FieldDescriptor[] = [
  {
    path: "lnb_kind",
    kind: "select",
    required: true,
    label: "lnb_kind",
    hint: "universal | legacy_cascade（SPEC-621 §5）；legacy_cascade 不得携带 scr 子段（SPEC-621 §8 prepare 拒绝）",
    options: ["universal", "legacy_cascade"],
  },
  {
    path: "lo_frequencies",
    kind: "group",
    required: true,
    label: "lo_frequencies（本振频率计划）",
    hint: "universal 参考 default {9750, 10600}（kHz）——参考值不落 wire 默认，缺填即后端拒绝（SPEC-621 §5/§8）",
    children: [
      { path: "lo_frequencies.low_khz", kind: "number", required: true, label: "low_khz", hint: "≥ 1（kHz；universal 低本振参考 9750）" },
      { path: "lo_frequencies.high_khz", kind: "number", required: true, label: "high_khz", hint: "≥ 1（kHz；universal 高本振参考 10600）" },
    ],
  },
  {
    path: "scr",
    kind: "group",
    required: false,
    label: "scr（SCR/Unicable 子段，可选）",
    hint: "结构归 SPEC-623 §5；同 lnb 混用 EN50494/EN50607 由后端拒绝（SIM_TOPO_UB_* 族）",
    children: [
      {
        path: "scr.protocol",
        kind: "select",
        required: true,
        label: "protocol",
        hint: "EN50494（Unicable I，UB 0..7）| EN50607（dCSS，UB 0..31）",
        options: ["EN50494", "EN50607"],
      },
      {
        path: "scr.ub_assignments",
        kind: "rows",
        required: true,
        label: "ub_assignments（UB 分配表）",
        hint: "tuner→UB 映射：同一 tuner 至多一个 UB（重复 tuner_node 后端拒绝）；tuner.ub_slot 须命中本表（SIM_TOPO_UB_* 权威）",
        rowFields: [
          { path: "scr.ub_assignments[].tuner_node", kind: "text", required: true, label: "tuner_node", hint: "本拓扑内 tuner 节点 id" },
          { path: "scr.ub_assignments[].ub_slot", kind: "number", required: true, label: "ub_slot", hint: "≥ 0；位宽上限按 protocol（I >7 / II >31 后端拒绝）" },
          { path: "scr.ub_assignments[].ub_center_freq_mhz", kind: "number", required: true, label: "ub_center_freq_mhz", hint: "≥ 1（MHz；默认频率组 1210/1420/1680/2040 为非 normative 参考）" },
          { path: "scr.ub_assignments[].position", kind: "text", required: true, label: "position", hint: "EN50494: \"A\"/\"B\"；EN50607: 整数 0..63（按 protocol 词表，后端权威）" },
          { path: "scr.ub_assignments[].pin", kind: "number", required: false, label: "pin", hint: "可选 multihome PIN（0..255；EN 50494 0x5C / EN 50607 0x71 变体）" },
          { path: "scr.ub_assignments[].ub_bandwidth_mhz", kind: "number", required: false, wireDefault: 46, label: "ub_bandwidth_mhz", hint: "wire 默认 46（SPEC-623 §5）" },
        ],
      },
    ],
  },
];

/** TunerConfigDTO = tuning_request + ub_slot? + diseqc_commands? (SPEC-620/622
 * §5). diseqc_commands.target_register rides dotted paths (two-level wire
 * object; the serializer nests them — REPORT deviation note). */
export const TUNER_FIELD_INVENTORY: FieldDescriptor[] = [
  {
    path: "tuning_request",
    kind: "group",
    required: true,
    label: "tuning_request（调谐意图）",
    hint: "缺 tuning_request 即 prepare 拒绝（SPEC-620 §8）；锁定四分支消费上游 LNB/开关 metrics",
    children: [
      { path: "tuning_request.frequency_khz", kind: "number", required: true, label: "frequency_khz", hint: "≥ 1（kHz；IF = |tuning − lo_delivered| 求值输入）" },
      {
        path: "tuning_request.polarization",
        kind: "select",
        required: true,
        label: "polarization",
        hint: "与上游 polarization_delivered 不符 → unlocked（可判定事实，SPEC-620 §8）",
        options: ["vertical", "horizontal"],
      },
    ],
  },
  {
    path: "ub_slot",
    kind: "number",
    required: false,
    label: "ub_slot",
    hint: "SCR 模式必引用 lnb.scr.ub_assignments 表项；越位宽/双 tuner 同 UB 由后端 SIM_TOPO_UB_* 拒绝（静态校验权威）",
  },
  {
    path: "diseqc_commands",
    kind: "group",
    required: false,
    label: "diseqc_commands（DiSEqC 命令意图，可选）",
    hint: "nibble_writes 引用的寄存器须由 target_register 声明（SPEC-622 §8）；A15：意图由编排桥接至目标 switch config",
    children: [
      { path: "diseqc_commands.target_register.committed", kind: "checkbox", required: false, label: "target_register.committed", hint: "声明 committed 寄存器（0x38 Write N0）为写入目标" },
      { path: "diseqc_commands.target_register.uncommitted", kind: "checkbox", required: false, label: "target_register.uncommitted", hint: "声明 uncommitted 寄存器（0x39 Write N1）为写入目标" },
      {
        path: "diseqc_commands.nibble_writes",
        kind: "rows",
        required: true,
        label: "nibble_writes（nibble 写序列）",
        hint: "diseqc_commands 携带时至少 1 行；高 nibble 清 / 低 nibble 置位逐条应用，终态 = 最后生效（SPEC-622 §6）",
        rowFields: [
          { path: "diseqc_commands.nibble_writes[].register", kind: "select", required: true, label: "register", hint: "committed | uncommitted（wire 键 register，DiseqcNibbleWriteDTO）", options: ["committed", "uncommitted"] },
          { path: "diseqc_commands.nibble_writes[].nibble", kind: "select", required: true, label: "nibble", hint: "high | low（4-bit 位组半字节）", options: ["high", "low"] },
          { path: "diseqc_commands.nibble_writes[].value", kind: "number", required: true, label: "value", hint: "0..15（4-bit nibble 载荷，越界后端拒绝）" },
        ],
      },
    ],
  },
];

/** SwitchConfigDTO = power_pass（config 透传；电源域求值归 SPEC-621）. */
export const SWITCH_FIELD_INVENTORY: FieldDescriptor[] = [
  {
    path: "power_pass",
    kind: "select",
    required: true,
    label: "power_pass",
    hint: "on | off（config 透传，SPEC-622 §5；电源域求值归 SPEC-621）",
    options: ["on", "off"],
  },
];
