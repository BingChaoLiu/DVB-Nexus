// Editor draft-state seam tests (SPEC-401 §4.3/§5.2/§7.1/§7.4). The reducer
// is the canvas's application state owner (ADR-0009 decision-4 controlled
// mode) — these tests pin the draft/save/validation contract without
// rendering React Flow.
import { describe, expect, it } from "vitest";

import type { TopologyDTO, TopologyViolationDTO } from "../../api/endpoints/topologies";
import type { TopologyFlowNode } from "./graphMapping";
import {
  createNodeFromType,
  editorReducer,
  initialEditorState,
  type EditorAction,
  type EditorState,
} from "./editorState";

function topologyFixture(): TopologyDTO {
  return {
    topology_id: "5f0e3d5e-1e2d-4c3b-9a8f-6b5a4c3d2e1f",
    revision: 2,
    nodes: [
      {
        node_id: "gen-0",
        node_type: "ts_generator",
        config: {},
        ports: [{ port_id: "ts_out", direction: "output", plane: "MPEG_TS", max_connections: 1 }],
      },
      {
        node_id: "mon-0",
        node_type: "ts_monitor",
        config: {},
        ports: [{ port_id: "ts_in", direction: "input", plane: "MPEG_TS", max_connections: 1 }],
      },
    ],
    connections: [
      { connection_id: "conn-0", from_node: "gen-0", from_port: "ts_out", to_node: "mon-0", to_port: "ts_in", plane: "MPEG_TS" },
    ],
  };
}

describe("draft lifecycle", () => {
  it("starts as an unsaved empty draft", () => {
    const state = initialEditorState();
    expect(state.topologyId).toBeNull();
    expect(state.revision).toBeNull();
    expect(state.dirty).toBe(false);
    expect(state.nodes).toEqual([]);
    expect(state.connections).toEqual([]);
  });

  it("newDraft resets to the fresh unsaved shape", () => {
    const loaded = editorReducer(initialEditorState(), { type: "newDraft" });
    expect(loaded.topologyId).toBeNull();
    expect(loaded.revision).toBeNull();
  });

  it("loaded hydrates from the wire and clears dirty", () => {
    const state = editorReducer(initialEditorState(), { type: "loaded", topology: topologyFixture() });
    expect(state.topologyId).toBe(topologyFixture().topology_id);
    expect(state.revision).toBe(2);
    expect(state.dirty).toBe(false);
    expect(state.nodes.map((n) => n.id)).toEqual(["gen-0", "mon-0"]);
    expect(state.connections[0]!.sourceHandle).toBe("ts_out"); // Handle id = port_id
  });
});

describe("drop → node creation (REQ-UI-401-002/004)", () => {
  it("createNodeFromType generates the registry template ports and a deterministic slug", () => {
    const node = createNodeFromType("ts_mux", { x: 120, y: 80 }, []);
    expect(node.id).toBe("mux-0");
    expect(node.type).toBe("topology");
    expect(node.position).toEqual({ x: 120, y: 80 });
    expect(node.data.node.ports).toEqual([
      { port_id: "ts_in_1", direction: "input", plane: "MPEG_TS", max_connections: 1 },
      { port_id: "ts_in_2", direction: "input", plane: "MPEG_TS", max_connections: 1 },
      { port_id: "ts_out", direction: "output", plane: "MPEG_TS", max_connections: 1 },
    ]);
    expect(node.data.node.config).toEqual({});
    expect(node.data.violationCodes).toEqual([]);
  });

  it("the next drop skips taken ordinals", () => {
    const first = createNodeFromType("ts_generator", { x: 0, y: 0 }, []);
    const second = createNodeFromType("ts_generator", { x: 10, y: 10 }, [first]);
    expect(second.id).toBe("gen-1");
  });
});

describe("draft edits mark dirty (controlled mode change intents)", () => {
  const base = editorReducer(initialEditorState(), { type: "newDraft" });

  it("a position change marks the draft dirty", () => {
    const withNode = editorReducer(base, {
      type: "nodeAdded",
      node: createNodeFromType("ts_generator", { x: 0, y: 0 }, []),
    });
    const state = editorReducer(withNode, {
      type: "nodesChanged",
      changes: [{ id: "gen-0", type: "position", position: { x: 50, y: 60 } } as never],
    });
    expect(state.dirty).toBe(true);
    expect(state.nodes[0]!.position).toEqual({ x: 50, y: 60 });
  });

  it("a selection-only change does NOT mark the draft dirty", () => {
    const loaded = editorReducer(initialEditorState(), { type: "loaded", topology: topologyFixture() });
    expect(loaded.dirty).toBe(false);
    const state = editorReducer(loaded, {
      type: "nodesChanged",
      changes: [{ id: "gen-0", type: "select", selected: true } as never],
    });
    expect(state.dirty).toBe(false);
  });

  it("an edge removal marks the draft dirty", () => {
    const loaded = editorReducer(initialEditorState(), { type: "loaded", topology: topologyFixture() });
    const state = editorReducer(loaded, { type: "edgesChanged", changes: [{ id: "conn-0", type: "remove" } as never] });
    expect(state.dirty).toBe(true);
    expect(state.connections).toEqual([]);
  });
});

