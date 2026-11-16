// Demo one-click orchestration phase machine (SPEC-408 §7.4, ticket #99):
// a REAL backend pipeline over existing endpoints only (zero backend delta).
// Phase order (spec authority, NOT the prototype's key names):
//   scenario → create → start → generate → inject → recover → diagnose → land
// Every phase emits one honest progress row (pending/active/done/failed);
// any failure stops in place — the caller never lands, never fakes success,
// and a created session is kept for manual cleanup. `land` itself is only
// marked done by the caller once navigation actually happened (the module
// owns no router).
//
// The pre-anchored deep link resolves the REAL fault locus from the scenario
// fault_plan (target hex PID + activation packet slot) against the injected
// run's faulted_ts artifact — parse failure yields null and the landing path
// simply carries no inspect_* params (honest absence, no fabrication).
//
// verify is DELIBERATELY not automated (§4.3): 通关判定 = 修复后新 Run 证据,
// PASS is the user's own walk. The zero-verify assertion lives in the tests.
import {
  createSession,
  diagnoseRun,
  getRun,
  getScenario,
  isApiError,
  listScenarios,
  startSession,
  submitRun,
  type DiagnosisReportDTO,
  type RunStatusDTO,
  type ScenarioDetailDTO,
} from "../../../api";
import { ApiError } from "../../../api/client";
import { buildCreateSessionBody } from "../../../features/lab/labBodies";
import { LAB_RUN_CONFIG } from "../../../features/lab/labGeometry";

const RUN_POLL_INTERVAL_MS = 200;
const RUN_POLL_DEADLINE_MS = 30_000;
const DIAGNOSE_404_RETRY_WINDOW_MS = 10_000;
const DIAGNOSE_404_RETRY_INTERVAL_MS = 100;

// ---------------------------------------------------------------------------
// Phase table (§7.4 order — spec authority; the prototype's `baseline` key is
// renamed `generate` and the terminal `land` phase is added per spec).
// ---------------------------------------------------------------------------

export type DemoPhaseKey =
  | "scenario"
  | "create"
  | "start"
  | "generate"
  | "inject"
  | "recover"
  | "diagnose"
  | "land";

export type DemoPhaseState = "pending" | "active" | "done" | "failed";

export interface DemoPhase {
  key: DemoPhaseKey;
  label: string;
  state: DemoPhaseState;
  detail?: string;
}

const DEMO_PHASE_DEFS: ReadonlyArray<{ key: DemoPhaseKey; label: string }> = [
  { key: "scenario", label: "取场景(SC-01 认识闭环)" },
  { key: "create", label: "创建会话(Create)" },
  { key: "start", label: "启动会话(Start)" },
  { key: "generate", label: "基线 Run(Generate,空 plan)" },
  { key: "inject", label: "注入 Run(Inject,场景 fault_plan)" },
  { key: "recover", label: "恢复 Run(Recover,空 plan)" },
  { key: "diagnose", label: "诊断注入 Run(Diagnose)" },
  { key: "land", label: "落地 Monitor(预锚定注入槽位)" },
];

export function initialDemoPhases(): DemoPhase[] {
  return DEMO_PHASE_DEFS.map((def) => ({ ...def, state: "pending" as const }));
}

export function markDemoPhase(
  phases: DemoPhase[],
  key: DemoPhaseKey,
  state: DemoPhaseState,
  detail?: string,
): DemoPhase[] {
  return phases.map((phase) => (phase.key === key ? { ...phase, state, detail } : phase));
}

/** One honest progress emission: the full row set + the session id once the
 * sandbox session exists (kept visible on failure — 已建会话保留可手动清理). */
export interface DemoProgress {
  phases: DemoPhase[];
  sessionId: string | null;
}

export interface DemoInspectLocator {
  artifact_id: string;
  pid: number;
  packet_index: number;
}

export interface DemoSessionResult {
  sessionId: string;
  scenarioTitle: string;
  /** Real locator triple into the faulted stream (packet inspector seed);
   * null when the scenario/plan shape defies parsing (honest absence). */
  inspectLocator: DemoInspectLocator | null;
  /** Phase rows at return: everything through `diagnose` done, `land` still
   * "active" — the caller marks it done after navigation lands. */
  phases: DemoPhase[];
}

