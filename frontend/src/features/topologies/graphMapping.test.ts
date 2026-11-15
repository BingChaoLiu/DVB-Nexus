// graphMapping seam tests (SPEC-401 §5.3/§7.1/§7.2/§7.3). Expected values are
// worked examples computed from the approved spec, never from the code under
// test (tautology guard). The four-tuple mapping is ADR-0005 decision 5; the
// layout contract is ADR-0009 decision 5 (deterministic topo-order columns).
import { describe, expect, it } from "vitest";

import type { TopologyDTO, TopologyNodeDTO } from "../../api/endpoints/topologies";
import {
  canConnect,
  defaultPortsFor,
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
