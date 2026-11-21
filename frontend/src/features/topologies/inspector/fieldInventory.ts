// Field inventory for the node inspector (SPEC-402 §5.1, APPROVED 0.5.0):
// the hand-written descriptor tables for the frozen node config schemas,
// selected per node type through fieldInventoryFor. MVP carried exactly one
// non-null config_schema (GeneratorConfigDTO — the #62 approval); Phase 2
// (SPEC-401 §Phase2, ticket #135) adds T2miEncapsulatorConfigDTO /
// T2miDemuxConfigDTO whose lists live in nodeTypes.ts (OWN face) hand-written
// to the #121 backend schemas — no generated wire DTO exists yet.
// Data sources, in authority order:
//   1. generated wire types  frontend/src/api/schema.gen.ts
//      (GeneratorConfigDTO / ProgramDTO / ElementaryStreamDTO — key sets and
//      @default values verbatim, fieldInventory.test.ts transcribes them as
//      the drift lock);
//   2. the #121 backend config schemas (domain.topology.node_types) for the
//      Phase 2 lists (constraint notes are hint text ONLY — presentation,
//      never client-side enforcement);
//   3. the NodeType registry pointer (config_schema) — this module never
//      invents fields for a schema it has no list for.
// This is NOT a JSON Schema engine (SPEC-402 §2.2): no schema parser, no
// runtime introspection, no control derivation — the renderer (NodeInspector)
// switches on the frozen ControlKinds and nothing else.
import {
  LNB_FIELD_INVENTORY,
  SWITCH_FIELD_INVENTORY,
  T2MI_DEMUX_FIELD_INVENTORY,
  T2MI_ENCAPSULATOR_FIELD_INVENTORY,
  TUNER_FIELD_INVENTORY,
  nodeTypeSpec,
  type NodeTypeSpec,
} from "../nodeTypes";

/** The closed control-kind set (SPEC-402 §5.2 six MVP kinds + the Phase 2
 * additive "checkbox" — the #121 demux/encapsulator schemas carry free
 * booleans (strict_crc has a wire default, npd_enabled is required) that the
 * locked-checkbox (contract-single-value) cannot represent faithfully.
 * #135 deviation note: the six-kind freeze predates the Phase 2 schemas; the
 * renderer stays switch-based, no engine). */
export type ControlKind = "number" | "text" | "select" | "locked-checkbox" | "checkbox" | "group" | "rows";

export interface FieldDescriptor {
  /** Config-root-relative dot path. Rows use the `[]` index placeholder,
   * e.g. "program.streams[].pid" (concrete indexes only ever appear in
   * backend error strings — see schemaPathMatch.ts). */
  path: string;
  kind: ControlKind;
  /** Wire-side default (generated schema @default). Absent = required: the
   * field is a G1 completeness subject and starts empty on a fresh form. */
  wireDefault?: unknown;
  /** true = wire has no default → "配置待填" subject (existence check ONLY,
   * never a value judgment — SPEC-402 §7.3). */
  required: boolean;
  /** Display label (zh). */
  label: string;
  /** SPEC-108 §4/§5 constraint note — presented verbatim as hint text, not
   * enforced (the backend stays the authority). */
  hint?: string;
  /** select option set = the SPEC-108 frozen enum (no guessing). */
  options?: string[];
  /** Pinned initial value where the form differs from the wire default
   * (schema_version = 1, the supported version per
   * examples/ts-generator-minimal.json; the set of supported versions is
   * backend authority, SPEC-108 §5). */
  initial?: unknown;
  /** group children (program) — exactly one nesting level, static shape. */
  children?: FieldDescriptor[];
  /** rows row fields (program.streams). */
  rowFields?: FieldDescriptor[];
}

