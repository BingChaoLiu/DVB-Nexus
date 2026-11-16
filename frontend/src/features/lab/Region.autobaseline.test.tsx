// LabRegion opening auto-baseline third hop (SPEC-408 §4.4/§7.3, AC-408-07):
// the §7.1 two-hop orchestration (create ready → start running) gains a THIRD
// hop — an empty-plan baseline run with the FROZEN golden geometry
// (LAB_RUN_CONFIG import, never a re-copy) is auto-submitted before the
// console navigation; the console opens with the run already in its registry
// (props-carried initialRuns) and the 200ms poller drives it to completion
// (Generate lights by itself). ANY hop-3 failure is a SILENT fallback: the
// console still opens, nothing fakes success, and the empty registry speaks
// the §4.6 fallback copy honestly. Walks driven through mocked api seams
// (jsdom has no backend); live composition is E2E's job (#101).
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  DiagnosisDTO,
  RunAcceptedDTO,
  RunStatusDTO,
  ScenarioDetailDTO,
  SnapshotDTO,
} from "../../api";

vi.mock("../../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api")>();
  return {
    ...actual,
    createSession: vi.fn(),
    startSession: vi.fn(),
    getScenario: vi.fn(),
    getSnapshot: vi.fn(),
    queryEvents: vi.fn(),
    listDiagnoses: vi.fn(),
    listSessionRuns: vi.fn(),
    submitRun: vi.fn(),
    getRun: vi.fn(),
  };
});

import { LAB_RUN_CONFIG } from "./labGeometry";
import {
  createSession,
  getRun,
  getScenario,
  getSnapshot,
  listDiagnoses,
  listSessionRuns,
  queryEvents,
  startSession,
  submitRun,
} from "../../api";
import type { RunListItemDTO } from "../../api";
import LabRegion from "./Region";

const mocked = {
  createSession: vi.mocked(createSession),
  startSession: vi.mocked(startSession),
  getScenario: vi.mocked(getScenario),
  getSnapshot: vi.mocked(getSnapshot),
  queryEvents: vi.mocked(queryEvents),
  listDiagnoses: vi.mocked(listDiagnoses),
  listSessionRuns: vi.mocked(listSessionRuns),
  submitRun: vi.mocked(submitRun),
  getRun: vi.mocked(getRun),
};

const SID = "5c010000-0000-4000-8000-000000000001";

const SCENARIO: ScenarioDetailDTO = {
  schema_version: "1.0",
  scenario_id: SID,
  version: "1.0.0",
  content_hash: "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  title: "认识闭环：PAT 缺失",
  difficulty: "intro",
  initial_topology: {
    topology_id: "topo-1",
    revision: 1,
    nodes: [],
    connections: [],
  },
  simulation_config: {
    seed: 1234567,
    mode: "deterministic",
    clock: { mode: "deterministic", start_time_ns: 0, speed_num: 1, speed_den: 1, tick_quantum_ns: 1000000 },
  },
  fault_plan: [{ fault_id: "fd000000-0000-4000-8000-00000000f1a1" }],
  objectives: [],
  hints: [],
  pass_criteria: [{ criterion_id: "fault-cleared" }],
};

/** Runs submitted through the mocked seam, remembered for getRun answers. */
const submitted = new Map<string, boolean>();
let runSeq = 0;

function setupApiMocks() {
  submitted.clear();
  runSeq = 0;
  mocked.getScenario.mockResolvedValue(SCENARIO);
  mocked.createSession.mockResolvedValue({
    session_id: "s-new",
    revision: 1,
    lifecycle: "ready",
    virtual_time_ns: 0,
    topology_revision: 1,
  });
  mocked.startSession.mockResolvedValue({
    session_id: "s-new",
    revision: 1,
    lifecycle: "running",
    virtual_time_ns: 0,
    topology_revision: 1,
  });
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
  mocked.submitRun.mockImplementation(async (sessionId, body) => {
    expect(sessionId).toBe("s-new");
    submitted.set(`run-${runSeq + 1}`, (body.fault_plan ?? []).length > 0);
    runSeq += 1;
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
}

function renderLab(initialPath: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter([{ path: "/lab", element: <LabRegion /> }], { initialEntries: [initialPath] });
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { router };
}

beforeEach(() => {
  setupApiMocks();
});

async function openViaStart(user: ReturnType<typeof userEvent.setup>) {
  renderLab(`/lab?scenario=${SID}`);
  await user.click(await screen.findByRole("button", { name: "开始实验" }));
  await screen.findByTestId("lab-console-session", {}, { timeout: 3_000 });
}

describe("LabRegion — opening auto-baseline third hop (SPEC-408 §7.3)", () => {
  it("success path: submits an empty-plan baseline run with the frozen LAB_RUN_CONFIG, opens the console with it in the registry, and declares it", async () => {
    const user = userEvent.setup();
    await openViaStart(user);

    // The third hop fired: exactly one auto submit, empty plan, frozen config.
    expect(mocked.submitRun).toHaveBeenCalledTimes(1);
    const [submitSessionId, submitBody] = mocked.submitRun.mock.calls[0] ?? [];
    expect(submitSessionId).toBe("s-new");
    expect(submitBody?.fault_plan).toEqual([]);
    expect(submitBody?.config).toEqual(LAB_RUN_CONFIG);

    // The console opens ALREADY carrying the auto run in its registry.
    await waitFor(() => expect(screen.getByTestId("lab-run-row-run-1")).toBeInTheDocument(), { timeout: 3_000 });

    // The standing declaration note renders (REAL data, next step inject).
    const note = screen.getByTestId("lab-autorun-note");
    expect(note).toHaveTextContent("开局已自动提交基线 Run——真实沙盘数据，非示例");
    expect(note).toHaveTextContent("下一步：注入故障");

    // The poller takes over: the auto run completes and Generate lights up
    // by itself (never clicked 生成基线 in this walk).
    await waitFor(() => expect(screen.getByTestId("lab-run-row-run-1")).toHaveTextContent("completed"), {
      timeout: 3_000,
    });
    expect(screen.getByTestId("lab-step-generate")).toHaveTextContent("基线完成");

    // The fallback empty state never shows (the registry is NOT empty).
    expect(screen.queryByText("尚无 Run")).not.toBeInTheDocument();
  });

  it("failure path: hop-3 rejection is a SILENT fallback — the console still opens, nothing fakes success, the §4.6 empty-registry copy speaks", async () => {
    const user = userEvent.setup();
    mocked.submitRun.mockRejectedValue(new Error("backend refused"));
    await openViaStart(user);

    // 开局两跳 succeeded — the console opened; the failure did NOT surface as
    // a start error (静默回退) and no declaration note is rendered.
    expect(screen.getByTestId("lab-console-session")).toHaveTextContent("s-new");
    expect(screen.queryByTestId("lab-start-error")).not.toBeInTheDocument();
    expect(screen.queryByTestId("lab-autorun-note")).not.toBeInTheDocument();

    // The empty registry + the EMPTY §6.3 server list state the fallback
    // honestly (§4.6 Lab 组行 3 逐字; the copy awaits list confirmation — F1).
    expect(
      await screen.findByText(
        "本会话尚未触发任何 Run（开局自动基线未成功，回落手动流程，诚实态）。下一步：点击『生成基线（Generate，空 plan）』",
        {},
        { timeout: 3_000 },
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("尚无 Run")).toBeInTheDocument();

    // The pointer stays honest: Generate is still 待办 (no fake progress).
    expect(screen.getByTestId("lab-step-generate")).toHaveTextContent("待办");
  });
});
