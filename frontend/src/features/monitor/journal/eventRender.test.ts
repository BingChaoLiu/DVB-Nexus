// Pin: PHASE2_EVENT_RENDER_TABLE must carry exactly the eleven registered
// Phase 2 event types with the #129 REPORT §2 payload key sets (the registry
// validate_payload strict key sets — triple-pinned: #128 REPORT / #129
// registry / brief §2bis) plus the #164 Phase 3 state-observation key sets
// (SPEC-303 §Phase3 — rf./sec. state_observed, extracted verbatim from
// domain/observation/registry.py RF_TUNER_SNAPSHOT_KEYS / the sec union).
// The expected values below are the independent extractions, not a copy of
// the implementation table.
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

// #164 Phase 3 state-observation key-set extraction (SPEC-303 §Phase3; the
// registered sec shape = lnb ∪ legacy sat_selected ∪ switch union — one
// per-node snapshot face). Keys extracted from the backend registry
// constants, NOT from payloadKeys.gen.ts (the same-source gen module is
// pinned separately by the drift-lock test below).
const REPORT_164_KEY_SETS: Record<string, readonly string[]> = {
  "rf.state_observed": [
    "node_id",
    "health",
    "causes",
    "source",
    "confidence",
    "lock_state",
    "if_frequency_khz",
    "ber_state",
    "locked_transponder_id",
    "stale",
  ],
  "sec.state_observed": [
    "node_id",
    "health",
    "causes",
    "source",
    "confidence",
    "voltage",
    "tone_commanded",
    "tone_actual",
    "tone_composite",
    "band_selected",
    "lo_frequency_khz",
    "polarization_delivered",
    "short_circuit_state",
    "ub_assignments",
    "sat_selected",
    "committed_switch_state",
    "uncommitted_switch_state",
    "port_selected",
    "power_pass",
  ],
};

// The optional #127 derivation face (base + these = legal on mode "E"/"2").
const BISS_DERIVATION_FACE = ["derivation_ref", "mismatch_variants"] as const;

describe("PHASE2_EVENT_RENDER_TABLE — registry-driven rendering surface", () => {
  it("covers exactly the eleven registered Phase 2/Phase 3 event types (no extra, no missing)", () => {
    expect(Object.keys(PHASE2_EVENT_RENDER_TABLE).sort()).toEqual([...PHASE2_EVENT_TYPES].sort());
  });

  it("every table entry carries the full #129/#164 base key set (display order)", () => {
    for (const [eventType, keys] of Object.entries({ ...REPORT_129_KEY_SETS, ...REPORT_164_KEY_SETS })) {
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

  it("no table entry invents keys outside the #129/#164 key sets + derivation face", () => {
    const legal = new Set([
      ...Object.values(REPORT_129_KEY_SETS).flat(),
      ...Object.values(REPORT_164_KEY_SETS).flat(),
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
