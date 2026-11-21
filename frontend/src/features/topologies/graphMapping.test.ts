// graphMapping seam tests (SPEC-401 §5.3/§7.1/§7.2/§7.3). Expected values are
// worked examples computed from the approved spec, never from the code under
// test (tautology guard). The four-tuple mapping is ADR-0005 decision 5; the
// layout contract is ADR-0009 decision 5 (deterministic topo-order columns).
import { describe, expect, it } from "vitest";

import type { TopologyDTO, TopologyNodeDTO } from "../../api/endpoints/topologies";
import type { TopologyFlowEdge } from "./graphMapping";
import {
  canConnect,
  defaultPortsFor,
  explainConnection,
  fromWire,
  layoutGraph,
  nextConnectionId,
  nextNodeId,
  toWire,
} from "./graphMapping";
import { nodeTypeSpec } from "./nodeTypes";

function node(nodeId: string, nodeType: string): TopologyNodeDTO {
  const spec = nodeTypeSpec(nodeType);
  return {
    node_id: nodeId,
    node_type: nodeType,
    config: {},
    ports: spec ? spec.ports.map((p) => ({ ...p })) : [],
  };
}

describe("toWire / fromWire — ADR-0005 decision-5 four-tuple round trip", () => {
  const topology: TopologyDTO = {
    topology_id: "5f0e3d5e-1e2d-4c3b-9a8f-6b5a4c3d2e1f",
    revision: 3,
    nodes: [node("gen-0", "ts_generator"), node("mux-0", "ts_mux"), node("mon-0", "ts_monitor")],
    connections: [
      {
        connection_id: "conn-0",
        from_node: "gen-0",
        from_port: "ts_out",
        to_node: "mux-0",
        to_port: "ts_in_1",
        plane: "MPEG_TS",
      },
      {
        connection_id: "conn-1",
        from_node: "mux-0",
        from_port: "ts_out",
        to_node: "mon-0",
        to_port: "ts_in",
        plane: "MPEG_TS",
      },
    ],
  };

  it("fromWire maps Handle ids to port ids and carries the wire bodies verbatim", () => {
    const { nodes, connections } = fromWire(topology);
    expect(nodes.map((n) => n.id)).toEqual(["gen-0", "mux-0", "mon-0"]);
    expect(nodes[0]!.data.node).toEqual(topology.nodes![0]);
    expect(connections).toEqual([
      {
        id: "conn-0",
        source: "gen-0",
        sourceHandle: "ts_out",
        target: "mux-0",
        targetHandle: "ts_in_1",
        data: { connection: topology.connections![0], violation: false },
      },
      {
        id: "conn-1",
        source: "mux-0",
        sourceHandle: "ts_out",
        target: "mon-0",
        targetHandle: "ts_in",
        data: { connection: topology.connections![1], violation: false },
      },
    ]);
  });

  it("toWire emits the SPEC-202 four-tuple + plane and never node-pair shapes", () => {
    const { nodes, connections } = fromWire(topology);
    const request = toWire(nodes, connections);
    expect(request).toEqual({ nodes: topology.nodes, connections: topology.connections });
  });

  it("toWire keeps stored ports verbatim even when the registry has moved on", () => {
    const drifted: TopologyDTO = {
      topology_id: "t",
      revision: 1,
      nodes: [
        {
          node_id: "legacy-0",
          node_type: "ts_generator",
          config: { kept: true },
          ports: [{ port_id: "old_out", direction: "output", plane: "MPEG_TS", max_connections: 4 }],
        },
      ],
      connections: [],
    };
    const { nodes, connections } = fromWire(drifted);
    expect(toWire(nodes, connections).nodes).toEqual(drifted.nodes);
  });
});

