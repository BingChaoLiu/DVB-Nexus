// Stream Monitor page (SPEC-403 §4.1): control bar + overview card + run
// trigger + PID/metrics + alerts + diagnoses + verify + journal tail, all
// scoped to one tracked session (/monitor?session=<id>). Real-time = journal
// /hint throttled refetch via the #61 bridge (useSessionStream) — never
// streaming DOM. Queries here are the ONLY REST faces; freshness follows the
// SPEC-305 §8 matrix (summary has no hint row: refreshed on mount/actions/
// manual).
//
// Guidance layer (SPEC-408 §4.3, ticket #95): without a session param the
// page renders the 会话列表区 guide seat (recent-session list as the main
// seat, the 一键演示 placeholder in the primary button position — wiring is
// ticket #99's, the manual-UUID fallback degraded to second use). A session
// that does not exist server-side (REST 404 / WS 4404) renders the explicit
// unknown-session state (§4.6 row 0), never an error stack. The header
// carries the source-scenario link back to Lab (zero state params — the
// Lab→Monitor inspect_* deep link stays untouched). The verify form is
// wired to the §7.5 editable prefill (scenario_id ← session detail,
// version/content_hash ← scenario detail, baseline/recovery candidates ←
// the run list datalist); runs are never auto-guessed.
//
// Feature-local query keys: the canonical vocabulary (src/query/keys.ts)
 // now carries the sessions prefix (ticket #95 additive); monitorKeys below
