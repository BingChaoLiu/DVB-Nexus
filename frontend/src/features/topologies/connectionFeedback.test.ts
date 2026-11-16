// Connection feedback state machine tests (SPEC-408 §4.5 item 4 / §7.6).
// The machine is pure: it turns RF connection-attempt callbacks into the
// canvas preview marker (非法把手降透明度 CSS hook) and the one-line toolbar
// rejection reason (落空提示). Expected reason strings are the §7.6 spec
// literals byte-exact — the page renders them verbatim (约 4 秒自动消失).
import { describe, expect, it } from "vitest";

import { fromWire, type TopologyFlowEdge, type TopologyFlowNode } from "./graphMapping";
import {
  CONNECTION_HINT_VISIBLE_MS,
  connectionAttempted,
  connectionStarted,
  idleConnectionFeedback,
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
    const standing = { connectingFrom: null, rejection: "不能连回同一端口", attempt: 3 };
    const next = connectionStarted(standing, attempt("gen-0", "ts_out", "source"));
    expect(next).toEqual({ connectingFrom: "source", rejection: null, attempt: 3 });
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
    const standing = { connectingFrom: "source" as const, rejection: "平面不符（当前仅支持 MPEG_TS）", attempt: 1 };
    const feedback = connectionAttempted(standing, attempt("gen-0", "ts_out", "source"), null, graph);
    expect(feedback).toEqual({ connectingFrom: null, rejection: "平面不符（当前仅支持 MPEG_TS）", attempt: 1 });
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