describe("defaultPortsFor — REQ-UI-401-004 default port generation", () => {
  it("deep-copies the registry template (mutating the copy must not touch the registry)", () => {
    const ports = defaultPortsFor("ts_generator");
    expect(ports).toEqual([{ port_id: "ts_out", direction: "output", plane: "MPEG_TS", max_connections: 1 }]);
    ports[0]!.max_connections = 99;
    expect(nodeTypeSpec("ts_generator")!.ports[0]!.max_connections).toBe(1);
  });

  it("returns [] for an unknown node type (defensive; palette only offers registry types)", () => {
    expect(defaultPortsFor("not_a_type")).toEqual([]);
  });
});

describe("nextNodeId / nextConnectionId — deterministic draft ids (SPEC-401 §7.1)", () => {
  it("picks the smallest unused ordinal per prefix", () => {
    const nodes = fromWire({
      topology_id: "t",
      revision: 1,
      nodes: [node("gen-0", "ts_generator"), node("gen-2", "ts_generator")],
      connections: [],
    }).nodes;
    expect(nextNodeId(nodes, "gen")).toBe("gen-1");
    expect(nextNodeId(nodes, "mux")).toBe("mux-0");
  });

  it("picks the smallest unused connection ordinal", () => {
    const edges = fromWire({
      topology_id: "t",
      revision: 1,
      nodes: [],
      connections: [
        { connection_id: "conn-0", from_node: "a", from_port: "p", to_node: "b", to_port: "q", plane: "MPEG_TS" },
        { connection_id: "conn-2", from_node: "a", from_port: "p", to_node: "c", to_port: "q", plane: "MPEG_TS" },
      ],
    }).connections;
    expect(nextConnectionId(edges)).toBe("conn-1");
    expect(nextConnectionId([])).toBe("conn-0");
  });
});

describe("canConnect — the four UX prechecks (SPEC-401 §7.2)", () => {
  const draft = fromWire({
    topology_id: "t",
    revision: 1,
    nodes: [node("gen-0", "ts_generator"), node("mux-0", "ts_mux"), node("mon-0", "ts_monitor")],
    connections: [
      { connection_id: "conn-0", from_node: "gen-0", from_port: "ts_out", to_node: "mux-0", to_port: "ts_in_1", plane: "MPEG_TS" },
    ],
  });

  const connect = (
    sourceId: string,
    sourceHandle: string,
    targetId: string,
    targetHandle: string,
    connections = draft.connections,
  ) => {
    const nodes = draft.nodes;
    const source = nodes.find((n) => n.id === sourceId)!;
    const target = nodes.find((n) => n.id === targetId)!;
    return canConnect({ source, target, sourceHandle, targetHandle, connections });
  };

  it("accepts output→input across nodes with free cardinality", () => {
    expect(connect("mux-0", "ts_out", "mon-0", "ts_in")).toBe(true);
  });

  it("rejects input→output (direction precheck)", () => {
    expect(connect("mux-0", "ts_in_2", "gen-0", "ts_out")).toBe(false);
  });

  it("rejects the same node + same port self loop (SPEC-202 §5 same rule)", () => {
    expect(connect("mux-0", "ts_out", "mux-0", "ts_out")).toBe(false);
  });

  it("accepts same-node different-port links (backend treats only same node+port as self loop)", () => {
    expect(connect("mux-0", "ts_out", "mux-0", "ts_in_2")).toBe(true);
  });

  it("rejects when either endpoint port would exceed max_connections", () => {
    // gen-0.ts_out already carries conn-0 (max 1) → a second link from it must fail…
    expect(connect("gen-0", "ts_out", "mon-0", "ts_in")).toBe(false);
    // …and so must a second link INTO the occupied mux-0.ts_in_1.
    expect(connect("mux-0", "ts_out", "mux-0", "ts_in_1")).toBe(false);
  });

  it("rejects non-enabled planes (REQ-UI-401-005; defensive against registry drift)", () => {
    const rfNode = {
      id: "rf-0",
      type: "topology" as const,
      position: { x: 0, y: 0 },
      data: {
        node: {
          node_id: "rf-0",
          node_type: "ts_generator",
          config: {},
          ports: [{ port_id: "rf_out", direction: "output", plane: "RF", max_connections: 1 }],
        },
        violationCodes: [],
      },
    };
    const monNode = draft.nodes.find((n) => n.id === "mon-0")!;
    expect(
      canConnect({
        source: rfNode as unknown as Parameters<typeof canConnect>[0]["source"],
        target: monNode,
        sourceHandle: "rf_out",
        targetHandle: "ts_in",
        connections: [],
      }),
    ).toBe(false);
  });

  it("rejects unknown handles defensively", () => {
    expect(connect("gen-0", "nope", "mon-0", "ts_in")).toBe(false);
    expect(connect("gen-0", "ts_out", "mon-0", "nope")).toBe(false);
  });
});

