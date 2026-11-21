// nodeStateSummary pure-module tests (SPEC-401 §Phase3 card summary + SPEC-404
// §Phase3 detail panel data path, ticket #169). Expected values are worked
// examples built from the SPEC-303 §Phase3 payload shape (NodeEvalResult
// JSON-safe), never recomputed from the implementation (tautology guard).
import { describe, expect, it } from "vitest";

import {
  buildNodeStatusMap,
  extractStateObservedSnapshots,
  latestSnapshotFor,
  mergeSnapshotItems,
  renderMetricValue,
  snapshotsForNode,
  STATE_OBSERVED_ENVELOPE_KEYS,
} from "./nodeStateSummary";

/** A minimal rf.state_observed envelope the way the REST events endpoint and
 * the WS journal frames both carry it (loose Record — EventsDataDTO.items). */
function rfEnvelope(overrides: Record<string, unknown>): Record<string, unknown> {
  return {
    event_type: "rf.state_observed",
    journal_seq: 10,
    severity: "info",
    correlation: { node_id: "tuner-a" },
    payload: {
      node_id: "tuner-a",
      health: "ok",
      causes: [],
      source: "state_evaluator",
      confidence: "simulated",
      lock_state: "locked",
      if_frequency_khz: 1250000,
      ber_state: "normal",
      locked_transponder_id: "tp-1",
      stale: false,
    },
    ...overrides,
  };
}

describe("extractStateObservedSnapshots — envelope → snapshot normalization", () => {
  it("keeps only the rf./sec. state_observed event types (registry-derived filter)", () => {
    const items = [
      rfEnvelope({ journal_seq: 1 }),
      rfEnvelope({ event_type: "fault.injected", journal_seq: 2 }),
      rfEnvelope({ event_type: "sec.state_observed", journal_seq: 3, correlation: { node_id: "lnb-0" } }),
      rfEnvelope({ event_type: "gen.ts_packet_stream", journal_seq: 4 }),
    ];
    const snapshots = extractStateObservedSnapshots(items);
    expect(snapshots.map((s) => s.event_type)).toEqual(["rf.state_observed", "sec.state_observed"]);
    expect(snapshots.map((s) => s.journal_seq)).toEqual([1, 3]);
  });

  it("resolves node_id from correlation and drops items without a string node_id (per-node discipline)", () => {
    const snapshots = extractStateObservedSnapshots([
      rfEnvelope({ correlation: { node_id: "tuner-a", port_id: "rf_in" } }),
      rfEnvelope({ journal_seq: 11, correlation: null }),
      rfEnvelope({ journal_seq: 12, correlation: {} }),
      rfEnvelope({ journal_seq: 13, correlation: undefined }), // no correlation at all
    ]);
    expect(snapshots).toHaveLength(1);
    expect(snapshots[0]!.node_id).toBe("tuner-a");
  });

  it("carries the payload object verbatim and degrades a missing payload to {}", () => {
    const snapshots = extractStateObservedSnapshots([rfEnvelope({}), rfEnvelope({ journal_seq: 14, payload: null })]);
    expect(snapshots[0]!.payload.lock_state).toBe("locked");
    expect(snapshots[1]!.payload).toEqual({});
  });

  it("degrades a non-number journal_seq to null (ordering credential absent)", () => {
    const snapshots = extractStateObservedSnapshots([rfEnvelope({ journal_seq: "not-a-seq" })]);
    expect(snapshots[0]!.journal_seq).toBeNull();
  });
});

describe("snapshotsForNode / latestSnapshotFor — client-side node_id narrowing", () => {
  const snapshots = extractStateObservedSnapshots([
    rfEnvelope({ journal_seq: 10 }),
    rfEnvelope({ journal_seq: 11, payload: { ...(rfEnvelope({ journal_seq: 0 }).payload as Record<string, unknown>), lock_state: "unlocked", health: "error" } }),
    rfEnvelope({ event_type: "sec.state_observed", journal_seq: 12, correlation: { node_id: "lnb-0" } }),
  ]);

  it("narrows to one node's snapshots (the events endpoint has no node_id param — §5 whitelist unchanged)", () => {
    const narrowed = snapshotsForNode(snapshots, "tuner-a");
    expect(narrowed).toHaveLength(2);
    expect(narrowed.every((s) => s.node_id === "tuner-a")).toBe(true);
    expect(snapshotsForNode(snapshots, "sw-0")).toEqual([]);
  });

  it("latest = max journal_seq; null-seq items never outrank sequenced ones", () => {
    expect(latestSnapshotFor(snapshots, "tuner-a")!.journal_seq).toBe(11);
    expect(latestSnapshotFor(snapshots, "tuner-a")!.payload.lock_state).toBe("unlocked");
    const withNullSeq = [
      ...snapshots,
      ...extractStateObservedSnapshots([rfEnvelope({ journal_seq: null, payload: { health: "idle" } })]),
    ];
    expect(latestSnapshotFor(withNullSeq, "tuner-a")!.journal_seq).toBe(11);
    expect(latestSnapshotFor(snapshots, "sw-0")).toBeUndefined();
  });
});