/** The header demo-bar state (AppShell-owned React state + callbacks — zero
 * new dependencies, zero global state library, SPEC-400 discipline). null on
 * the shell = no demo period. A created session id is KEPT on failure so the
 * 已建会话保留可手动清理 semantics hold. */
export interface DemoSessionState {
  status: "orchestrating" | "landed" | "failed";
  phases: DemoPhase[];
  sessionId: string | null;
  scenarioTitle: string | null;
  inspectLocator: DemoInspectLocator | null;
}

// ---------------------------------------------------------------------------
// Engine
// ---------------------------------------------------------------------------

type PhaseSetter = (key: DemoPhaseKey, state: DemoPhaseState, detail?: string) => void;

/** Run one phase with active/failed row marking; the caller marks done. */
async function runPhase<T>(key: DemoPhaseKey, setPhase: PhaseSetter, fn: () => Promise<T>): Promise<T> {
  setPhase(key, "active");
  try {
    return await fn();
  } catch (error) {
    const message =
      isApiError(error)
        ? `${error.errorCode}: ${error.message}`
        : error instanceof Error
          ? error.message
          : String(error);
    setPhase(key, "failed", message);
    throw error instanceof Error ? error : new Error(message);
  }
}

/** Submit one run (frozen golden geometry — LAB_RUN_CONFIG imported, never
 * re-copied) and poll 200ms to `completed`; 30s window, explicit failures. */
export async function runAndWait(sessionId: string, faultPlan: ReadonlyArray<unknown>): Promise<RunStatusDTO> {
  const accepted = await submitRun(sessionId, {
    config: LAB_RUN_CONFIG as unknown as Parameters<typeof submitRun>[1]["config"],
    fault_plan: faultPlan as Parameters<typeof submitRun>[1]["fault_plan"],
  });
  const deadline = Date.now() + RUN_POLL_DEADLINE_MS;
  for (;;) {
    const status = await getRun(sessionId, accepted.run_id);
    if (status.status !== "running") {
      if (status.status !== "completed") {
        throw new Error(`run ${accepted.run_id} 终态 ${status.status}(期望 completed)`);
      }
      return status;
    }
    if (Date.now() >= deadline) {
      throw new Error("轮询超窗(30s):run 未在窗口内完成");
    }
    await new Promise((resolve) => setTimeout(resolve, RUN_POLL_INTERVAL_MS));
  }
}

/** Diagnose on the injected run: 404-until-drained retry window (the report
 * becomes answerable once the pump committed the run's terminal events). */
async function diagnoseFaultedRun(sessionId: string, faultedRunId: string): Promise<DiagnosisReportDTO> {
  const deadline = Date.now() + DIAGNOSE_404_RETRY_WINDOW_MS;
  for (;;) {
    try {
      return await diagnoseRun(sessionId, faultedRunId);
    } catch (error) {
      if (error instanceof ApiError && error.status === 404 && Date.now() < deadline) {
        await new Promise((resolve) => setTimeout(resolve, DIAGNOSE_404_RETRY_INTERVAL_MS));
        continue;
      }
      throw error;
    }
  }
}

/** Pre-anchor resolution (SC-01 = faulted_ts · PID 0 · packet 202): the
 * faulted_ts artifact from the injected run + `fault_plan[0]`'s declared
 * target (hex PID inside `target_id`) + activation packet slot. Any missing
 * piece → null (the landing path then carries no inspect_* params). */
export function resolveInspectLocator(
  scenarioDetail: ScenarioDetailDTO,
  faultedRun: RunStatusDTO,
): DemoInspectLocator | null {
  const plan0 = (scenarioDetail.fault_plan ?? [])[0] as
    | { activation?: { kind?: string; packet_index?: number | null }; target_id?: string }
    | undefined;
  const faultedArtifact = (faultedRun.artifacts ?? []).find((artifact) => artifact.kind === "faulted_ts");
  const packetIndex = plan0?.activation?.packet_index;
  const pidHex = /0x([0-9a-fA-F]+)/.exec(plan0?.target_id ?? "")?.[1];
  if (faultedArtifact === undefined || typeof packetIndex !== "number" || pidHex === undefined) {
    return null;
  }
  return {
    artifact_id: faultedArtifact.artifact_id,
    pid: Number.parseInt(pidHex, 16),
    packet_index: packetIndex,
  };
}

