// gen.* event consumption contract for the Lab 只读折叠区 (SPEC-406 §Phase2
// L323). The journal REST face answers loose envelope records
// (`EventsDataDTO.items` is `{[key: string]: unknown}[]` — WS journal frames
// and envelope payloads sit outside OpenAPI, #129 REPORT §一.4), so this
// module owns the defensive parse against the triple-pinned payload key sets
// (#128 REPORT keys + #129 registry validator + brief §5-9):
//
//   gen.stage_started   = { layer }
//   gen.stage_completed = { layer, item_count }
//   gen.packet_sampled  = { layer, packet_index, byte_size, sha256 }
//
// Discipline: wire enums render verbatim (layer values TS/BBFRAME/T2MI/BISS —
// no aliasing, no case folding, SPEC-403 L315 / SPEC-406 L319); malformed
// rows are skipped — honest absence, never a fabricated row (SPEC-406 §4.6
// 空态纪律). The layer→inspector-view mapping is the #132 string contract:
// the Lab side only builds the URL parameter string, no inspector import
// beyond the read-only view vocabulary (ruling §10-5).
import {
  DEFAULT_PACKET_INSPECTOR_VIEW,
  PACKET_INSPECTOR_VIEWS,
  type PacketInspectorView,
} from "../monitor/packet-inspector/viewTypes";

export const GEN_STAGE_STARTED_EVENT_TYPE = "gen.stage_started";
export const GEN_STAGE_COMPLETED_EVENT_TYPE = "gen.stage_completed";
export const GEN_PACKET_SAMPLED_EVENT_TYPE = "gen.packet_sampled";

/** The gen.* REST query filter — exactly the three registered wire types
 * (#129 GEN_EVENT_TYPES; gen.* 仅分层 run 发射, ruling §10-15④). */
export const GEN_EVENT_TYPES: readonly string[] = [
  GEN_STAGE_STARTED_EVENT_TYPE,
  GEN_STAGE_COMPLETED_EVENT_TYPE,
  GEN_PACKET_SAMPLED_EVENT_TYPE,
];

/**
 * Presentation order for stage rows: the layered chain's contribution order
 * (STAGE_ORDER mirror — TS contribution → BISS scrambler → BBFRAME → T2MI,
 * ADR-0011 §2). Layers outside this list render verbatim after the known
 * ones (zero special-casing — future layers stay visible).
 */
const STAGE_PRESENTATION_ORDER: readonly string[] = ["TS", "BISS", "BBFRAME", "T2MI"];

export interface GenStageRow {
  /** Wire layer value verbatim (e.g. "TS" / "BBFRAME" / "T2MI" / "BISS"). */
  layer: string;
  state: "started" | "completed";
  /** gen.stage_completed item_count; null while the stage is only started. */
  itemCount: number | null;
}

export interface GenSampleCard {
  /** The per-session full order credential (ordering + React key). */
  journalSeq: number;
  /** Envelope scope.run_id passthrough — the jump resolves this run's
   * transmission artifact from the console's registry face. */
  runId: string | null;
  layer: string;
  packetIndex: number;
  byteSize: number;
  /** 64-hex lowercase (registry value domain) — rendered verbatim. */
  sha256: string;
}

