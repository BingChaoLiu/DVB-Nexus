// gen.* event consumption contract (SPEC-406 §Phase2 只读折叠区; SPEC-303
// §Phase2 payload key sets — triple-pinned: #128 REPORT keys + #129 registry
// validator + brief §5-9). The journal REST face answers loose envelope
// records (`EventsDataDTO.items` is outside OpenAPI typing), so this module
// owns the defensive parse: wire enums rendered verbatim, malformed rows
// skipped (honest absence, never fabricated), and the layer→inspector-view
// mapping (#132 string contract — Lab only builds the URL parameter string).
import { describe, expect, it } from "vitest";

import {
  GEN_EVENT_TYPES,
  layerToInspectorView,
  parseGenEvents,
  resolveJumpTarget,
  type GenRunFace,
} from "./genEvents";

const SHA = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2";

/** Journal-shaped envelope record (the subset the fold consumes). */
function envelope(eventType: string, payload: Record<string, unknown>, seq: number, runId?: string) {
  return {
    journal_seq: seq,
    event_type: eventType,
    severity: "info",
    payload,
    scope: { session_id: "s-1", run_id: runId ?? null },
  };
}

describe("parseGenEvents — stage progress rows", () => {
  it("derives one row per layer in chain order with verbatim wire layer strings", () => {
    const items = [
      envelope("gen.stage_started", { layer: "TS" }, 1),
      envelope("gen.stage_completed", { layer: "TS", item_count: 188 }, 2),
      envelope("gen.stage_started", { layer: "BBFRAME" }, 3),
      envelope("gen.stage_completed", { layer: "BBFRAME", item_count: 12 }, 4),
      envelope("gen.stage_started", { layer: "T2MI" }, 5),
    ];
    const face = parseGenEvents(items);
    expect(face.stages.map((stage) => stage.layer)).toEqual(["TS", "BBFRAME", "T2MI"]);
    expect(face.stages[0]).toMatchObject({ state: "completed", itemCount: 188 });
    expect(face.stages[1]).toMatchObject({ state: "completed", itemCount: 12 });
    expect(face.stages[2]).toMatchObject({ state: "started", itemCount: null });
  });

  it("orders known layers in contribution chain order (TS → BISS → BBFRAME → T2MI) regardless of arrival order", () => {
    const items = [
      envelope("gen.stage_started", { layer: "T2MI" }, 1),
      envelope("gen.stage_started", { layer: "BISS" }, 2),
    ];
    const face = parseGenEvents(items);
    expect(face.stages.map((stage) => stage.layer)).toEqual(["BISS", "T2MI"]);
  });

  it("last event per layer wins (a re-started layer flips back to started)", () => {
    const items = [
      envelope("gen.stage_completed", { layer: "TS", item_count: 10 }, 1),
      envelope("gen.stage_started", { layer: "TS" }, 2),
    ];
    const face = parseGenEvents(items);
    expect(face.stages).toEqual([{ layer: "TS", state: "started", itemCount: null }]);
  });
});

describe("parseGenEvents — sampled packet cards", () => {
  it("carries layer/packet_index/byte_size/sha256 verbatim plus the run attribution", () => {
    const items = [
      envelope(
        "gen.packet_sampled",
        { layer: "T2MI", packet_index: 3, byte_size: 194, sha256: SHA },
        7,
        "run-1",
      ),
    ];
    const face = parseGenEvents(items);
    expect(face.samples).toEqual([
      { journalSeq: 7, runId: "run-1", layer: "T2MI", packetIndex: 3, byteSize: 194, sha256: SHA },
    ]);
  });

  it("sorts samples by journal_seq (the per-session full order) regardless of arrival order", () => {
    const items = [
      envelope("gen.packet_sampled", { layer: "TS", packet_index: 2, byte_size: 188, sha256: SHA }, 9),
      envelope("gen.packet_sampled", { layer: "TS", packet_index: 0, byte_size: 188, sha256: SHA }, 8),
    ];
    const face = parseGenEvents(items);
    expect(face.samples.map((sample) => sample.journalSeq)).toEqual([8, 9]);
  });
});

