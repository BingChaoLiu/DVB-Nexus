// WS hint topics — the five-topic whitelist, exact strings matching the
// server's HINT_TOPICS (src/api/ws/frames.py L71-79; SPEC-305 §8 matrix).
// Events never travel as hints; unknown topics are ignored client-side
// (ADR-0006 decision 4 unknown-tolerance posture).
export const HINT_TOPICS = [
  "observation.event_appended",
  "observation.metric_updated",
  "observation.alert_changed",
  "observation.health_changed",
  "observation.export_progress",
] as const;

export type HintTopic = (typeof HINT_TOPICS)[number];

export function isHintTopic(value: unknown): value is HintTopic {
  return typeof value === "string" && (HINT_TOPICS as readonly string[]).includes(value);
}