const STREAM_ROW_FIELDS: FieldDescriptor[] = [
  { path: "program.streams[].pid", kind: "number", required: true, label: "PID", hint: "程序内唯一（SPEC-108 §5）" },
  { path: "program.streams[].stream_type", kind: "number", required: true, label: "stream_type", hint: "按字段位宽校验（SPEC-108 §5）" },
  { path: "program.streams[].stream_id", kind: "number", required: true, label: "stream_id", hint: "按字段位宽校验（SPEC-108 §5）" },
  { path: "program.streams[].bitrate_bps", kind: "number", required: true, label: "bitrate_bps", hint: "> 0；须装入 target 码率（SPEC-108 §5）" },
  {
    path: "program.streams[].payload_profile",
    kind: "text",
    required: false,
    wireDefault: "synthetic_test_data",
    label: "payload_profile",
    hint: "wire 默认 synthetic_test_data（值集归后端，不发明客户端枚举）",
  },
  { path: "program.streams[].payload_seed_offset", kind: "number", required: false, wireDefault: 0, label: "payload_seed_offset" },
];

const PROGRAM_CHILDREN: FieldDescriptor[] = [
  { path: "program.transport_stream_id", kind: "number", required: true, label: "transport_stream_id", hint: "按字段位宽校验（SPEC-108 §5）" },
  { path: "program.program_number", kind: "number", required: true, label: "program_number", hint: "≠ 0（SPEC-108 §5）" },
  { path: "program.pmt_pid", kind: "number", required: true, label: "pmt_pid", hint: "PID 不得冲突或使用保留 PID（SPEC-108 §5）" },
  { path: "program.pcr_pid", kind: "number", required: true, label: "pcr_pid", hint: "可复用一个 ES PID（SPEC-108 §5）" },
  { path: "program.version_number", kind: "number", required: true, label: "version_number", hint: "按字段位宽校验（SPEC-108 §5）" },
  {
    path: "program.streams",
    kind: "rows",
    required: true,
    label: "streams（基本流）",
    // SPEC-108 §5 states no minimum stream count — the empty array is legal
    // and the frontend must NOT invent a minLength constraint.
    hint: " ElementaryStreamDTO 行列表；可为空数组（§5 无最少流数约束）；ES PID 程序内唯一",
    rowFields: STREAM_ROW_FIELDS,
  },
  { path: "program.program_descriptors", kind: "text", required: false, wireDefault: "", label: "program_descriptors", hint: "bytes → hex 编码（SPEC-500 §5）；空串 = 无描述符" },
];

/** The §5.1 table — the ONLY code embodiment of the GeneratorConfigDTO field
 * list. Order follows the generated type; the key-set equality test is the
 * drift lock in both directions. */
export const GENERATOR_FIELD_INVENTORY: FieldDescriptor[] = [
  {
    path: "schema_version",
    kind: "number",
    required: true,
    label: "schema_version",
    hint: "受支持版本集归后端（SPEC-108 §5）；DTO 约束 ge=1，现行值 1",
    initial: 1,
  },
  {
    path: "profile",
    kind: "select",
    required: false,
    wireDefault: "analysis_only",
    label: "profile",
    hint: "MVP 仅 analysis_only（SPEC-108 §4）",
    options: ["analysis_only"],
  },
  {
    path: "deterministic",
    kind: "locked-checkbox",
    required: false,
    wireDefault: true,
    label: "deterministic",
    hint: "必须为 true（SPEC-108 §4 映射表）——契约单值，控件锁定",
  },
  { path: "seed", kind: "number", required: true, label: "seed", hint: "进入生成指纹；不读取墙钟字段（SPEC-108 §5）" },
  { path: "initial_media_clock_27mhz", kind: "number", required: true, label: "initial_media_clock_27mhz", hint: "非负（SPEC-108 §4）" },
  {
    path: "target_bitrate_bps",
    kind: "number",
    required: true,
    label: "target_bitrate_bps",
    hint: "> 0；冻结范围 1~100 Mbps（ADR-0008 第 2 条）",
  },
  { path: "output_packet_count", kind: "number", required: true, label: "output_packet_count", hint: "> 0（SPEC-108 §5）" },
  { path: "program", kind: "group", required: true, label: "program（节目）", children: PROGRAM_CHILDREN },
  { path: "pat_period_ms", kind: "number", required: false, wireDefault: 101, label: "pat_period_ms", hint: "> 0；#72 错相裁决默认 101" },
  { path: "pmt_period_ms", kind: "number", required: false, wireDefault: 103, label: "pmt_period_ms", hint: "> 0；#72 错相裁决默认 103" },
  { path: "pcr_interval_ms", kind: "number", required: false, wireDefault: 40, label: "pcr_interval_ms", hint: "> 0（SPEC-108 §5）" },
  {
    path: "pcr_insertion_policy",
    kind: "select",
    required: false,
    wireDefault: "payload_packet_first",
    label: "pcr_insertion_policy",
    hint: "枚举（SPEC-108 §5，语义见 SPEC-107 §5.3）",
    options: ["payload_packet_first", "adaptation_only_fallback"],
  },
];

