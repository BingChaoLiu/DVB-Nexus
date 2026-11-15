// 口径 B schema-path matcher (SPEC-402 §7.5, APPROVED 0.5.0): run prepare
// 422 error strings → best-effort field placement.
//
// REAL wire shapes (fixtures in schemaPathMatch.test.ts):
//   - SIM_TS_CONFIG_INVALID (backends.py L594 raises WITHOUT details; the
//     caller feeds the envelope message): the message embeds the offending
//     field in the frozen slot `(field '<name>'; ...)` where <name> is the
//     validator's BARE field string (validator.py: "target_bitrate_bps",
//     "pid", "stream_type", ...). Primary parse = that quoted slot; the bare
//     name resolves uniquely to a descriptor path by its last segment (every
//     validator field string maps to exactly one inventory path — the bare
//     "pid" decoy parentheticals like "(pid 256)" do not match the slot).
//   - SIM_TS_PLAN_INVALID (details.errors[] free-text strings): may name
//     target node ids; fuller path substrings are matched defensively.
//
// Node attribution REUSES the #62 mapPlanErrors word-boundary rule (禁另写)
// plus the approved single-candidate rule: a string naming no node is
// attributed to the caller's ONLY candidate id (caller-supplied context —
// the config owner in single-generator scope); with multiple candidates an
// unattributed string stays in `rest` (the panel shows it verbatim with the
// run_prepare tag) — ambiguity is never resolved by fabrication.
import type { FieldDescriptor } from "./fieldInventory";
import { GENERATOR_FIELD_INVENTORY } from "./fieldInventory";
import type { FieldError } from "./locChain";
import { mapPlanErrors } from "../violations";

export interface SchemaPathMatchResult {
  /** Field/node-level placements (FieldError semantics shared with 口径 A). */
  fieldHits: FieldError[];
  /** Strings that could not be honestly placed — same-channel panel entries
   * (ViolationPanel, source run_prepare; #62 §7.5). */
  rest: string[];
}

/** All descriptor paths, longest first (longest-match-wins fallback). */
const PATHS_BY_LENGTH: string[] = (() => {
  const paths: string[] = [];
  const walk = (fields: FieldDescriptor[]): void => {
    for (const field of fields) {
      paths.push(field.path);
      if (field.children) walk(field.children);
      if (field.rowFields) walk(field.rowFields);
    }
  };
  walk(GENERATOR_FIELD_INVENTORY);
  return paths.sort((a, b) => b.length - a.length);
})();

/** Bare validator field string → descriptor path, resolved by last segment.
 * The real CONFIG 422 names fields this way (validator.py `_error(...,
 * field)`); every emitted name is unique across the inventory levels. */
const PATH_BY_BARE_NAME: Map<string, string> = (() => {
  const map = new Map<string, string>();
  for (const path of PATHS_BY_LENGTH) {
    const last = path.split(".").pop()!;
    if (!map.has(last)) map.set(last, path); // first (= shortest under equal name) wins
  }
  return map;
})();

/** The frozen CONFIG 422 message slot: `(field '<name>'; ...)`. */
const FIELD_SLOT = /\(field '([^']+)';/;

function isWordChar(ch: string | undefined): boolean {
  return ch !== undefined && /[A-Za-z0-9_]/.test(ch);
}

function mentionsPath(text: string, path: string): boolean {
  let index = text.indexOf(path);
  while (index !== -1) {
    const beforeOk = index === 0 || !isWordChar(text[index - 1]);
    const afterIndex = index + path.length;
    const afterOk = afterIndex === text.length || !isWordChar(text[afterIndex]);
    if (beforeOk && afterOk) return true;
    index = text.indexOf(path, index + 1);
  }
  return false;
}

/** Field resolution for one error string: primary quoted-slot parse (bare
 * name → unique path), fallback longest word-boundary path substring with
 * concrete indexes normalized to the `[]` placeholder. */
function resolveFieldPath(message: string): string | null {
  const slot = FIELD_SLOT.exec(message);
  if (slot !== null) {
    const bare = slot[1]!;
    const resolved = PATH_BY_BARE_NAME.get(bare);
    if (resolved !== undefined) return resolved;
  }
  const normalized = message.replace(/\[\d+\]/g, "[]");
  return PATHS_BY_LENGTH.find((path) => mentionsPath(normalized, path)) ?? null;
}

export function matchSchemaPathErrors(errors: string[], draftNodeIds: string[]): SchemaPathMatchResult {
  const fieldHits: FieldError[] = [];
  const rest: string[] = [];
  for (const message of errors) {
    // Reuse the #62 word-boundary node attribution — same channel, same rule.
    const mentioned = mapPlanErrors([message], draftNodeIds)[0]?.nodeIds ?? [];
    const fieldPath = resolveFieldPath(message);
    if (mentioned.length > 0) {
      fieldHits.push({ nodeId: mentioned[0]!, fieldPath, message });
    } else if (draftNodeIds.length === 1 && fieldPath !== null) {
      // approved single-candidate rule, evidence-gated: the caller vouches
      // this is the config owner AND the string carries a config-field
      // slot — strings without field evidence keep the panel channel (no
      // pinning arbitrary plan text onto the node).
      fieldHits.push({ nodeId: draftNodeIds[0]!, fieldPath, message });
    } else {
      rest.push(message);
    }
  }
  return { fieldHits, rest };
}
