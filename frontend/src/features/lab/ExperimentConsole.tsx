// Experiment console (SPEC-406 §4.3/§4.5/§4.6/§4.7): one scoped scenario
// session — eight-step stepper + run triggers (Generate/Inject/Recover) +
// diagnose + evidence/events + verify + the PASS-gated solution panel.
//
// Wire discipline: run configs use the frozen teaching geometry
// (labGeometry.ts); Inject submits the scenario document's fault_plan
// VERBATIM (no UI rewrite); verify bodies come from labBodies.buildVerifyBody
// (criteria passthrough + declared content_hash marker, no ui_state); the
// solution panel unlocks only on the card-rendered verdict === "PASS" and
// the reveal rides the 裁定 F backend gate. Diagnosis candidate jumps use
// the SPEC-404 §4.2 Monitor deep link (inspect_artifact/inspect_pid/
// inspect_packet seed the packet inspector without any monitor/** import —
// Plan A of the §7.6 dual plan; finalized at the merge tip).
import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router";
import {
  diagnoseRun,
  getRun,
  getScenario,
  getSnapshot,
  listDiagnoses,
  queryEvents,
  revealScenarioSolution,
  submitRun,
  verifyRun,
  type DiagnosisReportDTO,
  type RunStatusDTO,
  type VerificationResultDTO,
  isApiError,
} from "../../api";
import { Badge, EmptyState, Panel } from "../../components/ui";
import { qk } from "../../query/keys";
import { monitorKeys } from "../monitor/Region";
import { DiagnosisCandidateList, DiagnosisList } from "../monitor/components";
import { VerifyResultCard } from "../monitor/components";
import { LAB_RUN_CONFIG } from "./labGeometry";
import { buildVerifyBody } from "./labBodies";
import { deriveStepState, type LabFacts, type LabRunFact } from "./stepperState";
import { Stepper } from "./Stepper";
import { SolutionPanel, type SolutionErrorState, type SolutionFetchState } from "./SolutionPanel";

const POLL_INTERVAL_MS = 200;
const POLL_WINDOW_MS = 30_000;
const EVENTS_LIMIT = 100;

interface RegistryEntry {
  view: RunStatusDTO;
  submittedAtMs: number;
  timedOut: boolean;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function ExperimentConsole({
  scenarioId,
  sessionId,
  onBack,
}: {
  scenarioId: string;
  sessionId: string;
  onBack: () => void;
}) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  // --- server facts ---------------------------------------------------------
  const snapshotQuery = useQuery({
    queryKey: qk.snapshot(sessionId),
    queryFn: () => getSnapshot(sessionId),
    retry: 1,
  });
  const detailQuery = useQuery({
    queryKey: qk.scenario(scenarioId),
    queryFn: () => getScenario(scenarioId),
    retry: 1,
  });
  const eventsQuery = useQuery({
    queryKey: qk.events(sessionId, "lab-inspect"),
    queryFn: () => queryEvents(sessionId, { limit: EVENTS_LIMIT }),
    retry: 1,
  });
  const diagnosesQuery = useQuery({
    queryKey: [...monitorKeys.diagnoses(sessionId)],
    queryFn: () => listDiagnoses(sessionId),
    retry: 1,
  });

