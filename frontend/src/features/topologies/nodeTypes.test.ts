// SPEC-401 §5.1 + §Phase2 registry contract tests. The expected values below
// are the APPROVED type-set tables typed independently from the implementation
// (MVP four = the #62 approval record; Phase 2 two = the SPEC-401 §Phase2
// table / #121 backend mirror — the spec is the source of truth, tautology
// guard).
import { describe, expect, it } from "vitest";

import {
  MVP_ENABLED_PLANES,
  MVP_NODE_TYPES,
  T2MI_DEMUX_FIELD_INVENTORY,
  T2MI_ENCAPSULATOR_FIELD_INVENTORY,
} from "./nodeTypes";

const SPEC_TABLE: Record<
  string,
  {
    label: string;
    id_prefix: string;
    ports: { port_id: string; direction: string; plane: string; max_connections: number }[];
    config_schema: string | null;
  }
> = {
  ts_generator: {
    label: "TS 生成器",
    id_prefix: "gen",
    ports: [{ port_id: "ts_out", direction: "output", plane: "MPEG_TS", max_connections: 1 }],
    config_schema: "GeneratorConfigDTO",
  },
  ts_mux: {
    label: "TS 复用器",
    id_prefix: "mux",
    ports: [
      { port_id: "ts_in_1", direction: "input", plane: "MPEG_TS", max_connections: 1 },
      { port_id: "ts_in_2", direction: "input", plane: "MPEG_TS", max_connections: 1 },
      { port_id: "ts_out", direction: "output", plane: "MPEG_TS", max_connections: 1 },
    ],
    config_schema: null,
  },
  ts_demux: {
    label: "TS 解复用器",
    id_prefix: "demux",
    ports: [
      { port_id: "ts_in", direction: "input", plane: "MPEG_TS", max_connections: 1 },
      { port_id: "ts_out_1", direction: "output", plane: "MPEG_TS", max_connections: 1 },
      { port_id: "ts_out_2", direction: "output", plane: "MPEG_TS", max_connections: 1 },
    ],
    config_schema: null,
  },
  ts_monitor: {
    label: "TS 监测器",
    id_prefix: "mon",
    ports: [{ port_id: "ts_in", direction: "input", plane: "MPEG_TS", max_connections: 1 }],
    config_schema: null,
  },
  // SPEC-401 §Phase2 修订章 table (verbatim; labels also byte-identical with
  // the #121 backend registry entries).
  t2mi_encapsulator: {
    label: "T2-MI 封装器",
    id_prefix: "enc",
    ports: [
      { port_id: "inner_in", direction: "input", plane: "MPEG_TS", max_connections: 1 },
      { port_id: "t2mi_out", direction: "output", plane: "T2MI", max_connections: 1 },
    ],
    config_schema: "T2miEncapsulatorConfigDTO",
  },
  t2mi_demux: {
    label: "T2-MI 解封装器",
    id_prefix: "dmx",
    ports: [
      { port_id: "t2mi_in", direction: "input", plane: "T2MI", max_connections: 1 },
      { port_id: "inner_out", direction: "output", plane: "MPEG_TS", max_connections: 1 },
    ],
    config_schema: "T2miDemuxConfigDTO",
  },
};

describe("MVP NodeType registry (SPEC-401 §5.1 + §Phase2, approved type set)", () => {
  it("declares exactly the six approved node types in spec order (MVP four, then Phase 2)", () => {
    expect(MVP_NODE_TYPES.map((t) => t.node_type)).toEqual([
      "ts_generator",
      "ts_mux",
      "ts_demux",
      "ts_monitor",
      "t2mi_encapsulator",
      "t2mi_demux",
    ]);
  });

  for (const [nodeType, spec] of Object.entries(SPEC_TABLE)) {
    it(`${nodeType} matches the approved spec-table row`, () => {
      const entry = MVP_NODE_TYPES.find((t) => t.node_type === nodeType);
      expect(entry).toBeDefined();
      expect(entry!.label).toBe(spec.label);
      expect(entry!.id_prefix).toBe(spec.id_prefix);
      expect(entry!.config_schema).toBe(spec.config_schema);
      expect(entry!.ports).toEqual(spec.ports);
    });
  }

  it("keeps MVP_ENABLED_PLANES to the enabled MPEG_TS / T2MI pair (mirror of domain frozenset, #121 REPORT §7)", () => {
    expect([...MVP_ENABLED_PLANES]).toEqual(["MPEG_TS", "T2MI"]);
  });

  it("keeps the CONTEXT.md 词条 label anchors (Phase 2 封装层: no encapsulator/demux conflation)", () => {
    const enc = MVP_NODE_TYPES.find((t) => t.node_type === "t2mi_encapsulator")!;
    const demux = MVP_NODE_TYPES.find((t) => t.node_type === "t2mi_demux")!;
    expect(enc.label).toBe("T2-MI 封装器");
    expect(demux.label).toBe("T2-MI 解封装器");
    // descriptions anchor the CONTEXT.md wording (in/out planes verbatim).
    expect(enc.description).toContain("把 Inner TS 经 BBFrame 封装段包化为 T2-MI 包流");
    expect(enc.description).toContain("（in MPEG_TS / out T2MI）");
    expect(demux.description).toContain("Inner TS 重建的观测侧链");
    expect(demux.description).toContain("（in T2MI / out MPEG_TS）");
  });

  it("satisfies the registry invariants (unique ids, pinned cardinality, no bidirectional)", () => {
    const nodeTypes = MVP_NODE_TYPES.map((t) => t.node_type);
    expect(new Set(nodeTypes).size).toBe(nodeTypes.length);
    for (const entry of MVP_NODE_TYPES) {
      const portIds = entry.ports.map((p) => p.port_id);
      expect(new Set(portIds).size).toBe(portIds.length);
      expect(portIds.length).toBeGreaterThanOrEqual(1);
      for (const port of entry.ports) {
        expect(["input", "output", "bidirectional"]).toContain(port.direction);
        expect(["RF", "SEC_CONTROL", "MPEG_TS", "T2MI", "IP"]).toContain(port.plane);
        expect(port.max_connections).toBeTypeOf("number");
        expect(port.max_connections).toBeGreaterThanOrEqual(1);
        expect(port.direction).not.toBe("bidirectional"); // ADR-0009 decision 3悬项MVP不触发
      }
    }
  });

  it("keeps the three-level encapsulation chain expressible (三级封装：gen→enc→demux→mon)", () => {
    const portsOf = (nodeType: string) => MVP_NODE_TYPES.find((t) => t.node_type === nodeType)!.ports;
    const planeOf = (nodeType: string, portId: string) => portsOf(nodeType).find((p) => p.port_id === portId)!.plane;
    // 外层 TS → BBFrame 封装段 → T2-MI → 解封装 → Inner TS (BBFrame 是节点内部层次，不出现独立平面)
    expect(planeOf("ts_generator", "ts_out")).toBe("MPEG_TS");
    expect(planeOf("t2mi_encapsulator", "inner_in")).toBe("MPEG_TS");
    expect(planeOf("t2mi_encapsulator", "t2mi_out")).toBe("T2MI");
    expect(planeOf("t2mi_demux", "t2mi_in")).toBe("T2MI");
    expect(planeOf("t2mi_demux", "inner_out")).toBe("MPEG_TS");
    expect(planeOf("ts_monitor", "ts_in")).toBe("MPEG_TS");
  });
});

