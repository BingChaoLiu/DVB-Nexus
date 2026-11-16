// Lab route region (SPEC-406 §4.1): /lab view switch over the URL —
// library list → scenario detail → experiment console (?scenario= &
// ?session=). routes.tsx registration is #61's entry; this file replaces
// the #61 placeholder in place (shared shell untouched). The 开局 action
// runs the §7.1 two-hop orchestration: create (201 ready) → start
// (running — the runs face requires RUNNING). Hint reveal state is
// per-scenario page memory (pure frontend, resets on reload — honest).
import { useCallback, useState } from "react";
import { useLocation, useSearchParams } from "react-router";
import { createSession, getScenario, isApiError, startSession, submitRun, type RunStatusDTO } from "../../api";
import { qk } from "../../query/keys";
import { useQueryClient } from "@tanstack/react-query";
// PROTOTYPE (issue #87, DEV-only): variant B adds a third hop to the §7.1
// orchestration — the empty-plan baseline run is auto-submitted at 开局 so
// the console opens with first real data in flight. Stock flow when off.
import { readExampleDataVariant } from "../../app/prototype/exampleDataPrototype";
import { LAB_RUN_CONFIG } from "./labGeometry";
import { buildCreateSessionBody } from "./labBodies";
import { ScenarioDetail } from "./ScenarioDetail";
import { ScenarioLibrary } from "./ScenarioLibrary";
import { ExperimentConsole } from "./ExperimentConsole";
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
  const { search } = useLocation();
  const queryClient = useQueryClient();
  const scenarioId = searchParams.get("scenario");
  const sessionId = searchParams.get("session");

  // Per-scenario hint reveal counters (component memory — no persistence).
  const [revealedHints, setRevealedHints] = useState<Record<string, number>>({});
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<StartErrorShape | null>(null);
  // PROTOTYPE (issue #87, variant B): the auto-submitted baseline run handed
  // to the console so its registry opens populated (console remounts per
  // session via key, so a plain state carrier in the region is enough).
  const [prototypeInitialRuns, setPrototypeInitialRuns] = useState<RunStatusDTO[]>([]);

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
        // PROTOTYPE (issue #87, variant B): third hop — auto-submit the
        // empty-plan baseline run (frozen golden geometry). The console's
        // poller tracks it to completion; Generate lights up by itself.
        if (readExampleDataVariant(search) === "B") {
          try {
            const accepted = await submitRun(created.session_id, {
              config: LAB_RUN_CONFIG as unknown as Parameters<typeof submitRun>[1]["config"],
              fault_plan: [] as Parameters<typeof submitRun>[1]["fault_plan"],
            });
            setPrototypeInitialRuns([
              { run_id: accepted.run_id, status: "running", artifacts: [] } as RunStatusDTO,
            ]);
          } catch {
            // auto-baseline is best-effort: the stock buttons remain, the
            // engineer can always 生成基线 manually (honest fallback).
            setPrototypeInitialRuns([]);
          }
        } else {
          setPrototypeInitialRuns([]);
        }
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
    // PROTOTYPE (issue #87): search (variant B read) + the initial-runs
    // setter are additional closure reads of the prototype extension.
    [queryClient, setSearchParams, search],
  );

  const revealNext = useCallback(
    (id: string) => setRevealedHints((prev) => ({ ...prev, [id]: (prev[id] ?? 0) + 1 })),
    [],
  );

  if (scenarioId !== null && sessionId !== null) {
    return (
      <>
        <h2>Lab</h2>
        {/* key={sessionId} remounts the console on a ?session= switch —
            SPEC-406 §7.5 rule 4: 面板复位锁定 + 已取文本丢弃（禁跨会话
            残留；same per-session remount posture as the Monitor 区 key）. */}
        <ExperimentConsole
          key={sessionId}
          scenarioId={scenarioId}
          sessionId={sessionId}
          onBack={() => openDetail(scenarioId)}
          prototypeInitialRuns={prototypeInitialRuns}
        />
      </>
    );
  }
  if (scenarioId !== null) {
    return (
      <>
        <h2>Lab</h2>
        <ScenarioDetail
          scenarioId={scenarioId}
          revealedCount={revealedHints[scenarioId] ?? 0}
          onRevealNext={() => revealNext(scenarioId)}
          onBack={backToLibrary}
          onStart={() => void startExperiment(scenarioId)}
          starting={starting}
          startError={startError}
        />
      </>
    );
  }
  // SPEC-406 §4.2: 列表行不直接开局，开局前必见详情——两行动作都导航到
  // 详情页（开局动作在详情 §4.3）。
  return (
    <>
      <h2>Lab</h2>
      <ScenarioLibrary onOpenDetail={openDetail} onStart={openDetail} />
    </>
  );
}
