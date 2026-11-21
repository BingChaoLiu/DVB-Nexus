// Connection feedback state machine tests (SPEC-408 §4.5 item 4 / §7.6).
// The machine is pure: it turns RF connection-attempt callbacks into the
// canvas preview marker (非法把手降透明度 CSS hook) and the one-line toolbar
// rejection reason (落空提示). Expected reason strings are the §7.6 spec
// literals byte-exact — the page renders them verbatim (约 4 秒自动消失).
import { describe, expect, it } from "vitest";

import { explainConnection, fromWire, type TopologyFlowEdge, type TopologyFlowNode } from "./graphMapping";
import {
  CONNECTION_HINT_VISIBLE_MS,
  connectionAttempted,
  connectionStarted,
  idleConnectionFeedback,
  illegalEndHandles,
  illegalHandleKey,
  type ConnectionAttempt,
} from "./connectionFeedback";

const draft = fromWire({
  topology_id: "t",
  revision: 1,
  nodes: [
    {
      node_id: "gen-0",
      node_type: "ts_generator",
      config: {},
      ports: [{ port_id: "ts_out", direction: "output", plane: "MPEG_TS", max_connections: 1 }],
    },
    {
      node_id: "mux-0",
      node_type: "ts_mux",
      config: {},
      ports: [
        { port_id: "ts_in_1", direction: "input", plane: "MPEG_TS", max_connections: 1 },
        { port_id: "ts_in_2", direction: "input", plane: "MPEG_TS", max_connections: 1 },
        { port_id: "ts_out", direction: "output", plane: "MPEG_TS", max_connections: 1 },
      ],
    },
    {
      node_id: "mon-0",
      node_type: "ts_monitor",
      config: {},
      ports: [{ port_id: "ts_in", direction: "input", plane: "MPEG_TS", max_connections: 1 }],
    },
  ],
  connections: [
    { connection_id: "conn-0", from_node: "gen-0", from_port: "ts_out", to_node: "mux-0", to_port: "ts_in_1", plane: "MPEG_TS" },
  ],
});

const attempt = (nodeId: string, handleId: string, handleType: "source" | "target"): ConnectionAttempt => ({
  nodeId,
  handleId,
  handleType,
});

describe("connectionStarted — drag/click-connect preview marker", () => {
  it("records the origin handle type and clears any standing rejection", () => {
    const standing = { connectingFrom: null, connecting: null, rejection: "不能连回同一端口", attempt: 3 };
    const next = connectionStarted(standing, attempt("gen-0", "ts_out", "source"));
    expect(next).toEqual({
      connectingFrom: "source",
      connecting: { nodeId: "gen-0", handleId: "ts_out", handleType: "source" },
      rejection: null,
      attempt: 3,
    });
  });

  it("records a target-type origin (drag started from an input handle)", () => {
    const next = connectionStarted(idleConnectionFeedback, attempt("mon-0", "ts_in", "target"));
    expect(next.connectingFrom).toBe("target");
  });
});