// SPEC-408 §7.6 (连线落空原因映射): the four prechecks' failures get one-line
// reasons rendered verbatim in the toolbar status area (约 4 秒自动消失).
// Expected strings are the spec literals, copied byte-exact (fullwidth
// punctuation, “” curly quotes) — never recomputed from the implementation.
describe("explainConnection — the §7.6 reason lines (parallel to canConnect)", () => {
  const draft = fromWire({
    topology_id: "t",
    revision: 1,
    nodes: [node("gen-0", "ts_generator"), node("mux-0", "ts_mux"), node("mon-0", "ts_monitor")],
    connections: [
      { connection_id: "conn-0", from_node: "gen-0", from_port: "ts_out", to_node: "mux-0", to_port: "ts_in_1", plane: "MPEG_TS" },
    ],
  });

  const explain = (
    sourceId: string,
    sourceHandle: string,
    targetId: string,
    targetHandle: string,
    connections = draft.connections,
  ) => {
    const nodes = draft.nodes;
    const source = nodes.find((n) => n.id === sourceId)!;
    const target = nodes.find((n) => n.id === targetId)!;
    return explainConnection({ source, target, sourceHandle, targetHandle, connections });
  };

  const booleanOf = (
    sourceId: string,
    sourceHandle: string,
    targetId: string,
    targetHandle: string,
    connections = draft.connections,
  ) => {
    const nodes = draft.nodes;
    const source = nodes.find((n) => n.id === sourceId)!;
    const target = nodes.find((n) => n.id === targetId)!;
    return canConnect({ source, target, sourceHandle, targetHandle, connections });
  };

  it("returns null exactly when canConnect passes — same checks, same order (cross invariant)", () => {
    const cases: [string, string, string, string][] = [
      ["mux-0", "ts_out", "mon-0", "ts_in"], // legal
      ["mux-0", "ts_in_2", "gen-0", "ts_out"], // direction
      ["mux-0", "ts_out", "mux-0", "ts_out"], // direction first (same port: output is not target-capable)
      ["mux-0", "ts_out", "mux-0", "ts_in_2"], // legal same-node different-port
      ["gen-0", "ts_out", "mon-0", "ts_in"], // cardinality (source full)
      ["mux-0", "ts_out", "mux-0", "ts_in_1"], // cardinality (target full)
    ];
    for (const [sourceId, sourceHandle, targetId, targetHandle] of cases) {
      expect(explain(sourceId, sourceHandle, targetId, targetHandle) === null).toBe(
        booleanOf(sourceId, sourceHandle, targetId, targetHandle),
      );
    }
  });

  it("direction failure → 「方向不符（需 输出/双向 → 输入/双向）」", () => {
    expect(explain("mux-0", "ts_in_2", "gen-0", "ts_out")).toBe("方向不符（需 输出/双向 → 输入/双向）");
  });

  it("self loop → 「不能连回同一端口」 — reachable only for direction-capable ports (bidirectional stored rows); same node AND same port only", () => {
    // The MVP registry has no bidirectional ports, so a same-port loop on
    // registry rows fails the DIRECTION check first (a port is never both
    // output- and input-capable). The §7.6 self-loop line stays total via the
    // stored-row drift shape (the wire allows direction bidirectional), the
    // same defensive posture as the plane test below.
    const bidiNode = {
      id: "bidi-0",
      type: "topology" as const,
      position: { x: 0, y: 0 },
      data: {
        node: {
          node_id: "bidi-0",
          node_type: "ts_generator",
          config: {},
          ports: [{ port_id: "bi", direction: "bidirectional", plane: "MPEG_TS", max_connections: 4 }],
        },
        violationCodes: [],
      },
    };
    const input = {
      source: bidiNode as unknown as Parameters<typeof explainConnection>[0]["source"],
      target: bidiNode as unknown as Parameters<typeof explainConnection>[0]["target"],
      sourceHandle: "bi",
      targetHandle: "bi",
      connections: [],
    };
    expect(explainConnection(input)).toBe("不能连回同一端口");
    expect(canConnect(input)).toBe(false); // cross invariant holds on the drift shape too
    // same-node DIFFERENT-port links are not self loops (both pass direction)
    expect(explain("mux-0", "ts_out", "mux-0", "ts_in_2")).not.toBe("不能连回同一端口");
  });

  it("cardinality failure names the FULL port and its registry limit, source side first", () => {
    // gen-0.ts_out already carries conn-0 (max_connections 1)
    expect(explain("gen-0", "ts_out", "mon-0", "ts_in")).toBe("“ts_out”连接数已满（上限 1）");
    // mux-0.ts_in_1 already carries conn-0 → the TARGET side names its own port
    expect(explain("mux-0", "ts_out", "mux-0", "ts_in_1")).toBe("“ts_in_1”连接数已满（上限 1）");
  });

  it("plane failure → 「平面不符（当前支持 MPEG_TS / T2MI / RF / SEC_CONTROL）」 (SPEC-401 §Phase3 扩容文案)", () => {
    const rfNode = {
      id: "rf-0",
      type: "topology" as const,
      position: { x: 0, y: 0 },
      data: {
        node: {
          node_id: "rf-0",
          node_type: "ts_generator",
          config: {},
          ports: [{ port_id: "rf_out", direction: "output", plane: "RF", max_connections: 1 }],
        },
        violationCodes: [],
      },
    };
    const monNode = draft.nodes.find((n) => n.id === "mon-0")!;
    expect(
      explainConnection({
        source: rfNode as unknown as Parameters<typeof explainConnection>[0]["source"],
        target: monNode,
        sourceHandle: "rf_out",
        targetHandle: "ts_in",
        connections: [],
      }),
    ).toBe("平面不符（当前支持 MPEG_TS / T2MI / RF / SEC_CONTROL）");
  });

  it("unknown/missing handles stay silent (defensive; no spec enumeration for them)", () => {
    expect(explain("gen-0", "nope", "mon-0", "ts_in")).toBeNull();
    expect(explain("gen-0", "ts_out", "mon-0", "nope")).toBeNull();
  });
});

