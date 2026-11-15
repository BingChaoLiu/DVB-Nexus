// Three-part joint save gate (SPEC-402 §7.6, approved 2026-11-15 "M5 SPEC
// 批准记录 #6"): G1 completeness (edit-state statement 配置待填, existence
// only) ∧ G2 structural validation report (the #62 editorState validate-panel
// state — server report over the STORED graph + prepare 422 same-channel
// entries) ∧ G3 displayed field errors (口径 A loc-chain backfill + 口径 B
// schema-path field hits).
//
// Honest semantics: reasons.length === 0 means "no known blocking signal",
// NEVER "config is valid" — the backend stays the authority (session
// VALIDATING / run prepare). Pure function over a structural projection of
// EditorState + the inspector's FieldError[]; exported signature-frozen for
// the session-entry owner tickets (#67 additive adoption; #64 stays as-is).
import { isConfigComplete } from "./fieldInventory";
import type { FieldError } from "./locChain";

export type GateReason =
  | { kind: "config_incomplete"; nodeIds: string[] }
  | { kind: "structural_violations" }
  | { kind: "field_errors" };

export interface GateInput {
  /** Draft projection: the only fields the gate may look at. */
  nodes: { node_id: string; node_type: string; config: unknown }[];
  /** Structural projection of the #62 editorState ValidationView. */
  validation: { status: "idle" | "done"; entries: unknown[]; graphEntries: unknown[]; planErrors: unknown[] };
  /** Currently displayed field-level errors (口径 A/B confluence). */
  fieldErrors: FieldError[];
}

export interface GateResult {
  /** Empty = gate passes. Reasons are ordered G1 → G2 → G3 (deterministic). */
  reasons: GateReason[];
}

export function computeInspectorGate(input: GateInput): GateResult {
  const reasons: GateReason[] = [];

  // G1 — completeness (配置待填): any ts_generator node with unfilled
  // required fields. config_schema=null / unregistered types pass trivially
  // (isConfigComplete never guesses shapes).
  const incomplete = input.nodes
    .filter((node) => !isConfigComplete(node.node_type, node.config))
    .map((node) => node.node_id);
  if (incomplete.length > 0) {
    reasons.push({ kind: "config_incomplete", nodeIds: incomplete });
  }

  // G2 — the most recent server report, when one exists (status done),
  // blocks while it carries any violation entry. idle (unsaved draft) never
  // blocks: no server report exists and the first save is the only path to
  // one (SPEC-401 §7.4 fixed third step).
  const report = input.validation;
  if (report.status === "done" && report.entries.length + report.graphEntries.length + report.planErrors.length > 0) {
    reasons.push({ kind: "structural_violations" });
  }

  // G3 — field-level errors currently displayed.
  if (input.fieldErrors.length > 0) {
    reasons.push({ kind: "field_errors" });
  }

  return { reasons };
}
