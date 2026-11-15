// Stream Monitor page (SPEC-403): control bar + overview card + run trigger
// + PID/metrics + alerts + diagnoses + verify + journal tail, all scoped to
// one tracked session (/monitor?session=<id>). Real-time = journal/hint
// throttled refetch via the #61 bridge (useSessionStream) — never streaming
// DOM. Queries here are the ONLY REST faces; freshness follows the SPEC-305
// §8 matrix (summary has no hint row: refreshed on mount/actions/manual).
//
// Feature-local query keys: the canonical vocabulary (src/query/keys.ts) is a
// shared face this ticket does not modify; these keys follow the same
// <prefix, sessionId> convention, are exported from the components barrel for
// #65/#67 reuse, and are candidates for a one-line keys.ts additive landing.
import { useCallback, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router";
import type { DiagnosisReportDTO, RunStatusDTO, VerificationResultDTO } from "./types";
import {
  diagnoseRun,
  getRun,
  getSnapshot,
  listDiagnoses,
  queryAlerts,
  queryMetrics,
  querySummary,
  verifyRun,
  disposeSession,
  pauseSession,
  resumeSession,
  startSession,
  stopSession,
  validateSession,
  submitRun,
} from "../../api";
import { ApiError } from "../../api/client";
import { Panel } from "../../components/ui";
import { qk } from "../../query/keys";
import { Badge } from "../../components/ui";
import { AlertsPanel } from "./alerts/AlertsPanel";
import { DiagnosisCandidateList, DiagnosisList } from "./diagnosis/DiagnosisList";
import { JournalTail } from "./journal/JournalTail";
import { ControlBar } from "./lifecycle/ControlBar";
import type { LifecycleAction, LifecycleWire } from "./lifecycle/lifecycleTable";
import { OverviewCard, RunTrigger } from "./overview/OverviewCard";
import { MetricsPanel } from "./metrics/MetricsPanel";
import { useSessionStream } from "./stream/useSessionStream";
import { VerifyResultCard } from "./verify/VerifyResultCard";
import { VerifyRunForm, type VerifyRunPayload } from "./verify/VerifyRunForm";
import { EmptyState } from "../../components/ui";
import "./monitor.css";

/** Feature-local canonical-convention keys (see file header note). */
export const monitorKeys = {
  diagnoses: (sessionId: string) => ["diagnoses", sessionId] as const,
  report: (sessionId: string) => ["diagnosis-report", sessionId] as const,
};

interface MetricsBody {
  metric_names: string[];
  start_ns: number;
  end_ns: number;
  step_ns: number;
  clock_domain: string;
  allow_unknown: boolean;
}

const RUN_POLL_INTERVAL_MS = 200;
const RUN_POLL_DEADLINE_MS = 30_000;
const DIAGNOSE_404_RETRY_WINDOW_MS = 10_000;
const DIAGNOSE_404_RETRY_INTERVAL_MS = 100;

export default function MonitorRegion() {
  const [searchParams, setSearchParams] = useSearchParams();
  const sessionId = searchParams.get("session");

  if (sessionId === null || sessionId === "") {
    return <SessionGuide onTrack={(id) => setSearchParams({ session: id })} />;
  }
  return <MonitorPage key={sessionId} sessionId={sessionId} onUntrack={() => setSearchParams({})} />;
}

function SessionGuide({ onTrack }: { onTrack: (sessionId: string) => void }) {
  const [draft, setDraft] = useState("");
  return (
    <div className="dvb-region dvb-mon-page">
      <h2>Monitor</h2>
      <p className="dvb-mon-guide">
        输入 session id 以跟踪（无 session 列表端点；会话由拓扑区/实验区创建后在此跟踪）。
      </p>
      <form
        className="dvb-mon-session-form"
        onSubmit={(e) => {
          e.preventDefault();
          if (draft.trim() !== "") onTrack(draft.trim());
        }}
      >
        <input
          aria-label="session id"
          placeholder="session id"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
        <button type="submit">跟踪</button>
      </form>
    </div>
  );
}

function MonitorPage({ sessionId, onUntrack }: { sessionId: string; onUntrack: () => void }) {
  const queryClient = useQueryClient();
  const wsStatus = useSessionStream(sessionId);

  // --- server state (all queries session-scoped) ---------------------------
  const snapshotQuery = useQuery({
    queryKey: [...qk.snapshot(sessionId)],
    queryFn: () => getSnapshot(sessionId),
  });
  const summaryQuery = useQuery({
    queryKey: [...qk.summary(sessionId)],
    queryFn: () => querySummary(sessionId),
  });
  const alertsQuery = useQuery({
    queryKey: [...qk.alerts(sessionId, "page")],
    queryFn: () => queryAlerts(sessionId, { limit: 50 }),
  });
  const diagnosesQuery = useQuery({
    queryKey: [...monitorKeys.diagnoses(sessionId)],
    queryFn: () => listDiagnoses(sessionId),
  });
  const [metricsBody, setMetricsBody] = useState<MetricsBody | null>(null);
  const metricsQuery = useQuery({
    queryKey: [...qk.metrics(sessionId), metricsBody],
    queryFn: () => queryMetrics(sessionId, metricsBody!),
    enabled: metricsBody !== null,
  });

  // --- run registry (page state; facts always from getRun answers) ---------
  const [runs, setRuns] = useState<RunStatusDTO[]>([]);
  const [runBusy, setRunBusy] = useState(false);

  const submitEmptyPlanRun = useCallback(
    async (config: unknown) => {
      setRunBusy(true);
      try {
        const accepted = await submitRun(sessionId, { config: config as never, fault_plan: [] });
        const deadline = Date.now() + RUN_POLL_DEADLINE_MS;
        for (;;) {
          const status = await getRun(sessionId, accepted.run_id);
          setRuns((current) => [
            status,
            ...current.filter((r) => r.run_id !== status.run_id),
          ]);
          if (status.status !== "running") break;
          if (Date.now() >= deadline) break;
          await new Promise((resolve) => setTimeout(resolve, RUN_POLL_INTERVAL_MS));
        }
        void queryClient.invalidateQueries({ queryKey: [...qk.snapshot(sessionId)] });
      } finally {
        setRunBusy(false);
      }
    },
    [queryClient, sessionId],
  );

  // --- lifecycle actions ----------------------------------------------------
  const runLifecycleAction = useCallback(
    async (action: LifecycleAction) => {
      switch (action) {
        case "validate":
          await validateSession(sessionId);
          break;
        case "start":
          await startSession(sessionId);
          break;
        case "pause":
          await pauseSession(sessionId);
          break;
        case "resume":
          await resumeSession(sessionId);
          break;
        case "stop":
          await stopSession(sessionId);
          break;
        case "dispose":
          await disposeSession(sessionId);
          // 204: the session is recycled — no snapshot to re-pull; leave the
          // page scope (the guide state is the honest post-dispose view).
          onUntrack();
          return;
      }
      void queryClient.invalidateQueries({ queryKey: [...qk.snapshot(sessionId)] });
      void queryClient.invalidateQueries({ queryKey: [...qk.summary(sessionId)] });
    },
    [onUntrack, queryClient, sessionId],
  );

  const onLifecycleResync = useCallback(
    // 409 resync: the server view is authoritative — re-pull the snapshot.
    () => void queryClient.invalidateQueries({ queryKey: [...qk.snapshot(sessionId)] }),
    [queryClient, sessionId],
  );

  // --- diagnose face ---------------------------------------------------------
  const [diagnoseRunId, setDiagnoseRunId] = useState("");
  const [diagnoseBusy, setDiagnoseBusy] = useState(false);
  const [report, setReport] = useState<DiagnosisReportDTO | null>(null);
  const [diagnoseError, setDiagnoseError] = useState<string | null>(null);

  const triggerDiagnose = useCallback(async () => {
    if (diagnoseRunId.trim() === "") return;
    setDiagnoseBusy(true);
    setDiagnoseError(null);
    try {
      // 404-until-drained: the report becomes answerable once the pump has
      // committed the run's terminal journal events (SPEC-306 §5 idempotent).
      const deadline = Date.now() + DIAGNOSE_404_RETRY_WINDOW_MS;
      let last: DiagnosisReportDTO | null = null;
      for (;;) {
        try {
          last = await diagnoseRun(sessionId, diagnoseRunId.trim());
          break;
        } catch (error) {
          if (error instanceof ApiError && error.status === 404 && Date.now() < deadline) {
            await new Promise((resolve) => setTimeout(resolve, DIAGNOSE_404_RETRY_INTERVAL_MS));
            continue;
          }
          throw error;
        }
      }
      setReport(last);
      void queryClient.invalidateQueries({ queryKey: [...monitorKeys.diagnoses(sessionId)] });
    } catch (error) {
      setDiagnoseError(error instanceof ApiError ? `${error.errorCode}: ${error.message}` : String(error));
    } finally {
      setDiagnoseBusy(false);
    }
  }, [diagnoseRunId, queryClient, sessionId]);

  // --- verify face -----------------------------------------------------------
  const [verifyResult, setVerifyResult] = useState<VerificationResultDTO | null>(null);
  const [verifyBusy, setVerifyBusy] = useState(false);
  const [verifyError, setVerifyError] = useState<string | null>(null);

  const triggerVerify = useCallback(
    async (payload: VerifyRunPayload) => {
      setVerifyBusy(true);
      setVerifyError(null);
      try {
        setVerifyResult(await verifyRun(sessionId, payload.recoveryRunId, payload.body));
      } catch (error) {
        setVerifyError(error instanceof ApiError ? `${error.errorCode}: ${error.message}` : String(error));
      } finally {
        setVerifyBusy(false);
      }
    },
    [sessionId],
  );

  const runCandidates = useMemo(() => runs.map((run) => run.run_id), [runs]);

  return (
    <div className="dvb-region dvb-mon-page">
      <header className="dvb-mon-page-header">
        <h2>Monitor</h2>
        <span className="dvb-mon-session">session: {sessionId}</span>
        <Badge tone="neutral">ws: {wsStatus}</Badge>
        <button type="button" onClick={() => { onUntrack(); }}>
          取消跟踪
        </button>
      </header>

      <Panel title="运行控制">
        <ControlBar
          lifecycle={(snapshotQuery.data?.lifecycle as LifecycleWire | undefined) ?? null}
          onAction={runLifecycleAction}
          onResync={onLifecycleResync}
        />
      </Panel>

      <Panel title="概览">
        <OverviewCard summary={summaryQuery.data?.data} snapshot={snapshotQuery.data} />
        {summaryQuery.error instanceof ApiError && (
          <p className="dvb-mon-error">
            {summaryQuery.error.errorCode}: {summaryQuery.error.message}
          </p>
        )}
      </Panel>

      <Panel title="Run 触发">
        <RunTrigger onSubmit={(config) => void submitEmptyPlanRun(config)} runs={runs} busy={runBusy} />
      </Panel>

      <Panel title="PID/指标">
        <MetricsPanel
          sessionId={sessionId}
          virtualTimeNs={snapshotQuery.data?.virtual_time_ns ?? 0}
          data={metricsQuery.data}
          onQueryChange={setMetricsBody}
        />
      </Panel>

      <Panel title="告警">
        <AlertsPanel alerts={alertsQuery.data?.data.items ?? []} total={alertsQuery.data?.data.total ?? 0} />
      </Panel>

      <Panel title="诊断">
        <div className="dvb-mon-diagnose-bar">
          <input
            aria-label="diagnose run id"
            list="monitor-run-candidates"
            placeholder="run id（diagnose 幂等）"
            value={diagnoseRunId}
            onChange={(e) => setDiagnoseRunId(e.target.value)}
          />
          <datalist id="monitor-run-candidates">
            {runCandidates.map((runId) => (
              <option key={runId} value={runId} />
            ))}
          </datalist>
          <button type="button" disabled={diagnoseBusy || diagnoseRunId.trim() === ""} onClick={() => void triggerDiagnose()}>
            diagnose
          </button>
          {diagnoseError !== null && <p className="dvb-mon-error">{diagnoseError}</p>}
        </div>
        {report !== null && (
          <section className="dvb-mon-report">
            <p className="dvb-mon-line">
              report: run {report.run_id} · {report.candidates.length} candidates ·{" "}
              {report.warnings?.length ?? 0} warnings
            </p>
            <DiagnosisCandidateList candidates={report.candidates} />
          </section>
        )}
        <DiagnosisList diagnoses={diagnosesQuery.data ?? []} />
      </Panel>

      <Panel title="Verify">
        <VerifyRunForm runCandidates={runCandidates} onSubmit={(payload) => void triggerVerify(payload)} />
        {verifyBusy && <p className="dvb-mon-line">判定中…</p>}
        {verifyError !== null && <p className="dvb-mon-error">{verifyError}</p>}
        {verifyResult !== null && <VerifyResultCard result={verifyResult} />}
        {verifyResult === null && !verifyBusy && verifyError === null && (
          <EmptyState title="尚无判定结果" note="提交 verify 请求后在此渲染服务端三态判定（无本地推导）。" />
        )}
      </Panel>

      <Panel title="journal 尾窗">
        <JournalTail sessionId={sessionId} />
      </Panel>
    </div>
  );
}
