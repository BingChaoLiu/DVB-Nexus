// 生成过程 只读折叠区 (SPEC-406 §Phase2 L323): a <details> static-wayfinding
// block inside the console's Inspect section — the ONLY allowed guidance
// posture (SPEC-408 §3 文案语言规范: 静态路标式, no popups/tours/animations;
// no timeline, no separate page). Data = the gen.* journal face via REST pull
// (gen.* 仅分层 run 发射 — v1/MVP runs answer the honest empty face; ruling
// §10-15④). Faces:
//
//   - 阶段级进度行  : gen.stage_started / gen.stage_completed per layer
//                     (wire layer values verbatim, chain presentation order)
//   - 抽样包卡片    : gen.packet_sampled (layer badge + packet_index +
//                     byte_size + sha256 verbatim) + the inspector jump,
//                     which hands the console a GenJumpTarget — the console
//                     owns navigation and builds the #132 deep-link string
//                     (Lab only assembles parameters, no inspector import
//                     beyond the read-only view vocabulary).
//
// The query stays disabled while the fold is closed (a folded signpost does
// no reading); while open it re-pulls every GEN_POLL_INTERVAL_MS during run
// activity plus one final pull when the last run leaves the registry's
// running set (the terminal gen.* events land before the run status flips).
import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Badge, EmptyState } from "../../components/ui";
import { getRun, isApiError, queryEvents } from "../../api";
import { qk } from "../../query/keys";
import {
  GEN_EVENT_TYPES,
  parseGenEvents,
  resolveJumpTarget,
  type GenJumpTarget,
  type GenRunFace,
} from "./genEvents";

/** Poll window while the fold is open and a run is executing (same posture
 * family as the console's 200ms run poller — bounded, page-local). */
const GEN_POLL_INTERVAL_MS = 500;
/** gen.* events are O(层数) + O(抽样) (StageSampler window 8 + activations +
 * final slot per stage, ≤4 stages per run) — a few runs fit far below the
 * REST face's default page (limit 100 default, hard cap 2000). */
const GEN_EVENTS_LIMIT = 200;

export interface GenerationFoldProps {
  sessionId: string;
  /** The console's run registry face — the jump resolves the sampled run's
   * layered transmission artifact from it (resolveJumpTarget). */
  runs: ReadonlyArray<GenRunFace>;
  /** True while any registry row is running — gates the poll window. */
  active: boolean;
  /** The console's jump callback (it navigates to /monitor with the view
   * parameter string; this component never builds URLs itself). */
  onJump: (target: GenJumpTarget) => void;
}

function errorMessage(error: unknown): string {
  return isApiError(error) ? `${error.errorCode}: ${error.message}` : error instanceof Error ? error.message : String(error);
}