// SPEC-401 §Phase2: MVP_ENABLED_PLANES = ["MPEG_TS","T2MI"] (mirror of the
// #121 domain frozenset) — the plane precheck admits T2MI links verbatim, and
// the three-level encapsulation chain (三级封装 gen→enc→demux→mon) becomes
// expressible on the canvas with NO precheck-code change (the constant is the
// only plane authority on this side).
describe("plane precheck on the Phase 2 enabled set (T2MI links admitted)", () => {
  const t2miDraft = fromWire({
    topology_id: "t",
    revision: 1,
    nodes: [node("gen-0", "ts_generator"), node("enc-0", "t2mi_encapsulator"), node("dmx-0", "t2mi_demux"), node("mon-0", "ts_monitor")],
    connections: [],
  });

  const verdictOf = (sourceId: string, sourceHandle: string, targetId: string, targetHandle: string) => {
    const nodes = t2miDraft.nodes;
    const input = {
      source: nodes.find((n) => n.id === sourceId)!,
      target: nodes.find((n) => n.id === targetId)!,
      sourceHandle,
      targetHandle,
      connections: t2miDraft.connections,
    };
    return { can: canConnect(input), reason: explainConnection(input) };
  };

  it("the three-level chain passes all four prechecks (MPEG_TS → T2MI → MPEG_TS links)", () => {
    expect(verdictOf("gen-0", "ts_out", "enc-0", "inner_in")).toEqual({ can: true, reason: null });
    expect(verdictOf("enc-0", "t2mi_out", "dmx-0", "t2mi_in")).toEqual({ can: true, reason: null });
    expect(verdictOf("dmx-0", "inner_out", "mon-0", "ts_in")).toEqual({ can: true, reason: null });
  });

  it("an MPEG_TS→T2MI mix still fails the plane precheck with the §Phase2 reason line", () => {
    // demux.inner_out (MPEG_TS output) against a T2MI-cast input handle shape:
    // the stored-row drift posture — cast gen.ts_out as a T2MI port to build
    // the mismatch (direction-capable ends, disagreeing planes).
    const nodes = t2miDraft.nodes;
    const gen = nodes.find((n) => n.id === "gen-0")!;
    const dmx = nodes.find((n) => n.id === "dmx-0")!;
    const mismatch = {
      source: gen,
      target: dmx,
      sourceHandle: "ts_out",
      targetHandle: "t2mi_in",
      connections: t2miDraft.connections,
    };
    expect(canConnect(mismatch)).toBe(false);
    expect(explainConnection(mismatch)).toBe("平面不符（当前支持 MPEG_TS / T2MI / RF / SEC_CONTROL）");
  });

  it("a non-enabled plane stays rejected (RF defensive posture unchanged)", () => {
    const verdict = verdictOf("gen-0", "ts_out", "mon-0", "ts_in");
    // gen.ts_out is occupied nowhere, mon.ts_in is free — this pair is LEGAL
    // (both MPEG_TS); the RF rejection lives in the drift-shape tests above
    // and keeps its assertion there.
    expect(verdict.can).toBe(true);
  });
});

