// The state_observed snapshot read path for the canvas faces (ticket #169,
// SPEC-401 §Phase3 card summary + SPEC-404 §Phase3 detail panel). ONE hook per
// page scope: the static read goes through the SPEC-305 §Phase3 query face
// (namespace/node_type flat scalar params — registry-derived values, never
// hand-listed), the live tail rides the canonical journal cache the page-level
// useSessionStream keeps updated (applyJournalFrame) — zero new data channels.
import { useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { queryStateObservedEvents } from "../../../api/endpoints/observation";
import { qk } from "../../../query/keys";
import { STATE_DOMAIN_NODE_TYPES, STATE_OBSERVED_NAMESPACES } from "../nodeTypes";
import { mergeSnapshotItems, type StateObservedSnapshot } from "./nodeStateSummary";

/** Session-wide state_observed snapshots (REST history page + journal live
 * tail, merged + journal_seq-ordered). Empty while no session is tracked. */
export function useNodeStateSnapshots(sessionId: string | null): StateObservedSnapshot[] {
  const queryClient = useQueryClient();
  const restQuery = useQuery({
    queryKey: [...qk.events(sessionId ?? "", "state-observed")],
    queryFn: () =>
      queryStateObservedEvents(sessionId!, {
        namespace: [...STATE_OBSERVED_NAMESPACES],
        node_type: [...STATE_DOMAIN_NODE_TYPES],
        // newest-first window: the status faces consume the LATEST snapshot
        // per node, so the first page of journal_desc carries them.
        sort: "journal_desc",
        limit: 200,
      }),
    enabled: sessionId !== null,
  });
  const journalKey = [...qk.events(sessionId ?? "", "journal")];
  const journalQuery = useQuery({
    queryKey: journalKey,
    enabled: sessionId !== null,
    // Identity refetch: the journal cache is updated by applyJournalFrame
    // (WS facts); a refetch can only return the cached truth (JournalTail
    // posture — the same cache, never a second store).
    queryFn: () => queryClient.getQueryData<Record<string, unknown>[]>(journalKey) ?? [],
    staleTime: Number.POSITIVE_INFINITY,
  });
  return useMemo(
    () =>
      mergeSnapshotItems(
        Array.isArray(restQuery.data?.data.items) ? (restQuery.data!.data.items as Record<string, unknown>[]) : [],
        journalQuery.data ?? [],
      ),
    [restQuery.data, journalQuery.data],
  );
}