  // --- run registry (page memory; facts ride getRun answers) ----------------
  const [registry, setRegistry] = useState<RegistryEntry[]>([]);
  const refreshSnapshot = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: qk.snapshot(sessionId) });
    void queryClient.invalidateQueries({ queryKey: [...monitorKeys.diagnoses(sessionId)] });
  }, [queryClient, sessionId]);

  const submit = useCallback(
    async (faultPlan: ReadonlyArray<unknown>) => {
      const accepted = await submitRun(sessionId, {
        config: LAB_RUN_CONFIG as unknown as Parameters<typeof submitRun>[1]["config"],
        fault_plan: faultPlan as Parameters<typeof submitRun>[1]["fault_plan"],
      });
      setRegistry((prev) => [
        ...prev,
        { view: { run_id: accepted.run_id, status: "running", artifacts: [] } as RunStatusDTO, submittedAtMs: Date.now(), timedOut: false },
      ]);
    },
    [sessionId],
  );

  // Single 200ms poller over pending runs (30s window → explicit timeout).
  // The effect re-arms on every registry change, so `registry` is read from
  // the closure (no ref access).
  useEffect(() => {
    const pending = registry.filter((entry) => entry.view.status === "running" && !entry.timedOut);
    if (pending.length === 0) return;
    const timer = setInterval(() => {
      void (async () => {
        for (const entry of pending) {
          if (Date.now() - entry.submittedAtMs > POLL_WINDOW_MS) {
            setRegistry((prev) =>
              prev.map((item) => (item.view.run_id === entry.view.run_id ? { ...item, timedOut: true } : item)),
            );
            continue;
          }
          try {
            const latest = await getRun(sessionId, entry.view.run_id);
            if (latest.status !== entry.view.status) {
              setRegistry((prev) =>
                prev.map((item) => (item.view.run_id === latest.run_id ? { ...item, view: latest } : item)),
              );
              if (latest.status !== "running") refreshSnapshot();
            }
          } catch {
            // transient poll error → keep last known state (next tick retries)
          }
        }
      })();
    }, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [registry, sessionId, refreshSnapshot]);

  // --- diagnose / verify / solution page state ------------------------------
  const [report, setReport] = useState<DiagnosisReportDTO | null>(null);
  const [reportError, setReportError] = useState<string | null>(null);
  const [diagnosing, setDiagnosing] = useState(false);
  const [verdict, setVerdict] = useState<VerificationResultDTO | null>(null);
  const [verifyError, setVerifyError] = useState<string | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [solution, setSolution] = useState<SolutionFetchState | null>(null);
  const [solutionError, setSolutionError] = useState<SolutionErrorState | null>(null);

  const completed = registry.filter((entry) => entry.view.status === "completed");
  const injectRun = completed.find((entry) =>
    (entry.view.artifacts ?? []).some((artifact) => artifact.kind === "faulted_ts"),
  );
  const cleanRuns = completed.filter(
    (entry) =>
      (entry.view.artifacts ?? []).some((artifact) => artifact.kind === "generated_ts") &&
      !(entry.view.artifacts ?? []).some((artifact) => artifact.kind === "faulted_ts"),
  );
  const recoveryRun = cleanRuns.length > 0 ? cleanRuns[cleanRuns.length - 1] : null;
  const baselineRunId = injectRun?.view.run_id ?? "";
  const recoveryRunId = recoveryRun?.view.run_id ?? "";

  const facts: LabFacts = useMemo(
    () => ({
      sessionLifecycle: snapshotQuery.data?.lifecycle ?? null,
      runs: registry.map(
        (entry): LabRunFact => ({
          runId: entry.view.run_id,
          status: entry.view.status,
          artifacts: entry.view.artifacts ?? [],
        }),
      ),
      reportFetched: report !== null,
      eventsSeen: eventsQuery.data?.data.items?.length ?? 0,
      verdictFetched: verdict !== null,
    }),
    [snapshotQuery.data, registry, report, eventsQuery.data, verdict],
  );
  const steps = deriveStepState(facts);

  const runDiagnose = useCallback(async () => {
    if (baselineRunId === "") return;
    setDiagnosing(true);
    setReportError(null);
    try {
      setReport(await diagnoseRun(sessionId, baselineRunId));
      refreshSnapshot();
    } catch (error) {
      setReportError(
        isApiError(error) ? `${error.errorCode}: ${error.message}` : errorMessage(error),
      );
    } finally {
      setDiagnosing(false);
    }
  }, [baselineRunId, sessionId, refreshSnapshot]);

  const runVerify = useCallback(async () => {
    if (detailQuery.data === undefined || baselineRunId === "" || recoveryRunId === "") return;
    setVerifying(true);
    setVerifyError(null);
    try {
      setVerdict(
        await verifyRun(sessionId, recoveryRunId, buildVerifyBody(detailQuery.data, baselineRunId)),
      );
    } catch (error) {
      setVerifyError(isApiError(error) ? `${error.errorCode}: ${error.message}` : errorMessage(error));
    } finally {
      setVerifying(false);
    }
  }, [detailQuery.data, baselineRunId, recoveryRunId, sessionId]);

  const revealSolution = useCallback(
    async (id: string, sid: string) => {
      setSolutionError(null);
      try {
        const answer = await revealScenarioSolution(id, sid);
        setSolution({ text: answer.hidden_reference_solution });
      } catch (error) {
        if (isApiError(error)) {
          setSolutionError({ errorCode: error.errorCode, message: error.message });
        } else {
          setSolutionError({ errorCode: "UNKNOWN", message: errorMessage(error) });
        }
      }
    },
    [],
  );

  // Jump wiring (§7.6 Plan A): the SPEC-404 §4.2 Monitor deep link seeds the
  // packet inspector with the locator triple verbatim — no monitor/**
  // import, no decoding here.
  const jumpToEvidence = useCallback(
    (locator: { artifact_id: string; pid: number; packet_index: number }) => {
      navigate(
        `/monitor?session=${encodeURIComponent(sessionId)}&inspect_artifact=${encodeURIComponent(locator.artifact_id)}&inspect_pid=${locator.pid}&inspect_packet=${locator.packet_index}`,
      );
    },
    [navigate, sessionId],
  );

  const lifecycle = snapshotQuery.data?.lifecycle ?? null;
  return (
    <div className="dvb-lab-console">
      <Stepper steps={steps} />
      <Panel title={`实验控制台 · ${detailQuery.data?.title ?? scenarioId}`}>
        <button type="button" onClick={onBack}>
          返回场景库
        </button>
        <div className="dvb-lab-line">
          session:{" "}
          <span className="dvb-lab-mono" data-testid="lab-console-session">
            {sessionId}
          </span>
          {lifecycle !== null && <Badge tone={lifecycle === "running" ? "good" : "warn"}>{lifecycle}</Badge>}
        </div>
        {snapshotQuery.isError && (
          <div className="dvb-lab-error" data-testid="lab-console-error">
            {isApiError(snapshotQuery.error)
              ? `${snapshotQuery.error.errorCode}: ${snapshotQuery.error.message}`
              : errorMessage(snapshotQuery.error)}
          </div>
        )}
        <section>
          <h3 className="dvb-lab-h3">Run 触发</h3>
          <div className="dvb-lab-run-actions">
            <button type="button" onClick={() => void submit([])} disabled={lifecycle !== "running"}>
              生成基线（Generate，空 plan）
            </button>
            <button
              type="button"
              onClick={() => void submit(detailQuery.data?.fault_plan ?? [])}
              disabled={lifecycle !== "running" || detailQuery.data === undefined}
            >
              注入故障（Inject，场景 fault_plan）
            </button>
            <button type="button" onClick={() => void submit([])} disabled={lifecycle !== "running"}>
              恢复重跑（Recover，空 plan）
            </button>
          </div>
          {registry.length === 0 ? (
            <EmptyState title="尚无 Run" note="本页触发的 run 将按注册表呈现（Generate → Inject → Recover）。" />
          ) : (
            <ul className="dvb-lab-list">
              {registry.map((entry) => (
                <li key={entry.view.run_id} className="dvb-lab-row" data-testid={`lab-run-row-${entry.view.run_id}`}>
                  <span className="dvb-lab-mono">{entry.view.run_id}</span>
                  <Badge
                    tone={
                      entry.view.status === "completed"
                        ? "good"
                        : entry.view.status === "running"
                          ? "info"
                          : "bad"
                    }
                  >
                    {entry.timedOut && entry.view.status === "running" ? "轮询超窗（30s）" : entry.view.status}
                  </Badge>
                  {(entry.view.artifacts ?? []).map((artifact) => (
                    <span key={artifact.artifact_id} className="dvb-lab-ref-chip">
                      {artifact.kind}
                    </span>
                  ))}
                </li>
              ))}
            </ul>
          )}
        </section>

        <section>
          <h3 className="dvb-lab-h3">诊断（Diagnose）</h3>
          <button type="button" onClick={() => void runDiagnose()} disabled={diagnosing || baselineRunId === ""}>
            {diagnosing ? "评估中…" : "对注入 Run 评估（diagnose）"}
          </button>
          {reportError !== null && <div className="dvb-lab-error">{reportError}</div>}
          {report !== null && (
            <div className="dvb-lab-line">
              report: run {report.run_id} · {report.candidates.length} candidates · {report.warnings?.length ?? 0} warnings
            </div>
          )}
          <DiagnosisCandidateList
            candidates={report?.candidates ?? []}
            onEvidenceSelect={(locator) => jumpToEvidence(locator)}
            context={<span>场景语境：{detailQuery.data?.title ?? scenarioId}</span>}
          />
          <DiagnosisList
            diagnoses={diagnosesQuery.data ?? []}
            context={<span>session 诊断表行（GET .../diagnoses）</span>}
          />
        </section>

        <section>
          <h3 className="dvb-lab-h3">证据 / 事件（Inspect）</h3>
          {eventsQuery.isPending ? (
            <EmptyState title="加载中" note="读取 journal 事件…" />
          ) : eventsQuery.isError ? (
            <div className="dvb-lab-error">{errorMessage(eventsQuery.error)}</div>
          ) : (
            <ul className="dvb-lab-list">
              {((eventsQuery.data?.data.items ?? []) as Array<{ journal_seq: number; event_type?: string }>)
                .slice(0, 20)
                .map((item) => (
                  <li key={String(item.journal_seq)} className="dvb-lab-line dvb-lab-mono">
                    seq {String(item.journal_seq)} · {String(item.event_type ?? "")}
                  </li>
                ))}
            </ul>
          )}
        </section>

        <section>
          <h3 className="dvb-lab-h3">通关判定（Verify）</h3>
          <div className="dvb-lab-line">
            recovery_run_id: <span className="dvb-lab-mono">{recoveryRunId === "" ? "（待恢复 Run 完成）" : recoveryRunId}</span>
            · baseline_run_id（注入锚）: <span className="dvb-lab-mono">{baselineRunId === "" ? "（待注入 Run 完成）" : baselineRunId}</span>
          </div>
          <button
            type="button"
            onClick={() => void runVerify()}
            disabled={verifying || baselineRunId === "" || recoveryRunId === ""}
          >
            {verifying ? "判定中…" : "提交判定（verify）"}
          </button>
          {verifyError !== null && <div className="dvb-lab-error">{verifyError}</div>}
          {verdict !== null && (
            <VerifyResultCard
              result={verdict}
              context={<span>场景语境：{detailQuery.data?.title ?? scenarioId} @ {detailQuery.data?.version}</span>}
            />
          )}
        </section>

        <section>
          <h3 className="dvb-lab-h3">参考解（hidden_reference_solution）</h3>
          <SolutionPanel
            scenarioId={scenarioId}
            sessionId={sessionId}
            verdict={verdict?.verdict ?? null}
            solution={solution}
            error={solutionError}
            onRequest={(id, sid) => void revealSolution(id, sid)}
          />
        </section>
      </Panel>
    </div>
  );
}
