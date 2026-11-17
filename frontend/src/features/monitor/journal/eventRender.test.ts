// Pin: PHASE2_EVENT_RENDER_TABLE must carry exactly the nine registered
// Phase 2 event types with the #129 REPORT §2 payload key sets (the registry
// validate_payload strict key sets — triple-pinned: #128 REPORT / #129
// registry / brief §2bis). The expected values below are the independent
// #129 extraction, not a copy of the implementation table.
import { describe, expect, it } from "vitest";
import { PHASE2_EVENT_TYPES } from "../types";
import { PHASE2_PAYLOAD_KEYS } from "./payloadKeys.gen";
import { PHASE2_EVENT_RENDER_TABLE, phase2RenderSpec } from "./eventRender";

// #129 REPORT §2 key-set extraction (base keys per event type; the
// biss.scramble_applied Mode E/2 fault face additively carries the derivation
// face — legal optional keys, never required).
const REPORT_129_KEY_SETS: Record<string, readonly string[]> = {
  "t2mi.stage_summary": ["packet_count", "padding_count", "packet_type_distribution", "plp_distribution"],
  "t2mi.plp_mismatch": ["expected_plp", "actual_plp", "business_absent_evidence"],
  "bbframe.stage_summary": ["frame_count", "n_ups_distribution", "stuffing_ratio"],
  "bbframe.recovery_failed": ["failure_count", "first_failed_frame_index"],
  "biss.scramble_applied": ["pid_scope", "packet_count", "key_fingerprint", "mutation_log_ref", "mode"],
  "biss.descramble_failed": ["pid_scope", "failed_indices_sample", "self_check_kind", "key_fingerprint_ref", "mode"],
  "gen.stage_started": ["layer"],
  "gen.stage_completed": ["layer", "item_count"],
  "gen.packet_sampled": ["layer", "packet_index", "byte_size", "sha256"],
};

// The optional #127 derivation face (base + these = legal on mode "E"/"2").
const BISS_DERIVATION_FACE = ["derivation_ref", "mismatch_variants"] as const;

describe("PHASE2_EVENT_RENDER_TABLE — registry-driven rendering surface", () => {
  it("covers exactly the nine registered Phase 2 event types (no extra, no missing)", () => {
    expect(Object.keys(PHASE2_EVENT_RENDER_TABLE).sort()).toEqual([...PHASE2_EVENT_TYPES].sort());
  });

  it("every table entry carries the full #129 base key set (display order)", () => {
    for (const [eventType, keys] of Object.entries(REPORT_129_KEY_SETS)) {
      const spec = PHASE2_EVENT_RENDER_TABLE[eventType as keyof typeof PHASE2_EVENT_RENDER_TABLE];
      expect(spec, eventType).toBeDefined();
      for (const key of keys) {
        expect(spec.payloadKeys, `${eventType} missing ${key}`).toContain(key);
      }
    }
  });

  it("biss.scramble_applied optionally carries the #127 derivation face keys", () => {
    const spec = PHASE2_EVENT_RENDER_TABLE["biss.scramble_applied"];
    for (const key of BISS_DERIVATION_FACE) {
      expect(spec.payloadKeys).toContain(key);
    }
  });

  it("no table entry invents keys outside the #129 key sets + derivation face", () => {
    const legal = new Set([
      ...Object.values(REPORT_129_KEY_SETS).flat(),
      ...BISS_DERIVATION_FACE,
    ]);
    for (const [eventType, spec] of Object.entries(PHASE2_EVENT_RENDER_TABLE)) {
      for (const key of spec.payloadKeys) {
        expect(legal.has(key), `${eventType} invented key ${key}`).toBe(true);
      }
    }
  });

  it("phase2RenderSpec resolves table entries and returns null for unregistered types", () => {
    expect(phase2RenderSpec("gen.packet_sampled")).not.toBeNull();
    expect(phase2RenderSpec("ts.continuity_error")).toBeNull();
    expect(phase2RenderSpec("fault.applied")).toBeNull();
    expect(phase2RenderSpec("")).toBeNull();
  });

  it("the table is built from the same-source gen module verbatim (#141 drift lock)", () => {
    // no local override: every table entry IS the generated key array
    // (identity, not equality) — a hand-edited table fails here, and a
    // stale gen module fails npm run payload-keys:check
    for (const [eventType, spec] of Object.entries(PHASE2_EVENT_RENDER_TABLE)) {
      expect(spec.payloadKeys).toBe(PHASE2_PAYLOAD_KEYS[eventType as keyof typeof PHASE2_PAYLOAD_KEYS]);
    }
    expect(Object.keys(PHASE2_PAYLOAD_KEYS).sort()).toEqual([...PHASE2_EVENT_TYPES].sort());
  });
});
