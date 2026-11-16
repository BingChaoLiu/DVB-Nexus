// PROTOTYPE (issue #87, variant A): the demo-session orchestration. Runs a
// REAL backend pipeline over existing endpoints only (zero backend delta —
// that is part of what this variant demonstrates): scenario session two-hop
// (SPEC-406 §7.1) → three runs (baseline / faulted / recovery, frozen golden
// geometry) → diagnose on the faulted run. Every byte of data the reviewer
// then sees on Monitor is genuinely sandbox-generated (source/confidence
// axes untouched — honesty discipline holds by construction).
//
// The verify step is deliberately NOT automated: 通关判定 = 修复后新 Run 证据,
// and the point of the journey is that the engineer walks it themselves.
import {
  createSession,
  diagnoseRun,
  getRun,
  getScenario,
  isApiError,
  listScenarios,
  startSession,
  submitRun,
  type ScenarioDetailDTO,
} from "../../api";
import { ApiError } from "../../api/client";
import { buildCreateSessionBody } from "../../features/lab/labBodies";
import { LAB_RUN_CONFIG } from "../../features/lab/labGeometry";

const RUN_POLL_INTERVAL_MS = 200;
const RUN_POLL_DEADLINE_MS = 30_000;
const DIAGNOSE_404_RETRY_WINDOW_MS = 10_000;
const DIAGNOSE_404_RETRY_INTERVAL_MS = 100;

export type DemoStepState = "pending" | "active" | "done" | "failed";

export interface DemoStep {
  key: string;
  label: string;
  state: DemoStepState;
  detail?: string;
}

const STEP_DEFS: ReadonlyArray<{ key: string; label: string }> = [
  { key: "scenario", label: "取场景文档(SC-01 认识闭环)" },
  { key: "create", label: "创建会话(Create)" },
  { key: "start", label: "启动会话" },
  { key: "baseline", label: "基线 Run(Generate)" },
  { key: "inject", label: "注入 Run(Inject)" },
  { key: "recover", label: "恢复 Run(Recover)" },
  { key: "diagnose", label: "诊断注入 Run(Diagnose)" },
];

export function initialDemoSteps(): DemoStep[] {
  return STEP_DEFS.map((def) => ({ ...def, state: "pending" as const }));
}

type Progress = (steps: DemoStep[]) => void;

type StepSetter = (key: string, state: DemoStepState, detail?: string) => void;

function mark(steps: DemoStep[], key: string, state: DemoStepState, detail?: string): DemoStep[] {
  return steps.map((step) => (step.key === key ? { ...step, state, detail } : step));
}

/** Run one phase with active/failed step marking; the caller marks done. */
async function phase<T>(key: string, setStep: StepSetter, fn: () => Promise<T>): Promise<T> {
  setStep(key, "active");
  try {
    return await fn();
  } catch (error) {
    const message =
      isApiError(error)
        ? `${error.errorCode}: ${error.message}`
        : error instanceof Error
          ? error.message
          : String(error);
    setStep(key, "failed", message);
    throw error instanceof Error ? error : new Error(message);
  }
}

type RunStatusLike = Awaited<ReturnType<typeof getRun>>;

/** Submit one run (frozen golden geometry) and poll to a terminal state. */
async function runAndWait(sessionId: string, faultPlan: ReadonlyArray<unknown>): Promise<RunStatusLike> {
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

export interface DemoSessionResult {
  sessionId: string;
  scenarioTitle: string;
  /** Real locator triple into the faulted stream (packet inspector seed);
   * null when the scenario/plan shape defies parsing (honest absence). */
  inspectLocator: { artifact_id: string; pid: number; packet_index: number } | null;
}

export async function orchestrateDemoSession(onProgress: Progress): Promise<DemoSessionResult> {
  let steps = initialDemoSteps();
  const setStep: StepSetter = (key, state, detail) => {
    steps = mark(steps, key, state, detail);
    onProgress(steps);
  };
  onProgress(steps);

  // 1. scenario: the library is filename-ASC, so the introductory SC-01 is
  //    first — deterministic teaching material.
  const scenarioDetail: ScenarioDetailDTO = await phase("scenario", setStep, async () => {
    const summaries = await listScenarios();
    if (summaries.length === 0) throw new Error("场景注册表为空(需 Lab Pack 落位)");
    return getScenario(summaries[0]!.scenario_id);
  });
  setStep("scenario", "done", scenarioDetail.title);

  // 2-3. session two-hop (create 201 ready → start running; the runs face
  //      requires RUNNING — same assertions as the Lab §7.1 orchestration).
  const sessionId = await phase("create", setStep, async () => {
    const created = await createSession(buildCreateSessionBody(scenarioDetail));
    if (created.lifecycle !== "ready") {
      throw new Error(`开局异常:create 应答 lifecycle=${created.lifecycle}(期望 ready)`);
    }
    return created.session_id;
  });
  setStep("create", "done", sessionId);
  await phase("start", setStep, async () => {
    const started = await startSession(sessionId);
    if (started.lifecycle !== "running") {
      throw new Error(`开局异常:start 应答 lifecycle=${started.lifecycle}(期望 running)`);
    }
    return started;
  });
  setStep("start", "done");

  // 4-6. the three golden-geometry runs (real bytes, real artifacts).
  const faultPlan = (scenarioDetail.fault_plan ?? []) as ReadonlyArray<unknown>;
  const baselineRun = await phase("baseline", setStep, () => runAndWait(sessionId, []));
  setStep("baseline", "done", `${baselineRun.packet_count ?? "?"} packets`);

  const faultedRun = await phase("inject", setStep, () => runAndWait(sessionId, faultPlan));
  setStep("inject", "done", faultedRun.run_id);

  const recoverRun = await phase("recover", setStep, () => runAndWait(sessionId, []));
  setStep("recover", "done", recoverRun.run_id);

  // 7. diagnose on the faulted run so the Monitor deck lands with root-cause
  //    candidates + evidence deep links (404-until-drained, same posture as
  //    the Monitor diagnose bar).
  const report = await phase("diagnose", setStep, async () => {
    const deadline = Date.now() + DIAGNOSE_404_RETRY_WINDOW_MS;
    for (;;) {
      try {
        return await diagnoseRun(sessionId, faultedRun.run_id);
      } catch (error) {
        if (error instanceof ApiError && error.status === 404 && Date.now() < deadline) {
          await new Promise((resolve) => setTimeout(resolve, DIAGNOSE_404_RETRY_INTERVAL_MS));
          continue;
        }
        throw error;
      }
    }
  });
  setStep("diagnose", "done", `${report.candidates.length} candidates · ${faultedRun.run_id}`);

  // Seed the packet inspector with the REAL fault locus: the faulted_ts
  // artifact + the scenario's activation (packet slot + target PID hex).
  const plan0 = (scenarioDetail.fault_plan ?? [])[0] as
    | { activation?: { kind?: string; packet_index?: number }; target_id?: string }
    | undefined;
  let inspectLocator: DemoSessionResult["inspectLocator"] = null;
  const faultedArtifact = (faultedRun.artifacts ?? []).find((a) => a.kind === "faulted_ts");
  const packetIndex = plan0?.activation?.packet_index;
  const pidHex = /0x([0-9a-fA-F]+)/.exec(plan0?.target_id ?? "")?.[1];
  if (faultedArtifact !== undefined && typeof packetIndex === "number" && pidHex !== undefined) {
    inspectLocator = { artifact_id: faultedArtifact.artifact_id, pid: Number.parseInt(pidHex, 16), packet_index: packetIndex };
  }

  return { sessionId, scenarioTitle: scenarioDetail.title, inspectLocator };
}
