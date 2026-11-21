// SPEC-401 §5.1 + §Phase2 registry contract tests. The expected values below
// are the APPROVED type-set tables typed independently from the implementation
// (MVP four = the #62 approval record; Phase 2 two = the SPEC-401 §Phase2
// table / #121 backend mirror — the spec is the source of truth, tautology
// guard).
import { describe, expect, it } from "vitest";

import {
  isStateDomainNodeType,
  LNB_FIELD_INVENTORY,
  MVP_ENABLED_PLANES,
  MVP_NODE_TYPES,
  STATE_DOMAIN_NODE_TYPES,
  STATE_OBSERVED_EVENT_TYPES,
  SWITCH_FIELD_INVENTORY,
  T2MI_DEMUX_FIELD_INVENTORY,
  T2MI_ENCAPSULATOR_FIELD_INVENTORY,
  TUNER_FIELD_INVENTORY,
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
  // SPEC-401 §Phase3 修订章 table (verbatim; labels/prefixes/port templates
  // byte-identical with the #160 backend PHASE3_NODE_TYPES entries).
  lnb: {
    label: "LNB",
    id_prefix: "lnb",
    ports: [
      { port_id: "coax_out", direction: "output", plane: "SEC_CONTROL", max_connections: 2 },
    ],
    config_schema: "LnbConfigDTO",
  },
  tuner: {
    label: "卫星调谐器",
    id_prefix: "tuner",
    ports: [
      { port_id: "rf_in", direction: "input", plane: "SEC_CONTROL", max_connections: 1 },
    ],
    config_schema: "TunerConfigDTO",
  },
  diseqc_switch: {
    label: "DiSEqC 开关",
    id_prefix: "sw",
    ports: [
      { port_id: "coax_in", direction: "input", plane: "SEC_CONTROL", max_connections: 1 },
      { port_id: "coax_out", direction: "output", plane: "SEC_CONTROL", max_connections: 4 },
    ],
    config_schema: "SwitchConfigDTO",
  },
};

