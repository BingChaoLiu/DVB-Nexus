// SessionStream seam tests (SPEC-400 §4.4): connection/subscription frames,
// downstream frame dispatch, and the close-code reconnect discipline. The
// socket is injected (socketFactory) — tests never touch the network; frames
// assert the exact wire shapes from src/api/ws/frames.py (L151-176 upstream,
// L89-127 downstream).
import { describe, expect, it, vi } from "vitest";
import { CLOSE_SLOW_CONSUMER, parseSlowConsumerCursor } from "./closeCodes";
import { SessionStream } from "./SessionStream";
import { FakeSocketHandle } from "./testSupport";

function newStream(options: Partial<ConstructorParameters<typeof SessionStream>[0]> = {}) {
  const sockets: FakeSocketHandle[] = [];
  const stream = new SessionStream({
    sessionId: "sess-1",
    baseUrl: "ws://test/ws/v1",
    socketFactory: (url) => {
      const socket = new FakeSocketHandle(url);
      sockets.push(socket);
      return socket;
    },
    jitter: (ms) => ms,
    reconnectBaseDelayMs: 100,
    reconnectMaxDelayMs: 400,
    ...options,
  });
  return { stream, sockets };
}

/** The socket the stream is expected to speak on after n (re)connections. */
function current(sockets: FakeSocketHandle[]) {
  return sockets[sockets.length - 1];
}

describe("SessionStream — connection and subscription frames", () => {
  it("sends the subscribe frame on open (session id verbatim, no cursor by default)", () => {
    const { stream, sockets } = newStream();
    stream.subscribe();
    const socket = current(sockets);
    socket.serverAccept();
    expect(socket.sent).toEqual([
      JSON.stringify({ type: "subscribe", session_id: "sess-1" }),
    ]);
  });

  it("carries last_journal_seq in the subscribe frame when a cursor is known", () => {
    const { stream, sockets } = newStream({ lastJournalSeq: 7 });
    stream.subscribe();
    current(sockets).serverAccept();
    expect(JSON.parse(current(sockets).sent[0])).toEqual({
      type: "subscribe",
      session_id: "sess-1",
      last_journal_seq: 7,
    });
  });

  it("transitions idle → connecting → ready and reports replayed_from", () => {
    const statuses: string[] = [];
    const { stream, sockets } = newStream({ onStatus: (s) => statuses.push(s) });
    stream.subscribe();
    expect(statuses).toEqual(["connecting"]);
    const socket = current(sockets);
    socket.serverAccept();
    socket.serverMessage({ type: "ready", replayed_from: 1235 });
    expect(stream.status).toBe("ready");
    expect(statuses).toEqual(["connecting", "ready"]);
  });
});

describe("SessionStream — downstream frame dispatch", () => {
  it("dispatches journal frames with the envelope verbatim and tracks the cursor", () => {
    const onJournal = vi.fn();
    const { stream, sockets } = newStream({ onJournal });
    stream.subscribe();
    const socket = current(sockets);
    socket.serverAccept();
    const envelope = { journal_seq: 41, event_type: "simulation.run_completed", payload: {} };
    socket.serverMessage({ type: "journal", envelope });
    expect(onJournal).toHaveBeenCalledWith(envelope);
    expect(stream.lastJournalSeq).toBe(41);
  });

  it("dispatches hint frames with topic + data", () => {
    const onHint = vi.fn();
    const { stream, sockets } = newStream({ onHint });
    stream.subscribe();
    const socket = current(sockets);
    socket.serverAccept();
    const data = { session_id: "sess-1", journal_seq_watermark: 5, previous_watermark: 4, processed: 1 };
    socket.serverMessage({ type: "hint", topic: "observation.metric_updated", data });
    expect(onHint).toHaveBeenCalledWith("observation.metric_updated", data);
  });

  it("ignores unknown hint topics and malformed frames without throwing", () => {
    const onHint = vi.fn();
    const { stream, sockets } = newStream({ onHint });
    stream.subscribe();
    const socket = current(sockets);
    socket.serverAccept();
    expect(() => {
      socket.serverMessage({ type: "hint", topic: "topology.mutation", data: {} });
      socket.serverMessage({ type: "mystery" });
      socket.serverRaw("not-json");
    }).not.toThrow();
    expect(onHint).not.toHaveBeenCalled();
  });

  it("answers the server lifecycle with nothing on pong (no upstream echo)", () => {
    const { stream, sockets } = newStream();
    stream.subscribe();
    const socket = current(sockets);
    socket.serverAccept();
    socket.serverMessage({ type: "pong" });
    expect(socket.sent).toHaveLength(1); // only the original subscribe
  });
});

