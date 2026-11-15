// SPEC-402 §7.6 / §11 (TV-402-06) three-part joint gate truth table + the
// configApplied additive editorState behavior (consumed via the real reducer
// import — the #62 file itself is untouched; the test lives on the #63 side).
import { describe, expect, it } from "vitest";

import { editorReducer, initialEditorState } from "../editorState";
import { computeInspectorGate, type GateInput } from "./inspectorGate";

function gateInput(overrides: Partial<GateInput> = {}): GateInput {
  return {
    nodes: [],
    validation: { status: "idle", entries: [], graphEntries: [], planErrors: [] },
    fieldErrors: [],
    ...overrides,
  };
}

function generatorNode(config: unknown) {
  return { node_id: "gen-0", node_type: "ts_generator", config };
}

describe("computeInspectorGate (SPEC-402 §7.6, TV-402-06)", () => {
  it("passes on a clean draft (2^3 clean corner: no nodes, idle validation, no field errors)", () => {
    expect(computeInspectorGate(gateInput()).reasons).toEqual([]);
  });

  // --- G1 completeness (edit-state statement, 配置待填) -----------------------

  it("G1: an empty generator config blocks with config_incomplete naming the node", () => {
    const result = computeInspectorGate(gateInput({ nodes: [generatorNode({})] }));
    expect(result.reasons).toEqual([{ kind: "config_incomplete", nodeIds: ["gen-0"] }]);
  });

  it("G1: a filled generator config passes", () => {
    const config = {
      schema_version: 1,
      seed: 1,
      initial_media_clock_27mhz: 0,
      target_bitrate_bps: 3008000,
      output_packet_count: 1000,
      program: { transport_stream_id: 1, program_number: 1, pmt_pid: 4096, pcr_pid: 256, version_number: 0, streams: [] },
    };
    expect(computeInspectorGate(gateInput({ nodes: [generatorNode(config)] })).reasons).toEqual([]);
  });

  it("G1: config_schema=null node types are trivially complete even with opaque {}", () => {
    expect(
      computeInspectorGate(
        gateInput({
          nodes: [
            { node_id: "mux-0", node_type: "ts_mux", config: {} },
            { node_id: "mon-0", node_type: "ts_monitor", config: undefined },
          ],
        }),
      ).reasons,
    ).toEqual([]);
  });

  it("G1: names every incomplete generator node", () => {
    const result = computeInspectorGate(
      gateInput({ nodes: [generatorNode({}), { node_id: "gen-1", node_type: "ts_generator", config: {} }] }),
    );
    expect(result.reasons).toEqual([{ kind: "config_incomplete", nodeIds: ["gen-0", "gen-1"] }]);
  });

  // --- G2 structural validation report (server report via #62 editorState) ----

  it("G2: idle validation never blocks (unsaved draft — no server report exists yet)", () => {
    const result = computeInspectorGate(gateInput({ validation: { status: "idle", entries: [], graphEntries: [], planErrors: [] } }));
    expect(result.reasons).toEqual([]);
  });

  it("G2: a done report with violations blocks with structural_violations", () => {
    const result = computeInspectorGate(
      gateInput({
        validation: {
          status: "done",
          entries: [{ code: "SIM_PLANE_DISABLED", path: "connections[conn-1]", message: "x" }],
          graphEntries: [],
          planErrors: [],
        },
      }),
    );
    expect(result.reasons).toEqual([{ kind: "structural_violations" }]);
  });

  it("G2: a done report with only graph-level entries blocks the same way", () => {
    const result = computeInspectorGate(
      gateInput({
        validation: {
          status: "done",
          entries: [],
          graphEntries: [{ code: "SIM_TOPO_CYCLE", path: "topology", message: "cycle" }],
          planErrors: [],
        },
      }),
    );
    expect(result.reasons).toEqual([{ kind: "structural_violations" }]);
  });

  it("G2: a done report with only planErrors blocks the same way", () => {
    const result = computeInspectorGate(
      gateInput({
        validation: {
          status: "done",
          entries: [],
          graphEntries: [],
          planErrors: [{ source: "run_prepare", message: "program.streams[0].pid invalid", nodeIds: [] }],
        },
      }),
    );
    expect(result.reasons).toEqual([{ kind: "structural_violations" }]);
  });

  it("G2: a done empty report (无违规) passes", () => {
    const result = computeInspectorGate(
      gateInput({ validation: { status: "done", entries: [], graphEntries: [], planErrors: [] } }),
    );
    expect(result.reasons).toEqual([]);
  });

  // --- G3 field errors ---------------------------------------------------------

  it("G3: displayed field errors block with field_errors", () => {
    const fieldErrors = [{ nodeId: "gen-0", fieldPath: "target_bitrate_bps", message: "…loc msg…" }];
    expect(computeInspectorGate(gateInput({ fieldErrors })).reasons).toEqual([{ kind: "field_errors" }]);
  });

  // --- conjunction -------------------------------------------------------------

  it("combines all three independently (G1+G2+G3 all firing → three reasons)", () => {
    const result = computeInspectorGate(
      gateInput({
        nodes: [generatorNode({})],
        validation: {
          status: "done",
          entries: [{ code: "X", path: "nodes[gen-0]", message: "m" }],
          graphEntries: [],
          planErrors: [],
        },
        fieldErrors: [{ nodeId: "gen-0", fieldPath: null, message: "m" }],
      }),
    );
    expect(result.reasons.map((r) => r.kind)).toEqual(["config_incomplete", "structural_violations", "field_errors"]);
  });
});

// --- configApplied additive action (approved wiring ①) -------------------------

describe("editorState configApplied (approved additive action, SPEC-402 §4.2)", () => {
  it("writes the config onto the target node and marks the draft dirty", () => {
    let state = initialEditorState();
    state = editorReducer(state, { type: "nodeAdded", node: {
      id: "gen-0",
      type: "topology",
      position: { x: 0, y: 0 },
      data: { node: { node_id: "gen-0", node_type: "ts_generator", config: {}, ports: [] }, violationCodes: [], violationPorts: [] },
    } });
    state = editorReducer(state, { type: "configApplied", nodeId: "gen-0", config: { seed: 7 } });
    expect(state.dirty).toBe(true);
    expect(state.nodes[0]!.data.node.config).toEqual({ seed: 7 });
    expect(state.nodes).toHaveLength(1); //定点更新 — no duplicate
  });

  it("leaves other nodes untouched (unknown nodeId is a no-op, still total)", () => {
    let state = initialEditorState();
    state = editorReducer(state, { type: "configApplied", nodeId: "ghost", config: { seed: 7 } });
    expect(state.nodes).toEqual([]);
    expect(state.dirty).toBe(false);
  });
});
