// WS client core (SPEC-400 §4.4): single-connection single-session stream
// over /ws/v1/sessions/{session_id} (SPEC-501 §3), upstream subscribe/ping
// only, downstream journal/hint/ready/pong dispatch, and the close-code
// reconnect discipline of SPEC-501 §5/§8. Hints are best-effort (loss needs
// no compensation — recovery is the reconnect full refetch); journal frames
// carry facts and always resume via last_journal_seq.
import { wsBaseFromLocation } from "../lib/env";
import {
  CLOSE_NORMAL,
  CLOSE_SESSION_UNKNOWN,
  CLOSE_SLOW_CONSUMER,
  CLOSE_SUBSCRIBE_MISMATCH,
  parseSlowConsumerCursor,
} from "./closeCodes";
import { isHintTopic } from "./topics";

export type StreamStatus = "idle" | "connecting" | "ready" | "reconnecting" | "closed";

export type JournalEnvelope = Record<string, unknown>;

export interface SessionStreamOptions {
  sessionId: string;
  /** ws(s) base ending at /ws/v1 (default: derived from window.location). */
  baseUrl?: string;
  /** Resume cursor for the first subscribe (SPEC-501 §5 recovery). */
  lastJournalSeq?: number;
  /** Socket injection seam for tests; must behave like a WebSocket subset. */
  socketFactory?: (url: string) => MinimalSocket;
  reconnectBaseDelayMs?: number;
  reconnectMaxDelayMs?: number;
  /** Applied on top of the base backoff; default adds uniform jitter. */
  jitter?: (delayMs: number) => number;
  onJournal?: (envelope: JournalEnvelope) => void;
  onHint?: (topic: string, data: Record<string, unknown>) => void;
  onReady?: (replayedFrom: number) => void;
  onStatus?: (status: StreamStatus) => void;
  /** Close-code observer (SPEC-408 §4.3 ticket #95): every close event is
   * forwarded verbatim — including the permanent 4404 session-unknown close
   * the monitor page's unknown-session state branches on. Additive; absent
   * observers change nothing. */
  onClose?: (code: number, reason: string) => void;
}

// The real DOM WebSocket's handler property types are not directly
// assignable to narrow callback shapes (this-params + MessageEvent), so the
// seam types handlers as unknown — the stream only ever ASSIGNS (with
// explicit param annotations) and never reads them back.
export interface MinimalSocket {
  send(data: string): void;
  close(code?: number, reason?: string): void;
  onopen: unknown;
  onclose: unknown;
  onerror: unknown;
  onmessage: unknown;
}

const DEFAULT_BASE_DELAY_MS = 250;
const DEFAULT_MAX_DELAY_MS = 8000;

/** Close codes that terminate the stream permanently (no reconnect). */
const PERMANENT_CLOSE_CODES: ReadonlySet<number> = new Set([
  CLOSE_NORMAL,
  CLOSE_SESSION_UNKNOWN,
  CLOSE_SUBSCRIBE_MISMATCH,
]);

export class SessionStream {
  #options: SessionStreamOptions;
  #socket: MinimalSocket | null = null;
  #status: StreamStatus = "idle";
  #lastJournalSeq: number | null;
  #reconnectAttempt = 0;
  #reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  #closedByUser = false;

  constructor(options: SessionStreamOptions) {
    this.#options = options;
    this.#lastJournalSeq = options.lastJournalSeq ?? null;
  }

  get status(): StreamStatus {
    return this.#status;
  }

  get sessionId(): string {
    return this.#options.sessionId;
  }

  /** The freshest journal_seq seen on journal frames (reconnect cursor). */
  get lastJournalSeq(): number | null {
    return this.#lastJournalSeq;
  }