describe("connectionAttempted — the §7.6 one-line reason, mapped from the four prechecks", () => {
  const graph = { nodes: draft.nodes as TopologyFlowNode[], connections: draft.connections as TopologyFlowEdge[] };

  it("direction rejection (input dragged onto an output) → 方向不符 line", () => {
    const feedback = connectionAttempted(
      connectionStarted(idleConnectionFeedback, attempt("mux-0", "ts_in_2", "source")),
      attempt("mux-0", "ts_in_2", "source"),
      attempt("gen-0", "ts_out", "target"),
      graph,
    );
    expect(feedback.rejection).toBe("方向不符（需 输出/双向 → 输入/双向）");
    expect(feedback.connectingFrom).toBeNull();
  });

  it("self loop → 不能连回同一端口", () => {
    const feedback = connectionAttempted(
      connectionStarted(idleConnectionFeedback, attempt("mux-0", "ts_out", "source")),
      attempt("mux-0", "ts_out", "source"),
      attempt("mux-0", "ts_out", "target"),
      graph,
    );
    // direction fires first for registry ports (output is not target-capable);
    // the §7.6 self-loop line surfaces for direction-capable stored rows —
    // exercised exhaustively in graphMapping.test.ts.
    expect(["不能连回同一端口", "方向不符（需 输出/双向 → 输入/双向）"]).toContain(feedback.rejection);
  });

  it("cardinality rejection names the full port (source side used)", () => {
    const feedback = connectionAttempted(
      connectionStarted(idleConnectionFeedback, attempt("gen-0", "ts_out", "source")),
      attempt("gen-0", "ts_out", "source"),
      attempt("mon-0", "ts_in", "target"),
      graph,
    );
    expect(feedback.rejection).toBe("“ts_out”连接数已满（上限 1）");
  });

  it("start from a TARGET handle swaps the ends (input grabbed first, dropped on an output)", () => {
    const feedback = connectionAttempted(
      connectionStarted(idleConnectionFeedback, attempt("mon-0", "ts_in", "target")),
      attempt("mon-0", "ts_in", "target"),
      attempt("mux-0", "ts_out", "source"),
      graph,
    );
    // mux.ts_out (output) → mon.ts_in (input) is LEGAL once the ends are
    // normalized — the machine maps start-type target ↔ end-type source.
    expect(feedback.rejection).toBeNull();
    expect(feedback.connectingFrom).toBeNull();
  });

  it("cardinality rejection via a target-type start (into the occupied ts_in_1)", () => {
    const feedback = connectionAttempted(
      connectionStarted(idleConnectionFeedback, attempt("mux-0", "ts_in_1", "target")),
      attempt("mux-0", "ts_in_1", "target"),
      attempt("mux-0", "ts_out", "source"),
      graph,
    );
    // normalized: mux.ts_out → mux.ts_in_1 — ts_in_1 already carries conn-0.
    expect(feedback.rejection).toBe("“ts_in_1”连接数已满（上限 1）");
  });

  it("a legal connection produces no rejection and clears the preview", () => {
    const feedback = connectionAttempted(
      connectionStarted(idleConnectionFeedback, attempt("mux-0", "ts_out", "source")),
      attempt("mux-0", "ts_out", "source"),
      attempt("mon-0", "ts_in", "target"),
      graph,
    );
    expect(feedback.rejection).toBeNull();
    expect(feedback.connectingFrom).toBeNull();
  });

  it("dropped on the pane (no end handle) → preview off, standing rejection untouched", () => {
    const standing = {
      connectingFrom: "source" as const,
      connecting: attempt("gen-0", "ts_out", "source"),
      rejection: "平面不符（当前支持 MPEG_TS / T2MI / RF / SEC_CONTROL）",
      attempt: 1,
    };
    const feedback = connectionAttempted(standing, attempt("gen-0", "ts_out", "source"), null, graph);
    expect(feedback).toEqual({
      connectingFrom: null,
      connecting: null,
      rejection: "平面不符（当前支持 MPEG_TS / T2MI / RF / SEC_CONTROL）",
      attempt: 1,
    });
  });

  it("no start in flight is a no-op (defensive; RF never ends what it never started)", () => {
    const feedback = connectionAttempted(
      idleConnectionFeedback,
      null,
      attempt("gen-0", "ts_out", "source"),
      graph,
    );
    expect(feedback).toBe(idleConnectionFeedback);
  });

  it("each attempt advances the sequence counter (remounts the hint → fresh window)", () => {
    const started = connectionStarted(idleConnectionFeedback, attempt("gen-0", "ts_out", "source"));
    const first = connectionAttempted(started, attempt("gen-0", "ts_out", "source"), attempt("mon-0", "ts_in", "target"), graph);
    const second = connectionAttempted(
      connectionStarted(first, attempt("gen-0", "ts_out", "source")),
      attempt("gen-0", "ts_out", "source"),
      attempt("mon-0", "ts_in", "target"),
      graph,
    );
    expect(second.attempt).toBeGreaterThan(first.attempt);
  });
});

describe("CONNECTION_HINT_VISIBLE_MS — the §4.5 约 4 秒 auto-dismiss window", () => {
  it("is pinned at 4000 ms", () => {
    expect(CONNECTION_HINT_VISIBLE_MS).toBe(4000);
  });
});

