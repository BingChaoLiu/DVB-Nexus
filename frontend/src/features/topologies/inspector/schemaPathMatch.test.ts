// SPEC-402 §7.5 / §11 (TV-402-03) 口径 B: run prepare 422 error strings →
// best-effort field placement. Fixtures are the REAL wire shapes:
//
//   - SIM_TS_CONFIG_INVALID (src/bootstrap/backends.py L594: NO details —
//     the caller feeds the envelope message): the message embeds the
//     offending field in the frozen slot `(field '<name>'; ...)` where
//     <name> is the validator's BARE field string (src/ts/generator/
//     validator.py: "target_bitrate_bps", "pid", "stream_type", ...);
//   - SIM_TS_PLAN_INVALID (details.errors[] strings, per-element free text,
//     may name target node ids — test_rest_runs.py L201-220 asserts
//     "bogus_key" appears in errors[0]).
//
// Node attribution REUSES the #62 mapPlanErrors word-boundary rule (禁另写)
// plus the approved single-candidate rule: when the string names no node and
// the caller's candidate set has exactly one id, that id is the config owner
// by caller-supplied context (never fabricated when ambiguous).
import { describe, expect, it } from "vitest";

import { mapPlanErrors } from "../violations";
import { matchSchemaPathErrors } from "./schemaPathMatch";

const NODES = ["gen-0", "gen-1", "mux-0"];

/** Real CONFIG 422 envelope message (ts_runtime.py L506-508 format over
 * validator.py GENERATOR_INVALID_BITRATE). */
const CONFIG_BITRATE =
  "GENERATOR_INVALID_BITRATE: target_bitrate_bps must be in 1000000..100000000 bps " +
  "(frozen envelope, ADR-0008 §2), got 500 (field 'target_bitrate_bps'; " +
  "SPEC-108 §5 via the public validator)";

/** Real CONFIG 422 for a reserved ES PID — note the decoy "(pid 256)"
 * parenthetical must not win over the quoted field slot. */
const CONFIG_RESERVED_PID =
  "GENERATOR_PID_COLLISION: pid 0x1000 is a project-reserved PID (0x0000..0x001f " +
  "PSI range or null PID 0x1fff) and can never carry PMT/ES/PCR traffic " +
  "(SPEC-108 §5) (field 'pid'; SPEC-108 §5 via the public validator)";

describe("matchSchemaPathErrors (SPEC-402 §7.5, TV-402-03)", () => {
  it("parses the frozen (field '<name>') slot of a real CONFIG message to the top-level field", () => {
    const result = matchSchemaPathErrors([CONFIG_BITRATE], ["gen-0"]);
    expect(result.fieldHits).toEqual([{ nodeId: "gen-0", fieldPath: "target_bitrate_bps", message: CONFIG_BITRATE }]);
    expect(result.rest).toEqual([]);
  });

  it("resolves the bare row-field name 'pid' (quoted slot wins over the decoy '(pid 256)' text)", () => {
    const result = matchSchemaPathErrors([CONFIG_RESERVED_PID], ["gen-0"]);
    expect(result.fieldHits).toEqual([
      { nodeId: "gen-0", fieldPath: "program.streams[].pid", message: CONFIG_RESERVED_PID },
    ]);
  });

  it("prefers the longest bare-name-to-path resolution (stream_type stays a row field)", () => {
    const message =
      "GENERATOR_INVALID_PROGRAM_CONFIG: stream_type must fit 8 bits (0..255), got 999 " +
      "(pid 256) (field 'stream_type'; SPEC-108 §5 via the public validator)";
    const result = matchSchemaPathErrors([message], ["gen-0"]);
    expect(result.fieldHits[0]!.fieldPath).toBe("program.streams[].stream_type");
  });

  it("a full path substring (defensive fallback for fuller shapes) lands by longest match", () => {
    const message = "ts_generator config invalid: program.streams[2] bitrate budget exceeded";
    const result = matchSchemaPathErrors([message], ["gen-0"]);
    expect(result.fieldHits[0]!.fieldPath).toBe("program.streams");
  });

  it("single-candidate rule: CONFIG message naming no node attributes to the only candidate", () => {
    expect(NODES).toHaveLength(3); // guard: the shared NODES set is multi-candidate
    const result = matchSchemaPathErrors([CONFIG_BITRATE], ["gen-0"]);
    expect(result.fieldHits[0]!.nodeId).toBe("gen-0");
  });

  it("multi-candidate + no node mention stays in rest (ambiguous — never fabricated)", () => {
    const result = matchSchemaPathErrors([CONFIG_BITRATE], NODES);
    expect(result.fieldHits).toEqual([]);
    expect(result.rest).toEqual([CONFIG_BITRATE]);
  });

  it("PLAN string naming a target node without a config field is a node-level FieldError", () => {
    const message = "fault target mux-0 unreachable: port ts_in has no incoming MPEG_TS connection";
    const result = matchSchemaPathErrors([message], NODES);
    expect(result.fieldHits).toEqual([{ nodeId: "mux-0", fieldPath: null, message }]);
    expect(result.rest).toEqual([]);
  });

  it("PLAN parameter string with no field and no node mention degrades to the panel (rest)", () => {
    const message = "fault_plan[0].parameters: bogus_key is not a supported parameter key";
    const result = matchSchemaPathErrors([message], NODES);
    expect(result.fieldHits).toEqual([]);
    expect(result.rest).toEqual([message]);
  });

  it("reuses the #62 mapPlanErrors word-boundary rule (gen-01 does not match gen-0)", () => {
    const message = "config invalid on node gen-01 (field 'pat_period_ms'; SPEC-108 §5)";
    const viaSharedMapper = mapPlanErrors([message], NODES);
    expect(viaSharedMapper[0]!.nodeIds).toEqual([]); // word boundary rejects gen-0 inside gen-01
    const result = matchSchemaPathErrors([message], NODES);
    expect(result.fieldHits).toEqual([]); // no honest node home with 3 candidates → rest
    expect(result.rest).toEqual([message]);
  });

  it("attributes to exactly the node ids mapPlanErrors reports (shared-rule assertion)", () => {
    const message = `config invalid for gen-1 (field 'pmt_pid'; SPEC-108 §5)`;
    const result = matchSchemaPathErrors([message], NODES);
    const viaSharedMapper = mapPlanErrors([message], NODES);
    expect(viaSharedMapper[0]!.nodeIds).toEqual(["gen-1"]);
    expect(result.fieldHits).toEqual([{ nodeId: "gen-1", fieldPath: "program.pmt_pid", message }]);
  });

  it("maps every string in order, hits and rest interleaved", () => {
    const plan = "fault target mon-9 unknown"; // names no candidate node, no config field
    const bogus = "fault_plan[0].parameters: bogus_key is not a supported parameter key";
    const result = matchSchemaPathErrors([CONFIG_BITRATE, plan, bogus], ["gen-0"]);
    // single-candidate rule fires ONLY with field evidence (config-field slot);
    // plan/garbage strings keep the panel channel — no pinning onto the node.
    expect(result.fieldHits).toEqual([{ nodeId: "gen-0", fieldPath: "target_bitrate_bps", message: CONFIG_BITRATE }]);
    expect(result.rest).toEqual([plan, bogus]);
  });
});
