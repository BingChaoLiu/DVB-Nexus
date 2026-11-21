// LabRegion cross-session reset (SPEC-406 §7.5 rule 4): a ?session= switch
// must remount the console — panels reset to unfetched and already-fetched
// text is discarded (session A's revealed reference solution must never
// render under session B). The full PASS→reveal walk is driven through
// mocked api seams at the Region boundary (jsdom has no backend); the live
// composition is the E2E suite's job on the real backend.
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
  ScenarioSolutionDTO,
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
    submitRun: vi.fn(),
    getRun: vi.fn(),
    verifyRun: vi.fn(),
    revealScenarioSolution: vi.fn(),
  };
});

import {
  getRun,
  getScenario,
  getSnapshot,
  listDiagnoses,
  queryEvents,
  revealScenarioSolution,
  submitRun,
  verifyRun,
} from "../../api";
import LabRegion from "./Region";

const mocked = {
  getScenario: vi.mocked(getScenario),
  getSnapshot: vi.mocked(getSnapshot),
  queryEvents: vi.mocked(queryEvents),
  listDiagnoses: vi.mocked(listDiagnoses),
  submitRun: vi.mocked(submitRun),
  getRun: vi.mocked(getRun),
  verifyRun: vi.mocked(verifyRun),
  revealScenarioSolution: vi.mocked(revealScenarioSolution),
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
  pass_criteria: [{ criterion_id: "cc-ok" }],
};

const SOLUTION_TEXT = "恢复路径：以空 fault_plan 重跑并复核 CC 连续（参考解文本，禁跨会话残留）。";

/** Runs submitted through the mocked seam, remembered so getRun answers the
 * terminal view immediately (artifact kind follows the submitted plan). */
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
  mocked.submitRun.mockImplementation(async (_sessionId, body) => {
    runSeq += 1;
    const runId = `run-${runSeq}`;
    submitted.set(runId, (body.fault_plan ?? []).length > 0);
    return { run_id: runId, config_hash: "h", status: "running" } satisfies RunAcceptedDTO;
  });
  mocked.getRun.mockImplementation(async (_sessionId, runId) => {
    const faulted = submitted.get(runId) ?? false;
    return {
      run_id: runId,
      status: "completed",
      fidelity: "SIM_TS",
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
      scenario: { scenario_id: SCENARIO.scenario_id, version: SCENARIO.version, content_hash: "hash" },
      verdict: "PASS",
      criteria: [{ criterion_id: "cc-ok", kind: "cc_continuous", mandatory: true, result: "pass" }],
      summary: "全部强制判据通过",
      verified_at_utc_ms: 1_700_000_000_000,
    }) satisfies VerificationResultDTO,
  );
  mocked.revealScenarioSolution.mockResolvedValue({
    scenario_id: SCENARIO.scenario_id,
    hidden_reference_solution: SOLUTION_TEXT,
  } satisfies ScenarioSolutionDTO);
}

function renderLab(initialPath: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const router = createMemoryRouter(
    [
      {
        path: "/lab",
        element: <LabRegion />,
      },
    ],
    { initialEntries: [initialPath] },
  );
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

describe("LabRegion — session switch reset (SPEC-406 §7.5 rule 4)", () => {
  it("switching ?session= resets the console: verdict/solution/run panels unfetched, session A text not leaked to session B", async () => {
    const user = userEvent.setup();
    const { router } = renderLab("/lab?scenario=5c010000-0000-4000-8000-000000000001&session=s-A");

    // --- session A: walk Generate → Inject → Recover → verify PASS → reveal.
    expect(await screen.findByTestId("lab-console-session", {}, { timeout: 3_000 })).toHaveTextContent("s-A");
    await user.click(screen.getByRole("button", { name: "生成基线（Generate，空 plan）" }));
    await waitFor(() => expect(screen.getByTestId("lab-run-row-run-1")).toHaveTextContent("completed"), {
      timeout: 3_000,
    });
    await user.click(screen.getByRole("button", { name: "注入故障（Inject，场景 fault_plan）" }));
    await waitFor(() => expect(screen.getByTestId("lab-run-row-run-2")).toHaveTextContent("completed"), {
      timeout: 3_000,
    });
    await user.click(screen.getByRole("button", { name: "恢复重跑（Recover，空 plan）" }));
    await waitFor(() => expect(screen.getByTestId("lab-run-row-run-3")).toHaveTextContent("completed"), {
      timeout: 3_000,
    });

    // Verify is the editable prefill form now (SPEC-408 §7.5): the run ids
    // are the user's EXPLICIT picks (run-2 = inject anchor, run-3 = clean
    // recovery) — the auto-guess one-click posture is retired, so the walk
    // fills the two run fields first (identity prefills from the detail).
    await user.type(screen.getByLabelText("baseline_run_id"), "run-2");
    await user.type(screen.getByLabelText("recovery_run_id"), "run-3");
    await user.click(screen.getByRole("button", { name: "提交判定（verify）" }));
    expect(await screen.findByTestId("verify-verdict", {}, { timeout: 3_000 })).toHaveTextContent("PASS");

    const reveal = screen.getByRole("button", { name: "展开参考解" });
    await waitFor(() => expect(reveal).toBeEnabled());
    await user.click(reveal);
    expect(await screen.findByTestId("lab-solution-text", {}, { timeout: 3_000 })).toHaveTextContent(SOLUTION_TEXT);

    // --- the switch under test: ?session=s-A → s-B (same scenario page).
    await router.navigate("/lab?scenario=5c010000-0000-4000-8000-000000000001&session=s-B");
    await waitFor(
      () => expect(screen.getByTestId("lab-console-session")).toHaveTextContent("s-B"),
      { timeout: 3_000 },
    );

    // 面板复位锁定 + 已取文本丢弃（禁跨会话残留）— session B starts clean.
    expect(screen.queryByTestId("lab-solution-text")).not.toBeInTheDocument();
    expect(screen.queryByText(SOLUTION_TEXT)).not.toBeInTheDocument();
    expect(screen.getByTestId("lab-solution-locked")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "展开参考解" })).toBeDisabled();
    expect(screen.queryByTestId("verify-verdict")).not.toBeInTheDocument();
    expect(screen.getByText("尚无 Run")).toBeInTheDocument();
  });
});
