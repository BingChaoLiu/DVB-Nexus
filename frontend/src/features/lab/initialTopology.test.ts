// initial_topology readability pure functions (SPEC-408 §4.4 REQ-UI-408-012
// 部分 / AC-408-07): the camelCase island → human-readable Chinese-labelled
// structured rows. LAYOUT translation only — key NAMES are never semantically
// translated, and the raw authored document stays available verbatim
// (键名原样, the #45 canonical-example authority) via rawLines. Table-driven
// unit tests (断形状, 不快照 DOM).
import { describe, expect, it } from "vitest";
import { summarizeInitialTopology } from "./initialTopology";

const RAW = {
  topology_id: "topo-sc-01",
  revision: 1,
  nodes: [
    {
      nodeId: "gen-0",
      nodeType: "ts_generator",
      ports: [{ portId: "ts_out", direction: "out", plane: "MPEG_TS", maxConnections: 1 }],
    },
    {
      nodeId: "mux-0",
      nodeType: "ts_mux",
      ports: [
        { portId: "pat_in", direction: "in", plane: "MPEG_TS", maxConnections: 2 },
        { portId: "pmt_out", direction: "out", plane: "MPEG_TS", maxConnections: 1 },
      ],
    },
  ],
  connections: [
    { connectionId: "c-0", from: { nodeId: "gen-0", portId: "ts_out" }, to: { nodeId: "mux-0", portId: "pat_in" } },
  ],
};

describe("summarizeInitialTopology — stats line", () => {
  it("renders 「N 节点 · M 连接 · topology_id/revision」", () => {
    const summary = summarizeInitialTopology(RAW);
    expect(summary?.statsLine).toBe("2 节点 · 1 连接 · topology_id topo-sc-01/revision 1");
  });
});

describe("summarizeInitialTopology — structured Chinese-labelled rows", () => {
  it("renders node rows as 「节点 {nodeId}（{nodeType}）」", () => {
    const summary = summarizeInitialTopology(RAW);
    expect(summary?.nodes.map((node) => node.line)).toEqual(["节点 gen-0（ts_generator）", "节点 mux-0（ts_mux）"]);
  });

  it("renders port rows as 「端口 … · 方向 … · 平面 … · 连接上限 …」", () => {
    const summary = summarizeInitialTopology(RAW);
    expect(summary?.nodes[0]?.ports.map((port) => port.line)).toEqual([
      "端口 ts_out · 方向 out · 平面 MPEG_TS · 连接上限 1",
    ]);
    expect(summary?.nodes[1]?.ports.map((port) => port.line)).toEqual([
      "端口 pat_in · 方向 in · 平面 MPEG_TS · 连接上限 2",
      "端口 pmt_out · 方向 out · 平面 MPEG_TS · 连接上限 1",
    ]);
  });

  it("renders connection rows as 「连接 {id}：{from}:{port} → {to}:{port}」", () => {
    const summary = summarizeInitialTopology(RAW);
    expect(summary?.connections.map((connection) => connection.line)).toEqual([
      "连接 c-0：gen-0:ts_out → mux-0:pat_in",
    ]);
  });
});

describe("summarizeInitialTopology — raw lines keep the authored camelCase keys verbatim", () => {
  it("emits 「{key} {value}」 pairs in document order (键名原样, no translation)", () => {
    const summary = summarizeInitialTopology(RAW);
    expect(summary?.rawLines).toEqual([
      "nodeId gen-0",
      "nodeType ts_generator",
      "portId ts_out",
      "direction out",
      "plane MPEG_TS",
      "maxConnections 1",
      "nodeId mux-0",
      "nodeType ts_mux",
      "portId pat_in",
      "direction in",
      "plane MPEG_TS",
      "maxConnections 2",
      "portId pmt_out",
      "direction out",
      "plane MPEG_TS",
      "maxConnections 1",
      "connectionId c-0",
      "from gen-0/ts_out",
      "to mux-0/pat_in",
    ]);
  });
});

describe("summarizeInitialTopology — honest null on unexpected shapes", () => {
  it.each([null, undefined, 42, "str", {}, { nodes: "not-an-array" }, { topology_id: "t", revision: 1 }])(
    "returns null for %j",
    (raw) => {
      expect(summarizeInitialTopology(raw)).toBeNull();
    },
  );

  it("tolerates missing connections (empty array)", () => {
    const summary = summarizeInitialTopology({
      topology_id: "t",
      revision: 3,
      nodes: [{ nodeId: "n", nodeType: "ts_generator", ports: [] }],
      connections: [],
    });
    expect(summary?.statsLine).toBe("1 节点 · 0 连接 · topology_id t/revision 3");
    expect(summary?.connections).toEqual([]);
    expect(summary?.rawLines).toEqual(["nodeId n", "nodeType ts_generator"]);
  });
});
