// SPEC-404 §Phase2 — the packet-inspector view parameter vocabulary
// (ruling §10-5: this file is #132's exclusive face; monitor/types.ts is
// #134's). The wire enum is rendered verbatim everywhere — no aliasing, no
// case folding, no semantic rewriting (SPEC-403 L315 discipline).
//
// The locator triple (inspect_artifact/inspect_pid/inspect_packet) keeps its
// MVP semantics untouched; `view` is additive on the deep link only
// (SPEC-404 §Phase2: Lab 诊断证据深链与 Monitor 直达共用).

/** The wire view vocabulary (`view=t2mi|bbframe|ts`; default `ts`). */
export const PACKET_INSPECTOR_VIEWS = ["t2mi", "bbframe", "ts"] as const;

export type PacketInspectorView = (typeof PACKET_INSPECTOR_VIEWS)[number];

/** MVP-compatibility default — the absent/invalid param behaves exactly like
 * the pre-Phase2 panel (zero-regression face). */
export const DEFAULT_PACKET_INSPECTOR_VIEW: PacketInspectorView = "ts";

export function isPacketInspectorView(value: string): value is PacketInspectorView {
  return (PACKET_INSPECTOR_VIEWS as readonly string[]).includes(value);
}

/**
 * Deep-link/prop parser: `null` (param absent) or a value outside the wire
 * vocabulary falls back to the default `ts` — the honest MVP face, never a
 * fabricated view.
 */
export function parsePacketInspectorView(raw: string | null): PacketInspectorView {
  return raw !== null && isPacketInspectorView(raw) ? raw : DEFAULT_PACKET_INSPECTOR_VIEW;
}

/**
 * Optional BISS evidence annotation (SPEC-404 §Phase2 BISS face). The keys
 * mirror the `biss.*` envelope payloads (#129 REPORT §2 key sets — WS journal
 * frames are outside OpenAPI, so this prop is the consumers' hand-off seam:
 * #134 journal face / #136 wiring). Key material NEVER crosses this face —
 * only the fingerprint reference (`sha256:` prefix verbatim) and the
 * mutation-log artifact id.
 */
export interface BissEvidenceAnnotation {
  /** `biss.*` `mode` wire value ("1" | "E" | "2") — rendered verbatim. */
  mode?: string;
  /** `key_fingerprint` / `key_fingerprint_ref` — fingerprint reference only. */
  key_fingerprint_ref?: string;
  /** `mutation_log_ref` — the run's log artifact id (the summary face). */
  mutation_log_ref?: string | null;
}
