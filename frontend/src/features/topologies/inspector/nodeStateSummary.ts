// State-domain node status summaries (SPEC-401 §Phase3 card summary + SPEC-404
// §Phase3 detail panel data path, ticket #169). Pure normalization over the
// state_observed snapshot stream: the events REST face (SPEC-305 §Phase3
// namespace/node_type query) and the WS journal frames carry the SAME loose
// envelope shape, and both funnel through extractStateObservedSnapshots so the
// card badge/metrics and the detail panel read one merged fact set.
//
// Honesty posture: wire values render verbatim (no case conversion, no enum
// aliasing — the payload's health/source/confidence strings are the state
// evaluator's own words); a missing snapshot is a missing snapshot (缺失 ≠ 零),
// never rendered as a clean/zero state.
import { STATE_OBSERVED_EVENT_TYPES } from "../nodeTypes";

/** One normalized per-node state_observed snapshot. */
export interface StateObservedSnapshot {
  event_type: string;
  /** Ordering credential (SPEC-301); null when the envelope lacks one. */
  journal_seq: number | null;
  /** correlation.node_id — the per-node discipline of the state_observed face. */
  node_id: string;
  /** NodeEvalResult-shaped JSON-safe payload verbatim. */
  payload: Record<string, unknown>;
}

/** Payload keys that ride DEDICATED presentation faces (identity/health header,
 * CauseRef chain, honesty source/confidence row) — the metrics list renders
 * everything else, so "全量 metrics" keeps every wire key visible. */
export const STATE_OBSERVED_ENVELOPE_KEYS: readonly string[] = [
  "node_id",
  "health",
  "causes",
  "source",
  "confidence",
];

function isStateObservedEventType(eventType: unknown): eventType is string {
  return typeof eventType === "string" && (STATE_OBSERVED_EVENT_TYPES as readonly string[]).includes(eventType);
}

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

/** REST items / journal frames → normalized snapshots (rf./sec. only, node_id
 * resolved from correlation; items without a string node_id are dropped — the
 * per-node discipline means such items have no consumer). */
export function extractStateObservedSnapshots(items: readonly Record<string, unknown>[]): StateObservedSnapshot[] {
  const snapshots: StateObservedSnapshot[] = [];
  for (const item of items) {
    if (!isStateObservedEventType(item.event_type)) continue;
    const correlation = asRecord(item.correlation);
    const nodeId = correlation.node_id;
    if (typeof nodeId !== "string" || nodeId.length === 0) continue;
    const seq = item.journal_seq;
    snapshots.push({
      event_type: item.event_type,
      journal_seq: typeof seq === "number" ? seq : null,
      node_id: nodeId,
      payload: asRecord(item.payload),
    });
  }
  return snapshots;
}

/** Client-side node_id narrowing (the events endpoint carries no node_id
 * param — the §5 query whitelist stays frozen; the panel narrows here). */
export function snapshotsForNode(
  snapshots: readonly StateObservedSnapshot[],
  nodeId: string,
): StateObservedSnapshot[] {
  return snapshots.filter((snapshot) => snapshot.node_id === nodeId);
}

/** The node's latest snapshot: max journal_seq wins; unsequenced snapshots
 * never outrank a sequenced one. */
export function latestSnapshotFor(
  snapshots: readonly StateObservedSnapshot[],
  nodeId: string,
): StateObservedSnapshot | undefined {
  let latest: StateObservedSnapshot | undefined;
  for (const snapshot of snapshotsForNode(snapshots, nodeId)) {
    if (
      latest === undefined ||
      (snapshot.journal_seq !== null && (latest.journal_seq === null || snapshot.journal_seq > latest.journal_seq))
    ) {
      latest = snapshot;
    }
  }
  return latest;
}

/** One node's card summary: health from the latest snapshot payload + the full
 * metrics map (envelope keys stripped — they have dedicated faces). */
export interface NodeStatus {
  health?: string;
  metrics: Record<string, unknown>;
}

/** node_id → status map over the whole snapshot stream (the canvas face feeds
 * every card from one merged fact set — no per-node queries). Later journal_seq
 * overwrites earlier; unsequenced snapshots only fill nodes nothing sequenced
 * has touched. */
export function buildNodeStatusMap(snapshots: readonly StateObservedSnapshot[]): Map<string, NodeStatus> {
  const map = new Map<string, NodeStatus>();
  const latestSeq = new Map<string, number>();
  for (const snapshot of snapshots) {
    const seq = snapshot.journal_seq;
    const seen = latestSeq.get(snapshot.node_id);
    if (seen !== undefined && (seq === null || seq <= seen)) continue;
    if (seq !== null) latestSeq.set(snapshot.node_id, seq);
    const metrics: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(snapshot.payload)) {
      if (!STATE_OBSERVED_ENVELOPE_KEYS.includes(key)) metrics[key] = value;
    }
    map.set(snapshot.node_id, {
      health: typeof snapshot.payload.health === "string" ? snapshot.payload.health : undefined,
      metrics,
    });
  }
  return map;
}

/** REST page + journal tail merge: journal_seq is the dedup identity (a WS
 * frame repeating a REST item's seq collapses); output is journal_seq
 * ascending; unsequenced snapshots pass through without colliding. */
export function mergeSnapshotItems(
  restItems: readonly Record<string, unknown>[],
  journalItems: readonly Record<string, unknown>[],
): StateObservedSnapshot[] {
  const bySeq = new Map<number, StateObservedSnapshot>();
  const unsequenced: StateObservedSnapshot[] = [];
  for (const snapshot of extractStateObservedSnapshots([...restItems, ...journalItems])) {
    if (snapshot.journal_seq === null) {
      unsequenced.push(snapshot);
    } else {
      bySeq.set(snapshot.journal_seq, snapshot);
    }
  }
  return [...[...bySeq.entries()].sort((a, b) => a[0] - b[0]).map(([, snapshot]) => snapshot), ...unsequenced];
}

/** Wire-value verbatim presentation: strings/numbers/booleans via String(),
 * null as null, structured values (ub_assignments table) as canonical JSON.
 * No enum aliasing, no case conversion, no invented units. */
export function renderMetricValue(value: unknown): string {
  if (value === null || value === undefined) return "null";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