describe("SessionStream — close-code discipline", () => {
  it("reconnects after 1013 slow-consumer and resumes with the carried cursor", async () => {
    vi.useFakeTimers();
    try {
      const { stream, sockets } = newStream();
      stream.subscribe();
      const first = current(sockets);
      first.serverAccept();
      first.serverMessage({
        type: "journal",
        envelope: { journal_seq: 100 },
      });
      expect(parseSlowConsumerCursor("slow-consumer;journal_seq=99")).toBe(99);
      first.serverClose(CLOSE_SLOW_CONSUMER, "slow-consumer;journal_seq=99");
      expect(stream.status).toBe("reconnecting");
      await vi.advanceTimersByTimeAsync(100);
      const second = current(sockets);
      second.serverAccept();
      expect(JSON.parse(second.sent[0])).toEqual({
        type: "subscribe",
        session_id: "sess-1",
        last_journal_seq: 99,
      });
    } finally {
      vi.useRealTimers();
    }
  });

  it("closes permanently on 4404 (session unknown/DISPOSED)", async () => {
    vi.useFakeTimers();
    try {
      const { stream, sockets } = newStream();
      stream.subscribe();
      current(sockets).serverAccept();
      current(sockets).serverClose(4404, "session unknown");
      expect(stream.status).toBe("closed");
      await vi.advanceTimersByTimeAsync(10_000);
      expect(sockets).toHaveLength(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("closes permanently on 4400 (subscribe/route mismatch)", () => {
    const { stream, sockets } = newStream();
    stream.subscribe();
    current(sockets).serverAccept();
    current(sockets).serverClose(4400, "subscribe mismatch");
    expect(stream.status).toBe("closed");
    expect(sockets).toHaveLength(1);
  });

  it("backs off exponentially after transient closes (1008), capped at maxDelay", async () => {
    vi.useFakeTimers();
    try {
      const { stream, sockets } = newStream();
      stream.subscribe();
      current(sockets).serverAccept();
      current(sockets).serverClose(1008, "pong timeout");

      await vi.advanceTimersByTimeAsync(100); // 100 * 2^0
      expect(sockets).toHaveLength(2);
      current(sockets).serverClose(1008, "pong timeout");

      await vi.advanceTimersByTimeAsync(199);
      expect(sockets).toHaveLength(2);
      await vi.advanceTimersByTimeAsync(1); // 200 * 2^1 measured from this close
      expect(sockets).toHaveLength(3);
      current(sockets).serverClose(1008, "pong timeout");

      await vi.advanceTimersByTimeAsync(400); // 400 * 2^2 → capped at 400
      expect(sockets).toHaveLength(4);
      expect(stream.status).toBe("reconnecting");
    } finally {
      vi.useRealTimers();
    }
  });

  it("does not reconnect after an explicit user close()", async () => {
    vi.useFakeTimers();
    try {
      const { stream, sockets } = newStream();
      stream.subscribe();
      const socket = current(sockets);
      socket.serverAccept();
      stream.close();
      expect(stream.status).toBe("closed");
      await vi.advanceTimersByTimeAsync(10_000);
      expect(sockets).toHaveLength(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("reconnects on abnormal close (1006 network drop) and updates status", async () => {
    vi.useFakeTimers();
    try {
      const { stream, sockets } = newStream();
      stream.subscribe();
      current(sockets).serverAccept();
      current(sockets).serverClose(1006, "");
      expect(stream.status).toBe("reconnecting");
      await vi.advanceTimersByTimeAsync(100);
      expect(sockets).toHaveLength(2);
    } finally {
      vi.useRealTimers();
    }
  });
});