// --- Phase 2 #63 field lists (hand-written to the #121 backend schemas) -------

describe("Phase 2 config field lists (SPEC-402 §5.1 mechanism consumes by schema name)", () => {
  it("T2miEncapsulatorConfigDTO declares exactly plp_assignment + bbframe_params", () => {
    expect(T2MI_ENCAPSULATOR_FIELD_INVENTORY.map((f) => f.path)).toEqual(["plp_assignment", "bbframe_params"]);
  });

  it("plp_assignment.entries carries exactly the PlpAssignmentEntryDTO keys", () => {
    const assignment = T2MI_ENCAPSULATOR_FIELD_INVENTORY.find((f) => f.path === "plp_assignment")!;
    const entries = assignment.children?.find((f) => f.path === "plp_assignment.entries");
    expect(entries?.kind).toBe("rows");
    expect(entries?.rowFields?.map((f) => f.path.replace("plp_assignment.entries[].", ""))).toEqual([
      "plp_id",
      "source_tag",
    ]);
    // backend authority surfaced as hint text only (never client-side enforcement)
    expect(entries?.required).toBe(true);
    expect(entries?.hint).toContain("至少 1 行");
  });

  it("bbframe_params carries exactly the BBFrameBuildParamsDTO keys", () => {
    const params = T2MI_ENCAPSULATOR_FIELD_INVENTORY.find((f) => f.path === "bbframe_params")!;
    expect(params.kind).toBe("group");
    expect(params.children?.map((f) => f.path.replace("bbframe_params.", ""))).toEqual([
      "matype_value",
      "upl",
      "n_ups",
      "issy_mode",
      "npd_enabled",
    ]);
    // all five are required (no wire defaults in the #121 schema)
    expect(params.children?.every((f) => f.required)).toBe(true);
  });

  it("T2miDemuxConfigDTO declares exactly plp_filter + strict_crc", () => {
    expect(T2MI_DEMUX_FIELD_INVENTORY.map((f) => f.path)).toEqual(["plp_filter", "strict_crc"]);
  });

  it("plp_filter carries mode (expected|all) + expected_plp; strict_crc defaults to true", () => {
    const filter = T2MI_DEMUX_FIELD_INVENTORY.find((f) => f.path === "plp_filter")!;
    const mode = filter.children?.find((f) => f.path === "plp_filter.mode");
    const expectedPlp = filter.children?.find((f) => f.path === "plp_filter.expected_plp");
    expect(mode?.kind).toBe("select");
    expect(mode?.options).toEqual(["expected", "all"]);
    expect(mode?.required).toBe(true);
    // backend default null → no wireDefault on the descriptor (empty input, key omitted)
    expect(expectedPlp?.wireDefault).toBeUndefined();
    expect(expectedPlp?.required).toBe(false);
    const strictCrc = T2MI_DEMUX_FIELD_INVENTORY.find((f) => f.path === "strict_crc")!;
    expect(strictCrc.wireDefault).toBe(true);
    expect(strictCrc.required).toBe(false);
  });

  it("keeps the wire enums verbatim (no invented vocabulary)", () => {
    const filter = T2MI_DEMUX_FIELD_INVENTORY.find((f) => f.path === "plp_filter")!;
    const mode = filter.children!.find((f) => f.path === "plp_filter.mode")!;
    for (const option of mode.options ?? []) {
      expect(["expected", "all"]).toContain(option); // PlpFilterConfigDTO Literal — snake_case island untouched
    }
  });
});