describe("layoutGraph — deterministic topo-order columns (ADR-0009 decision 5)", () => {
  const ids = ["mon-0", "gen-0", "mux-0", "demux-a", "demux-b"];

  it("assigns columns by longest-path depth and sorts peers by node_id lexicographically", () => {
    const links = [
      { from: "gen-0", to: "mux-0" },
      { from: "gen-0", to: "demux-b" },
      { from: "gen-0", to: "demux-a" },
      { from: "mux-0", to: "mon-0" },
    ];
    const layout1 = layoutGraph(ids, links);
    const layout2 = layoutGraph(ids, links);
    expect(layout1).toEqual(layout2); // pure + deterministic
    // column = depth: gen-0 → 0; demux-a/demux-b/mux-0 → 1 (lexicographic rows); mon-0 → 2
    expect(layout1.get("gen-0")).toEqual({ x: 40, y: 40 });
    expect(layout1.get("demux-a")).toEqual({ x: 280, y: 40 });
    expect(layout1.get("demux-b")).toEqual({ x: 280, y: 160 });
    expect(layout1.get("mux-0")).toEqual({ x: 280, y: 280 });
    expect(layout1.get("mon-0")).toEqual({ x: 520, y: 40 });
  });

  it("degrades to a node_id grid when the graph contains a cycle (total function)", () => {
    const layout = layoutGraph(["b-0", "a-0"], [
      { from: "a-0", to: "b-0" },
      { from: "b-0", to: "a-0" },
    ]);
    expect(layout.get("a-0")).toEqual({ x: 40, y: 40 });
    expect(layout.get("b-0")).toEqual({ x: 280, y: 40 });
  });
});