export function GenerationFold({ sessionId, runs, active, onJump }: GenerationFoldProps) {
  // Uncontrolled <details> with a state mirror: the body renders ONLY while
  // opened (folded = no fetch, no faces — the summary line is the signpost).
  const [open, setOpen] = useState(false);
  const query = useQuery({
    queryKey: [...qk.events(sessionId, "lab-gen")],
    queryFn: () => queryEvents(sessionId, { limit: GEN_EVENTS_LIMIT, event_type: [...GEN_EVENT_TYPES] }),
    enabled: open,
    retry: 1,
    refetchInterval: open && active ? GEN_POLL_INTERVAL_MS : false,
  });
  // Completion-edge final pull: the 500ms window can miss the terminal
  // gen.* events of a run that finishes between ticks (the events are
  // journaled during the run, the status flips at its end).
  const refetch = query.refetch;
  const prevActiveRef = useRef(active);
  useEffect(() => {
    if (prevActiveRef.current && !active) {
      if (open) void refetch();
    }
    prevActiveRef.current = active;
  }, [active, open, refetch]);

  // Parse rides the query-data identity (the parse is pure; the items array
  // degrades to a fresh empty literal only when the answer is absent).
  const face = useMemo(
    () => parseGenEvents((query.data?.data.items ?? []) as ReadonlyArray<unknown>),
    [query.data],
  );

  // --- jump affordance across page-memory loss (review-fix F1 posture) ------
  // The console's §6.3 DERIVED rows (refresh / deep-link / REST-seeded walks)
  // honestly carry no artifacts face, and completed derived rows never poll —
  // so the packet-card jump would silently vanish outside the page-submitted
  // journey. The fold therefore reads the terminal run faces it needs (one
  // read-only getRun per unresolved run; terminal faces are immutable, and a
  // RUNNING answer stays unresolved because the console's poller pulls that
  // row into page memory with its artifacts at completion).
  const [lazyFaces, setLazyFaces] = useState<Record<string, GenRunFace>>({});
  const unresolvedRunIds = useMemo(() => {
    const ids = new Set<string>();
    for (const sample of face.samples) {
      if (sample.runId === null) continue;
      if (lazyFaces[sample.runId] !== undefined) continue;
      if (runs.some((candidate) => candidate.runId === sample.runId && candidate.artifacts.length > 0)) continue;
      ids.add(sample.runId);
    }
    return [...ids];
  }, [face.samples, runs, lazyFaces]);
  const unresolvedRunKey = unresolvedRunIds.join(",");
  useEffect(() => {
    if (!open || unresolvedRunKey === "") return;
    const runIds = unresolvedRunKey.split(",");
    let cancelled = false;
    void (async () => {
      const answers = await Promise.all(
        runIds.map(async (runId): Promise<GenRunFace | null> => {
          try {
            const view = await getRun(sessionId, runId);
            if (view.status === "running") return null; // the poller owns live rows
            return {
              runId,
              artifacts: (view.artifacts ?? []).map((artifact) => ({
                artifact_id: artifact.artifact_id,
                kind: artifact.kind,
              })),
            };
          } catch {
            return null; // unknown run → the jump stays honestly absent
          }
        }),
      );
      if (cancelled) return;
      setLazyFaces((prev) => {
        const next = { ...prev };
        for (const answer of answers) {
          if (answer !== null && next[answer.runId] === undefined) next[answer.runId] = answer;
        }
        return next;
      });
    })();
    return () => {
      cancelled = true;
    };
  }, [open, unresolvedRunKey, sessionId]);
  // Resolution face: the console registry rows first (freshest); the fold's
  // lazily read terminal faces fill empty registry rows (derived §6.3 rows)
  // and runs the registry has not seen at all.
  const effectiveRuns: ReadonlyArray<GenRunFace> = useMemo(() => {
    const merged = runs.map((row) =>
      row.artifacts.length === 0 && lazyFaces[row.runId] !== undefined ? lazyFaces[row.runId] : row,
    );
    const extras = Object.values(lazyFaces).filter(
      (candidate) => !merged.some((row) => row.runId === candidate.runId),
    );
    return [...merged, ...extras];
  }, [runs, lazyFaces]);

  return (
    <details
      className="dvb-lab-gen-details"
      data-testid="lab-gen-section"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary data-testid="lab-gen-summary">生成过程（分层流水线只读折叠区）</summary>
      {open && (
        <div className="dvb-lab-gen-body" data-testid="lab-gen-body">
          {query.isPending ? (
            <div className="dvb-lab-line" data-testid="lab-gen-loading">
              读取 gen.* 构造事件…
            </div>
          ) : query.isError ? (
            <div className="dvb-lab-error" data-testid="lab-gen-error">
              生成事件读取失败（失败 ≠ 空库）：{errorMessage(query.error)}
            </div>
          ) : face.stages.length === 0 && face.samples.length === 0 ? (
            // §4.6 空态纪律: gen.* events exist only for layered runs — v1
            // scenarios and MVP single-layer runs answer the honest empty
            // face (无记录 ≠ 干净), never a fabricated pipeline.
            <div data-testid="lab-gen-empty">
              <EmptyState
                title="尚无分层生成事件"
                note="gen.* 构造事件仅分层 Run 发射（MVP 单层 Run 与 v1 场景为诚实空态——无记录 ≠ 干净）。下一步：注入 Phase 2 分层故障（如 BBHEADER_SYNC_FAULT）后重新展开"
              />
            </div>
          ) : (
            <>
              {face.stages.length > 0 && (
                <ul className="dvb-lab-gen-stages" data-testid="lab-gen-stages">
                  {face.stages.map((stage) => (
                    <li key={stage.layer} data-testid={`lab-gen-stage-${stage.layer}`} className="dvb-lab-gen-stage">
                      <Badge tone="neutral">{stage.layer}</Badge>
                      <span className="dvb-lab-line">
                        {stage.state === "completed" ? `已完成 ${stage.itemCount ?? 0} 项` : "进行中"}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
              {face.samples.length > 0 && (
                <ul className="dvb-lab-gen-samples" data-testid="lab-gen-samples">
                  {face.samples.map((sample) => {
                    const target = resolveJumpTarget(sample, effectiveRuns);
                    return (
                      <li
                        key={sample.journalSeq}
                        data-testid={`lab-gen-sample-${sample.journalSeq}`}
                        className="dvb-lab-gen-sample"
                      >
                        <Badge tone="info">{sample.layer}</Badge>
                        <span className="dvb-lab-line dvb-lab-mono">packet_index {sample.packetIndex}</span>
                        <span className="dvb-lab-line dvb-lab-mono">byte_size {sample.byteSize}</span>
                        <span className="dvb-lab-mono dvb-lab-gen-sha">{sample.sha256}</span>
                        {target !== null && (
                          <button
                            type="button"
                            className="dvb-lab-gen-jump"
                            data-testid={`lab-gen-jump-${sample.journalSeq}`}
                            onClick={() => onJump(target)}
                          >
                            定位包检查器（view {target.view}）
                          </button>
                        )}
                      </li>
                    );
                  })}
                </ul>
              )}
            </>
          )}
        </div>
      )}
    </details>
  );
}
