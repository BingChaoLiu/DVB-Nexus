// The Phase 2 event rendering registry (SPEC-403 §Phase2 L319-321): the ONE
// structural table the journal tail window and the diagnosis detail consume —
// no hardcoded event list in any component (票 #134: 注册表驱动渲染,新事件
// 类型加表即渲染). Keys are the wire event_type names (#129 registry); the
// payloadKeys come from the SAME-SOURCE generated module (#141 —
// payloadKeys.gen.ts, generated from the backend registry's ordered face,
// drift-locked by payload-keys:check) rendered verbatim
// (SPEC-403 L315: wire enums/keys 禁改写). Presentation faces look entries up
// through phase2RenderSpec — an unregistered type resolves to null and falls
// back to the generic wire face (ADR-0006 unknown tolerance, zero invention).
import type { Phase2EventType } from "../types";
import { PHASE2_PAYLOAD_KEYS } from "./payloadKeys.gen";

export interface Phase2EventRenderSpec {
  /** The #129 payload key set in display order (wire key names verbatim).
   * Payload keys absent on a concrete envelope simply do not render (the
   * biss.scramble_applied derivation face is optional per mode). */
  readonly payloadKeys: readonly string[];
}

export const PHASE2_EVENT_RENDER_TABLE = (
  Object.keys(PHASE2_PAYLOAD_KEYS) as Phase2EventType[]
).reduce((table, eventType) => {
  table[eventType] = { payloadKeys: PHASE2_PAYLOAD_KEYS[eventType] };
  return table;
}, {} as Record<Phase2EventType, Phase2EventRenderSpec>);

/** Registry lookup: the render spec for a wire event type, or `null` when the
 * type is not in the table (generic wire face — never a fabricated row). */
export function phase2RenderSpec(eventType: string): Phase2EventRenderSpec | null {
  if (!Object.prototype.hasOwnProperty.call(PHASE2_EVENT_RENDER_TABLE, eventType)) return null;
  return PHASE2_EVENT_RENDER_TABLE[eventType as Phase2EventType];
}

/** The payload entries a Phase 2 envelope renders: the spec's keys that are
 * actually present (display order first), then any extra payload keys the
 * envelope carries beyond the table (append-only defensive face — unknown
 * tolerance per ADR-0006; the backend registry's strict key sets make this
 * empty in practice). Values are returned unwired for verbatim rendering. */
export function phase2PayloadEntries(
  eventType: string,
  payload: Record<string, unknown> | undefined,
): [string, unknown][] {
  if (payload === undefined || typeof payload !== "object") return [];
  const spec = phase2RenderSpec(eventType);
  const entries: [string, unknown][] = [];
  const seen = new Set<string>();
  if (spec !== null) {
    for (const key of spec.payloadKeys) {
      if (Object.prototype.hasOwnProperty.call(payload, key)) {
        entries.push([key, payload[key]]);
        seen.add(key);
      }
    }
  }
  for (const [key, value] of Object.entries(payload)) {
    if (!seen.has(key)) entries.push([key, value]);
  }
  return entries;
}
