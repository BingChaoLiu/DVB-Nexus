// Experiment console opening + verify-form package (SPEC-408 §4.4/§7.3/§7.5,
// AC-408-07; Lab verify 同口径 per orchestrator ruling on §4.3 L113 + §6.4):
// - the auto-baseline declaration note (REAL data, next step inject) renders
//   ABOVE the Stepper only when initialRuns carried a hop-3 run in;
// - the §4.6 Lab 组 honest empty states: run-registry fallback copy, the
//   diagnose-section empty copy, and the zero-journal-events copy;
// - the verify face is an EDITABLE PREFILL FORM: scenario identity
//   (scenario_id/version/content_hash) prefills from the scenario detail's
//   REAL pinned hash (the lab-ui-unpinned declared marker is RETIRED),
//   baseline/recovery run ids are NEVER auto-guessed (empty until the user
//   picks — zero verify requests before that), candidates come from the
//   console's run registry as a datalist, and the submit stays gated until
//   every field holds a value. jsdom mock-seam walks; live composition is
//   E2E's job (#101).
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  DiagnosisDTO,
  RunAcceptedDTO,
  RunListItemDTO,
  RunStatusDTO,
  ScenarioDetailDTO,
  SnapshotDTO,
  VerificationResultDTO,
} from "../../api";

vi.mock("../../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api")>();
  return {
    ...actual,
    getScenario: vi.fn(),
    getSnapshot: vi.fn(),
    queryEvents: vi.fn(),
    listDiagnoses: vi.fn(),
    listSessionRuns: vi.fn(),
    submitRun: vi.fn(),
    getRun: vi.fn(),
    verifyRun: vi.fn(),
  };
});

import {
  getRun,
  getScenario,
  getSnapshot,
  listDiagnoses,
  listSessionRuns,
  queryEvents,
  submitRun,
  verifyRun,
} from "../../api";
import { ExperimentConsole } from "./ExperimentConsole";

const mocked = {
  getScenario: vi.mocked(getScenario),
  getSnapshot: vi.mocked(getSnapshot),
  queryEvents: vi.mocked(queryEvents),
  listDiagnoses: vi.mocked(listDiagnoses),
  listSessionRuns: vi.mocked(listSessionRuns),
  submitRun: vi.mocked(submitRun),
  getRun: vi.mocked(getRun),
  verifyRun: vi.mocked(verifyRun),
};

const SCENARIO: ScenarioDetailDTO = {
  schema_version: "1.0",
  scenario_id: "5c010000-0000-4000-8000-000000000001",
  version: "1.0.0",
  content_hash: "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  title: "CC 不连续训练",
  difficulty: "intro",
  initial_topology: {},
  simulation_config: {},
  fault_plan: [{ fault_id: "fd000000-0000-4000-8000-00000000f103" }],
  objectives: [],
  hints: [],
  pass_criteria: [{ criterion_id: "cc-ok", kind: "fault_inactive", mandatory: true }],
};

const submitted = new Map<string, boolean>();
let runSeq = 0;

function setupApiMocks() {
  submitted.clear();
  runSeq = 0;
  mocked.getScenario.mockResolvedValue(SCENARIO);
  mocked.getSnapshot.mockImplementation(async (sessionId) =>
    ({
      session_id: sessionId,
      revision: 1,
      lifecycle: "running",
      virtual_time_ns: 0,
      topology_revision: 1,
    }) satisfies SnapshotDTO,
  );
  mocked.queryEvents.mockResolvedValue({ data: { items: [], total: 0 } } as never);
  mocked.listDiagnoses.mockResolvedValue([] satisfies DiagnosisDTO[]);
  mocked.listSessionRuns.mockResolvedValue([] satisfies RunListItemDTO[]);
  mocked.submitRun.mockImplementation(async (_sessionId, body) => {
    runSeq += 1;
    submitted.set(`run-${runSeq}`, (body.fault_plan ?? []).length > 0);
    return { run_id: `run-${runSeq}`, config_hash: "h", status: "running" } satisfies RunAcceptedDTO;
  });
  mocked.getRun.mockImplementation(async (_sessionId, runId) => {
    const faulted = submitted.get(runId) ?? false;
    return {
      run_id: runId,
      status: "completed",
      artifacts: [
        {
          artifact_id: `${runId}-ts`,
          kind: faulted ? "faulted_ts" : "generated_ts",
          sha256: "ab",
          byte_size: 1880,
          partial: false,
        },
      ],
    } satisfies RunStatusDTO;
  });
  mocked.verifyRun.mockImplementation(async (sessionId, recoveryRunId, body) =>
    ({
      session_id: sessionId,
      recovery_run_id: recoveryRunId,
      baseline_run_id: body.baseline_run_id,
      scenario: body.scenario,
      verdict: "PASS",
      criteria: [{ criterion_id: "cc-ok", kind: "fault_inactive", mandatory: true, result: "pass" }],
      summary: "全部强制判据通过",
      verified_at_utc_ms: 1_700_000_000_000,
    }) satisfies VerificationResultDTO,
  );
}