// SPEC-401 §Phase2: with MVP_ENABLED_PLANES = ["MPEG_TS","T2MI"] the machine
// walks the three-level encapsulation chain (三级封装) rejection-free — the
// T2MI link enc.t2mi_out → dmx.t2mi_in passes the plane precheck like any
// other, with BBFrame kept a node-internal layer (never named as a plane).
describe("Phase 2 chain feedback (T2MI links admitted by the mirrored plane set)", () => {
  const t2miDraft = fromWire({
    topology_id: "t",
    revision: 1,
    nodes: [
      {
        node_id: "gen-0",
        node_type: "ts_generator",
        config: {},
        ports: [{ port_id: "ts_out", direction: "output", plane: "MPEG_TS", max_connections: 1 }],
      },
      {
        node_id: "enc-0",
        node_type: "t2mi_encapsulator",
        config: {},
        ports: [
          { port_id: "inner_in", direction: "input", plane: "MPEG_TS", max_connections: 1 },
          { port_id: "t2mi_out", direction: "output", plane: "T2MI", max_connections: 1 },
        ],
      },
      {
        node_id: "dmx-0",
        node_type: "t2mi_demux",
        config: {},
        ports: [
          { port_id: "t2mi_in", direction: "input", plane: "T2MI", max_connections: 1 },
          { port_id: "inner_out", direction: "output", plane: "MPEG_TS", max_connections: 1 },
        ],
      },
      {
        node_id: "mon-0",
        node_type: "ts_monitor",
        config: {},
        ports: [{ port_id: "ts_in", direction: "input", plane: "MPEG_TS", max_connections: 1 }],
      },
    ],
    connections: [],
  });
  const graph = { nodes: t2miDraft.nodes as TopologyFlowNode[], connections: t2miDraft.connections as TopologyFlowEdge[] };

  it("walks gen→enc→dmx→mon with zero rejections (planes MPEG_TS / T2MI / MPEG_TS)", () => {
    let feedback = idleConnectionFeedback;
    for (const [sourceId, sourcePort, targetId, targetPort] of [
      ["gen-0", "ts_out", "enc-0", "inner_in"],
      ["enc-0", "t2mi_out", "dmx-0", "t2mi_in"],
      ["dmx-0", "inner_out", "mon-0", "ts_in"],
    ] as const) {
      feedback = connectionAttempted(
        connectionStarted(feedback, attempt(sourceId, sourcePort, "source")),
        attempt(sourceId, sourcePort, "source"),
        attempt(targetId, targetPort, "target"),
        graph,
      );
      expect(feedback.rejection).toBeNull();
    }
    expect(feedback.attempt).toBe(3);
  });

  it("the §7.6 preview keeps non-T2MI and illegal ends dim during an enc.t2mi_out drag", () => {
    const illegal = illegalEndHandles(attempt("enc-0", "t2mi_out", "source"), graph);
    // legal end: the demux T2MI input stays lit…
    expect(illegal.has(illegalHandleKey("dmx-0", "t2mi_in"))).toBe(false);
    // …while every MPEG_TS input dims (plane mismatch under the enabled set)
    // and the origin dims (self-loop rule).
    expect(illegal.has(illegalHandleKey("enc-0", "inner_in"))).toBe(true);
    expect(illegal.has(illegalHandleKey("mon-0", "ts_in"))).toBe(true);
    expect(illegal.has(illegalHandleKey("enc-0", "t2mi_out"))).toBe(true);
  });
});

