// state_observed 快照消费契约(#170, SPEC-406 §Phase3「生成过程」折叠区状态域
// 形态): SIM_STATE Run 无 gen.* 构造事件——折叠区状态域呈现 L0 求值摘要
// (节点数 / 各节点 health / 快照事件计数), 数据源 = journal 快照事件
// (rf./sec. state_observed, #164 注册表), 不冒充构造事件。
//
// The journal REST face answers loose envelope records (`EventsDataDTO.items`
// is `{[key: string]: unknown}[]` — the same defensive-parse posture as
// genEvents.ts): shape-violating rows are skipped (honest absence, never a
// fabricated node row), wire values render verbatim (无别名/无大小写转换,
// SPEC-403 L315), and the same node's later snapshot wins (journal asc order
// mirrors the latest journal truth — the genEvents stage-row posture).
//
// 诚实口径: the payload carries its provenance axes (source/confidence);
// SPEC-303 §Phase3 pins the pairing constant (state_evaluator + simulated).
// The summary surfaces the first-seen wire values verbatim — 呈现层不混标,
// the journal face stays the fact source.

/** The state-domain REST query filter — exactly the two #164 registered
 * per-node snapshot types (rf = tuner, sec = lnb/switch). */
export const STATE_SNAPSHOT_EVENT_TYPES: readonly string[] = ["rf.state_observed", "sec.state_observed"];

export interface StateNodeHealthRow {
  /** Wire node_id verbatim. */
  nodeId: string;
  /** Wire Health value verbatim (ok/warn/error/idle — no case folding). */
  health: string;
}

export interface StateSnapshotSummary {
  /** One row per distinct node (first-appearance order), carrying the node's
   * LATEST snapshot health. */
  nodes: StateNodeHealthRow[];
  /** rf.state_observed snapshot event count (parsed rows only). */
  rfCount: number;
  /** sec.state_observed snapshot event count (parsed rows only). */
  secCount: number;
  /** First-seen payload `source` wire value (the 恒定配对 face; null when no
   * snapshot carried one). */
  source: string | null;
  /** First-seen payload `confidence` wire value. */
  confidence: string | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function readSnapshotRow(eventType: string, payload: Record<string, unknown>): StateNodeHealthRow | null {
  const nodeId = payload.node_id;
  const health = payload.health;
  if (typeof nodeId !== "string" || nodeId === "") return null;
  if (typeof health !== "string" || health === "") return null;
  void eventType;
  return { nodeId, health };
}

/**
 * Parse the journal items into the fold's L0 求值摘要 face. Foreign event
 * types (gen.* / fault.* / topology.state_changed — anything but the two
 * registered snapshot types) and shape-violating rows are dropped (honest
 * absence; the empty-input face states 无记录 ≠ 干净 upstream in the
 * component copy).
 */
export function parseStateSnapshotSummary(items: ReadonlyArray<unknown>): StateSnapshotSummary {
  const nodeHealth = new Map<string, string>();
  let rfCount = 0;
  let secCount = 0;
  let source: string | null = null;
  let confidence: string | null = null;

  for (const item of items) {
    if (!isRecord(item)) continue;
    const eventType = item.event_type;
    const payload = item.payload;
    if (typeof eventType !== "string" || !isRecord(payload)) continue;
    if (!STATE_SNAPSHOT_EVENT_TYPES.includes(eventType)) continue;

    const row = readSnapshotRow(eventType, payload);
    if (row === null) continue;
    nodeHealth.set(row.nodeId, row.health);
    if (eventType === "rf.state_observed") rfCount += 1;
    else secCount += 1;
    if (source === null && typeof payload.source === "string") source = payload.source;
    if (confidence === null && typeof payload.confidence === "string") confidence = payload.confidence;
  }

  return { nodes: [...nodeHealth.entries()].map(([nodeId, health]) => ({ nodeId, health })), rfCount, secCount, source, confidence };
}