describe("connect flow (REQ-UI-401-003)", () => {
  it("connected appends a deterministic four-tuple edge and marks dirty", () => {
    let state = editorReducer(initialEditorState(), { type: "newDraft" });
    state = editorReducer(state, { type: "nodeAdded", node: createNodeFromType("ts_generator", { x: 0, y: 0 }, state.nodes) });
    state = editorReducer(state, { type: "nodeAdded", node: createNodeFromType("ts_monitor", { x: 10, y: 10 }, state.nodes) });
    state = editorReducer(state, {
      type: "connected",
      connection: { connection_id: "conn-0", from_node: "gen-0", from_port: "ts_out", to_node: "mon-0", to_port: "ts_in", plane: "MPEG_TS" },
    });
    expect(state.dirty).toBe(true);
    expect(state.connections[0]).toMatchObject({
      id: "conn-0",
      source: "gen-0",
      sourceHandle: "ts_out",
      target: "mon-0",
      targetHandle: "ts_in",
    });
    expect(state.connections[0]!.data!.connection).toEqual({
      connection_id: "conn-0",
      from_node: "gen-0",
      from_port: "ts_out",
      to_node: "mon-0",
      to_port: "ts_in",
      plane: "MPEG_TS",
    });
  });
});

describe("save flow (REQ-UI-401-007; §7.4 fixed third step)", () => {
  it("saveSucceeded from a POST pins the server id and revision 1 and clears dirty", () => {
    const withNode = editorReducer(initialEditorState(), { type: "nodeAdded", node: createNodeFromType("ts_generator", { x: 0, y: 0 }, []) });
    const state = editorReducer(withNode, {
      type: "saveSucceeded",
      topologyId: "9a8b-uuid",
      revision: 1,
    });
    expect(state.topologyId).toBe("9a8b-uuid");
    expect(state.revision).toBe(1);
    expect(state.dirty).toBe(false);
    expect(state.error).toBeNull();
  });

  it("saveFailed keeps the draft dirty and surfaces the error", () => {
    const withNode = editorReducer(initialEditorState(), { type: "nodeAdded", node: createNodeFromType("ts_generator", { x: 0, y: 0 }, []) });
    const state = editorReducer(withNode, {
      type: "saveFailed",
      error: { errorCode: "HTTP_501", message: "Not Implemented" },
    });
    expect(state.dirty).toBe(true);
    expect(state.error).toEqual({ errorCode: "HTTP_501", message: "Not Implemented" });
  });
});

describe("validation display (REQ-UI-401-006; §7.4 mapping applied to the draft)", () => {
  const violations: TopologyViolationDTO[] = [
    { code: "SIM_TOPO_DUPLICATE_ID", path: "nodes[gen-0]", message: "declared twice" },
    { code: "SIM_TOPO_CARDINALITY", path: "nodes[mon-0].ports[ts_in]", message: "above max_connections=1" },
    { code: "SIM_TOPO_MEDIA_INCOMPATIBLE", path: "connections[conn-0]", message: "plane mismatch" },
    { code: "SIM_TOPO_CYCLE", path: "topology", message: "cycle" },
  ];

  it("validationSucceeded maps entries and flags nodes/ports/edges in place", () => {
    const state = editorReducer(
      editorReducer(initialEditorState(), { type: "loaded", topology: topologyFixture() }),
      { type: "validationSucceeded", violations },
    );
    const gen = state.nodes.find((n) => n.id === "gen-0")!;
    const mon = state.nodes.find((n) => n.id === "mon-0")!;
    expect(gen.data.violationCodes).toEqual(["SIM_TOPO_DUPLICATE_ID"]);
    expect(mon.data.violationCodes).toEqual(["SIM_TOPO_CARDINALITY"]); // port violations light the node too
    expect(mon.data.violationPorts).toEqual(["ts_in"]);
    expect(state.connections[0]!.data!.violation).toBe(true);
    expect(state.connections[0]!.className).toBe("dvb-topo-edge-violation"); // §7.4 edge highlight
    expect(state.validation.entries.map((e) => e.code)).toEqual(violations.map((v) => v.code));
    expect(state.validation.graphEntries.map((e) => e.code)).toEqual(["SIM_TOPO_CYCLE"]);
    expect(state.validation.status).toBe("done");
  });

  it("a clean report clears previous highlight flags", () => {
    const flagged = editorReducer(
      editorReducer(initialEditorState(), { type: "loaded", topology: topologyFixture() }),
      { type: "validationSucceeded", violations },
    );
    const state = editorReducer(flagged, { type: "validationSucceeded", violations: [] });
    for (const n of state.nodes) {
      expect(n.data.violationCodes).toEqual([]);
      expect(n.data.violationPorts).toEqual([]);
    }
    for (const e of state.connections) {
      expect(e.data!.violation).toBe(false);
    }
    expect(state.validation.status).toBe("done");
  });
});

describe("run prepare 422 same-channel (§7.5)", () => {
  it("planErrors maps error strings with node mentions", () => {
    const state = editorReducer(
      editorReducer(initialEditorState(), { type: "loaded", topology: topologyFixture() }),
      { type: "planErrors", errors: ["fault_plan[0].target_id: mon-0:pid:0x0100 ..."] },
    );
    expect(state.validation.planErrors).toEqual([
      { source: "run_prepare", message: "fault_plan[0].target_id: mon-0:pid:0x0100 ...", nodeIds: ["mon-0"] },
    ]);
  });
});

export type { EditorAction, EditorState, TopologyFlowNode };
