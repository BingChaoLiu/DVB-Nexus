// Feature-local DTO type aliases (SPEC-403 §5): every consumed wire type in
// one place, aliased from the generated authority (schema.gen.ts — read-only
// import; the file itself is NEVER modified). Where the api barrel already
// re-exports a type, both paths resolve to the identical generated type.
import type { components } from "../../api/schema.gen";
import type { JournalEnvelope } from "../../ws/SessionStream";

type Schemas = components["schemas"];

export type AlertRecordDTO = Schemas["AlertRecordDTO"];
export type AlertsDataDTO = Schemas["AlertsDataDTO"];
export type CriterionResultDTO = Schemas["CriterionResultDTO"];
export type DiagnosisCandidateDTO = Schemas["DiagnosisCandidateDTO"];
export type DiagnosisDTO = Schemas["DiagnosisDTO"];
export type DiagnosisEvidenceDTO = Schemas["DiagnosisEvidenceDTO"];
export type DiagnosisObservationRefDTO = Schemas["DiagnosisObservationRefDTO"];
export type DiagnosisReportDTO = Schemas["DiagnosisReportDTO"];
export type MetricsResponseDTO = Schemas["MetricsResponseDTO"];
export type PassCriterionDTO = Schemas["PassCriterionDTO"];
export type RunStatusDTO = Schemas["RunStatusDTO"];
export type SnapshotDTO = Schemas["SnapshotDTO"];
export type SummaryDataDTO = Schemas["SummaryDataDTO"];
export type VerificationResultDTO = Schemas["VerificationResultDTO"];
export type VerifyRunRequest = Schemas["VerifyRunRequest"];

// --- Phase 2 事件命名空间消费面(SPEC-303 §Phase2;#129 注册表) --------------
// WS journal 帧在 OpenAPI 之外(裁定 §10-16-④:payload-schema 端点归 #136
// 收口评估)——事件 payload 类型没有 schema.gen 权威可 alias。本文件 = 事件
// 类型消费面唯一归属(裁定 §10-5);键集按 #129 REPORT §2 终稿(与后端
// registry validate_payload 严格键集三重钉死:#128 REPORT / #129 注册表 /
// 简报 §2bis)。wire 枚串(layer/mode/self_check_kind/payload_kind)一律
// 原样渲染(SPEC-403 L315 禁改写)。

/** The registered Phase 2/Phase 3 event types (#129 REPORT §1 registry
 * constants + the #164 rf./sec. state-observation additions, SPEC-303
 * §Phase3). Wire names verbatim — the render table keys ride these. */
export const PHASE2_EVENT_TYPES = [
  "t2mi.stage_summary",
  "t2mi.plp_mismatch",
  "bbframe.stage_summary",
  "bbframe.recovery_failed",
  "biss.scramble_applied",
  "biss.descramble_failed",
  "gen.stage_started",
  "gen.stage_completed",
  "gen.packet_sampled",
  "rf.state_observed",
  "sec.state_observed",
] as const;

export type Phase2EventType = (typeof PHASE2_EVENT_TYPES)[number];

/** The gen.* layer vocabulary (registry GENERATION_LAYERS; rendered verbatim). */
export const GENERATION_LAYERS = ["TS", "BBFRAME", "T2MI", "BISS"] as const;
/** The biss.* mode vocabulary (registry BISS_MODES; rendered verbatim). */
export const BISS_MODES = ["1", "E", "2"] as const;

/** `t2mi.stage_summary` payload (#129 REPORT §2; SPEC-600 §6). Distribution
 * dicts carry decimal-string keys rendered verbatim (`packet_type_distribution`
 * keys ∈ {bbframe, padding, unknown}). */
export interface T2miStageSummaryPayload {
  packet_count: number;
  padding_count: number;
  packet_type_distribution: Record<string, number>;
  plp_distribution: Record<string, number>;
}

/** `t2mi.plp_mismatch` nested evidence locator (#129 REPORT §2; SPEC-602 §6). */
export interface T2miBusinessAbsentEvidence {
  plps_seen: number[];
  bbframe_packet_count: number;
  filtered_packet_count: number;
  total_packet_count: number;
}

/** `t2mi.plp_mismatch` payload — `actual_plp` is honestly `null` when ≠1 PLP
 * was observed (never a guess; the 缺失 ≠ 零 carrier). */
export interface T2miPlpMismatchPayload {
  expected_plp: number;
  actual_plp: number | null;
  business_absent_evidence: T2miBusinessAbsentEvidence;
}

/** `bbframe.stage_summary` payload (#129 REPORT §2; SPEC-601 §5). */
export interface BbframeStageSummaryPayload {
  frame_count: number;
  n_ups_distribution: Record<string, number>;
  stuffing_ratio: number;
}

/** `bbframe.recovery_failed` payload — `first_failed_frame_index` honestly
 * `null` when no first-failure position is derivable. */
export interface BbframeRecoveryFailedPayload {
  failure_count: number;
  first_failed_frame_index: number | null;
}

/** `biss.scramble_applied` payload (#129 REPORT §2; SPEC-610/611 §5). The base
 * five keys ride every mode; the Mode "E"/"2" fault face additively carries
 * `derivation_ref` (fingerprint references — never key material) and
 * `mismatch_variants`. */
