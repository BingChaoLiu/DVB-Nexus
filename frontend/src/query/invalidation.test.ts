// Invalidation bridge seam tests (SPEC-400 §6.3, matrix = SPEC-305 §8):
// every hint topic maps to exactly the canonical query-key prefix; bursts
// coalesce to one invalidation per prefix within the throttle window; journal
// frames merge into the events cache in journal_seq order.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient } from "@tanstack/react-query";
import { applyJournalFrame } from "./journalCache";
import { attachHintBridge } from "./invalidation";
import { qk } from "./keys";
import { HINT_THROTTLE_MS } from "./throttle";

let queryClient: QueryClient;

beforeEach(() => {
  vi.useFakeTimers();
  queryClient = new QueryClient();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("hint → query-key matrix (SPEC-305 §8, one row per topic)", () => {
  it.each([
    [
      "observation.metric_updated",
      { session_id: "s1", journal_seq_watermark: 5, previous_watermark: 4, processed: 1 },
      qk.metrics("s1"),
    ],
    [
      "observation.alert_changed",
      { session_id: "s1", alert_id: "a", fingerprint: "f", rule_id: "r", state: "active", severity: "warning" },
      qk.alerts("s1"),
    ],
    ["observation.health_changed", { session_id: "s1", clock_domain: "sim:s1", overall: "healthy", previous: null }, qk.health("s1")],
    ["observation.export_progress", { session_id: "s1", export_id: "e1", status: "running", total_records: 3 }, qk.export("s1", "e1")],
  ])("%s invalidates %j", async (topic, data, expectedPrefix) => {
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    const detach = attachHintBridge(queryClient, {
      onHint: (handler) => {
        handler(topic as string, data as Record<string, unknown>);
      },
    });
    detach();
    await vi.advanceTimersByTimeAsync(HINT_THROTTLE_MS + 1);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: [...expectedPrefix] });
  });

  it("observation.event_appended triggers NO invalidation (journal frames carry the facts)", async () => {
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    const detach = attachHintBridge(queryClient, {
      onHint: (handler) => {
        handler("observation.event_appended", { journal_seq: 9, event_id: "e", event_type: "ts.generated" });
      },
    });
    detach();
    await vi.advanceTimersByTimeAsync(HINT_THROTTLE_MS + 1);
    expect(invalidate).not.toHaveBeenCalled();
  });
});

describe("throttling / coalescing", () => {
  it("collapses a burst of same-topic hints into one invalidation", async () => {
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    const detach = attachHintBridge(queryClient, {
      onHint: (handler) => {
        for (let i = 0; i < 5; i += 1) {
          handler("observation.alert_changed", { session_id: "s1" });
        }
      },
    });
    detach();
    await vi.advanceTimersByTimeAsync(HINT_THROTTLE_MS + 1);
    expect(invalidate).toHaveBeenCalledTimes(1);
  });

  it("different prefixes within the window each fire exactly once", async () => {
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    const detach = attachHintBridge(queryClient, {
      onHint: (handler) => {
        handler("observation.alert_changed", { session_id: "s1" });
        handler("observation.metric_updated", { session_id: "s1" });
        handler("observation.alert_changed", { session_id: "s2" });
      },
    });
    detach();
    await vi.advanceTimersByTimeAsync(HINT_THROTTLE_MS + 1);
    expect(invalidate).toHaveBeenCalledTimes(3);
  });

  it("a hint arriving inside the window does not push the invalidation out", async () => {
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    let handler!: (topic: string, data: Record<string, unknown>) => void;
    const detach = attachHintBridge(queryClient, {
      onHint: (h) => {
        handler = h;
      },
    });
    handler("observation.alert_changed", { session_id: "s1" }); // schedules at t=HINT_THROTTLE_MS
    await vi.advanceTimersByTimeAsync(HINT_THROTTLE_MS - 10); // t=240: not yet fired
    handler("observation.alert_changed", { session_id: "s1" }); // inside window: coalesced, no re-schedule
    await vi.advanceTimersByTimeAsync(HINT_THROTTLE_MS - 50); // t=440
    expect(invalidate).toHaveBeenCalledTimes(1); // fired once at t=250, not re-armed
    detach();
  });
});

describe("journal frame cache merge (journal_seq full order)", () => {
  const envelope = (seq: number, eventId: string) => ({
    journal_seq: seq,
    event_id: eventId,
    event_type: "simulation.run_completed",
  });

  it("appends in-order frames and orders out-of-order frames by journal_seq", () => {
    const key = qk.events("s1", "journal");
    queryClient.setQueryData([...key], [envelope(1, "a")]);
    applyJournalFrame(queryClient, "s1", envelope(2, "b"));
    applyJournalFrame(queryClient, "s1", envelope(4, "d"));
    applyJournalFrame(queryClient, "s1", envelope(3, "c"));
    const items = queryClient.getQueryData<ReturnType<typeof envelope>[]>([...key]);
    expect(items?.map((e) => e.journal_seq)).toEqual([1, 2, 3, 4]);
  });

  it("deduplicates by journal_seq (replay after reconnect carries overlaps)", () => {
    const key = qk.events("s1", "journal");
    queryClient.setQueryData([...key], [envelope(1, "a")]);
    applyJournalFrame(queryClient, "s1", envelope(1, "a-dup"));
    const items = queryClient.getQueryData<ReturnType<typeof envelope>[]>([...key]);
    expect(items).toHaveLength(1);
  });

  it("ignores frames missing a numeric journal_seq (envelope tolerance, ADR-0006)", () => {
    const key = qk.events("s1", "journal");
    queryClient.setQueryData([...key], []);
    applyJournalFrame(queryClient, "s1", { event_id: "x" });
    expect(queryClient.getQueryData<unknown[]>([...key])).toEqual([]);
  });
});
