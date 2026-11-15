// violations seam tests (SPEC-401 §7.4/§7.5). The path grammar is the
// backend validator's emit set (src/simulation/state/validate.py) — the
// expected targets below are the §7.4 mapping table typed independently.
import { describe, expect, it } from "vitest";

import type { TopologyViolationDTO } from "../../api/endpoints/topologies";
import { mapPlanErrors, mapViolations, violationIndex } from "./violations";

describe("mapViolations — the §7.4 path grammar → canvas entity mapping", () => {
  const violations: TopologyViolationDTO[] = [
    { code: "SIM_TOPO_DUPLICATE_ID", path: "nodes[gen-0]", message: "node_id 'gen-0' declared 2 times" },
    {
      code: "SIM_TOPO_CARDINALITY",
      path: "nodes[mux-0].ports[ts_in_1]",
      message: "port carries 2 connections, above max_connections=1",
    },
    { code: "SIM_TOPO_MEDIA_INCOMPATIBLE", path: "connections[conn-2]", message: "plane RF does not match endpoint planes" },
    { code: "SIM_TOPO_CYCLE", path: "topology", message: "cycle through demux-0 → mux-0 → demux-0" },
    { code: "SIM_TOPO_ENDPOINT_MISSING", path: "nodes[ghost-9].weird", message: "unexpected path shape" },
  ];

  it("addresses each path shape to its canvas entity", () => {
    const entries = mapViolations(violations);
    expect(entries.map((e) => e.target)).toEqual([
      { kind: "node", nodeId: "gen-0" },
      { kind: "port", nodeId: "mux-0", portId: "ts_in_1" },
      { kind: "edge", connectionId: "conn-2" },
      { kind: "graph" },
      { kind: "graph" }, // unknown path shape degrades to graph level, never dropped
    ]);
  });

  it("keeps code/path/message verbatim (snake_case wire discipline)", () => {
    const [first] = mapViolations(violations);
    expect(first).toMatchObject({
      code: "SIM_TOPO_DUPLICATE_ID",
      path: "nodes[gen-0]",
      message: "node_id 'gen-0' declared 2 times",
    });
  });

  it("indexes entries per canvas entity kind for in-place highlight", () => {
    const index = violationIndex(mapViolations(violations));
    expect(index.nodeCodes.get("gen-0")).toEqual(["SIM_TOPO_DUPLICATE_ID"]);
    expect(index.portCodes.get("mux-0:ts_in_1")).toEqual(["SIM_TOPO_CARDINALITY"]);
    expect(index.edgeCodes.get("conn-2")).toEqual(["SIM_TOPO_MEDIA_INCOMPATIBLE"]);
    expect(index.graphEntries.map((e) => e.code)).toEqual(["SIM_TOPO_CYCLE", "SIM_TOPO_ENDPOINT_MISSING"]);
  });
});

describe("mapPlanErrors — run prepare 422 same-channel entries (§7.5)", () => {
  it("carries the error strings verbatim and best-effort highlights mentioned node ids", () => {
    const entries = mapPlanErrors(
      [
        "fault_plan[0].target_id: mux-0:pid:0x0100 not present in topology",
        "fault_plan[0].parameters: bogus_key is not a v1 parameter",
      ],
      ["mux-0", "mon-0"],
    );
    expect(entries[0]).toEqual({ source: "run_prepare", message: "fault_plan[0].target_id: mux-0:pid:0x0100 not present in topology", nodeIds: ["mux-0"] });
    expect(entries[1]).toEqual({
      source: "run_prepare",
      message: "fault_plan[0].parameters: bogus_key is not a v1 parameter",
      nodeIds: [],
    });
  });

  it("matches node ids on non-alphanumeric boundaries only (no mux-0 inside mux-01)", () => {
    const entries = mapPlanErrors(["target mux-01 ignored; real: demux-0+ and mon-0."], ["mux-0", "demux-0", "mon-0"]);
    expect(entries[0]!.nodeIds).toEqual(["demux-0", "mon-0"]);
  });
});