describe("parseGenEvents — honest absence (malformed rows are skipped, never fabricated)", () => {
  it("ignores foreign namespaces and unparseable gen.* rows", () => {
    const items = [
      envelope("fault.applied", { fault_id: "f1" }, 1),
      envelope("gen.stage_started", { layer: 42 }, 2), // layer must be a string
      envelope("gen.stage_completed", { layer: "TS" }, 3), // missing item_count
      envelope("gen.stage_completed", { layer: "TS", item_count: "many" }, 4),
      envelope("gen.packet_sampled", { layer: "TS", packet_index: -1, byte_size: 188, sha256: SHA }, 5),
      envelope("gen.packet_sampled", { layer: "TS", packet_index: 0, byte_size: 188, sha256: "zz" }, 6),
      envelope("gen.packet_sampled", { layer: "TS", packet_index: 0, byte_size: 188 }, 7), // missing sha256
      "not-an-envelope",
      null,
      undefined,
    ];
    const face = parseGenEvents(items);
    expect(face.stages).toEqual([]);
    expect(face.samples).toEqual([]);
  });

  it("answers the empty honest face for zero items", () => {
    expect(parseGenEvents([])).toEqual({ stages: [], samples: [] });
  });
});

describe("layerToInspectorView — the layer→view mapping (dispatch: T2MI→t2mi, BBFRAME→bbframe, BISS/TS→ts)", () => {
  it("maps the four wire layers into the #132 view vocabulary", () => {
    expect(layerToInspectorView("T2MI")).toBe("t2mi");
    expect(layerToInspectorView("BBFRAME")).toBe("bbframe");
    expect(layerToInspectorView("TS")).toBe("ts");
    expect(layerToInspectorView("BISS")).toBe("ts");
  });

  it("falls back to the MVP default ts for unknown layers (never a fabricated view)", () => {
    expect(layerToInspectorView("RFCRYPTO")).toBe("ts");
  });

  it("keeps the gen.* query filter exactly the three registered wire types", () => {
    expect(GEN_EVENT_TYPES).toEqual(["gen.stage_started", "gen.stage_completed", "gen.packet_sampled"]);
  });
});

describe("resolveJumpTarget — run-face artifact resolution for the inspector deep link", () => {
  const runs: GenRunFace[] = [
    {
      runId: "run-1",
      artifacts: [
        { artifact_id: "art-log", kind: "log" },
        { artifact_id: "art-faulted", kind: "faulted_ts" },
      ],
    },
    { runId: "run-2", artifacts: [{ artifact_id: "art-baseline", kind: "generated_ts" }] },
  ];

  it("resolves the sample's run layered transmission artifact (faulted_ts preferred) with pid 0 and the mapped view", () => {
    const face = parseGenEvents([
      envelope("gen.packet_sampled", { layer: "T2MI", packet_index: 5, byte_size: 194, sha256: SHA }, 1, "run-1"),
    ]);
    const target = resolveJumpTarget(face.samples[0]!, runs);
    expect(target).toEqual({ artifactId: "art-faulted", pid: 0, packetIndex: 5, view: "t2mi" });
  });

  it("falls back to generated_ts when the run carried no faulted leg", () => {
    const face = parseGenEvents([
      envelope("gen.packet_sampled", { layer: "BBFRAME", packet_index: 1, byte_size: 1000, sha256: SHA }, 1, "run-2"),
    ]);
    const target = resolveJumpTarget(face.samples[0]!, runs);
    expect(target).toEqual({ artifactId: "art-baseline", pid: 0, packetIndex: 1, view: "bbframe" });
  });

  it("answers null when the run is unknown to the console registry (no fabricated locator)", () => {
    const face = parseGenEvents([
      envelope("gen.packet_sampled", { layer: "TS", packet_index: 0, byte_size: 188, sha256: SHA }, 1, "run-unknown"),
    ]);
    expect(resolveJumpTarget(face.samples[0]!, runs)).toBeNull();
  });
});
