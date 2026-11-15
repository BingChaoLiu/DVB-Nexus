// Journal frame → events cache merge (SPEC-400 §4.3 rule 3): journal frames
// carry facts; they are merged into the canonical events cache entry in
// journal_seq full order (sorting authority: journal_seq only, SPEC-301).
// This is a query-cache update, NOT a second store — the events query remains
// refetchable and the merge is replay-tolerant (dedup by journal_seq).
import type { QueryClient } from "@tanstack/react-query";
import { qk } from "./keys";
import type { JournalEnvelope } from "../ws/SessionStream";

export function applyJournalFrame(
  queryClient: QueryClient,
  sessionId: string,
  envelope: JournalEnvelope,
): void {
  const key = [...qk.events(sessionId, "journal")];
  const seq = envelope.journal_seq;
  if (typeof seq !== "number") return; // journal_seq is the ordering credential; no seq → ignore
  queryClient.setQueryData<JournalEnvelope[]>(key, (current) => {
    const items = current ?? [];
    if (items.some((item) => item.journal_seq === seq)) return items;
    const merged = [...items, envelope];
    merged.sort((a, b) => {
      const aSeq = a.journal_seq as number;
      const bSeq = b.journal_seq as number;
      return aSeq - bSeq;
    });
    return merged;
  });
}
