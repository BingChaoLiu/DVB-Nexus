// SPEC-402 §5.1/§11 (TV-402-04/05) field-inventory contract tests. The
// expected key sets and wire defaults below are transcribed independently
// from the generated types (frontend/src/api/schema.gen.ts — GeneratorConfigDTO
// / ProgramDTO / ElementaryStreamDTO) and SPEC-108 §4, NOT from the
// implementation — tautology guard: if the descriptor table drifts from the
// generated schema this suite goes red on both sides of the diff.
import { describe, expect, it } from "vitest";

import { GENERATOR_FIELD_INVENTORY, isConfigComplete } from "./fieldInventory";

// --- independent source of truth (schema.gen.ts, verbatim key sets) ----------

const GENERATOR_KEYS = [
  "schema_version",
  "profile",
  "deterministic",
  "seed",
  "initial_media_clock_27mhz",
  "target_bitrate_bps",
  "output_packet_count",
  "program",
  "pat_period_ms",
  "pmt_period_ms",
  "pcr_interval_ms",
  "pcr_insertion_policy",
];

const PROGRAM_KEYS = [
  "transport_stream_id",
  "program_number",
  "pmt_pid",
  "pcr_pid",
  "version_number",
  "streams",
  "program_descriptors",
];

const STREAM_KEYS = ["pid", "stream_type", "stream_id", "bitrate_bps", "payload_profile", "payload_seed_offset"];

/** Wire defaults from the generated schema @default annotations (SPEC-108 §4,
 * ruling-#72 out-of-phase periods). */
const WIRE_DEFAULTS: Record<string, unknown> = {
  profile: "analysis_only",
  deterministic: true,
  pat_period_ms: 101,
  pmt_period_ms: 103,
  pcr_interval_ms: 40,
  pcr_insertion_policy: "payload_packet_first",
  "program.program_descriptors": "",
  "program.streams[].payload_profile": "synthetic_test_data",
  "program.streams[].payload_seed_offset": 0,
};

// --- TV-402-05: descriptor ↔ generated type key-set equality -----------------

describe("fieldInventory (SPEC-402 §5.1, TV-402-05)", () => {
  it("declares exactly the 12 GeneratorConfigDTO keys", () => {
    expect(GENERATOR_FIELD_INVENTORY.map((f) => f.path).sort()).toEqual([...GENERATOR_KEYS].sort());
    expect(GENERATOR_FIELD_INVENTORY).toHaveLength(12);
  });

  it("declares program as a group with exactly the 7 ProgramDTO keys", () => {
    const program = GENERATOR_FIELD_INVENTORY.find((f) => f.path === "program");
    expect(program?.kind).toBe("group");
    expect(program?.children?.map((f) => f.path.replace("program.", "")).sort()).toEqual([...PROGRAM_KEYS].sort());
    expect(program?.children).toHaveLength(7);
  });

  it("declares program.streams as rows with exactly the 6 ElementaryStreamDTO keys", () => {
    const streams = GENERATOR_FIELD_INVENTORY.find((f) => f.path === "program")?.children?.find(
      (f) => f.path === "program.streams",
    );
    expect(streams?.kind).toBe("rows");
    expect(streams?.rowFields?.map((f) => f.path.replace("program.streams[].", "")).sort()).toEqual([
      ...STREAM_KEYS,
    ].sort());
    expect(streams?.rowFields).toHaveLength(6);
  });

  for (const [path, wireDefault] of Object.entries(WIRE_DEFAULTS)) {
    it(`carries the wire default of ${path} (${JSON.stringify(wireDefault)})`, () => {
      const all = [
        ...GENERATOR_FIELD_INVENTORY,
        ...(GENERATOR_FIELD_INVENTORY.find((f) => f.path === "program")?.children ?? []),
        ...(GENERATOR_FIELD_INVENTORY.find((f) => f.path === "program")?.children?.find(
          (f) => f.path === "program.streams",
        )?.rowFields ?? []),
      ];
      const field = all.find((f) => f.path === path);
      expect(field, `descriptor ${path} exists`).toBeDefined();
      expect(field!.wireDefault).toEqual(wireDefault);
      // a defaulted field is never a G1 completeness subject
      expect(field!.required).toBe(false);
    });
  }

  it("marks exactly the fields without a wire default as required (G1 subjects)", () => {
    const all = collectAll();
    const required = all.filter((f) => f.required).map((f) => f.path);
    expect(required.sort()).toEqual(
      [
        "schema_version",
        "seed",
        "initial_media_clock_27mhz",
        "target_bitrate_bps",
        "output_packet_count",
        "program",
        "program.transport_stream_id",
        "program.program_number",
        "program.pmt_pid",
        "program.pcr_pid",
        "program.version_number",
        "program.streams",
        "program.streams[].pid",
        "program.streams[].stream_type",
        "program.streams[].stream_id",
        "program.streams[].bitrate_bps",
      ].sort(),
    );
  });

  it("pins the closed set of six control kinds (SPEC-402 §5.2)", () => {
    const kinds = new Set(collectAll().map((f) => f.kind));
    expect([...kinds].sort()).toEqual(["group", "locked-checkbox", "number", "rows", "select", "text"].sort());
  });

  it("pins the two select option sets to the SPEC-108 §4/§5 enums", () => {
    const profile = GENERATOR_FIELD_INVENTORY.find((f) => f.path === "profile");
    expect(profile?.options).toEqual(["analysis_only"]);
    const policy = GENERATOR_FIELD_INVENTORY.find((f) => f.path === "pcr_insertion_policy");
    expect(policy?.options).toEqual(["payload_packet_first", "adaptation_only_fallback"]);
  });

  function collectAll() {
    const program = GENERATOR_FIELD_INVENTORY.find((f) => f.path === "program");
    const streams = program?.children?.find((f) => f.path === "program.streams");
    return [...GENERATOR_FIELD_INVENTORY, ...(program?.children ?? []), ...(streams?.rowFields ?? [])];
  }
});

