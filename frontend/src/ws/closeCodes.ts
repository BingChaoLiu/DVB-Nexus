// WS close-code discipline (SPEC-501 §5/§8; src/api/ws/frames.py L31-45).
// The server closes with these codes; the client state machine branches on
// them — 1013 slow-consumer carries the resumption cursor in its reason.
export const CLOSE_SESSION_UNKNOWN = 4404; // session unknown/DISPOSED — do not reconnect
export const CLOSE_SUBSCRIBE_MISMATCH = 4400; // subscribe session ≠ route — client bug, do not blind-retry
export const CLOSE_SLOW_CONSUMER = 1013; // reason carries slow-consumer;journal_seq=<n>
export const CLOSE_STORAGE_UNAVAILABLE = 1011; // transient — reconnect with backoff
export const CLOSE_PONG_TIMEOUT = 1008; // missed server pings — reconnect with backoff
export const CLOSE_NORMAL = 1000; // user-initiated
export const CLOSE_ABNORMAL = 1006; // network drop (browser-reported) — reconnect

export const SLOW_CONSUMER_REASON_PREFIX = "slow-consumer;journal_seq=";

/** Parse the slow-consumer resumption cursor from a close reason (null if the
 * reason is not the slow-consumer form or the cursor is not a plain integer). */
export function parseSlowConsumerCursor(reason: string | null | undefined): number | null {
  if (!reason || !reason.startsWith(SLOW_CONSUMER_REASON_PREFIX)) return null;
  const tail = reason.slice(SLOW_CONSUMER_REASON_PREFIX.length);
  if (!/^\d+$/.test(tail)) return null;
  return Number(tail);
}