// §7.6 拖拽预览全量降透明 (review-fix F2): while an attempt is in flight the
// ILLEGAL END set is computed per visible handle from the SAME four prechecks
// canConnect runs — direction / cardinality / plane / self loop ALL enter the
// preview, not just the drag direction. canConnect's signature stays frozen
// (it remains the legality authority); this mapping only reads it.
describe("illegalEndHandles — the four-precheck preview set (§7.6)", () => {
  /** A stored row on a plane OUTSIDE the MVP enablement (the §7.6 plane
   * line's honest face: plane mismatch AND non-enabled both fire —
   * MVP_ENABLED_PLANES pins ["MPEG_TS"], the wire union admits more). */
  const draftWithForeignPlane = fromWire({
    topology_id: "t",
    revision: 1,
    nodes: [
      {
        node_id: "gen-0",
        node_type: "ts_generator",
        config: {},
        ports: [{ port_id: "ts_out", direction: "output", plane: "MPEG_TS", max_connections: 1 }],
      },
      {
        node_id: "legacy-0",
        node_type: "ts_monitor",
        config: {},
        ports: [{ port_id: "rf_in", direction: "input", plane: "RF", max_connections: 5 }],
      },
      {
        node_id: "mon-0",
        node_type: "ts_monitor",
        config: {},
        ports: [{ port_id: "ts_in", direction: "input", plane: "MPEG_TS", max_connections: 1 }],
      },
    ],
    connections: [],
  });
  const emptyGraph = {
    nodes: draftWithForeignPlane.nodes as TopologyFlowNode[],
    connections: draftWithForeignPlane.connections as TopologyFlowEdge[],
  };
  const fromSource = attempt("gen-0", "ts_out", "source");

  it("direction: input handles can end a source-started attempt (lit)", () => {
    const illegal = illegalEndHandles(fromSource, emptyGraph);
    expect(illegal.has(illegalHandleKey("mon-0", "ts_in"))).toBe(false);
  });

  it("self loop: the ORIGIN handle itself is in the set (same node + same port per the §7.6 rule)", () => {
    const illegal = illegalEndHandles(fromSource, emptyGraph);
    expect(illegal.has(illegalHandleKey("gen-0", "ts_out"))).toBe(true);
  });

  it("plane: a non-MPEG_TS (non-enabled) plane handle is in the set even though direction fits", () => {
    const illegal = illegalEndHandles(fromSource, emptyGraph);
    expect(illegal.has(illegalHandleKey("legacy-0", "rf_in"))).toBe(true);
  });

  it("cardinality: a FULL endpoint port puts its handles in the set (source side full → every end dim)", () => {
    const fullGraph = {
      nodes: draft.nodes as TopologyFlowNode[],
      connections: draft.connections as TopologyFlowEdge[],
    };
    // conn-0 already occupies gen-0.ts_out (max 1) → the SOURCE side is full:
    // no end can make the connection legal, so every candidate end is illegal.
    const illegal = illegalEndHandles(fromSource, fullGraph);
    expect(illegal.has(illegalHandleKey("mon-0", "ts_in"))).toBe(true);
    expect(illegal.has(illegalHandleKey("mux-0", "ts_in_2"))).toBe(true);
    // TARGET-side fullness: mux.ts_in_1 carries conn-0; starting from
    // mux.ts_out, ending on mux.ts_in_1 exceeds the target's max.
    const fromMuxSource = attempt("mux-0", "ts_out", "source");
    const illegalTarget = illegalEndHandles(fromMuxSource, fullGraph);
    expect(illegalTarget.has(illegalHandleKey("mux-0", "ts_in_1"))).toBe(true);
    // ...while the free ts_in_2 stays lit.
    expect(illegalTarget.has(illegalHandleKey("mux-0", "ts_in_2"))).toBe(false);
    expect(illegalTarget.has(illegalHandleKey("mon-0", "ts_in"))).toBe(false);
  });

  it("direction (dedicated): an OUTPUT handle is never a legal end for a source-started attempt", () => {
    // The start node must be in the graph for the set to compute.
    const graphWithMux = {
      nodes: (draft.nodes as TopologyFlowNode[]).filter((n) => n.id === "gen-0" || n.id === "mux-0"),
      connections: [],
    };
    const illegalMux = illegalEndHandles(attempt("gen-0", "ts_out", "source"), graphWithMux);
    expect(illegalMux.has(illegalHandleKey("mux-0", "ts_out"))).toBe(true);
    expect(illegalMux.has(illegalHandleKey("mux-0", "ts_in_1"))).toBe(false);
    expect(illegalMux.has(illegalHandleKey("mux-0", "ts_in_2"))).toBe(false);
  });

  it("a target-type start mirrors the ends: only source-capable, precheck-passing handles stay lit", () => {
    const illegal = illegalEndHandles(attempt("mon-0", "ts_in", "target"), emptyGraph);
    // mon.ts_in as the held origin: same-node-same-handle self loop → illegal.
    expect(illegal.has(illegalHandleKey("mon-0", "ts_in"))).toBe(true);
    // gen.ts_out → mon.ts_in is legal (normalized source→target) → lit.
    expect(illegal.has(illegalHandleKey("gen-0", "ts_out"))).toBe(false);
    // legacy rf_in → mon.ts_in: plane mismatch (RF vs MPEG_TS) → illegal.
    expect(illegal.has(illegalHandleKey("legacy-0", "rf_in"))).toBe(true);
  });

  it("no attempt in flight → empty set (preview off)", () => {
    expect(illegalEndHandles(null, emptyGraph).size).toBe(0);
  });

  it("cross-invariant: a handle outside the set is exactly one explainConnection accepts", () => {
    const graph = emptyGraph;
    const illegal = illegalEndHandles(fromSource, graph);
    const genNode = graph.nodes.find((n) => n.id === "gen-0")!;
    for (const node of graph.nodes) {
      for (const port of node.data.node.ports) {
        const verdict = explainConnection({
          source: genNode,
          target: node,
          sourceHandle: "ts_out",
          targetHandle: port.port_id,
          connections: graph.connections,
        });
        if (illegal.has(illegalHandleKey(node.id, port.port_id))) {
          expect(verdict).not.toBeNull();
        } else {
          expect(verdict).toBeNull();
        }
      }
    }
  });
});

describe("connectionStarted/connectionAttempted — the in-flight attempt rides the feedback state", () => {
  const graph = { nodes: draft.nodes as TopologyFlowNode[], connections: draft.connections as TopologyFlowEdge[] };

  it("connectionStarted carries the origin attempt (the preview set derives from it)", () => {
    const started = connectionStarted(idleConnectionFeedback, attempt("gen-0", "ts_out", "source"));
    expect(started.connecting).toEqual({ nodeId: "gen-0", handleId: "ts_out", handleType: "source" });
  });

  it("connectionAttempted clears the in-flight attempt (preview off after the attempt lands)", () => {
    const started = connectionStarted(idleConnectionFeedback, attempt("gen-0", "ts_out", "source"));
    const ended = connectionAttempted(started, started.connecting, attempt("mon-0", "ts_in", "target"), graph);
    expect(ended.connecting).toBeNull();
    const dropped = connectionAttempted(started, started.connecting, null, graph);
    expect(dropped.connecting).toBeNull();
  });

  it("idle feedback holds no attempt", () => {
    expect(idleConnectionFeedback.connecting).toBeNull();
  });
});