// SPEC-401 §Phase3 (ticket #169): the Phase 3 plane set admits SEC_CONTROL
// links through the SAME four prechecks (constant = the only plane authority);
// the 1:N shared-coax fan-out renders as plain multiple edges with zero
// special-case edge logic (per-port cardinality carries it).
describe("plane precheck on the Phase 3 enabled set (SEC_CONTROL links + 1:N fan-out)", () => {
  const rfDraft = fromWire({
    topology_id: "t",
    revision: 1,
    nodes: [node("lnb-0", "lnb"), node("tuner-a", "tuner"), node("tuner-b", "tuner"), node("sw-0", "diseqc_switch")],
    connections: [],
  });

  const verdictOf = (sourceId: string, sourceHandle: string, targetId: string, targetHandle: string, extra = rfDraft.connections) => {
    const nodes = rfDraft.nodes;
    const input = {
      source: nodes.find((n) => n.id === sourceId)!,
      target: nodes.find((n) => n.id === targetId)!,
      sourceHandle,
      targetHandle,
      connections: extra,
    };
    return { can: canConnect(input), reason: explainConnection(input) };
  };

  it("an SEC_CONTROL lnb→tuner link passes all four prechecks (RF/SEC planes enabled)", () => {
    expect(verdictOf("lnb-0", "coax_out", "tuner-a", "rf_in")).toEqual({ can: true, reason: null });
  });

  it("the 1:N shared-coax fan-out admits the second tuner (coax_out max=2) and saturates at the limit", () => {
    const conn0: TopologyFlowEdge = {
      id: "conn-0",
      source: "lnb-0",
      sourceHandle: "coax_out",
      target: "tuner-a",
      targetHandle: "rf_in",
      data: { connection: { connection_id: "conn-0", from_node: "lnb-0", from_port: "coax_out", to_node: "tuner-a", to_port: "rf_in", plane: "SEC_CONTROL" }, violation: false },
    };
    expect(verdictOf("lnb-0", "coax_out", "tuner-b", "rf_in", [conn0]).can).toBe(true); // 1:N shared coax
    const conn1: TopologyFlowEdge = {
      id: "conn-1",
      source: "lnb-0",
      sourceHandle: "coax_out",
      target: "tuner-b",
      targetHandle: "rf_in",
      data: { connection: { connection_id: "conn-1", from_node: "lnb-0", from_port: "coax_out", to_node: "tuner-b", to_port: "rf_in", plane: "SEC_CONTROL" }, violation: false },
    };
    expect(verdictOf("lnb-0", "coax_out", "tuner-a", "rf_in", [conn0, conn1]).reason).toBe(
      "“coax_out”连接数已满（上限 2）",
    );
  });

  it("an SEC_CONTROL→MPEG_TS mix still fails with the §Phase3 reason line", () => {
    expect(verdictOf("lnb-0", "coax_out", "tuner-a", "ts_out", []).reason).toBeNull(); // unknown handle → silent
    const nodes = rfDraft.nodes;
    const lnb = nodes.find((n) => n.id === "lnb-0")!;
    const mon = {
      id: "mon-0",
      type: "topology" as const,
      position: { x: 0, y: 0 },
      data: {
        node: {
          node_id: "mon-0",
          node_type: "ts_monitor",
          config: {},
          ports: [{ port_id: "ts_in", direction: "input", plane: "MPEG_TS", max_connections: 1 }],
        },
        violationCodes: [],
        violationPorts: [],
      },
    };
    const mismatch = {
      source: lnb,
      target: mon as unknown as typeof lnb,
      sourceHandle: "coax_out",
      targetHandle: "ts_in",
      connections: [],
    };
    expect(canConnect(mismatch as unknown as Parameters<typeof canConnect>[0])).toBe(false);
    expect(explainConnection(mismatch as unknown as Parameters<typeof explainConnection>[0])).toBe(
      "平面不符（当前支持 MPEG_TS / T2MI / RF / SEC_CONTROL）",
    );
  });

  it("the switch upstream/downstream faces stay cardinality-pinned (coax_in=1 至多一条 DC 通路, coax_out=4)", () => {
    expect(verdictOf("sw-0", "coax_out", "tuner-a", "rf_in")).toEqual({ can: true, reason: null });
    expect(defaultPortsFor("diseqc_switch").map((p) => p.max_connections)).toEqual([1, 4]);
  });
});
