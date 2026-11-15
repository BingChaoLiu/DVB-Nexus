// Page-level session stream wiring (SPEC-403 §4.8, REQ-UI-403-007): the ONLY
// WS channel the monitor page uses — the #61 SessionStream client — wired to
// the #61 invalidation bridge and journal cache. No second WS channel, no
// second throttling mechanism: journal frames merge via applyJournalFrame
// (facts), hints flow through attachHintBridge (pointers → REST invalidation,
// 250ms coalescing). Real-time rendering = throttled refetch, never
// frame-driven DOM streaming.
//
// Wiring note: SessionStream takes its callbacks as constructor options (no
// on* methods), while attachHintBridge subscribes via a StreamLike method —
// so this module CONSTRUCTS the stream with forwarding options and attaches
// the bridge through a capturing StreamLike adapter.
import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";
import { SessionStream, type JournalEnvelope, type StreamStatus } from "../../../ws/SessionStream";
import { applyJournalFrame } from "../../../query/journalCache";
import { attachHintBridge } from "../../../query/invalidation";
import { qk } from "../../../query/keys";

export interface WireOptions {
  sessionId: string;
  /** Socket injection seam for tests (FakeSocketHandle posture). */
  socketFactory?: (url: string) => import("../../../ws/SessionStream").MinimalSocket;
  /** Status forwarding (header badge). */
  onStatus?: (status: StreamStatus) => void;
  /** Resume cursor override (default: the cached journal watermark). */
  lastJournalSeq?: number;
}

export interface WiredStream {
  stream: SessionStream;
  /** Detach: flushes pending throttled invalidations (tests / unmount). */
  detach: () => void;
}

/** The freshest journal_seq in the canonical journal cache (resume cursor). */
export function journalWatermark(queryClient: QueryClient, sessionId: string): number | null {
  const cached = queryClient.getQueryData<JournalEnvelope[]>(qk.events(sessionId, "journal"));
  const last = cached?.at(-1);
  return typeof last?.journal_seq === "number" ? last.journal_seq : null;
}

/**
 * Construct one stream and wire it to one query client: journal → cache
 * merge, hints → throttled bridge invalidation. Pure wiring — no React.
 */
export function wireSessionStream(queryClient: QueryClient, options: WireOptions): WiredStream {
  // The bridge attaches once and captures its handler here; every hint frame
  // the stream receives forwards into it (single bridge instance, shared
  // throttled invalidator).
  let hintHandler: ((topic: string, data: Record<string, unknown>) => void) | null = null;
  const stream = new SessionStream({
    sessionId: options.sessionId,
    socketFactory: options.socketFactory,
    lastJournalSeq: options.lastJournalSeq ?? journalWatermark(queryClient, options.sessionId) ?? undefined,
    onStatus: options.onStatus,
    onJournal: (envelope: JournalEnvelope) => {
      applyJournalFrame(queryClient, options.sessionId, envelope);
    },
    onHint: (topic, data) => {
      hintHandler?.(topic, data);
    },
  });
  const detachBridge = attachHintBridge(
    queryClient,
    {
      onHint: (handler) => {
        hintHandler = handler;
      },
    },
    { sessionId: options.sessionId },
  );
  return { stream, detach: detachBridge };
}

/**
 * React binding: one SessionStream per mounted page scope. The stream
 * subscribes on mount (resuming from the cached watermark on remount —
 * SPEC-501 §5 recovery posture) and closes on unmount/session change.
 * Returns the transport status for the neutral header badge (best-effort
 * pointer-layer visibility; carries no verdict semantics).
 */
export function useSessionStream(sessionId: string | null): StreamStatus {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<StreamStatus>("idle");

  useEffect(() => {
    // No scope tracked → no stream; status stays "idle" (initial state).
    // Session changes remount the page (key={sessionId}), so the state resets
    // naturally without a synchronous setState in the effect body.
    if (sessionId === null) return;
    const { stream, detach } = wireSessionStream(queryClient, { sessionId, onStatus: setStatus });
    stream.subscribe();
    return () => {
      detach();
      stream.close();
    };
  }, [sessionId, queryClient]);

  return status;
}