// remain the feature-local diagnosis/report keys.
import { useCallback, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router";
import type { DiagnosisEvidenceDTO, DiagnosisReportDTO, RunStatusDTO, VerificationResultDTO } from "./types";
import {
  getRun,
  getSnapshot,
  getSessionDetail,
  getScenario,
  listSessionRuns,
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
// SPEC-404 packet inspector (ticket #65, approved plan D1): minimal additive
// mount per the #66 R1 precedent — one import + drill-down state + the
// onEvidenceSelect prop line + a conditional panel inside the diagnosis
// Panel. SPEC-403's frozen onEvidenceSelect signature is consumed verbatim;
// the region only holds the locator triple (no navigation, no derivation).
import { PacketInspectorSection } from "./packet-inspector/PacketInspectorSection";
import { parsePacketInspectorView, type PacketInspectorView } from "./packet-inspector/viewTypes";
import { DiagnosisCandidateList, DiagnosisList } from "./diagnosis/DiagnosisList";
import { JournalTail } from "./journal/JournalTail";
import { ControlBar } from "./lifecycle/ControlBar";
import type { LifecycleAction, LifecycleWire } from "./lifecycle/lifecycleTable";
import { OverviewCard, RunTrigger } from "./overview/OverviewCard";
import { MetricsPanel } from "./metrics/MetricsPanel";
import { useSessionStream } from "./stream/useSessionStream";
import { VerifyResultCard } from "./verify/VerifyResultCard";
import { VerifyRunForm, type VerifyRunPayload } from "./verify/VerifyRunForm";
// SPEC-405 CLI console (ticket #66, approved R1): stream = the SPEC-403
// panels (default); cli = the #66 CLI console section.
import { CliConsoleSection } from "./cli-console/CliConsoleSection";
import "./cli-console/cli-console.css";
import { MONITOR_EMPTY_STATE_COPY } from "./copy";
import { ThreeQuestionState } from "./ThreeQuestionState";
import { SessionList } from "./sessionList/SessionList";
import { isUnknownSessionState } from "./unknownSession";
// SPEC-408 §4.3 demo one-click (ticket #99): the guide seat's primary button
// drives the shell-owned orchestration through the demo controller context
// (AppShell owns the state; this page only fires startDemo).
import { useDemoController } from "./demo/DemoSessionContext";
// ONE shared 404-until-drained diagnose retrier with the demo orchestration
// (review-fix F4 收拢: the two byte-identical inline loops are gone).
import { diagnoseWith404Retry } from "./demo/diagnoseRetry";
import "./monitor.css";

/** Feature-local canonical-convention keys (diagnoses/report faces). */
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

/** A complete session UUID tracks on input (输入即跟踪, §4.3 手输兜底); anything
 * else waits for the explicit submit (no partial-id navigation). */
const SESSION_UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default function MonitorRegion() {
  const [searchParams, setSearchParams] = useSearchParams();
  const sessionId = searchParams.get("session");
  const demo = useDemoController();

  if (sessionId === null || sessionId === "") {
    return (
      <SessionGuide
        onTrack={(id) => setSearchParams({ session: id })}
        onDemoStart={demo.startDemo}
        demoBusy={demo.demoBusy}
      />
    );
  }
  return <MonitorPage key={sessionId} sessionId={sessionId} onUntrack={() => setSearchParams({})} />;
}

/** 会话列表区(SPEC-408 §4.3;§4.6 row 1 copy verbatim). The main seat is the
 * recent-session list; the demo button holds the primary button position and
 * drives the shell-owned one-click orchestration (ticket #99 — busy disables
 * so a second click can never start a parallel demo); the manual-UUID form
 * is the degraded fallback. */
function SessionGuide({
  onTrack,
  onDemoStart,
  demoBusy,
}: {
  onTrack: (sessionId: string) => void;
  onDemoStart: () => void;
  demoBusy: boolean;
}) {
  const [draft, setDraft] = useState("");
  const changeDraft = (value: string) => {
    setDraft(value);
    const trimmed = value.trim();
    if (SESSION_UUID_RE.test(trimmed)) onTrack(trimmed);
  };
  return (
    <div className="dvb-region dvb-mon-page">
      <h2>Monitor</h2>
      <ThreeQuestionState copy={MONITOR_EMPTY_STATE_COPY.entry} testid="monitor-entry-guide" />
      <div className="dvb-mon-guide-actions">
        <button
          type="button"
          data-testid="monitor-demo-start"
          disabled={demoBusy}
          onClick={onDemoStart}
        >
          一键演示
        </button>
      </div>
      <SessionList onTrack={onTrack} />
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
          onChange={(e) => changeDraft(e.target.value)}
        />
        <button type="submit">跟踪</button>
        <p className="dvb-mon-note dvb-mon-fallback-note">
          手输 UUID(输入 session id 即跟踪:完整 UUID 输入后自动进入;非 UUID 形状的 id 回车或点「跟踪」提交)。列表覆盖不到时的兜底。
        </p>
      </form>
    </div>
  );
}

function MonitorPage({ sessionId, onUntrack }: { sessionId: string; onUntrack: () => void }) {
  const queryClient = useQueryClient();
  const demo = useDemoController();
  const { status: wsStatus, closeCode: wsCloseCode } = useSessionStream(sessionId);
  // SPEC-404 §4.2 deep-link entry: read-only for inspect_* (the tracker owns
  // that param surface; this page never writes inspect_* params back). The
  // setter is used by the unknown-session state's reselection path only.
  const [searchParams, setSearchParams] = useSearchParams();
  // SPEC-405 mount (R1): stream = the SPEC-403 panels (default, unchanged);
  // cli = the #66 CLI console section.
  const [section, setSection] = useState<"stream" | "cli">("stream");

  // --- server state (all queries session-scoped) ---------------------------
  const snapshotQuery = useQuery({
    queryKey: [...qk.snapshot(sessionId)],
    queryFn: () => getSnapshot(sessionId),
  });
  // SPEC-408 §6.2 detail read-back (ticket #95): provenance pair + the
  // unknown-session 404 signal + the verify prefill scenario_id source.
  const detailQuery = useQuery({
    queryKey: [...qk.sessionDetail(sessionId)],
    queryFn: () => getSessionDetail(sessionId),
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

  // --- provenance (source-scenario link + verify prefill identity) ---------
  const scenarioId = detailQuery.data?.scenario_id ?? null;
  const scenarioQuery = useQuery({
    queryKey: [...qk.scenario(scenarioId ?? "")],
    queryFn: () => getScenario(scenarioId!),
    enabled: scenarioId !== null,
  });
  // SPEC-408 §6.3 run list (ticket #95): the datalist source across
  // refresh/deep-link/manual entry (submitted_at ASC per contract).
  const runsListQuery = useQuery({
    queryKey: [...qk.sessionRuns(sessionId)],
    queryFn: () => listSessionRuns(sessionId),
  });

  // --- unknown-session explicit state (§4.6 row 0) --------------------------
  // Two signal routes, both server facts: a session-scoped REST read
  // answering 404 (snapshot/detail) or the WS permanent close 4404. The
  // state replaces the panel stack (never an error stack).
  const snapshotNotFound = snapshotQuery.error instanceof ApiError && snapshotQuery.error.status === 404;
  const detailNotFound = detailQuery.error instanceof ApiError && detailQuery.error.status === 404;
  const unknownSession = isUnknownSessionState({
    sessionHttpNotFound: snapshotNotFound || detailNotFound,
    wsCloseCode: wsCloseCode,
  });

  // --- run registry (page state; facts always from getRun answers) ---------
  // NOTE (review-fix F4 职责声明): this loop is deliberately NOT the demo
  // module's runAndWait — it owns per-tick rendering integration (every
  // poll's status answer updates the page registry row in place via
  // setRuns, so the Run 触发 face stays live during the poll). The pure
  // submit-and-wait shape would drop the intermediate rows. The byte-identical
  // diagnose-404 retry loop, by contrast, HAD no rendering duty and is now
  // the one shared diagnoseWith404Retry (demo/diagnoseRetry.ts).
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
        void queryClient.invalidateQueries({ queryKey: [...qk.sessionRuns(sessionId)] });
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
  // SPEC-404 drill-down: the evidence locator triple verbatim (SPEC-403 §6
  // frozen callback); the panel's close action clears it. No derivation.
  // Deep-link entry (SPEC-404 §4.2): inspect_artifact/inspect_pid/
  // inspect_packet seed the same panel without a candidate row — the UI
  // diagnose chain has no ts.* facts while the analyze REST face stays
  // frozen 501 (M4 裁定 B), so candidates are honestly zero there. Malformed
  // params seed nothing (honest absence, no fabricated locator).
  // SPEC-404 §Phase2 (#132): `view` is additive on the deep link only — the
  // locator triple keeps its semantics; absent/invalid falls back to the MVP
  // default (viewTypes owns the vocabulary, ruling §10-5). Read-only here
  // (本页面对 inspect_*/view 参数只读不写).
  const [drillDownView] = useState<PacketInspectorView>(() =>
    parsePacketInspectorView(searchParams.get("view")),
  );
  const [drillDown, setDrillDown] = useState<DiagnosisEvidenceDTO | null>(() => {
    const artifact = searchParams.get("inspect_artifact");
    const pidRaw = searchParams.get("inspect_pid");
    const packetRaw = searchParams.get("inspect_packet");
    if (artifact === null || pidRaw === null || packetRaw === null) return null;
    const pid = Number.parseInt(pidRaw, 10);
    const packetIndex = Number.parseInt(packetRaw, 10);
    if (!Number.isInteger(pid) || pid < 0 || !Number.isInteger(packetIndex) || packetIndex < 0) return null;
    return { artifact_id: artifact, pid, packet_index: packetIndex };
  });

  const triggerDiagnose = useCallback(async () => {
    if (diagnoseRunId.trim() === "") return;
    setDiagnoseBusy(true);
    setDiagnoseError(null);
    try {
      // 404-until-drained: the report becomes answerable once the pump has
      // committed the run's terminal journal events (SPEC-306 §5 idempotent).
      // ONE shared retrier with the demo orchestration (review-fix F4).
      const answer = await diagnoseWith404Retry(sessionId, diagnoseRunId.trim());
      setReport(answer);
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

  // Run candidates: the page registry (newest first) merged with the server
  // run list (contract ASC order) — the datalist source survives refresh /
  // deep-link / manual entry (SPEC-408 §6.3; dedup keeps one option per id).
  const runCandidates = useMemo(() => {
    const seen = new Set<string>();
    const merged: string[] = [];
    for (const run of runs) {
      if (!seen.has(run.run_id)) {
        seen.add(run.run_id);
        merged.push(run.run_id);
      }
    }
    for (const item of runsListQuery.data ?? []) {
      if (!seen.has(item.run_id)) {
        seen.add(item.run_id);
        merged.push(item.run_id);
      }
    }
    return merged;
  }, [runs, runsListQuery.data]);

  if (unknownSession) {
    // 未知会话态(§4.6 row 0,文案逐字):显式态替换面板栈;动作 = 回 Lab 开新
    // 实验;重新选择 = 下方最近列表(SessionGuide)。
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
        <section data-testid="monitor-unknown-session">
          <ThreeQuestionState copy={MONITOR_EMPTY_STATE_COPY.unknownSession} />
          <Link className="dvb-mon-back-lab" to="/lab">
            回 Lab 开新实验
          </Link>
        </section>
        <SessionGuide
          onTrack={(id) => setSearchParams({ session: id })}
          onDemoStart={demo.startDemo}
          demoBusy={demo.demoBusy}
        />
      </div>
    );
  }

  return (
    <div className="dvb-region dvb-mon-page">
      <header className="dvb-mon-page-header">
        <h2>Monitor</h2>
        <span className="dvb-mon-session">session: {sessionId}</span>
        {/* 来源场景(§4.3):仅来源回跳、零状态参数;Lab→Monitor 三元组深链
            (inspect_*)维持不变、不追加参数。 */}
        {scenarioId !== null && (
          <Link
            className="dvb-mon-scenario"
            data-testid="monitor-source-scenario"
            to={`/lab?scenario=${encodeURIComponent(scenarioId)}`}
          >
            来源场景:{scenarioId} ↗
          </Link>
        )}
        <Badge tone="neutral">ws: {wsStatus}</Badge>
        <button type="button" onClick={() => { onUntrack(); }}>
          取消跟踪
        </button>
      </header>

      <div className="dvb-mon-section-tabs" role="tablist" aria-label="monitor sections">
        <button
          type="button"
          role="tab"
          aria-selected={section === "stream"}
          onClick={() => setSection("stream")}
        >
          Stream Monitor
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={section === "cli"}
          onClick={() => setSection("cli")}
        >
          CLI 对照
        </button>
      </div>

      {section === "cli" ? (
        <CliConsoleSection sessionId={sessionId} />
      ) : (
        <>
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
            <DiagnosisCandidateList candidates={report.candidates} onEvidenceSelect={setDrillDown} />
          </section>
        )}
        <PacketInspectorSection locator={drillDown} view={drillDownView} onClose={() => setDrillDown(null)} />
        <DiagnosisList diagnoses={diagnosesQuery.data ?? []} />
      </Panel>

      <Panel title="Verify">
        {/* §7.5 可编辑预填:scenario_id ← 会话详情;version/content_hash ← 场景
            详情(真实钉扎哈希);baseline/recovery ← run 列表 datalist。全部可改;
            run 永不自动猜——用户未明确选择前不发 verify 请求。 */}
        <VerifyRunForm
          runCandidates={runCandidates}
          prefill={{
            scenarioId: detailQuery.data?.scenario_id ?? null,
            version: scenarioQuery.data?.version ?? null,
            contentHash: scenarioQuery.data?.content_hash ?? null,
          }}
          onSubmit={(payload) => void triggerVerify(payload)}
        />
        {verifyBusy && <p className="dvb-mon-line">判定中…</p>}
        {verifyError !== null && <p className="dvb-mon-error">{verifyError}</p>}
        {verifyResult !== null && <VerifyResultCard result={verifyResult} />}
        {verifyResult === null && !verifyBusy && verifyError === null && (
          <ThreeQuestionState copy={MONITOR_EMPTY_STATE_COPY.verify} />
        )}
      </Panel>

      <Panel title="journal 尾窗">
        <JournalTail sessionId={sessionId} />
      </Panel>
        </>
      )}
    </div>
  );
}
