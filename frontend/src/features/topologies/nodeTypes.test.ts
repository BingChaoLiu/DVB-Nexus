// SPEC-401 §5.1 registry contract tests. The expected values below are the
// APPROVED type-set table typed independently from the implementation (the
// spec is the source of truth — tautology guard).
import { describe, expect, it } from "vitest";

import { MVP_ENABLED_PLANES, MVP_NODE_TYPES } from "./nodeTypes";

const SPEC_TABLE: Record<
  string,
  {
    id_prefix: string;
    ports: { port_id: string; direction: string; plane: string; max_connections: number }[];
    config_schema: string | null;
  }
> = {
  ts_generator: {
    id_prefix: "gen",
    ports: [{ port_id: "ts_out", direction: "output", plane: "MPEG_TS", max_connections: 1 }],
    config_schema: "GeneratorConfigDTO",
  },
  ts_mux: {
    id_prefix: "mux",
    ports: [
      { port_id: "ts_in_1", direction: "input", plane: "MPEG_TS", max_connections: 1 },
      { port_id: "ts_in_2", direction: "input", plane: "MPEG_TS", max_connections: 1 },
      { port_id: "ts_out", direction: "output", plane: "MPEG_TS", max_connections: 1 },
    ],
    config_schema: null,
  },
  ts_demux: {
    id_prefix: "demux",
    ports: [
      { port_id: "ts_in", direction: "input", plane: "MPEG_TS", max_connections: 1 },
      { port_id: "ts_out_1", direction: "output", plane: "MPEG_TS", max_connections: 1 },
      { port_id: "ts_out_2", direction: "output", plane: "MPEG_TS", max_connections: 1 },
    ],
    config_schema: null,
  },
  ts_monitor: {
    id_prefix: "mon",
    ports: [{ port_id: "ts_in", direction: "input", plane: "MPEG_TS", max_connections: 1 }],
    config_schema: null,
  },
};

describe("MVP NodeType registry (SPEC-401 §5.1, approved type set)", () => {
  it("declares exactly the four approved node types in spec order", () => {
    expect(MVP_NODE_TYPES.map((t) => t.node_type)).toEqual([
      "ts_generator",
      "ts_mux",
      "ts_demux",
      "ts_monitor",
    ]);
  });

  for (const [nodeType, spec] of Object.entries(SPEC_TABLE)) {
    it(`${nodeType} matches the approved port template`, () => {
      const entry = MVP_NODE_TYPES.find((t) => t.node_type === nodeType);
      expect(entry).toBeDefined();
      expect(entry!.id_prefix).toBe(spec.id_prefix);
      expect(entry!.config_schema).toBe(spec.config_schema);
      expect(entry!.ports).toEqual(spec.ports);
    });
  }

  it("keeps MVP_ENABLED_PLANES to the single enabled MPEG_TS plane", () => {
    expect([...MVP_ENABLED_PLANES]).toEqual(["MPEG_TS"]);
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
});
