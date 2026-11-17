// Experiment console (SPEC-406 §4.3/§4.5/§4.6/§4.7; opening auto-baseline +
// verify prefill form per SPEC-408 §4.4/§7.3/§7.5): one scoped scenario
// session — auto-baseline declaration note (when the §7.3 third hop handed a
// run in via initialRuns) + eight-step stepper + run triggers
// (Generate/Inject/Recover) + diagnose + evidence/events + the EDITABLE
// PREFILL verify form + the PASS-gated solution panel.
//
// Wire discipline: run configs use the frozen teaching geometry
// (labGeometry.ts); Inject submits the scenario document's fault_plan
// VERBATIM (no UI rewrite); verify is NEVER auto-guessed — baseline/recovery
// run ids stay empty until the user explicitly picks them (datalist
// candidates = this console's run registry ⊕ the §6.3 server run list,
// deduped, submitted_at ASC — Monitor 同口径, review-fix F1), scenario
// identity prefills from the scenario detail's
// REAL pinned content_hash (the lab-ui-unpinned declared marker is RETIRED,
// SPEC-406 §7.4 0.5.1 注记), criteria pass through verbatim via
// labBodies.buildVerifyBody, and no ui_state is ever sent. The solution
// panel unlocks only on the card-rendered verdict === "PASS" and the reveal
// rides the 裁定 F backend gate. Diagnosis candidate jumps use the SPEC-404
// §4.2 Monitor deep link (inspect_artifact/inspect_pid/inspect_packet seed
// the packet inspector without any monitor/** import — Plan A of the §7.6
// dual plan; finalized at the merge tip).
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router";
import {
  diagnoseRun,
  getRun,
  getScenario,
  getSnapshot,
  listDiagnoses,
  listSessionRuns,
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
import { useHintsReveal } from "./hintsStorage";
import { HintsLadder, type LabHintWire } from "./HintsLadder";
import { currentActionGuide, deriveCurrentAction, type CurrentActionKey } from "./currentAction";
import { deriveStepState, type LabFacts, type LabRunFact } from "./stepperState";
import { Stepper } from "./Stepper";
import { SolutionPanel, type SolutionErrorState, type SolutionFetchState } from "./SolutionPanel";
import { GenerationFold } from "./GenerationFold";
import type { GenJumpTarget, GenRunFace } from "./genEvents";

const POLL_INTERVAL_MS = 200;
const POLL_WINDOW_MS = 30_000;
const EVENTS_LIMIT = 100;
const FLASH_RESET_MS = 1_200;

// Stepper click → scroll target (SPEC-408 §4.4「定位非打卡」): the console's
// five sections are the anchors; the eight steps collapse onto them (the
// four run-phase steps all land on the Run 触发 block, which holds their
// buttons and disable reasons).
type SectionKey = "run" | "diagnose" | "inspect" | "verify" | "solution";

const STEP_SECTION: Record<CurrentActionKey, SectionKey> = {
  create: "run",
  generate: "run",
  inject: "run",
  diagnose: "diagnose",
  inspect: "inspect",
  recover: "run",
  verify: "verify",
};

interface RegistryEntry {
  view: RunStatusDTO;
  /** Submission time — the §6.3 server submitted_at_ms for list-reconstructed
   * rows, the accept wall-clock for page-submitted ones (the datalist's ASC
   * order rides this). */
  submittedAtMs: number;
  /** THIS page's poll-window origin: the 30s window runs from the moment the
   * page learned of the run, never from a server timestamp long past. null =
   * a derived §6.3 row (the window anchors at this page's first poll of it,
   * inside the poller — event time, never render time). */
  pollSinceMs: number | null;
  timedOut: boolean;
  /** §6.3 list fact (review-fix F1): true/false = list-reconstructed row
   * (clean/faulted facts ride fault_plan_present); null = page-memory run
   * (facts stay on the artifact-kind path). */
  faultPlanPresent: boolean | null;
}

/** §7.3 hop-3 carrier (review-fix F6 诚实化): the at-accept MINIMUM face —
 * run id + async status only. It does NOT claim the full RunStatusDTO
 * read-back shape: artifacts/packet faces are simply not held at accept time
 * (omitted, never fabricated) — the console's poller fills the real face
 * from getRun answers. RunStatusDTO values are assignable to it. */
export interface AcceptedRunCarrier {
  run_id: string;
  status: RunStatusDTO["status"];
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function ExperimentConsole({
  scenarioId,
  sessionId,
  onBack,
  initialRuns,
}: {
  scenarioId: string;
  sessionId: string;
  onBack: () => void;
  /** Runs auto-submitted by the §7.3 opening third hop (Region carrier —
   * the honest at-accept minimum face, F6). Non-empty ⇒ the standing
   * auto-baseline declaration note renders and the registry opens already
   * carrying the run; empty/absent ⇒ the mount-time §6.3 run-list fetch
   * reconstructs the facts face (review-fix F1). */
  initialRuns?: ReadonlyArray<AcceptedRunCarrier>;
}) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  // Shared hint-reveal source (SPEC-408 §4.4 REQ-UI-408-011): the SAME
  // per-scenario localStorage key as the detail page's ladder — the
  // collapsible block below embeds hints WITHOUT a deep link (the ?session=
  // anchor would be lost).
  const hints = useHintsReveal(scenarioId);

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
  // §6.3 run list (SPEC-408 §7.5「Monitor 与 Lab 同口径」; review-fix F1):
  // the mount-time fetch that survives refresh/deep-link/manual entry. It
  // feeds the verify datalist (registry ⊕ list, dedup, submitted_at ASC) and
  // honestly rebuilds the facts face when the opening hop's carrier is
  // absent. Same qk key as Monitor — one invalidation bridge.
  const runsListQuery = useQuery({
    queryKey: [...qk.sessionRuns(sessionId)],
    queryFn: () => listSessionRuns(sessionId),
    retry: 1,
  });
  const serverRuns = runsListQuery.data;

  // --- run registry (page memory; facts ride getRun answers) ----------------
  // Seeded with the §7.3 auto-submitted baseline run so the registry opens
  // populated and the 200ms poller drives Generate to light up by itself.
  // §7.3 note (review-fix F1): the declaration rides the hop carrier when
  // present AND honestly rebuilds on refresh/deep-link — the first §6.3
  // list row being an empty-plan run IS the session's opening baseline (the
  // Lab opening always attempts it first; an manual regeneration after a
  // failed hop is indistinguishable from the list face and declared so in
  // the review-fix REPORT). The §4.6 fallback copy stays gated on BOTH
  // faces (registry + server list) being empty.
  const reconstructedBaseline =
    serverRuns !== undefined &&
    serverRuns.length > 0 &&
    serverRuns[0] !== undefined &&
    !serverRuns[0].fault_plan_present;
  const hasAutoBaseline =
    (initialRuns !== undefined && initialRuns.length > 0) || reconstructedBaseline;
  const [registry, setRegistry] = useState<RegistryEntry[]>(
    () =>
      initialRuns?.map((view) => ({
        view: { run_id: view.run_id, status: view.status },
        submittedAtMs: Date.now(),
        pollSinceMs: Date.now(),
        timedOut: false,
        faultPlanPresent: null,
      })) ?? [],
  );
  const refreshSnapshot = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: qk.snapshot(sessionId) });
    void queryClient.invalidateQueries({ queryKey: [...monitorKeys.diagnoses(sessionId)] });
    void queryClient.invalidateQueries({ queryKey: [...qk.sessionRuns(sessionId)] });
  }, [queryClient, sessionId]);

  // §6.3 reconstruction (review-fix F1): runs the server already knows about
  // (refresh / deep link / manual entry — the opening hop's carrier is
  // empty) join the face as DERIVED rows. No setState-in-effect mirror: the
  // derived rows recompute at render from serverRuns ⊖ registry (dedup by
  // run_id keeps page-memory rows authoritative). Their faces carry the
  // at-accept minimum + packet_count passthrough; the artifact list is NOT
  // available from the §6.3 face, so NO artifact chips render until a live
  // getRun answer pulls the row into page memory (the poller's upsert below
  // — event-time setState — fills the real face). Completed derived rows
  // stay derived: there is nothing to poll.
  const derivedRows: RegistryEntry[] = useMemo(() => {
    if (serverRuns === undefined) return [];
    const known = new Set(registry.map((entry) => entry.view.run_id));
    return serverRuns
      .filter((row) => !known.has(row.run_id))
      .map((row): RegistryEntry => ({
        view: {
          run_id: row.run_id,
          status: row.status,
          packet_count: row.packet_count ?? undefined,
        },
        submittedAtMs: row.submitted_at_ms,
        pollSinceMs: null,
        timedOut: false,
        faultPlanPresent: row.fault_plan_present,
      }));
  }, [registry, serverRuns]);
  const rowEntries = useMemo(() => [...registry, ...derivedRows], [registry, derivedRows]);

  const submit = useCallback(
    async (faultPlan: ReadonlyArray<unknown>) => {
      const accepted = await submitRun(sessionId, {
        config: LAB_RUN_CONFIG as unknown as Parameters<typeof submitRun>[1]["config"],
        fault_plan: faultPlan as Parameters<typeof submitRun>[1]["fault_plan"],
      });
      setRegistry((prev) => [
        ...prev,
        // Honest at-accept face (F6): run_id + status only — artifacts are
        // NOT claimed until a real getRun answer holds them.
        {
          view: { run_id: accepted.run_id, status: "running" },
          submittedAtMs: Date.now(),
          pollSinceMs: Date.now(),
          timedOut: false,
          faultPlanPresent: null,
        },
      ]);
    },
    [sessionId],
  );

  // Poll-window origins for DERIVED §6.3 rows: the 30s window anchors at this
  // page's first poll of the run — written at event time (inside the interval
  // callback) only, never during render.
  const pollSinceRef = useRef<Map<string, number>>(new Map());

  // Event-time registry writes for rows a poll touched (review-fix F1): a
  // derived §6.3 row PULLS INTO page memory at its first poll answer (face)
  // or timeout marking — until then it stays render-derived. Page-memory
  // rows update in place as before.
  const upsertRowFace = useCallback((face: RunStatusDTO, faultPlanPresent: boolean | null) => {
    setRegistry((prev) =>
      prev.some((entry) => entry.view.run_id === face.run_id)
        ? prev.map((entry) => (entry.view.run_id === face.run_id ? { ...entry, view: face } : entry))
        : [
            ...prev,
            { view: face, submittedAtMs: Date.now(), pollSinceMs: Date.now(), timedOut: false, faultPlanPresent },
          ],
    );
  }, []);
  const markRowTimedOut = useCallback((entry: RegistryEntry) => {
    setRegistry((prev) =>
      prev.some((item) => item.view.run_id === entry.view.run_id)
        ? prev.map((item) => (item.view.run_id === entry.view.run_id ? { ...item, timedOut: true } : item))
        : [...prev, { ...entry, pollSinceMs: Date.now(), timedOut: true }],
    );
  }, []);

  // Single 200ms poller over pending runs (30s window → explicit timeout).
  // The effect re-arms on every rowEntries change, so `rowEntries` is read
  // from the closure (no ref access). Derived §6.3 rows poll exactly like
  // page-memory rows (§7.5 同口径: a running row is a running row).
  // NOTE (review-fix F4 职责声明): this is deliberately NOT the demo
  // module's runAndWait — the loop owns per-tick rendering integration
  // (each poll's answer updates the registry row in place, driving the
  // stepper facts); a pure submit-and-wait shape would drop the live rows.
  useEffect(() => {
    const pending = rowEntries.filter((entry) => entry.view.status === "running" && !entry.timedOut);
    if (pending.length === 0) return;
    const timer = setInterval(() => {
      void (async () => {
        for (const entry of pending) {
          let since = entry.pollSinceMs;
          if (since === null) {
            since = pollSinceRef.current.get(entry.view.run_id) ?? Date.now();
            pollSinceRef.current.set(entry.view.run_id, since);
          }
          if (Date.now() - since > POLL_WINDOW_MS) {
            markRowTimedOut(entry);
            continue;
          }
          try {
            const latest = await getRun(sessionId, entry.view.run_id);
            if (latest.status !== entry.view.status) {
              upsertRowFace(latest, entry.faultPlanPresent);
              if (latest.status !== "running") refreshSnapshot();
            }
          } catch {
            // transient poll error → keep last known state (next tick retries)
          }
        }
      })();
    }, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [rowEntries, sessionId, refreshSnapshot, upsertRowFace, markRowTimedOut]);

  // --- diagnose / verify / solution page state ------------------------------
  const [report, setReport] = useState<DiagnosisReportDTO | null>(null);
  const [reportError, setReportError] = useState<string | null>(null);
  const [diagnosing, setDiagnosing] = useState(false);
  const [verdict, setVerdict] = useState<VerificationResultDTO | null>(null);
  const [verifyError, setVerifyError] = useState<string | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [solution, setSolution] = useState<SolutionFetchState | null>(null);
  const [solutionError, setSolutionError] = useState<SolutionErrorState | null>(null);

  // Verify prefill form (SPEC-408 §7.5 editable prefill; orchestrator ruling):
  // scenario identity DERIVES from the scenario detail (REAL pinned hash)
  // until the user edits the field — edits are stored and win over the
  // prefill, no effect needed. Run ids are NEVER auto-filled — run 不自动猜,
  // the user must explicitly pick (datalist suggestions come from this
  // console's run registry).
  const [baselineField, setBaselineField] = useState("");
  const [recoveryField, setRecoveryField] = useState("");
  const [identityEdits, setIdentityEdits] = useState<{
    scenario_id?: string;
    version?: string;
    content_hash?: string;
  }>({});
  const detailData = detailQuery.data;
  const scenarioField = identityEdits.scenario_id ?? detailData?.scenario_id ?? "";
  const versionField = identityEdits.version ?? detailData?.version ?? "";
  const hashField = identityEdits.content_hash ?? detailData?.content_hash ?? "";
  const verifyReady = [baselineField, recoveryField, scenarioField, versionField, hashField].every(
    (value) => value.trim() !== "",
  );

  const completed = rowEntries.filter((entry) => entry.view.status === "completed");
  const injectRun = completed.find((entry) =>
    (entry.view.artifacts ?? []).some((artifact) => artifact.kind === "faulted_ts"),
  );
  // 名实一致（review-fix F5，#96 命名陷阱解除）: 该变量指注入 Run id
  // （diagnose 的「注入锚」）。verify 不消费任何自动派生 run id —
  // recovery/baseline 都来自表单的显式选择（run 不自动猜）。
  const injectRunId = injectRun?.view.run_id ?? "";

  const facts: LabFacts = useMemo(
    () => ({
      sessionLifecycle: snapshotQuery.data?.lifecycle ?? null,
      runs: rowEntries.map(
        (entry): LabRunFact => ({
          runId: entry.view.run_id,
          status: entry.view.status,
          artifacts: entry.view.artifacts ?? [],
          faultPlanPresent: entry.faultPlanPresent,
        }),
      ),
      reportFetched: report !== null,
      eventsSeen: eventsQuery.data?.data.items?.length ?? 0,
      verdictFetched: verdict !== null,
    }),
    [snapshotQuery.data, rowEntries, report, eventsQuery.data, verdict],
  );
  const steps = deriveStepState(facts);

  // §7.5 datalist candidates (review-fix F1, Monitor 同口径): the page
  // registry ⊕ the §6.3 server list — dedup by run_id, submitted_at ASC
  // (the §6.3 contract order = the eight-step narrative order). Survives
  // refresh/deep-link/manual entry; run ids are still NEVER auto-filled —
  // the user picks explicitly.
  const runCandidates = useMemo(() => {
    const merged: Array<{ runId: string; at: number; status: string }> = [
      ...rowEntries.map((entry) => ({
        runId: entry.view.run_id,
        at: entry.submittedAtMs,
        status: entry.view.status,
      })),
      ...(serverRuns ?? []).map((row) => ({
        runId: row.run_id,
        at: row.submitted_at_ms,
        status: row.status,
      })),
    ];
    const seen = new Set<string>();
    return merged
      .sort((a, b) => a.at - b.at)
      .filter((row) => {
        if (seen.has(row.runId)) return false;
        seen.add(row.runId);
        return true;
      });
  }, [rowEntries, serverRuns]);

  // --- current action (SPEC-408 §7.2): pointer over the §7.3 facts ----------
  const current = deriveCurrentAction(steps);
  const primary = (key: CurrentActionKey): string | undefined =>
    current === key ? "dvb-lab-btn-primary" : undefined;

  // Stepper locator (定位非打卡): scroll to the step's section + flash it.
  // A click NEVER mutates light-up (steps above derive only from facts) and
  // never submits anything.
  const sectionRefs = useRef<Record<SectionKey, HTMLElement | null>>({
    run: null,
    diagnose: null,
    inspect: null,
    verify: null,
    solution: null,
  });
  const [flashSection, setFlashSection] = useState<SectionKey | null>(null);
  const flashTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const locateStep = useCallback((key: CurrentActionKey) => {
    const section = STEP_SECTION[key];
    const element = sectionRefs.current[section];
    if (element === null) return;
    if (typeof element.scrollIntoView === "function") {
      element.scrollIntoView({ behavior: "smooth", block: "start" });
    }
    setFlashSection(section);
    if (flashTimer.current !== null) clearTimeout(flashTimer.current);
    flashTimer.current = setTimeout(() => setFlashSection(null), FLASH_RESET_MS);
  }, []);

  const runDiagnose = useCallback(async () => {
    if (injectRunId === "") return;
    setDiagnosing(true);
    setReportError(null);
    try {
      setReport(await diagnoseRun(sessionId, injectRunId));
      refreshSnapshot();
    } catch (error) {
      setReportError(
        isApiError(error) ? `${error.errorCode}: ${error.message}` : errorMessage(error),
      );
    } finally {
      setDiagnosing(false);
    }
  }, [injectRunId, sessionId, refreshSnapshot]);

  const runVerify = useCallback(async () => {
    // The gate mirrors the disabled state: every form field must hold the
    // user's explicit choice — run ids are never derived here (run 不自动猜).
    if (detailQuery.data === undefined || !verifyReady) return;
    setVerifying(true);
    setVerifyError(null);
    try {
      setVerdict(
        await verifyRun(
          sessionId,
          recoveryField,
          buildVerifyBody(
            {
              baselineRunId: baselineField,
              scenarioId: scenarioField,
              version: versionField,
              contentHash: hashField,
            },
            detailQuery.data,
          ),
        ),
      );
    } catch (error) {
      setVerifyError(isApiError(error) ? `${error.errorCode}: ${error.message}` : errorMessage(error));
    } finally {
      setVerifying(false);
    }
  }, [detailQuery.data, verifyReady, baselineField, recoveryField, scenarioField, versionField, hashField, sessionId]);

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

  // 生成过程折叠区 jump wiring (SPEC-406 §Phase2): the #132 string contract —
  // the Lab side builds the deep-link parameter string, appending the mapped
  // `view` value (layer→view mapping lives in genEvents.ts; the inspector
  // only reads the parameter, no inspector import beyond the read-only view
  // vocabulary). pid carries the neutral 0 (layered packets have no TS PID;
  // the layered structure views never consume it — see GenJumpTarget).
  const jumpToGenerationPacket = useCallback(
    (target: GenJumpTarget) => {
      navigate(
        `/monitor?session=${encodeURIComponent(sessionId)}&inspect_artifact=${encodeURIComponent(target.artifactId)}&inspect_pid=${target.pid}&inspect_packet=${target.packetIndex}&view=${target.view}`,
      );
    },
    [navigate, sessionId],
  );

  // The fold's run registry face + activity flag (artifact resolution for
  // the packet-card jumps, poll gating while a run executes).
  const genRuns: ReadonlyArray<GenRunFace> = useMemo(
    () =>
      rowEntries.map((entry) => ({
        runId: entry.view.run_id,
        artifacts: (entry.view.artifacts ?? []).map((artifact) => ({
          artifact_id: artifact.artifact_id,
          kind: artifact.kind,
        })),
      })),
    [rowEntries],
  );
  const genActive = useMemo(() => rowEntries.some((entry) => entry.view.status === "running"), [rowEntries]);

  const lifecycle = snapshotQuery.data?.lifecycle ?? null;
  const sectionClass = (key: SectionKey): string | undefined =>
    flashSection === key ? "dvb-lab-section-flash" : undefined;
  return (
    <div className="dvb-lab-console">
      {/* 常驻自动基线声明条（SPEC-408 §4.4/§7.3; renders ABOVE the Stepper,
          sibling-ordered before it — the #96 guidance bar stays under it）:
          the third hop's run is REAL sandbox data; only the submission was
          automatic. Honest automation disclosure, never a fake row. */}
      {hasAutoBaseline && (
        <p className="dvb-lab-autorun-note" data-testid="lab-autorun-note">
          开局已自动提交基线 Run——真实沙盘数据，非示例。下一步：<strong>注入故障</strong>。
        </p>
      )}
      <Stepper steps={steps} onStepSelect={locateStep} />
      {/* 常驻指引条（SPEC-408 §4.4）: next-step name + VERBATIM button copy. */}
      <p className="dvb-lab-action-guide" data-testid="lab-action-guide">
        {currentActionGuide(steps)}
      </p>
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
        {/* 内嵌分阶段提示（SPEC-408 §4.4 REQ-UI-408-011）: collapsible, fed by
            the SAME localStorage-backed source as the detail page (the shared
            per-scenario key via useHintsReveal — no deep link, the ?session=
            anchor stays). Sits OUTSIDE the five lab-section-* anchors so
            Stepper locating is untouched. */}
        <details className="dvb-lab-hints-details" data-testid="lab-hints-section">
          <summary>分阶段提示</summary>
          {detailQuery.data !== undefined && (
            <HintsLadder
              hints={detailQuery.data.hints as unknown as LabHintWire[]}
              revealedCount={hints.count}
              onRevealNext={hints.revealNext}
              onResetHints={hints.resetHints}
              storageAvailable={hints.storageOk}
            />
          )}
        </details>
        <section data-testid="lab-section-run" ref={(el) => { sectionRefs.current.run = el; }} className={sectionClass("run")}>
          <h3 className="dvb-lab-h3">Run 触发</h3>
          <div className="dvb-lab-run-actions">
            <button type="button" className={primary("generate")} onClick={() => void submit([])} disabled={lifecycle !== "running"}>
              生成基线（Generate，空 plan）
            </button>
            <button
              type="button"
              className={primary("inject")}
              onClick={() => void submit(detailQuery.data?.fault_plan ?? [])}
              disabled={lifecycle !== "running" || detailQuery.data === undefined}
            >
              注入故障（Inject，场景 fault_plan）
            </button>
            <button type="button" className={primary("recover")} onClick={() => void submit([])} disabled={lifecycle !== "running"}>
              恢复重跑（Recover，空 plan）
            </button>
          </div>
          {rowEntries.length === 0 ? (
            // §4.6 Lab 组行 3 逐字: this empty state is the §7.3 SILENT
            // FALLBACK face — the opening auto baseline did not succeed, the
            // manual flow stands, nothing fakes success. It may ONLY speak
            // once the §6.3 server list has confirmed emptiness (review-fix
            // F1: in-flight → the loading face; failed → 失败 ≠ 空库 face —
            // the fallback copy asserts server-side emptiness and must not
            // render unverified).
            runsListQuery.isPending ? (
              <div data-testid="lab-runlist-loading">
                <EmptyState title="尚无 Run" note="正在读取服务端 Run 列表（§6.3）…读取完成前不下「未触发」结论" />
              </div>
            ) : runsListQuery.isError ? (
              <div className="dvb-lab-error" data-testid="lab-runlist-error">
                Run 列表读取失败（失败 ≠ 空库）：{errorMessage(runsListQuery.error)}
                。下一步：确认后端已运行（仓库根 `start.cmd`）
              </div>
            ) : (
              <EmptyState
                title="尚无 Run"
                note="本会话尚未触发任何 Run（开局自动基线未成功，回落手动流程，诚实态）。下一步：点击『生成基线（Generate，空 plan）』"
              />
            )
          ) : (
            <ul className="dvb-lab-list">
              {rowEntries.map((entry) => (
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

        <section data-testid="lab-section-diagnose" ref={(el) => { sectionRefs.current.diagnose = el; }} className={sectionClass("diagnose")}>
          <h3 className="dvb-lab-h3">诊断（Diagnose）</h3>
          <button
            type="button"
            className={primary("diagnose")}
            onClick={() => void runDiagnose()}
            disabled={diagnosing || injectRunId === ""}
          >
            {diagnosing ? "评估中…" : "对注入 Run 评估（diagnose）"}
          </button>
          {reportError !== null && <div className="dvb-lab-error">{reportError}</div>}
          {report !== null && (
            <div className="dvb-lab-line">
              report: run {report.run_id} · {report.candidates.length} candidates · {report.warnings?.length ?? 0} warnings
            </div>
          )}
          {report === null && (diagnosesQuery.data ?? []).length === 0 ? (
            // §4.6 Lab 组行 4（新增）: diagnose never happens by itself — the
            // honest empty face BEFORE any diagnose ran on this page.
            <div data-testid="lab-diagnose-empty">
              <EmptyState
                title="尚无诊断报告"
                note="诊断不自动发生：注入 Run 完成后点击『对注入 Run 评估（diagnose）』；无观测 ≠ 干净，空表是诚实态"
              />
            </div>
          ) : (
            <>
              <DiagnosisCandidateList
                candidates={report?.candidates ?? []}
                onEvidenceSelect={(locator) => jumpToEvidence(locator)}
                context={<span>场景语境：{detailQuery.data?.title ?? scenarioId}</span>}
              />
              <DiagnosisList
                diagnoses={diagnosesQuery.data ?? []}
                context={<span>session 诊断表行（GET .../diagnoses）</span>}
              />
            </>
          )}
        </section>

        <section data-testid="lab-section-inspect" ref={(el) => { sectionRefs.current.inspect = el; }} className={sectionClass("inspect")}>
          <h3 className="dvb-lab-h3">证据 / 事件（Inspect）</h3>
          {/* 生成过程 只读折叠区（SPEC-406 §Phase2）: stage progress rows +
              sampled packet cards over the gen.* journal face — static
              wayfinding (无动画/无时间线/无独立页面), sits inside the Inspect
              anchor so Stepper locating is untouched; gen.* 仅分层 run 发射,
              v1 runs answer the honest empty face. */}
          <GenerationFold sessionId={sessionId} runs={genRuns} active={genActive} onJump={jumpToGenerationPacket} />
          {eventsQuery.isPending ? (
            <EmptyState title="加载中" note="读取 journal 事件…" />
          ) : eventsQuery.isError ? (
            <div className="dvb-lab-error">{errorMessage(eventsQuery.error)}</div>
          ) : ((eventsQuery.data?.data.items ?? []) as Array<{ journal_seq: number; event_type?: string }>).length ===
            0 ? (
            // §4.6 Lab 组行 5（新增）: an established session with no engine
            // events yet — empty ≠ error.
            <div data-testid="lab-events-empty">
              <EmptyState
                title="暂无 journal 事件"
                note="会话已建立但引擎尚未产生事件（空 ≠ 错误）。下一步：触发一个 Run 后回来查看"
              />
            </div>
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

        <section data-testid="lab-section-verify" ref={(el) => { sectionRefs.current.verify = el; }} className={sectionClass("verify")}>
          <h3 className="dvb-lab-h3">通关判定（Verify）</h3>
          {/* Editable prefill form (SPEC-408 §7.5 同口径; the auto-derived
              one-click posture and the lab-ui-unpinned declared marker are
              RETIRED). Scenario identity prefills from the detail's REAL
              pinned hash; run ids are the user's explicit pick — datalist
              candidates = page registry ⊕ §6.3 server run list (dedup,
              submitted_at ASC, Monitor 同口径 — review-fix F1). */}
          <div className="dvb-lab-verify-form">
            <label htmlFor="lab-verify-baseline">baseline_run_id</label>
            <input
              id="lab-verify-baseline"
              list="lab-verify-run-candidates"
              value={baselineField}
              onChange={(event) => setBaselineField(event.target.value)}
              placeholder="从 Run 注册表选择或粘贴"
            />
            <label htmlFor="lab-verify-recovery">recovery_run_id</label>
            <input
              id="lab-verify-recovery"
              list="lab-verify-run-candidates"
              value={recoveryField}
              onChange={(event) => setRecoveryField(event.target.value)}
              placeholder="从 Run 注册表选择或粘贴（修复后新 Run）"
            />
            <label htmlFor="lab-verify-scenario">scenario_id</label>
            <input
              id="lab-verify-scenario"
              value={scenarioField}
              onChange={(event) => setIdentityEdits((prev) => ({ ...prev, scenario_id: event.target.value }))}
            />
            <label htmlFor="lab-verify-version">version</label>
            <input
              id="lab-verify-version"
              value={versionField}
              onChange={(event) => setIdentityEdits((prev) => ({ ...prev, version: event.target.value }))}
            />
            <label htmlFor="lab-verify-hash">content_hash</label>
            <input
              id="lab-verify-hash"
              className="dvb-lab-mono"
              value={hashField}
              onChange={(event) => setIdentityEdits((prev) => ({ ...prev, content_hash: event.target.value }))}
            />
            <datalist id="lab-verify-run-candidates">
              {runCandidates.map((candidate) => (
                <option key={candidate.runId} value={candidate.runId} label={candidate.status} />
              ))}
            </datalist>
          </div>
          <div className="dvb-lab-line">判定以修复后新 Run 的证据为准；五个字段全部填写后才可提交（run 不自动猜）。</div>
          <button
            type="button"
            className={primary("verify")}
            onClick={() => void runVerify()}
            disabled={verifying || !verifyReady}
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

        <section data-testid="lab-section-solution" ref={(el) => { sectionRefs.current.solution = el; }} className={sectionClass("solution")}>
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