export interface BissScrambleAppliedPayload {
  pid_scope: number[];
  packet_count: number;
  key_fingerprint: string;
  mutation_log_ref: string | null;
  mode: string;
  derivation_ref?: Record<string, string>;
  mismatch_variants?: string[];
}

/** `biss.descramble_failed` payload — fingerprint reference only; the 解扰失败
 * ≠ 码流损坏 carrier. */
export interface BissDescrambleFailedPayload {
  pid_scope: number[];
  failed_indices_sample: number[];
  self_check_kind: string;
  key_fingerprint_ref: string;
  mode: string;
}

/** `gen.stage_started` payload. */
export interface GenStageStartedPayload {
  layer: string;
}

/** `gen.stage_completed` payload. */
export interface GenStageCompletedPayload {
  layer: string;
  item_count: number;
}

/** `gen.packet_sampled` payload — `sha256` is the lowercase 64-hex digest of
 * the sampled packet bytes. */
export interface GenPacketSampledPayload {
  layer: string;
  packet_index: number;
  byte_size: number;
  sha256: string;
}

/** The shared per-node state-snapshot projection base (#164 registry
 * `_STATE_NODE_BASE_KEYS`; SPEC-303 §Phase3): NodeEvalResult-shape identity +
 * health + the JSON-safe CauseRef list + the CONSTANT observation axes.
 * 诚实口径: source is always the wire string `state_evaluator` and confidence
 * always `simulated` on these payloads — rendered verbatim, never re-labeled
 * (SPEC-403 §Phase3: 呈现层不得混标 parsed/measured). */
export interface StateObservedBase {
  node_id: string;
  /** Wire Health value verbatim (ok/warn/error/idle). */
  health: string;
  /** CauseRef projection `[{node_id, port_id?}]` — the root-cause chain. */
  causes: Array<{ node_id: string; port_id?: string }>;
  source: string;
  confidence: string;
}

/** `rf.state_observed` payload (tuner snapshot; #164 registry
 * RF_TUNER_SNAPSHOT_KEYS). `stale` rides every snapshot (true iff unlocked,
 * SPEC-620 §8 — the retained ber_state 档位 with unlocked lock is marked,
 * 不静默); `locked_transponder_id` honestly `null` while unlocked. */
export interface RfStateObservedPayload extends StateObservedBase {
  lock_state: string;
  if_frequency_khz: number | null;
  ber_state: string;
  locked_transponder_id: string | null;
  stale?: boolean;
}

/** `sec.state_observed` payload (lnb / legacy_cascade lnb / diseqc_switch
 * per-node snapshots; #164 registry shape = the lnb ∪ sat_selected ∪ switch
 * key union — a concrete payload carries exactly one node's face, so every
 * metric key is optional on the consumption type). Wire enum strings render
 * verbatim (SPEC-403 L315 禁改写). */
export interface SecStateObservedPayload extends StateObservedBase {
  voltage?: string;
  tone_commanded?: string;
  tone_actual?: string;
  tone_composite?: string;
  band_selected?: string;
  lo_frequency_khz?: number | null;
  polarization_delivered?: string;
  short_circuit_state?: string;
  ub_assignments?: Array<Record<string, unknown>>;
  /** legacy_cascade satellite-select fact only (never on universal LNBs or
   * switches). */
  sat_selected?: string;
  committed_switch_state?: number;
  uncommitted_switch_state?: number;
  port_selected?: string | null;
  power_pass?: string;
}

/** Event type → payload consumption type (the #129 key sets, typed). */
export type Phase2EventPayloadMap = {
  "t2mi.stage_summary": T2miStageSummaryPayload;
  "t2mi.plp_mismatch": T2miPlpMismatchPayload;
  "bbframe.stage_summary": BbframeStageSummaryPayload;
  "bbframe.recovery_failed": BbframeRecoveryFailedPayload;
  "biss.scramble_applied": BissScrambleAppliedPayload;
  "biss.descramble_failed": BissDescrambleFailedPayload;
  "gen.stage_started": GenStageStartedPayload;
  "gen.stage_completed": GenStageCompletedPayload;
  "gen.packet_sampled": GenPacketSampledPayload;
  "rf.state_observed": RfStateObservedPayload;
  "sec.state_observed": SecStateObservedPayload;
};

/** A journal envelope carrying a registered Phase 2 event type. The payload
 * stays a loose record at the render seam (loose envelope / tight payload:
 * consumers render the wire values verbatim; unknown tolerance per ADR-0006). */
export interface Phase2EventEnvelope extends JournalEnvelope {
  event_type: Phase2EventType;
  payload?: Record<string, unknown>;
}

/** Narrow a raw journal envelope to the Phase 2 view without asserting facts:
 * `null` for every non-registered event type (ADR-0006 unknown tolerance). */
export function asPhase2Envelope(envelope: JournalEnvelope): Phase2EventEnvelope | null {
  const eventType = envelope.event_type;
  return typeof eventType === "string" && (PHASE2_EVENT_TYPES as readonly string[]).includes(eventType)
    ? (envelope as Phase2EventEnvelope)
    : null;
}