  subscribe(): void {
    if (this.#socket !== null || this.#closedByUser) return;
    this.#setStatus("connecting");
    this.#open();
  }

  close(): void {
    this.#closedByUser = true;
    this.#clearTimer();
    this.#socket?.close(CLOSE_NORMAL, "client close");
    this.#socket = null;
    this.#setStatus("closed");
  }

  // --- internals ------------------------------------------------------------

  #open(): void {
    const base = this.#options.baseUrl ?? wsBaseFromLocation(window.location);
    const url = `${base}/sessions/${encodeURIComponent(this.#options.sessionId)}`;
    const socket = (this.#options.socketFactory ?? ((u: string) => new WebSocket(u)))(url);
    this.#socket = socket;
    socket.onopen = () => {
      const subscribe: { type: "subscribe"; session_id: string; last_journal_seq?: number } = {
        type: "subscribe",
        session_id: this.#options.sessionId,
      };
      if (this.#lastJournalSeq !== null) subscribe.last_journal_seq = this.#lastJournalSeq;
      socket.send(JSON.stringify(subscribe));
    };
    socket.onmessage = (event: { data: unknown }) => {
      this.#handleFrame(event.data);
    };
    socket.onclose = (event: { code: number; reason: string }) => {
      this.#handleClose(event.code, event.reason);
    };
    socket.onerror = () => {
      // close event follows with a code; nothing to do here
    };
  }

  #handleFrame(raw: unknown): void {
    let frame: unknown;
    try {
      frame = JSON.parse(typeof raw === "string" ? raw : String(raw));
    } catch {
      return; // tolerate malformed frames (ADR-0006 unknown tolerance)
    }
    if (typeof frame !== "object" || frame === null) return;
    const record = frame as Record<string, unknown>;
    switch (record.type) {
      case "journal": {
        const envelope = record.envelope;
        if (typeof envelope === "object" && envelope !== null) {
          const seq = (envelope as Record<string, unknown>).journal_seq;
          if (typeof seq === "number") this.#lastJournalSeq = seq;
          this.#options.onJournal?.(envelope as JournalEnvelope);
        }
        return;
      }
      case "hint": {
        const topic = record.topic;
        if (typeof topic === "string" && isHintTopic(topic)) {
          this.#options.onHint?.(
            topic,
            (typeof record.data === "object" && record.data !== null ? record.data : {}) as Record<string, unknown>,
          );
        }
        return; // unknown topics tolerated-and-ignored (ADR-0006 posture)
      }
      case "ready": {
        this.#reconnectAttempt = 0;
        const replayedFrom = typeof record.replayed_from === "number" ? record.replayed_from : null;
        this.#setStatus("ready");
        if (replayedFrom !== null) this.#options.onReady?.(replayedFrom);
        return;
      }
      case "pong":
        return; // server responds to our ping; nothing to echo
      default:
        return; // unknown frame types ignored (ADR-0006)
    }
  }

  #handleClose(code: number, reason: string): void {
    this.#socket = null;
    this.#options.onClose?.(code, reason);
    if (this.#closedByUser || PERMANENT_CLOSE_CODES.has(code)) {
      this.#setStatus("closed");
      return;
    }
    if (code === CLOSE_SLOW_CONSUMER) {
      const cursor = parseSlowConsumerCursor(reason);
      if (cursor !== null) this.#lastJournalSeq = cursor;
    }
    // Everything not in the permanent set goes through the backoff machine:
    // the known transient codes (1013/1008/1011/1006) and unknown codes alike
    // behave conservatively as recoverable network-class failures.
    this.#scheduleReconnect();
  }

  #scheduleReconnect(): void {
    this.#setStatus("reconnecting");
    const base = this.#options.reconnectBaseDelayMs ?? DEFAULT_BASE_DELAY_MS;
    const max = this.#options.reconnectMaxDelayMs ?? DEFAULT_MAX_DELAY_MS;
    const delay = Math.min(max, base * 2 ** this.#reconnectAttempt);
    this.#reconnectAttempt += 1;
    const jitter = this.#options.jitter ?? ((ms: number) => ms + ms * Math.random() / 2);
    this.#reconnectTimer = setTimeout(() => {
      this.#reconnectTimer = null;
      if (!this.#closedByUser) this.#open();
    }, jitter(delay));
  }

  #clearTimer(): void {
    if (this.#reconnectTimer !== null) {
      clearTimeout(this.#reconnectTimer);
      this.#reconnectTimer = null;
    }
  }

  #setStatus(status: StreamStatus): void {
    this.#status = status;
    this.#options.onStatus?.(status);
  }
}
