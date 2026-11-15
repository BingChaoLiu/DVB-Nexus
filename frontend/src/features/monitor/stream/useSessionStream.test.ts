// Session stream wiring tests (SPEC-403 §4.8, REQ-UI-403-007 / AC-403-07):
// the page-level throttled-refetch discipline driven through the REAL
// SessionStream + FakeSocketHandle — journal frames merge into the canonical
// events cache (sorted, deduped), hints invalidate via the shared bridge
// (250ms coalescing, exactly one invalidateQueries per prefix per window),
// and observation.event_appended triggers NO REST refetch.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient } from "@tanstack/react-query";
import { applyJournalFrame } from "../../../query/journalCache";
import { qk } from "../../../query/keys";
import { HINT_THROTTLE_MS } from "../../../query/throttle";
import { SessionStream, type JournalEnvelope } from "../../../ws/SessionStream";
import { FakeSocketHandle } from "../../../ws/testSupport";
import { wireSessionStream } from "./useSessionStream";

const envelope = (seq: number, event_type = "ts.generated"): JournalEnvelope => ({
  schema_version: "1.0",
  event_id: `e-${seq}`,
  event_type,
  journal_seq: seq,
  severity: "info",
});

let queryClient: QueryClient;
let handle: FakeSocketHandle;
let stream: SessionStream;
let invalidate: ReturnType<typeof vi.spyOn>;
let detach: () => void;

beforeEach(() => {
  vi.useFakeTimers();
  queryClient = new QueryClient();
  invalidate = vi.spyOn(queryClient, "invalidateQueries");
  handle = new FakeSocketHandle("ws://test/ws/v1/sessions/s-1");
  const wired = wireSessionStream(queryClient, { sessionId: "s-1", socketFactory: () => handle });
  stream = wired.stream;
  detach = wired.detach;
  stream.subscribe();
  handle.serverAccept(); // opens → sends subscribe
});

afterEach(() => {
  detach();
  stream.close();
  vi.useRealTimers();
});

describe("journal frames — the fact channel", () => {
  it("subscribes with the session id (single connection, single session)", () => {
    const sent = JSON.parse(handle.sent[0]!);
    expect(sent).toEqual({ type: "subscribe", session_id: "s-1" });
  });

  it("merges out-of-order frames into the journal cache in journal_seq order", () => {
    handle.serverMessage({ type: "journal", envelope: envelope(3) });
    handle.serverMessage({ type: "journal", envelope: envelope(1) });
    handle.serverMessage({ type: "journal", envelope: envelope(2) });
    const cached = queryClient.getQueryData<JournalEnvelope[]>(qk.events("s-1", "journal"));
    expect(cached?.map((e) => e.journal_seq)).toEqual([1, 2, 3]);
  });

  it("dedups replayed seqs (replay tolerance)", () => {
    handle.serverMessage({ type: "journal", envelope: envelope(1) });
    handle.serverMessage({ type: "journal", envelope: envelope(1) });
    const cached = queryClient.getQueryData<JournalEnvelope[]>(qk.events("s-1", "journal"));
    expect(cached?.length).toBe(1);
  });

  it("no REST invalidation happens for journal frames (frames carry the facts)", async () => {
    handle.serverMessage({ type: "journal", envelope: envelope(1) });
    await vi.advanceTimersByTimeAsync(HINT_THROTTLE_MS + 50);
    expect(invalidate).not.toHaveBeenCalled();
  });
});

describe("hint frames — the throttled pointer channel", () => {
  it("observation.event_appended triggers NO REST invalidation", async () => {
    handle.serverMessage({
      type: "hint",
      topic: "observation.event_appended",
      data: { journal_seq: 9, event_id: "e", event_type: "ts.generated" },
    });
    await vi.advanceTimersByTimeAsync(HINT_THROTTLE_MS + 50);
    expect(invalidate).not.toHaveBeenCalled();
  });

  it("a metric_updated hint invalidates the qk.metrics prefix after the window", async () => {
    handle.serverMessage({
      type: "hint",
      topic: "observation.metric_updated",
      data: { session_id: "s-1", journal_seq_watermark: 5, previous_watermark: 4, processed: 1 },
    });
    expect(invalidate).not.toHaveBeenCalled(); // inside the window
    await vi.advanceTimersByTimeAsync(HINT_THROTTLE_MS + 1);
    expect(invalidate).toHaveBeenCalledOnce();
    expect(invalidate).toHaveBeenCalledWith({ queryKey: [...qk.metrics("s-1")] });
  });

  it("a burst of five same-prefix hints within the window coalesces to ONE invalidation", async () => {
    for (let i = 0; i < 5; i += 1) {
      handle.serverMessage({
        type: "hint",
        topic: "observation.metric_updated",
        data: { session_id: "s-1", journal_seq_watermark: i, previous_watermark: i - 1, processed: 1 },
      });
    }
    await vi.advanceTimersByTimeAsync(HINT_THROTTLE_MS + 1);
    expect(invalidate).toHaveBeenCalledOnce();
  });

  it("observation.alert_changed invalidates the qk.alerts prefix", async () => {
    handle.serverMessage({
      type: "hint",
      topic: "observation.alert_changed",
      data: { session_id: "s-1", alert_id: "a", fingerprint: "f", rule_id: "r", state: "active", severity: "warning" },
    });
    await vi.advanceTimersByTimeAsync(HINT_THROTTLE_MS + 1);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: [...qk.alerts("s-1")] });
  });

  it("hints from a foreign session do not invalidate ours (payload scope honored)", async () => {
    handle.serverMessage({
      type: "hint",
      topic: "observation.metric_updated",
      data: { session_id: "s-other", journal_seq_watermark: 1, previous_watermark: 0, processed: 1 },
    });
    await vi.advanceTimersByTimeAsync(HINT_THROTTLE_MS + 1);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: [...qk.metrics("s-other")] });
    expect(invalidate).not.toHaveBeenCalledWith({ queryKey: [...qk.metrics("s-1")] });
  });
});

describe("applyJournalFrame — direct cache contract (reused, not reimplemented)", () => {
  it("is the same canonical merge the wiring uses", () => {
    applyJournalFrame(queryClient, "s-1", envelope(5));
    const cached = queryClient.getQueryData<JournalEnvelope[]>(qk.events("s-1", "journal"));
    expect(cached?.map((e) => e.journal_seq)).toEqual([5]);
  });
});