describe("MVP NodeType registry (SPEC-401 §5.1 + §Phase2/§Phase3, approved type set)", () => {
  it("declares exactly the nine approved node types in spec order (MVP four, Phase 2 two, Phase 3 three)", () => {
    expect(MVP_NODE_TYPES.map((t) => t.node_type)).toEqual([
      "ts_generator",
      "ts_mux",
      "ts_demux",
      "ts_monitor",
      "t2mi_encapsulator",
      "t2mi_demux",
      "lnb",
      "tuner",
      "diseqc_switch",
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

  it("keeps MVP_ENABLED_PLANES to the Phase 3 enabled set (mirror of domain frozenset, SPEC-003 §Phase3 / SPEC-401 §Phase3)", () => {
    expect([...MVP_ENABLED_PLANES]).toEqual(["MPEG_TS", "T2MI", "RF", "SEC_CONTROL"]);
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

// --- Phase 3 #169 (SPEC-401 §Phase3 + #160 backend registry mirror) ------------

describe("Phase 3 registry additions (lnb/tuner/diseqc_switch — SPEC-401 §Phase3)", () => {
  it("carries the SPEC-401 §Phase3 status-metric key lists per node type (card summary keys)", () => {
    const statusOf = (nodeType: string) => MVP_NODE_TYPES.find((t) => t.node_type === nodeType)!.status_metrics;
    // SPEC-401 §Phase3 verbatim: tuner lock_state/ber_state; lnb
    // voltage/tone_actual/band_selected; switch port_selected.
    expect(statusOf("tuner")).toEqual(["lock_state", "ber_state"]);
    expect(statusOf("lnb")).toEqual(["voltage", "tone_actual", "band_selected"]);
    expect(statusOf("diseqc_switch")).toEqual(["port_selected"]);
  });

  it("leaves status_metrics undefined on the pre-Phase3 types (cards unchanged, additive face)", () => {
    for (const nodeType of ["ts_generator", "ts_mux", "ts_demux", "ts_monitor", "t2mi_encapsulator", "t2mi_demux"]) {
      expect(MVP_NODE_TYPES.find((t) => t.node_type === nodeType)!.status_metrics).toBeUndefined();
    }
  });

  it("derives the state-domain type set from the registry (ports on RF/SEC_CONTROL planes)", () => {
    expect(STATE_DOMAIN_NODE_TYPES).toEqual(["lnb", "tuner", "diseqc_switch"]);
    expect(isStateDomainNodeType("tuner")).toBe(true);
    expect(isStateDomainNodeType("lnb")).toBe(true);
    expect(isStateDomainNodeType("diseqc_switch")).toBe(true);
    // TS/T2MI domain nodes carry no RF/SEC_CONTROL port.
    expect(isStateDomainNodeType("ts_generator")).toBe(false);
    expect(isStateDomainNodeType("t2mi_encapsulator")).toBe(false);
    expect(isStateDomainNodeType("ts_monitor")).toBe(false);
    expect(isStateDomainNodeType("not_a_type")).toBe(false);
  });

  it("pins the state_observed event type wire strings (SPEC-303 §Phase3; drift lock vs payloadKeys.gen.ts)", async () => {
    expect(STATE_OBSERVED_EVENT_TYPES).toEqual(["rf.state_observed", "sec.state_observed"]);
    // The generated payload-keys table is the #164 registration mirror —
    // both wire strings must exist there (same-source discipline).
    const { PHASE2_PAYLOAD_KEYS } = await import("../monitor/journal/payloadKeys.gen");
    for (const eventType of STATE_OBSERVED_EVENT_TYPES) {
      expect(Object.keys(PHASE2_PAYLOAD_KEYS)).toContain(eventType);
    }
  });

  it("satisfies the 1:N shared-coax cardinality face (lnb coax_out max=2 fans out, zero special-case edges)", () => {
    const lnbPorts = MVP_NODE_TYPES.find((t) => t.node_type === "lnb")!.ports;
    expect(lnbPorts.find((p) => p.port_id === "coax_out")!.max_connections).toBe(2);
    // A1 dual-tuner shared-coax topology stays expressible with plain
    // per-port cardinality — no per-node-type edge logic anywhere.
    const tunerPorts = MVP_NODE_TYPES.find((t) => t.node_type === "tuner")!.ports;
    expect(tunerPorts.find((p) => p.port_id === "rf_in")!.max_connections).toBe(1);
  });
});

describe("Phase 3 config field lists (hand-written to the #160 backend config DTOs)", () => {
  it("LnbConfigDTO declares exactly lnb_kind + lo_frequencies + scr", () => {
    expect(LNB_FIELD_INVENTORY.map((f) => f.path)).toEqual(["lnb_kind", "lo_frequencies", "scr"]);
  });

  it("lnb_kind carries the SPEC-621 §5 two-value vocabulary verbatim", () => {
    const kind = LNB_FIELD_INVENTORY.find((f) => f.path === "lnb_kind")!;
    expect(kind.kind).toBe("select");
    expect(kind.options).toEqual(["universal", "legacy_cascade"]);
    expect(kind.required).toBe(true);
    // legacy_cascade must not carry scr (SPEC-621 §8) — hint text only.
    expect(kind.hint).toContain("legacy_cascade");
    expect(kind.hint).toContain("scr");
  });

  it("lo_frequencies carries exactly low_khz + high_khz (SPEC-621 §5 LoFrequenciesDTO)", () => {
    const lo = LNB_FIELD_INVENTORY.find((f) => f.path === "lo_frequencies")!;
    expect(lo.kind).toBe("group");
    expect(lo.children!.map((c) => c.path.replace("lo_frequencies.", ""))).toEqual(["low_khz", "high_khz"]);
    expect(lo.children!.every((c) => c.required && c.kind === "number")).toBe(true);
  });

  it("scr carries protocol + ub_assignments rows (SPEC-623 §5 ScrConfigDTO), optional group", () => {
    const scr = LNB_FIELD_INVENTORY.find((f) => f.path === "scr")!;
    expect(scr.kind).toBe("group");
    expect(scr.required).toBe(false);
    const children = scr.children!.map((c) => c.path.replace("scr.", ""));
    expect(children).toEqual(["protocol", "ub_assignments"]);
    const protocol = scr.children!.find((c) => c.path === "scr.protocol")!;
    expect(protocol.kind).toBe("select");
    expect(protocol.options).toEqual(["EN50494", "EN50607"]);
    const rows = scr.children!.find((c) => c.path === "scr.ub_assignments")!;
    expect(rows.kind).toBe("rows");
    expect(rows.rowFields!.map((f) => f.path.replace("scr.ub_assignments[].", ""))).toEqual([
      "tuner_node",
      "ub_slot",
      "ub_center_freq_mhz",
      "position",
      "pin",
      "ub_bandwidth_mhz",
    ]);
    // wire defaults: pin optional null, ub_bandwidth_mhz defaults 46 (SPEC-623 §5).
    const pin = rows.rowFields!.find((f) => f.path.endsWith("pin"))!;
    expect(pin.required).toBe(false);
    expect(pin.wireDefault).toBeUndefined();
    const bandwidth = rows.rowFields!.find((f) => f.path.endsWith("ub_bandwidth_mhz"))!;
    expect(bandwidth.wireDefault).toBe(46);
    expect(bandwidth.required).toBe(false);
  });

  it("TunerConfigDTO declares exactly tuning_request + ub_slot + diseqc_commands", () => {
    expect(TUNER_FIELD_INVENTORY.map((f) => f.path)).toEqual(["tuning_request", "ub_slot", "diseqc_commands"]);
  });

  it("tuning_request carries frequency_khz + polarization (SPEC-620 §5); ub_slot optional", () => {
    const tuning = TUNER_FIELD_INVENTORY.find((f) => f.path === "tuning_request")!;
    expect(tuning.kind).toBe("group");
    expect(tuning.required).toBe(true);
    const children = tuning.children!.map((c) => c.path.replace("tuning_request.", ""));
    expect(children).toEqual(["frequency_khz", "polarization"]);
    const polarization = tuning.children!.find((c) => c.path === "tuning_request.polarization")!;
    expect(polarization.options).toEqual(["vertical", "horizontal"]);
    const ubSlot = TUNER_FIELD_INVENTORY.find((f) => f.path === "ub_slot")!;
    expect(ubSlot.required).toBe(false);
    expect(ubSlot.kind).toBe("number");
    expect(ubSlot.hint).toContain("SIM_TOPO_UB");
  });

  it("diseqc_commands carries target_register booleans (dotted paths) + nibble_writes rows (SPEC-622 §5)", () => {
    const commands = TUNER_FIELD_INVENTORY.find((f) => f.path === "diseqc_commands")!;
    expect(commands.kind).toBe("group");
    expect(commands.required).toBe(false);
    expect(commands.children!.map((c) => c.path)).toEqual([
      "diseqc_commands.target_register.committed",
      "diseqc_commands.target_register.uncommitted",
      "diseqc_commands.nibble_writes",
    ]);
    const committed = commands.children![0]!;
    expect(committed.kind).toBe("checkbox");
    expect(committed.required).toBe(false);
    const rows = commands.children![2]!;
    expect(rows.kind).toBe("rows");
    expect(rows.rowFields!.map((f) => f.path.replace("diseqc_commands.nibble_writes[].", ""))).toEqual([
      "register",
      "nibble",
      "value",
    ]);
    const register = rows.rowFields!.find((f) => f.path.endsWith("register"))!;
    expect(register.options).toEqual(["committed", "uncommitted"]); // wire key `register`, DiseqcNibbleWriteDTO
    const nibble = rows.rowFields!.find((f) => f.path.endsWith("nibble"))!;
    expect(nibble.options).toEqual(["high", "low"]);
    const value = rows.rowFields!.find((f) => f.path.endsWith("value"))!;
    expect(value.kind).toBe("number");
    expect(value.hint).toContain("0..15");
  });

  it("SwitchConfigDTO declares exactly power_pass with the on/off vocabulary (SPEC-622 §5)", () => {
    expect(SWITCH_FIELD_INVENTORY.map((f) => f.path)).toEqual(["power_pass"]);
    const powerPass = SWITCH_FIELD_INVENTORY[0]!;
    expect(powerPass.kind).toBe("select");
    expect(powerPass.options).toEqual(["on", "off"]);
    expect(powerPass.required).toBe(true);
    expect(powerPass.hint).toContain("透传");
  });

  it("keeps the Phase 3 wire enums verbatim (no invented vocabulary across all three lists)", () => {
    const enums: string[][] = [
      LNB_FIELD_INVENTORY.find((f) => f.path === "lnb_kind")!.options ?? [],
      LNB_FIELD_INVENTORY.find((f) => f.path === "scr")!.children!.find((c) => c.path === "scr.protocol")!.options ?? [],
      TUNER_FIELD_INVENTORY.find((f) => f.path === "tuning_request")!.children!.find((c) => c.path === "tuning_request.polarization")!.options ?? [],
      TUNER_FIELD_INVENTORY.find((f) => f.path === "diseqc_commands")!.children![2]!.rowFields!.find((f) => f.path.endsWith("register"))!.options ?? [],
      SWITCH_FIELD_INVENTORY[0]!.options ?? [],
    ];
    for (const options of enums) {
      for (const option of options) {
        // every option must be a wire literal from the #160 DTO Literals
        expect([
          "universal", "legacy_cascade", "EN50494", "EN50607",
          "vertical", "horizontal", "committed", "uncommitted", "high", "low", "on", "off",
        ]).toContain(option);
      }
    }
  });
});