function renderConsole(initialRuns?: ReadonlyArray<RunStatusDTO>) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(
    [
      {
        path: "/lab",
        element: <ExperimentConsole scenarioId={SCENARIO.scenario_id} sessionId="s-1" onBack={() => {}} initialRuns={initialRuns} />,
      },
    ],
    { initialEntries: ["/lab"] },
  );
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  setupApiMocks();
});

describe("ExperimentConsole — auto-baseline declaration note (§4.4/§7.3)", () => {
  it("renders the standing note ABOVE the Stepper when an auto run was carried in, with the verbatim declaration + inject signpost", async () => {
    renderConsole([{ run_id: "run-auto", status: "running", artifacts: [] } as RunStatusDTO]);
    const note = await screen.findByTestId("lab-autorun-note", {}, { timeout: 3_000 });
    expect(note).toHaveTextContent("开局已自动提交基线 Run——真实沙盘数据，非示例");
    expect(note).toHaveTextContent("下一步：注入故障");
    // ABOVE the Stepper (declaration → stepper → guidance bar ordering).
    const stepper = screen.getByTestId("lab-stepper");
    expect(note.compareDocumentPosition(stepper) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("renders no note without a carried auto run (deep link / fallback posture)", async () => {
    renderConsole();
    await screen.findByTestId("lab-action-guide", {}, { timeout: 3_000 });
    expect(screen.queryByTestId("lab-autorun-note")).not.toBeInTheDocument();
  });
});

describe("ExperimentConsole — §4.6 Lab 组 honest empty states", () => {
  it("empty run registry + empty §6.3 list speak the fallback copy verbatim (自动基线未成功 → 回落手动流程)", async () => {
    renderConsole();
    // The fallback note may only render AFTER the §6.3 list confirmed
    // emptiness (F1) — await the note itself, not the section title (the
    // loading face shares the title while the fetch is in flight).
    expect(
      await screen.findByText(
        "本会话尚未触发任何 Run（开局自动基线未成功，回落手动流程，诚实态）。下一步：点击『生成基线（Generate，空 plan）』",
        {},
        { timeout: 3_000 },
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("尚无 Run")).toBeInTheDocument();
  });

  it("diagnose section renders its empty copy before any diagnose (新增 §4.6 行 4)", async () => {
    renderConsole();
    const empty = await screen.findByTestId("lab-diagnose-empty", {}, { timeout: 3_000 });
    expect(empty).toHaveTextContent("尚无诊断报告");
    expect(empty).toHaveTextContent(
      "诊断不自动发生：注入 Run 完成后点击『对注入 Run 评估（diagnose）』；无观测 ≠ 干净，空表是诚实态",
    );
  });

  it("zero journal events render their empty copy (新增 §4.6 行 5)", async () => {
    renderConsole();
    const empty = await screen.findByTestId("lab-events-empty", {}, { timeout: 3_000 });
    expect(empty).toHaveTextContent("暂无 journal 事件");
    expect(empty).toHaveTextContent("会话已建立但引擎尚未产生事件（空 ≠ 错误）。下一步：触发一个 Run 后回来查看");
  });
});

// §6.3 run-list reconstruction (SPEC-408 §7.5 Monitor 与 Lab 同口径;
// review-fix F1): on refresh/deep-link the opening hop's carrier is empty —
// the mount-time GET /sessions/{id}/runs fetch honestly rebuilds the facts
// face (rows, steps, note, datalist) from server facts, never fabricated
// artifacts, and the §4.6 fallback copy stays gated on BOTH faces empty.
describe("ExperimentConsole — §6.3 run-list reconstruction (refresh/deep-link honesty, F1)", () => {
  const listRow = (over: { run_id: string } & Partial<RunListItemDTO>): RunListItemDTO => ({
    status: "completed",
    submitted_at_ms: 1_700_000_000_000,
    fault_plan_present: false,
    ...over,
  });

  it("rebuilds rows + steps + note from the server list (no initialRuns carrier); NO pseudo artifact chips", async () => {
    // Real-session shape: the opening auto-baseline (empty plan) is the FIRST
    // §6.3 row; the injected run follows it.
    mocked.listSessionRuns.mockResolvedValue([
      listRow({ run_id: "srv-baseline", submitted_at_ms: 1_000, fault_plan_present: false, packet_count: 500 }),
      listRow({ run_id: "srv-inject", submitted_at_ms: 2_000, fault_plan_present: true, packet_count: 600 }),
    ]);
    renderConsole();

    await screen.findByTestId("lab-run-row-srv-baseline", {}, { timeout: 3_000 });
    expect(screen.getByTestId("lab-run-row-srv-inject")).toBeInTheDocument();
    // The §6.3 face carries NO artifact list — no fabricated chips.
    expect(screen.getByTestId("lab-run-row-srv-inject").textContent).not.toContain("faulted_ts");
    // The §7.3 declaration note rides the reconstructed opening baseline
    // (first list row = empty plan), not just the hop carrier.
    expect(await screen.findByTestId("lab-autorun-note", {}, { timeout: 3_000 })).toHaveTextContent(
      "开局已自动提交基线 Run",
    );
    // Steps light from the list facts (fault_plan_present → inject; empty plan → generate).
    await waitFor(() => expect(screen.getByTestId("lab-step-inject")).toHaveTextContent("注入完成"), {
      timeout: 3_000,
    });
    expect(screen.getByTestId("lab-step-generate")).toHaveTextContent("基线完成");
    // Datalist = registry ⊕ server list, dedup, submitted_at ASC (§7.5 同口径).
    const options = [...(document.getElementById("lab-verify-run-candidates")?.getElementsByTagName("option") ?? [])].map(
      (option) => option.value,
    );
    expect(options).toEqual(["srv-baseline", "srv-inject"]);
  });

  it("a running §6.3 row joins the 200ms poller and gains its REAL face (artifact chip) on completion", async () => {
    mocked.listSessionRuns.mockResolvedValue([
      listRow({ run_id: "srv-running", status: "running", fault_plan_present: true }),
    ]);
    mocked.getRun.mockResolvedValue({
      run_id: "srv-running",
      status: "completed",
      artifacts: [
        { artifact_id: "srv-running-ts", kind: "faulted_ts", sha256: "ab", byte_size: 1880, partial: false },
      ],
    } satisfies RunStatusDTO);
    renderConsole();

    await screen.findByTestId("lab-run-row-srv-running", {}, { timeout: 3_000 });
    // No chip before the poll answer (honest absence).
    expect(screen.getByTestId("lab-run-row-srv-running").textContent).not.toContain("faulted_ts");
    await waitFor(() => expect(screen.getByTestId("lab-run-row-srv-running")).toHaveTextContent("completed"), {
      timeout: 3_000,
    });
    // The REAL poll answer fills the true artifact face.
    expect(screen.getByTestId("lab-run-row-srv-running").textContent).toContain("faulted_ts");
    await waitFor(() => expect(screen.getByTestId("lab-step-inject")).toHaveTextContent("注入完成"), {
      timeout: 3_000,
    });
    expect(mocked.getRun).toHaveBeenCalledWith("s-1", "srv-running");
  });

  it("a failed §6.3 fetch NEVER speaks the §4.6 fallback copy (失败 ≠ 空库)", async () => {
    mocked.listSessionRuns.mockRejectedValue(new Error("network down"));
    renderConsole();

    await screen.findByTestId("lab-runlist-error", {}, { timeout: 3_000 });
    expect(screen.getByTestId("lab-runlist-error").textContent).toContain("失败 ≠ 空库");
    expect(screen.getByTestId("lab-runlist-error").textContent).toContain("start.cmd");
    expect(
      screen.queryByText(/开局自动基线未成功，回落手动流程/),
    ).not.toBeInTheDocument();
  });

  it("while the §6.3 fetch is in flight the empty face is the loading face, not the fallback", async () => {
    mocked.listSessionRuns.mockReturnValue(new Promise(() => {}));
    renderConsole();

    await screen.findByTestId("lab-runlist-loading", {}, { timeout: 3_000 });
    expect(screen.queryByText(/开局自动基线未成功，回落手动流程/)).not.toBeInTheDocument();
  });
});

describe("ExperimentConsole — verify editable prefill form (§7.5 同口径)", () => {
  it("prefills scenario identity from the detail's REAL pinned hash; run ids stay EMPTY (never auto-guessed) and submit is gated", async () => {
    renderConsole();
    await screen.findByTestId("lab-action-guide", {}, { timeout: 3_000 });

    // Identity prefills (editable inputs) from the scenario detail.
    const scenarioInput = screen.getByLabelText("scenario_id") as HTMLInputElement;
    const versionInput = screen.getByLabelText("version") as HTMLInputElement;
    const hashInput = screen.getByLabelText("content_hash") as HTMLInputElement;
    await waitFor(() => expect(scenarioInput.value).toBe("5c010000-0000-4000-8000-000000000001"));
    await waitFor(() => expect(versionInput.value).toBe("1.0.0"));
    await waitFor(() =>
      expect(hashInput.value).toBe("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"),
    );
    // REAL hash — the declared marker is retired.
    expect(hashInput.value).not.toBe("lab-ui-unpinned");

    // Run ids are NOT derived (never auto-guessed): empty editable inputs,
    // and the submit gate holds.
    const baselineInput = screen.getByLabelText("baseline_run_id") as HTMLInputElement;
    const recoveryInput = screen.getByLabelText("recovery_run_id") as HTMLInputElement;
    expect(baselineInput.value).toBe("");
    expect(recoveryInput.value).toBe("");
    const submit = screen.getByRole("button", { name: "提交判定（verify）" });
    expect(submit).toBeDisabled();

    // Walk the whole poller to completion with the walk buttons — still no
    // verify request (提交不因 run 齐备而自动发生).
    const user = userEvent.setup();
    for (const name of ["生成基线（Generate，空 plan）", "注入故障（Inject，场景 fault_plan）", "恢复重跑（Recover，空 plan）"]) {
      await user.click(screen.getByRole("button", { name }));
    }
    await waitFor(() => expect(screen.getByTestId("lab-run-row-run-3")).toHaveTextContent("completed"), {
      timeout: 3_000,
    });
    expect(mocked.verifyRun).not.toHaveBeenCalled();
    expect(submit).toBeDisabled();
  });

  it("datalist candidates come from the console's run registry (…/#95 未合入前的本地数据源)", async () => {
    const user = userEvent.setup();
    renderConsole();
    await screen.findByTestId("lab-action-guide", {}, { timeout: 3_000 });
    await user.click(screen.getByRole("button", { name: "注入故障（Inject，场景 fault_plan）" }));
    await waitFor(() => expect(screen.getByTestId("lab-run-row-run-1")).toHaveTextContent("completed"), {
      timeout: 3_000,
    });
    const datalist = document.getElementById("lab-verify-run-candidates");
    expect(datalist).not.toBeNull();
    const options = [...(datalist?.getElementsByTagName("option") ?? [])].map((option) => option.value);
    expect(options).toContain("run-1");
  });

  it("a fully filled form submits the real identity + form-chosen run ids; criteria pass through verbatim", async () => {
    const user = userEvent.setup();
    renderConsole();
    await screen.findByTestId("lab-action-guide", {}, { timeout: 3_000 });

    // Produce two completed runs (clean + faulted) so the datalist has rows.
    await user.click(screen.getByRole("button", { name: "生成基线（Generate，空 plan）" }));
    await user.click(screen.getByRole("button", { name: "注入故障（Inject，场景 fault_plan）" }));
    await waitFor(() => expect(screen.getByTestId("lab-run-row-run-2")).toHaveTextContent("completed"), {
      timeout: 3_000,
    });

    const submit = screen.getByRole("button", { name: "提交判定（verify）" });
    expect(submit).toBeDisabled();
    await user.type(screen.getByLabelText("baseline_run_id"), "run-2");
    await user.type(screen.getByLabelText("recovery_run_id"), "run-1");
    expect(submit).toBeEnabled();
    await user.click(submit);

    await waitFor(() => expect(mocked.verifyRun).toHaveBeenCalledTimes(1));
    const [sessionId, recoveryRunId, body] = mocked.verifyRun.mock.calls[0] ?? [];
    expect(sessionId).toBe("s-1");
    expect(recoveryRunId).toBe("run-1");
    expect(body.baseline_run_id).toBe("run-2");
    expect(body.scenario).toEqual({
      scenario_id: "5c010000-0000-4000-8000-000000000001",
      version: "1.0.0",
      content_hash: "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    });
    expect(body.pass_criteria).toEqual(SCENARIO.pass_criteria);
    expect(JSON.stringify(body)).not.toContain("lab-ui-unpinned");
    expect(Object.keys(body)).not.toContain("ui_state");
    expect(await screen.findByTestId("verify-verdict", {}, { timeout: 3_000 })).toHaveTextContent("PASS");
  });
});