/** The form's initial value for a descriptor: the pinned initial, else the
 * wire default, else nothing (empty input → G1 "待填"). */
export function initialValueFor(descriptor: FieldDescriptor): unknown {
  return descriptor.initial !== undefined ? descriptor.initial : descriptor.wireDefault;
}

// --- per-schema inventory lookup (SPEC-402 §5.1 × SPEC-401 §Phase2) ------------

/** The descriptor list for one config_schema pointer. The MVP list is defined
 * here; the Phase 2 lists are nodeTypes.ts exports (hand-written to the #121
 * backend schemas). `null` (opaque config) and an unlisted pointer →
 * undefined: the honest "no inventory" state — the frontend never guesses
 * fields. */
export function fieldInventoryFor(configSchema: NodeTypeSpec["config_schema"]): FieldDescriptor[] | undefined {
  switch (configSchema) {
    case "GeneratorConfigDTO":
      return GENERATOR_FIELD_INVENTORY;
    case "T2miEncapsulatorConfigDTO":
      return T2MI_ENCAPSULATOR_FIELD_INVENTORY;
    case "T2miDemuxConfigDTO":
      return T2MI_DEMUX_FIELD_INVENTORY;
    // #169 (SPEC-401 §Phase3): the #160 backend config DTO pointers — the
    // lists live in nodeTypes.ts beside the Phase 2 lists (same hand-written
    // to-the-backend-schema discipline).
    case "LnbConfigDTO":
      return LNB_FIELD_INVENTORY;
    case "TunerConfigDTO":
      return TUNER_FIELD_INVENTORY;
    case "SwitchConfigDTO":
      return SWITCH_FIELD_INVENTORY;
    default:
      return undefined;
  }
}

// --- G1 completeness (existence only — SPEC-402 §7.3) -------------------------

/** G1 purity: a "filled" number is a finite number (null/NaN = unfilled); a
 * "filled" text is a non-empty string; presence is never a value judgment —
 * range/cross-field checks are backend business validation (SPEC-108 §5) and
 * are NEVER attempted here. */
function isFilled(value: unknown): boolean {
  if (typeof value === "number") return Number.isFinite(value);
  if (typeof value === "string") return value.length > 0;
  return value !== null && value !== undefined;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Completeness of one descriptor level against a config object. */
function levelComplete(fields: FieldDescriptor[], config: Record<string, unknown>): boolean {
  return fields.every((field) => {
    const value = config[field.path.includes(".") ? field.path.split(".").pop()! : field.path];
    if (!field.required) return true; // defaulted fields are born filled
    if (!isFilled(value)) return false;
    if (field.kind === "group") {
      return isPlainObject(value) && levelComplete(field.children ?? [], value);
    }
    if (field.kind === "rows") {
      if (!Array.isArray(value)) return false;
      // presence suffices for the array itself (empty = legal); every row
      // that DOES exist must have its required row fields filled.
      return value.every((row) => isPlainObject(row) && levelComplete(field.rowFields ?? [], row));
    }
    return true;
  });
}

/** G1 (SPEC-402 §7.3): does this draft node's config have every required
 * field filled? `config_schema = null` types (and unregistered types, and
 * non-null pointers without a frontend inventory — the frontend never
 * guesses their shape) are trivially complete; a typed config that is not a
 * plain object is incomplete (opaque kept, gate blocks). */
export function isConfigComplete(nodeType: string, config: unknown): boolean {
  const spec = nodeTypeSpec(nodeType);
  if (spec === undefined || spec.config_schema === null) return true;
  const inventory = fieldInventoryFor(spec.config_schema);
  if (inventory === undefined) return true;
  if (!isPlainObject(config)) return false;
  return levelComplete(inventory, config);
}
