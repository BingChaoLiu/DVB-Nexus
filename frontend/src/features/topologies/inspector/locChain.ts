// 口径 A loc-chain mapper (SPEC-402 §7.4, APPROVED 0.5.0): the save-path
// 400 REQUEST_BODY_INVALID details.errors[].loc chains → FieldError[].
//
// Envelope shape = SPEC-500 §6 path-addressed chain ({"errors":[{loc,msg,
// type},...]}; FastAPI's default 422 is overridden to 400 in
// src/api/errors.py). loc is body-relative: ["body","nodes",<i>,...].
//
// PRECISION CEILING (honest declaration, approved): the wire types config as
// an opaque object, so the backend never descends INTO config content — the
// deepest this mapper can land is a node's config placeholder. Content-level
// field errors only ever arrive via 口径 B (schemaPathMatch.ts, run prepare
// 422 free text).
//
// Degrade discipline (never throws, never fabricates): entries whose loc
// cannot be pinned to a draft node (missing/ out-of-range/ non-numeric index,
// no "nodes" segment, malformed details) return nothing here — the page's
// existing ApiError banner ([errorCode] message verbatim, SPEC-401 §8
// family branch) carries the graph-level content; nothing is silently
// swallowed by the FORM channel.
import { GENERATOR_FIELD_INVENTORY, type FieldDescriptor } from "./fieldInventory";

export interface FieldError {
  /** Draft node the error is pinned to. */
  nodeId: string;
  /** Descriptor path under the form ("config" = form-root banner,
   * "program" = group, "program.streams[].pid" = row field); null = node
   * level (under the node heading, no field claim). */
  fieldPath: string | null;
  /** Backend message verbatim (msg; type as fallback) — wire discipline:
   * never translated or re-worded. */
  message: string;
}

/** All descriptor paths known to the form (top level + program children +
 * stream row fields). */
const KNOWN_PATHS: Set<string> = (() => {
  const paths = new Set<string>();
  const walk = (fields: FieldDescriptor[]): void => {
    for (const field of fields) {
      paths.add(field.path);
      if (field.children) walk(field.children);
      if (field.rowFields) walk(field.rowFields);
    }
  };
  walk(GENERATOR_FIELD_INVENTORY);
  return paths;
})();

/** Turn loc segments after "config" into a canonical descriptor path.
 * Numeric segments (array indexes in the request body, e.g. streams[0]) are
 * normalized to the descriptor's `[]` placeholder; the concrete index is NOT
 * a form address (rows are identified by their content, not body order). */
function descriptorPathFor(rest: unknown[]): string | null {
  if (rest.length === 0 || rest[0] !== "config") return null; // node level
  const segments = rest.slice(1);
  if (segments.length === 0) return "config"; // form-root banner
  let path = "";
  for (const segment of segments) {
    if (typeof segment === "number") {
      path += "[]";
    } else if (typeof segment === "string") {
      path += path === "" ? segment : `.${segment}`;
    } else {
      return null; // unexpected segment shape → node level (defensive)
    }
  }
  return KNOWN_PATHS.has(path) ? path : null; // unmatched → node level
}

export function mapLocChain(details: unknown, draftNodeIds: string[]): FieldError[] {
  if (typeof details !== "object" || details === null) return [];
  const rawErrors = (details as { errors?: unknown }).errors;
  if (!Array.isArray(rawErrors)) return [];
  const result: FieldError[] = [];
  for (const raw of rawErrors) {
    if (typeof raw !== "object" || raw === null) continue;
    const loc = (raw as { loc?: unknown }).loc;
    const msg = (raw as { msg?: unknown }).msg;
    const type = (raw as { type?: unknown }).type;
    if (!Array.isArray(loc)) continue;
    const nodesIndex = loc.indexOf("nodes");
    if (nodesIndex === -1) continue; // graph level → page banner carries it
    const index = loc[nodesIndex + 1];
    if (typeof index !== "number" || !Number.isInteger(index) || index < 0 || index >= draftNodeIds.length) {
      continue; // unpinnable → graph level, no fabricated attribution
    }
    const message = typeof msg === "string" ? msg : typeof type === "string" ? type : "";
    result.push({ nodeId: draftNodeIds[index]!, fieldPath: descriptorPathFor(loc.slice(nodesIndex + 2)), message });
  }
  return result;
}
