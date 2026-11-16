// Journal tail (SPEC-403 §4.8): the visible REQ-UI-403-007 surface — a
// read-only window over the canonical journal cache. Frames land via
// applyJournalFrame (journal_seq order, dedup); this component reads the
// cache through useQuery (identity refetch — the journal is the fact source,
// a refetch can only return what is cached). Newest first, capped at N.
// This is deliberately NOT a streaming chart or a frame-driven DOM feed.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { JournalEnvelope } from "../../../ws/SessionStream";
import { qk } from "../../../query/keys";
import { Badge } from "../../../components/ui";
import { MONITOR_EMPTY_STATE_COPY } from "../copy";
import { ThreeQuestionState } from "../ThreeQuestionState";

/** Tail window size (SPEC-403 §9 resource posture). */
export const JOURNAL_TAIL_N = 50;

export function JournalTail({ sessionId }: { sessionId: string | null }) {
  const queryClient = useQueryClient();
  const key = [...qk.events(sessionId ?? "", "journal")];
  const { data } = useQuery({
    queryKey: key,
    enabled: sessionId !== null,
    // Identity refetch: the journal cache is updated by applyJournalFrame
    // (WS facts); a refetch can only return the cached truth.
    queryFn: () => queryClient.getQueryData<JournalEnvelope[]>(key) ?? [],
    staleTime: Number.POSITIVE_INFINITY,
  });

  const items = (data ?? []).slice(-JOURNAL_TAIL_N).reverse();

  if (items.length === 0) {
    // §4.6 Monitor 组行 9(文案逐字):零事件是诚实态(空 ≠ 错误)。
    return <ThreeQuestionState copy={MONITOR_EMPTY_STATE_COPY.journal} />;
  }
  return (
    <ul className="dvb-mon-rows">
      {items.map((envelope) => {
        const producer = (envelope.producer as { producer_id?: unknown } | undefined)?.producer_id;
        return (
          <li
            key={String(envelope.journal_seq)}
            data-testid={`journal-row-${String(envelope.journal_seq)}`}
            className="dvb-mon-row dvb-mon-journal-row"
          >
            <span className="dvb-mon-code">{String(envelope.journal_seq)}</span>
            <span>{String(envelope.event_type ?? "")}</span>
            <Badge tone="neutral">{String(envelope.severity ?? "")}</Badge>
            {typeof producer === "string" && <Badge tone="info">{producer}</Badge>}
          </li>
        );
      })}
    </ul>
  );
}