/** `/monitor?session=<id>` + the inspect_* deep-link triple ONLY when the
 * locator resolved (解析失败不带参数 — 诚实缺省). */
export function buildDemoLandingPath(sessionId: string, locator: DemoInspectLocator | null): string {
  const params = new URLSearchParams({ session: sessionId });
  if (locator !== null) {
    params.set("inspect_artifact", locator.artifact_id);
    params.set("inspect_pid", String(locator.pid));
    params.set("inspect_packet", String(locator.packet_index));
  }
  return `/monitor?${params.toString()}`;
}

export async function orchestrateDemoSession(
  onProgress: (progress: DemoProgress) => void,
): Promise<DemoSessionResult> {
  let phases = initialDemoPhases();
  let sessionId: string | null = null;
  const emit = () => onProgress({ phases, sessionId });
  const setPhase: PhaseSetter = (key, state, detail) => {
    phases = markDemoPhase(phases, key, state, detail);
    emit();
  };
  emit();

  // 1. scenario: the library is filename-ASC, so the introductory SC-01 is
  //    first — deterministic teaching material.
  const scenarioDetail: ScenarioDetailDTO = await runPhase("scenario", setPhase, async () => {
    const summaries = await listScenarios();
    if (summaries.length === 0) throw new Error("场景注册表为空(需 Lab Pack 落位)");
    return getScenario(summaries[0]!.scenario_id);
  });
  setPhase("scenario", "done", scenarioDetail.title);

  // 2-3. session two-hop (create 201 ready → start running — the runs face
  //      requires RUNNING; same assertions as the Lab §7.1 orchestration).
  sessionId = await runPhase("create", setPhase, async () => {
    const created = await createSession(buildCreateSessionBody(scenarioDetail));
    if (created.lifecycle !== "ready") {
      throw new Error(`开局异常:create 应答 lifecycle=${created.lifecycle}(期望 ready)`);
    }
    return created.session_id;
  });
  setPhase("create", "done", sessionId);
  emit();

  await runPhase("start", setPhase, async () => {
    const started = await startSession(sessionId!);
    if (started.lifecycle !== "running") {
      throw new Error(`开局异常:start 应答 lifecycle=${started.lifecycle}(期望 running)`);
    }
    return started;
  });
  setPhase("start", "done");

  // 4-6. the three golden-geometry runs (real bytes, real artifacts).
  const faultPlan = (scenarioDetail.fault_plan ?? []) as ReadonlyArray<unknown>;
  const generateRun = await runPhase("generate", setPhase, () => runAndWait(sessionId!, []));
  setPhase("generate", "done", `${generateRun.packet_count ?? "?"} packets`);

  const faultedRun = await runPhase("inject", setPhase, () => runAndWait(sessionId!, faultPlan));
  setPhase("inject", "done", faultedRun.run_id);

  const recoverRun = await runPhase("recover", setPhase, () => runAndWait(sessionId!, []));
  setPhase("recover", "done", recoverRun.run_id);

  // 7. diagnose on the injected run so Monitor lands with root-cause
  //    candidates + evidence deep links.
  const report = await runPhase("diagnose", setPhase, () => diagnoseFaultedRun(sessionId!, faultedRun.run_id));
  setPhase("diagnose", "done", `${report.candidates.length} candidates · ${faultedRun.run_id}`);

  // 8. land (hand-off): the module computes the landing payload and marks
  //    the row active; the CALLER navigates + hosts the demo bar and marks
  //    it done. The locator stays null on parse failure — the landing path
  //    then honestly carries no inspect_* params.
  const inspectLocator = resolveInspectLocator(scenarioDetail, faultedRun);
  setPhase(
    "land",
    "active",
    inspectLocator === null
      ? "跳转 Monitor(预锚定解析缺省:不带 inspect_* 参数)"
      : `跳转 Monitor(预锚定 PID ${inspectLocator.pid} · packet ${inspectLocator.packet_index})`,
  );

  return { sessionId, scenarioTitle: scenarioDetail.title, inspectLocator, phases };
}
