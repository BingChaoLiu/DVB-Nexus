// hint → REST invalidation bridge (SPEC-400 §6.3): the SPEC-305 §8 matrix as
// code. Each hint topic maps to the canonical query-key prefix whose queries
// refetch on invalidation; observation.event_appended maps to NO invalidation
// because journal frames themselves carry the facts (they merge via
// journalCache — the hint is only a cursor fallback there).
//
// The session scope comes from the hint payload's session_id (every hint
// carries it — the SPEC-305 §8 data keys), with an options override for
// callers that want to pin a scope.
import type { QueryClient } from "@tanstack/react-query";
import { createThrottledInvalidator } from "./throttle";
import { qk } from "./keys";
import { isHintTopic } from "../ws/topics";
import type { HintTopic } from "../ws/topics";

type PrefixFactory = (sessionId: string, data: Record<string, unknown>) => readonly unknown[];

const HINT_INVALIDATION_PREFIXES: Partial<Record<HintTopic, PrefixFactory>> = {
  // observation.event_appended: no REST refetch — journal frames carry facts.
  "observation.metric_updated": (sessionId) => qk.metrics(sessionId),
  "observation.alert_changed": (sessionId) => qk.alerts(sessionId),
  "observation.health_changed": (sessionId) => qk.health(sessionId),
  "observation.export_progress": (sessionId, data) => {
    const exportId = data.export_id;
    return typeof exportId === "string" ? qk.export(sessionId, exportId) : qk.export(sessionId, "");
  },
};

export interface StreamLike {
  onHint(handler: (topic: string, data: Record<string, unknown>) => void): void;
}

export interface HintBridgeOptions {
  /** Fallback scope when a hint payload omits session_id (defensive). */
  sessionId?: string;
}

export function attachHintBridge(
  queryClient: QueryClient,
  stream: StreamLike,
  options: HintBridgeOptions = {},
): () => void {
  const throttled = createThrottledInvalidator(queryClient);
  const handler = (topic: string, data: Record<string, unknown>) => {
    if (!isHintTopic(topic)) return;
    const factory = HINT_INVALIDATION_PREFIXES[topic];
    if (!factory) return;
    const payloadSession = data.session_id;
    const sessionId =
      typeof payloadSession === "string" && payloadSession.length > 0
        ? payloadSession
        : (options.sessionId ?? "");
    throttled.invalidate(factory(sessionId, data));
  };
  stream.onHint(handler);
  return () => throttled.flush();
}
