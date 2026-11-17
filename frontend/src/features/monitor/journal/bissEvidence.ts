// BissEvidence derivation (#134 seam, SPEC-404 §Phase2 BISS face): the
// Monitor journal face's hand-off to the packet inspector's BissAnnotation
// (#132 BissEvidenceAnnotation prop). Reads journal FACTS only:
// - the newest biss.descramble_failed wins for mode / key_fingerprint_ref
//   (the failure-evidence face the annotation interlinks — 解扰失败 ≠ 码流
//   损坏 evidence stays visible);
// - mutation_log_ref comes from the newest biss.scramble_applied that
//   carried one (only that event owns the wire key; a missing log ref is
//   omitted — undefined, never fabricated).
// Key material NEVER crosses this face: the payloads carry fingerprint
// references only (sha256: prefix verbatim, SPEC-610 §9). Malformed payloads
// are skipped honestly (ADR-0006 unknown tolerance; the backend registry's
// strict key sets make this a defensive posture, not a repair path).
import type { BissEvidenceAnnotation } from "../packet-inspector/viewTypes";
import type { JournalEnvelope } from "../../../ws/SessionStream";

// Namespace-prefix lookup (the registry-driven posture — no enumerated type
// list): every biss.* envelope is candidate evidence; the key-based guards
// below decide what the annotation actually carries. A future biss.* type
// lands here without an edit.
const BISS_NAMESPACE = "biss.";

/** Wire-string guards: a field participates only when it is a non-empty
 * string (fingerprint refs / modes); numbers are never coerced into string
 * slots (缺失 ≠ 零 posture for the annotation face). */
function wireString(value: unknown): string | undefined {
  return typeof value === "string" && value !== "" ? value : undefined;
}

function payloadOf(envelope: JournalEnvelope): Record<string, unknown> | null {
  const payload = envelope.payload;
  return typeof payload === "object" && payload !== null ? (payload as Record<string, unknown>) : null;
}

function seqOf(envelope: JournalEnvelope): number {
  return typeof envelope.journal_seq === "number" ? envelope.journal_seq : Number.NaN;
}

/**
 * Derive the BISS evidence annotation from the session's journal cache.
 * Returns `null` when no well-formed biss.* event exists — honest absence,
 * no fabricated annotation.
 */
export function deriveBissEvidence(envelopes: readonly JournalEnvelope[]): BissEvidenceAnnotation | null {
  // Newest-first scan: highest journal_seq first (NaN sorts last — a
  // malformed seq never outranks a stamped one).
  const ordered = [...envelopes]
    .filter((envelope) => typeof envelope.event_type === "string" && envelope.event_type.startsWith(BISS_NAMESPACE))
    .sort((a, b) => {
      const sa = seqOf(a);
      const sb = seqOf(b);
      if (Number.isNaN(sa) && Number.isNaN(sb)) return 0;
      if (Number.isNaN(sa)) return 1;
      if (Number.isNaN(sb)) return -1;
      return sb - sa;
    });

  let annotation: BissEvidenceAnnotation | null = null;
  let logRef: string | undefined;
  for (const envelope of ordered) {
    const payload = payloadOf(envelope);
    if (payload === null) continue;
    if (annotation === null) {
      const mode = wireString(payload.mode);
      // descramble_failed carries key_fingerprint_ref; scramble_applied
      // carries key_fingerprint — both are the same fingerprint-reference
      // symbol on their own wire key.
      const fingerprint = wireString(payload.key_fingerprint_ref) ?? wireString(payload.key_fingerprint);
      if (mode !== undefined || fingerprint !== undefined) {
        annotation = {
          ...(mode !== undefined ? { mode } : {}),
          ...(fingerprint !== undefined ? { key_fingerprint_ref: fingerprint } : {}),
        };
      }
    }
    if (logRef === undefined) {
      const ref = payload.mutation_log_ref;
      if (typeof ref === "string" && ref !== "") logRef = ref;
    }
    if (annotation !== null && logRef !== undefined) break;
  }
  if (annotation === null) return null;
  return logRef !== undefined ? { ...annotation, mutation_log_ref: logRef } : annotation;
}
