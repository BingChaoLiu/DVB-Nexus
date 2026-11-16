// Lab route region (SPEC-406 §4.1): /lab view switch over the URL —
// library list → scenario detail → experiment console (?scenario= &
// ?session=). routes.tsx registration is #61's entry; this file replaces
// the #61 placeholder in place (shared shell untouched). The 开局 action
// runs the §7.1 two-hop orchestration: create (201 ready) → start
// (running — the runs face requires RUNNING) — plus the SPEC-408 §7.3
// THIRD hop: an empty-plan baseline run with the FROZEN golden geometry
// (LAB_RUN_CONFIG import, never a re-copy) is auto-submitted before the
// console navigation; the run rides into the console's registry via the
// initialRuns prop (the honest at-accept carrier, AcceptedRunCarrier — the
// console remounts per session via key). Hop-3 failure is a SILENT fallback: the console
// still opens, nothing fakes success, and the §4.6 empty-registry copy
// speaks the fallback honestly. Hint reveal state (SPEC-408 §4.4
// REQ-UI-408-011) lives in the hintsStorage seam — ONE shared per-scenario
// localStorage key `dvb-lab-hints:{scenario_id}` is the record; each view
// instantiates useHintsReveal and Region keys the views by scenario/session
// so a fresh mount hydrates the same key (刷新不丢; the console embeds the
// ladder — NO deep link, the ?session= anchor stays). Reveal state never
// feeds any verify/evidence path — storage → UI display.
import { useCallback, useState } from "react";
import { useSearchParams } from "react-router";
import { createSession, getScenario, isApiError, startSession, submitRun } from "../../api";
import { qk } from "../../query/keys";
import { useQueryClient } from "@tanstack/react-query";
import { LAB_RUN_CONFIG } from "./labGeometry";
import { buildCreateSessionBody } from "./labBodies";
import { ScenarioDetail } from "./ScenarioDetail";
import { ScenarioLibrary } from "./ScenarioLibrary";
import { ExperimentConsole, type AcceptedRunCarrier } from "./ExperimentConsole";
import "./lab.css";

interface StartErrorShape {
  message: string;
  violations?: ReadonlyArray<{ code: string; path: string; message: string }>;
}

function violationList(details: Record<string, unknown> | undefined): StartErrorShape["violations"] {
  const raw = details?.violations;
  if (!Array.isArray(raw)) return undefined;
  return raw.map((entry) => {
    if (typeof entry === "string") return { code: "SIM_VALIDATION_FAILED", path: "$", message: entry };
    const record = entry as { code?: unknown; path?: unknown; message?: unknown };
    return {
      code: String(record.code ?? ""),
      path: String(record.path ?? ""),
      message: String(record.message ?? ""),
    };
  });
}

export default function LabRegion() {
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const scenarioId = searchParams.get("scenario");
  const sessionId = searchParams.get("session");

  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<StartErrorShape | null>(null);
  // §7.3 third-hop carrier: the auto-submitted baseline run handed to the
  // console so its registry opens populated (the console remounts per
  // session via key — a plain state carrier in the region is enough).
  // Carrier honesty (review-fix F6): the at-accept face holds ONLY run_id +
  // status — artifacts/packet faces are NOT claimed (omitted, never
  // fabricated); the console's poller fills the real face from getRun.
  // null = the hop failed or never ran (honest: NO note, NO fake row).
  const [autoBaselineRun, setAutoBaselineRun] = useState<AcceptedRunCarrier | null>(null);

  const openDetail = useCallback(
    (id: string) => {
      setStartError(null);
      setSearchParams({ scenario: id });
    },
    [setSearchParams],
  );

  const backToLibrary = useCallback(() => setSearchParams({}), [setSearchParams]);

  const startExperiment = useCallback(
    async (id: string) => {
      setStarting(true);
      setStartError(null);
      try {
        // The detail document feeds the request projection (permissive-
        // ignored server-side — the scenario branch is document-governed).
        const detail = await queryClient.fetchQuery({
          queryKey: qk.scenario(id),
          queryFn: () => getScenario(id),
        });
        const created = await createSession(buildCreateSessionBody(detail));
        if (created.lifecycle !== "ready") {
          throw new Error(`开局异常：create 应答 lifecycle=${created.lifecycle}（期望 ready）`);
        }
        const started = await startSession(created.session_id);
        if (started.lifecycle !== "running") {
          throw new Error(`开局异常：start 应答 lifecycle=${started.lifecycle}（期望 running）`);
        }
        // §7.3 THIRD hop — best-effort auto baseline: an empty-plan run with
        // the FROZEN golden geometry. Any failure here is a SILENT fallback:
        // the console still opens, nothing fakes success (the §4.6
        // empty-registry copy states the fallback), and the manual buttons
        // remain. The hop MUST NOT block the console navigation.
        let autoRun: AcceptedRunCarrier | null = null;
        try {
          const accepted = await submitRun(created.session_id, {
            config: LAB_RUN_CONFIG as unknown as Parameters<typeof submitRun>[1]["config"],
            fault_plan: [] as Parameters<typeof submitRun>[1]["fault_plan"],
          });
          // Honest at-accept carrier (F6): no `as RunStatusDTO` claim, no
          // fabricated empty artifacts face — just the two held facts.
          autoRun = { run_id: accepted.run_id, status: "running" };
        } catch {
          autoRun = null;
        }
        setAutoBaselineRun(autoRun);
        setSearchParams({ scenario: id, session: created.session_id });
      } catch (error) {
        if (isApiError(error)) {
          setStartError({
            message: `${error.errorCode}: ${error.message}`,
            violations: violationList(error.details),
          });
        } else {
          setStartError({ message: error instanceof Error ? error.message : String(error) });
        }
      } finally {
        setStarting(false);
      }
    },
    [queryClient, setSearchParams],
  );

  if (scenarioId !== null && sessionId !== null) {
    return (
      <>
        <h2>Lab</h2>
        {/* key remounts the console on a ?session= (or scenario) switch —
            SPEC-406 §7.5 rule 4: 面板复位锁定 + 已取文本丢弃（禁跨会话
            残留；same per-session remount posture as the Monitor 区 key）.
            The remount also re-hydrates the hints key (hintsStorage). */}
        <ExperimentConsole
          key={`${scenarioId}:${sessionId}`}
          scenarioId={scenarioId}
          sessionId={sessionId}
          onBack={() => openDetail(scenarioId)}
          initialRuns={autoBaselineRun === null ? [] : [autoBaselineRun]}
        />
      </>
    );
  }
  if (scenarioId !== null) {
    return (
      <>
        <h2>Lab</h2>
        {/* key={scenarioId}: entering a different scenario remounts the
            detail view, re-hydrating ITS hints key (same source, per
            scenario — never a stale count from another scenario). */}
        <ScenarioDetail
          key={scenarioId}
          scenarioId={scenarioId}
          onBack={backToLibrary}
          onStart={() => void startExperiment(scenarioId)}
          starting={starting}
          startError={startError}
        />
      </>
    );
  }
  // SPEC-406 §4.2 + SPEC-408 §4.4 row 单入口: the library row's ONLY action
  // is 「查看详情」 (the list row never starts — the 开局 entry stays the
  // detail page's 开局区).
  return (
    <>
      <h2>Lab</h2>
      <ScenarioLibrary onOpenDetail={openDetail} />
    </>
  );
}
