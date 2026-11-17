// Journal tail (SPEC-403 §4.8): the visible REQ-UI-403-007 surface — a
// read-only window over the canonical journal cache. Frames land via
// applyJournalFrame (journal_seq order, dedup); this component reads the
// cache through useQuery (identity refetch — the journal is the fact source,
// a refetch can only return what is cached). Newest first, capped at N.
// This is deliberately NOT a streaming chart or a frame-driven DOM feed.
//
// Phase 2 presentation (SPEC-403 §Phase2 L319-321, #134): registered
// t2mi.*/bbframe.*/biss.*/gen.* envelopes render their payload REGISTRY-
// DRIVEN — the eventRender table is the only event knowledge here (新事件
// 类型加表即渲染,无面板新增). Wire keys/enums render verbatim (L315 禁改写);
// the honesty discipline sentences come from copy.ts keyed by event type
// (「解扰失败 ≠ 码流损坏」/「缺失 ≠ 零」). Unregistered types keep the
// generic MVP wire face — no fabricated rows (ADR-0006).
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { JournalEnvelope } from "../../../ws/SessionStream";
import { qk } from "../../../query/keys";
import { Badge } from "../../../components/ui";
import { EVENT_HONESTY_COPY, MONITOR_EMPTY_STATE_COPY } from "../copy";
import { ThreeQuestionState } from "../ThreeQuestionState";
import { asPhase2Envelope } from "../types";
import { phase2PayloadEntries } from "./eventRender";

/** Tail window size (SPEC-403 §9 resource posture). */
export const JOURNAL_TAIL_N = 50;

/** Verbatim wire-value rendering (SPEC-403 L315): scalars as-is; null as
 * `null` (缺失 ≠ 零 — never coerced to 0); arrays as `[a, b]`; objects as
 * `key=value` pairs with recursive values. No aliasing, no case folding. */
function renderWireValue(value: unknown): string {
  if (value === null) return "null";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return `[${value.map(renderWireValue).join(", ")}]`;
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length === 0) return "{}";
    return entries.map(([k, v]) => `${k}=${renderWireValue(v)}`).join(", ");
  }
  return String(value);
}

function PayloadBlock({ seq, eventType, payload }: { seq: number; eventType: string; payload: Record<string, unknown> | undefined }) {
  const entries = phase2PayloadEntries(eventType, payload);
  if (entries.length === 0) return null;
  return (
    <ul className="dvb-mon-payload" data-testid={`journal-payload-${String(seq)}`}>
      {entries.map(([key, value]) => (
        <li key={key} className="dvb-mon-payload-item" data-testid={`journal-payload-${String(seq)}-${key}`}>
          <span className="dvb-mon-payload-key">{key}</span>
          <span className="dvb-mon-payload-value">{renderWireValue(value)}</span>
        </li>
      ))}
    </ul>
  );
}

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
        const seq = String(envelope.journal_seq);
        const phase2 = asPhase2Envelope(envelope);
        const discipline = phase2 !== null ? EVENT_HONESTY_COPY[phase2.event_type] : undefined;
        const body: ReactNode[] = [
          <span key="seq" className="dvb-mon-code">{seq}</span>,
          <span key="type">{String(envelope.event_type ?? "")}</span>,
          <Badge key="severity" tone="neutral">{String(envelope.severity ?? "")}</Badge>,
        ];
        if (typeof producer === "string") body.push(<Badge key="producer" tone="info">{producer}</Badge>);
        return (
          <li
            key={seq}
            data-testid={`journal-row-${seq}`}
            className={
              "dvb-mon-row dvb-mon-journal-row" + (phase2 !== null ? " dvb-mon-journal-row-phase2" : "")
            }
          >
            {body}
            {phase2 !== null && (
              <div className="dvb-mon-journal-detail">
                {discipline !== undefined && (
                  <span className="dvb-mon-discipline" data-testid={`journal-discipline-${seq}`}>
                    {discipline}
                  </span>
                )}
                <PayloadBlock seq={envelope.journal_seq as number} eventType={phase2.event_type} payload={phase2.payload} />
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}