describe("buildNodeStatusMap — per-node card summary (health + registry-keyed metrics source)", () => {
  it("maps each node to its latest snapshot health and metrics (envelope keys stripped)", () => {
    const snapshots = extractStateObservedSnapshots([
      rfEnvelope({ journal_seq: 10 }),
      rfEnvelope({
        journal_seq: 11,
        payload: {
          node_id: "tuner-a",
          health: "error",
          causes: [{ node_id: "lnb-0" }],
          source: "state_evaluator",
          confidence: "simulated",
          lock_state: "unlocked",
          ber_state: "severe",
        },
      }),
      rfEnvelope({
        event_type: "sec.state_observed",
        journal_seq: 12,
        correlation: { node_id: "lnb-0" },
        payload: {
          node_id: "lnb-0",
          health: "warn",
          causes: [],
          source: "state_evaluator",
          confidence: "simulated",
          voltage: "13V",
          tone_actual: "continuous",
          band_selected: "high",
        },
      }),
    ]);
    const map = buildNodeStatusMap(snapshots);
    expect(map.get("tuner-a")).toEqual({
      health: "error",
      metrics: { lock_state: "unlocked", ber_state: "severe" },
    });
    expect(map.get("lnb-0")).toEqual({
      health: "warn",
      metrics: { voltage: "13V", tone_actual: "continuous", band_selected: "high" },
    });
  });

  it("exposes the stripped envelope-key set (node_id/health/causes/source/confidence ride dedicated faces)", () => {
    expect(STATE_OBSERVED_ENVELOPE_KEYS).toEqual(["node_id", "health", "causes", "source", "confidence"]);
  });

  it("an empty snapshot list yields an empty map (idle canvas unchanged)", () => {
    expect(buildNodeStatusMap([]).size).toBe(0);
  });
});

describe("mergeSnapshotItems — REST page + journal tail dedup (journal_seq is the identity)", () => {
  it("deduplicates a journal frame repeating a REST item's journal_seq", () => {
    const rest = [rfEnvelope({ journal_seq: 10 })];
    const journal = [rfEnvelope({ journal_seq: 10 }), rfEnvelope({ journal_seq: 11 })];
    const merged = mergeSnapshotItems(rest, journal);
    expect(merged.map((s) => s.journal_seq)).toEqual([10, 11]);
  });

  it("orders merged snapshots by journal_seq ascending regardless of source order", () => {
    const merged = mergeSnapshotItems(
      [rfEnvelope({ journal_seq: 30 })],
      [rfEnvelope({ journal_seq: 12 }), rfEnvelope({ journal_seq: 21 })],
    );
    expect(merged.map((s) => s.journal_seq)).toEqual([12, 21, 30]);
  });

  it("keeps unsequenced snapshots (seq null) without colliding on the dedup key", () => {
    const merged = mergeSnapshotItems(
      [rfEnvelope({ journal_seq: null, payload: { health: "idle" } })],
      [rfEnvelope({ journal_seq: null, payload: { health: "idle" } })],
    );
    expect(merged).toHaveLength(2);
  });
});

describe("renderMetricValue — wire-value verbatim presentation (no enum aliasing)", () => {
  it("renders strings/numbers/booleans via String() and null as null", () => {
    expect(renderMetricValue("locked")).toBe("locked");
    expect(renderMetricValue("13V")).toBe("13V");
    expect(renderMetricValue(1250000)).toBe("1250000");
    expect(renderMetricValue(false)).toBe("false");
    expect(renderMetricValue(null)).toBe("null");
  });

  it("renders structured metrics (ub_assignments table) as canonical JSON", () => {
    expect(renderMetricValue({ protocol: "EN50494" })).toBe('{"protocol":"EN50494"}');
    expect(renderMetricValue([1, 2])).toBe("[1,2]");
  });
});