export interface GenEventFace {
  stages: GenStageRow[];
  samples: GenSampleCard[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isNonNegativeInt(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

function isSha256(value: unknown): value is string {
  return typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
}

/** The SHAPE-validated payload faces (key sets pinned by #128/#129; extra
 * keys are tolerated here — the registry is the strict-side authority). */
type StageStartedPayload = { layer: string };
type StageCompletedPayload = { layer: string; item_count: number };
type PacketSampledPayload = { layer: string; packet_index: number; byte_size: number; sha256: string };

function readLayer(payload: Record<string, unknown>): string | null {
  const layer = payload.layer;
  return typeof layer === "string" && layer !== "" ? layer : null;
}

function parseStageStarted(payload: Record<string, unknown>): StageStartedPayload | null {
  const layer = readLayer(payload);
  return layer === null ? null : { layer };
}

function parseStageCompleted(payload: Record<string, unknown>): StageCompletedPayload | null {
  const layer = readLayer(payload);
  const item = payload.item_count;
  if (layer === null || !isNonNegativeInt(item)) return null;
  return { layer, item_count: item };
}

function parsePacketSampled(payload: Record<string, unknown>): PacketSampledPayload | null {
  const layer = readLayer(payload);
  if (layer === null || !isNonNegativeInt(payload.packet_index) || !isNonNegativeInt(payload.byte_size) || !isSha256(payload.sha256)) {
    return null;
  }
  return { layer, packet_index: payload.packet_index, byte_size: payload.byte_size, sha256: payload.sha256 };
}

/**
 * Parse the journal items into the fold's read-only face. Foreign event
 * types and shape-violating gen.* rows are dropped (honest absence — the
 * empty face states 无记录 ≠ 干净 upstream in the component copy).
 */
export function parseGenEvents(items: ReadonlyArray<unknown>): GenEventFace {
  const stageState = new Map<string, GenStageRow>();
  const stageFirstSeq = new Map<string, number>();
  const samples: GenSampleCard[] = [];

  for (const item of items) {
    if (!isRecord(item)) continue;
    const eventType = item.event_type;
    const payload = item.payload;
    if (typeof eventType !== "string" || !isRecord(payload)) continue;

    if (eventType === GEN_STAGE_STARTED_EVENT_TYPE) {
      const parsed = parseStageStarted(payload);
      if (parsed === null) continue;
      const seq = typeof item.journal_seq === "number" ? item.journal_seq : 0;
      if (!stageFirstSeq.has(parsed.layer)) stageFirstSeq.set(parsed.layer, seq);
      // Last event per layer wins (a re-run's stage_started flips the row
      // back to started — the fold mirrors the latest journal truth).
      stageState.set(parsed.layer, { layer: parsed.layer, state: "started", itemCount: null });
    } else if (eventType === GEN_STAGE_COMPLETED_EVENT_TYPE) {
      const parsed = parseStageCompleted(payload);
      if (parsed === null) continue;
      const seq = typeof item.journal_seq === "number" ? item.journal_seq : 0;
      if (!stageFirstSeq.has(parsed.layer)) stageFirstSeq.set(parsed.layer, seq);
      stageState.set(parsed.layer, { layer: parsed.layer, state: "completed", itemCount: parsed.item_count });
    } else if (eventType === GEN_PACKET_SAMPLED_EVENT_TYPE) {
      const parsed = parsePacketSampled(payload);
      const seq = item.journal_seq;
      if (parsed === null || typeof seq !== "number") continue;
      const scope = isRecord(item.scope) ? item.scope : {};
      const runId = typeof scope.run_id === "string" ? scope.run_id : null;
      samples.push({
        journalSeq: seq,
        runId,
        layer: parsed.layer,
        packetIndex: parsed.packet_index,
        byteSize: parsed.byte_size,
        sha256: parsed.sha256,
      });
    }
  }

  const stages = [...stageState.values()].sort((a, b) => {
    const orderOf = (layer: string): number => {
      const known = STAGE_PRESENTATION_ORDER.indexOf(layer);
      return known === -1 ? STAGE_PRESENTATION_ORDER.length : known;
    };
    const byOrder = orderOf(a.layer) - orderOf(b.layer);
    if (byOrder !== 0) return byOrder;
    // Same bucket (unknown layers): first appearance order.
    return (stageFirstSeq.get(a.layer) ?? 0) - (stageFirstSeq.get(b.layer) ?? 0);
  });
  samples.sort((a, b) => a.journalSeq - b.journalSeq);
  return { stages, samples };
}

/** layer → inspector view mapping (dispatch final: T2MI→t2mi, BBFRAME→bbframe,
 * BISS/TS→ts; unknown layers fall to the MVP default). The mapped value is
 * re-checked against the #132 wire vocabulary (read-only import, ruling
 * §10-5) — vocabulary drift degrades to the default, never an alien value. */
const VIEW_BY_LAYER: Readonly<Record<string, PacketInspectorView>> = {
  T2MI: "t2mi",
  BBFRAME: "bbframe",
  TS: "ts",
  BISS: "ts",
};

export function layerToInspectorView(layer: string): PacketInspectorView {
  const mapped = VIEW_BY_LAYER[layer];
  if (mapped !== undefined && (PACKET_INSPECTOR_VIEWS as readonly string[]).includes(mapped)) {
    return mapped;
  }
  return DEFAULT_PACKET_INSPECTOR_VIEW;
}

/** The console-side run registry face the jump resolves against. */
export interface GenRunArtifactFace {
  artifact_id: string;
  kind: string;
}

export interface GenRunFace {
  runId: string;
  artifacts: ReadonlyArray<GenRunArtifactFace>;
}

export interface GenJumpTarget {
  artifactId: string;
  /** Layered packets carry no TS PID; 0 is the neutral wire-shape value the
   * locator triple's parser requires (it is NOT consumed by the layered
   * structure views — the t2mi/bbframe branches read the structure JSON
   * only). Declared here so the honest choice stays documented at the seam. */
  pid: number;
  packetIndex: number;
  view: PacketInspectorView;
}

/**
 * Resolve one sampled packet's inspector jump target from the console's run
 * registry face: the run's layered transmission artifact (faulted_ts tee leg
 * preferred, generated_ts fallback, then the first artifact) + the mapped
 * view. Unknown run / artifact-less run → null (no fabricated locator — the
 * card renders without a jump action).
 */
export function resolveJumpTarget(sample: GenSampleCard, runs: ReadonlyArray<GenRunFace>): GenJumpTarget | null {
  const run = runs.find((candidate) => candidate.runId === sample.runId);
  if (run === undefined) return null;
  const artifact =
    run.artifacts.find((candidate) => candidate.kind === "faulted_ts") ??
    run.artifacts.find((candidate) => candidate.kind === "generated_ts") ??
    run.artifacts[0];
  if (artifact === undefined) return null;
  return {
    artifactId: artifact.artifact_id,
    pid: 0,
    packetIndex: sample.packetIndex,
    view: layerToInspectorView(sample.layer),
  };
}
