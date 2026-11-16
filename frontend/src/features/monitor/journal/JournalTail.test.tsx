// Journal tail (SPEC-403 §4.8, REQ-UI-403-007 presentation face): reads the
// canonical journal cache (qk.events(sessionId,'journal')) — the throttle
// refetch surface — NOT a frame-driven DOM stream. Renders the most recent N
// envelopes with wire fields.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { JournalEnvelope } from "../../../ws/SessionStream";
import { qk } from "../../../query/keys";
import { JOURNAL_TAIL_N, JournalTail } from "./JournalTail";
import { MONITOR_EMPTY_STATE_COPY } from "../copy";

const envelope = (seq: number): JournalEnvelope => ({
  schema_version: "1.0",
  event_id: `e-${seq}`,
  event_type: "ts.generated",
  journal_seq: seq,
  severity: "info",
  producer: { producer_id: "gen-0", producer_version: "1", instance_id: "i-1" },
});

function renderTail(seed: JournalEnvelope[]) {
  const queryClient = new QueryClient();
  queryClient.setQueryData([...qk.events("s-1", "journal")], seed);
  return render(
    <QueryClientProvider client={queryClient}>
      <JournalTail sessionId="s-1" />
    </QueryClientProvider>,
  );
}

describe("JournalTail — cache-driven tail window", () => {
  it("renders wire fields per envelope (seq/event_type/severity/producer)", () => {
    renderTail([envelope(1), envelope(2)]);
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getAllByText("ts.generated")).toHaveLength(2);
    expect(screen.getAllByText("info")).toHaveLength(2);
    expect(screen.getAllByText("gen-0")).toHaveLength(2);
  });

  it("caps at the most recent JOURNAL_TAIL_N entries (newest first)", () => {
    const seed = Array.from({ length: JOURNAL_TAIL_N + 10 }, (_, i) => envelope(i + 1));
    renderTail(seed);
    const rows = screen.getAllByTestId(/^journal-row-/);
    expect(rows).toHaveLength(JOURNAL_TAIL_N);
    // newest first: the highest seq at the top, and the oldest shown is
    // seq = total - N + 1
    expect(rows[0]).toHaveAttribute("data-testid", `journal-row-${JOURNAL_TAIL_N + 10}`);
    expect(rows.at(-1)).toHaveAttribute("data-testid", `journal-row-11`);
  });

  it("renders an explicit empty state before any journal frame arrives", () => {
    const queryClient = new QueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <JournalTail sessionId="s-1" />
      </QueryClientProvider>,
    );
    const c = MONITOR_EMPTY_STATE_COPY.journal;
    expect(screen.getByText(c.what)).toBeInTheDocument();
    expect(screen.getByText(c.why)).toBeInTheDocument();
    expect(screen.getByText(`下一步:${c.next}`)).toBeInTheDocument();
  });
});