// --- TV-402-04: completeness truth table (G1, existence only) -----------------

describe("isConfigComplete (SPEC-402 §7.3, TV-402-04)", () => {
  /** Fully filled minimal config: required scalars set, streams present (and
   * empty — SPEC-108 §5 has no minimum stream count; inventing minLength is
   * forbidden), defaults fill the rest. */
  function completeConfig(overrides: Record<string, unknown> = {}): Record<string, unknown> {
    return {
      schema_version: 1,
      seed: 20260101,
      initial_media_clock_27mhz: 0,
      target_bitrate_bps: 3008000,
      output_packet_count: 1000,
      program: {
        transport_stream_id: 1,
        program_number: 1,
        pmt_pid: 4096,
        pcr_pid: 256,
        version_number: 0,
        program_descriptors: "",
        streams: [],
      },
      ...overrides,
    };
  }

  it("empty config {} is incomplete", () => {
    expect(isConfigComplete("ts_generator", {})).toBe(false);
  });

  it("a fully filled config with an empty streams array is complete (no invented minLength)", () => {
    expect(isConfigComplete("ts_generator", completeConfig())).toBe(true);
  });

  it("missing any required field is incomplete (seed removed)", () => {
    const config = completeConfig();
    delete config.seed;
    expect(isConfigComplete("ts_generator", config)).toBe(false);
  });

  it("empty-string required number treated as unfilled (null/NaN/missing number)", () => {
    expect(isConfigComplete("ts_generator", completeConfig({ target_bitrate_bps: null }))).toBe(false);
    expect(isConfigComplete("ts_generator", completeConfig({ target_bitrate_bps: Number.NaN }))).toBe(false);
  });

  it("a partially filled stream row is incomplete (row pid empty)", () => {
    const config = completeConfig();
    (config.program as Record<string, unknown>).streams = [
      { pid: 256, stream_type: 27, stream_id: 224, bitrate_bps: 120320 },
      { pid: null, stream_type: 27, stream_id: 224, bitrate_bps: 120320 },
    ];
    expect(isConfigComplete("ts_generator", config)).toBe(false);
  });

  it("a fully filled stream row is complete", () => {
    const config = completeConfig();
    (config.program as Record<string, unknown>).streams = [
      { pid: 256, stream_type: 27, stream_id: 224, bitrate_bps: 120320 },
    ];
    expect(isConfigComplete("ts_generator", config)).toBe(true);
  });

  it("is trivially complete for config_schema=null node types (honest empty state)", () => {
    expect(isConfigComplete("ts_mux", {})).toBe(true);
    expect(isConfigComplete("ts_demux", undefined)).toBe(true);
    expect(isConfigComplete("ts_monitor", { anything: "opaque" })).toBe(true);
  });

  it("is trivially complete for an unregistered node type (never guesses fields)", () => {
    expect(isConfigComplete("tuner_from_legacy_fixture", {})).toBe(true);
  });

  it("non-object config for a generator node is incomplete (opaque kept, gate blocks)", () => {
    expect(isConfigComplete("ts_generator", "corrupt")).toBe(false);
    expect(isConfigComplete("ts_generator", null)).toBe(false);
    expect(isConfigComplete("ts_generator", 42)).toBe(false);
  });
});
