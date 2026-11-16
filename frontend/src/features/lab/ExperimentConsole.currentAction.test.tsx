// Experiment console current-action package (SPEC-408 §4.4 REQ-UI-408-008/
// 009/010, AC-408-05): the guidance bar is always present under the Stepper
// and names the EXACT button copy; the current-action button carries the
// primary style and the elevation is consistent ACROSS blocks (run buttons,
// diagnose, verify); Stepper clicks scroll-locate the matching section with
// a flash highlight and never punch light-up nor submit runs. Walk driven
// through mocked api seams (jsdom has no backend) — the live composition is
// E2E's job (assertions for lab.spec.ts are reported to #101).
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  DiagnosisDTO,
  DiagnosisReportDTO,
  RunAcceptedDTO,
  RunStatusDTO,
  ScenarioDetailDTO,
  SnapshotDTO,
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
    diagnoseRun: vi.fn(),
  };
});

import { diagnoseRun, getRun, getScenario, getSnapshot, listDiagnoses, queryEvents, submitRun } from "../../api";
import { ExperimentConsole } from "./ExperimentConsole";

const mocked = {
  getScenario: vi.mocked(getScenario),
  getSnapshot: vi.mocked(getSnapshot),
  queryEvents: vi.mocked(queryEvents),
  listDiagnoses: vi.mocked(listDiagnoses),
  submitRun: vi.mocked(submitRun),
  getRun: vi.mocked(getRun),
  diagnoseRun: vi.mocked(diagnoseRun),
};

const SCENARIO: ScenarioDetailDTO = {
  schema_version: "1.0",
  scenario_id: "5c010000-0000-4000-8000-000000000001",
  version: "1.0.0",
  title: "CC 不连续训练",
  difficulty: "intro",
  initial_topology: {},
  simulation_config: {},
  fault_plan: [{ fault_id: "fd000000-0000-4000-8000-00000000f103" }],
  objectives: [],
  hints: [],
  pass_criteria: [{ criterion_id: "cc-ok" }],
};

/** Runs submitted through the mocked seam: artifact kind follows the plan. */
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
  mocked.queryEvents.mockResolvedValue({
    data: { items: [{ journal_seq: 7, event_type: "run.started" }], total: 1 },
  } as never);
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
  mocked.diagnoseRun.mockImplementation(async (sessionId, runId) =>
    ({
      session_id: sessionId,
      run_id: runId,
      evaluated_at_utc_ms: 1_700_000_000_000,
      candidates: [],
      warnings: [],
    }) satisfies DiagnosisReportDTO,
  );
}

function renderConsole() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const router = createMemoryRouter(
    [
      {
        path: "/lab",
        element: <ExperimentConsole scenarioId={SCENARIO.scenario_id} sessionId="s-1" onBack={() => {}} />,
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

const RUN_BUTTONS = ["生成基线（Generate，空 plan）", "注入故障（Inject，场景 fault_plan）", "恢复重跑（Recover，空 plan）"] as const;
const DIAGNOSE_BUTTON = "对注入 Run 评估（diagnose）";
const VERIFY_BUTTON = "提交判定（verify）";
const GUIDE_GENERATE = "下一步：生成基线 → 点击『生成基线（Generate，空 plan）』";
const GUIDE_INJECT = "下一步：注入故障 → 点击『注入故障（Inject，场景 fault_plan）』";

function primaryState() {
  const names = [...RUN_BUTTONS, DIAGNOSE_BUTTON, VERIFY_BUTTON] as const;
  return Object.fromEntries(
    names.map((name) => [name, screen.getByRole("button", { name }).className.includes("dvb-lab-btn-primary")]),
  );
}

async function clickAndWaitCompleted(user: ReturnType<typeof userEvent.setup>, name: string, runId: string) {
  await user.click(screen.getByRole("button", { name }));
  await waitFor(() => expect(screen.getByTestId(`lab-run-row-${runId}`)).toHaveTextContent("completed"), {
    timeout: 3_000,
  });
}

beforeEach(() => {
  setupApiMocks();
});

describe("ExperimentConsole — current action guidance + primary elevation (AC-408-05)", () => {
  it("guidance bar is always present and names the verbatim button copy; pointer advances as facts land", async () => {
    const user = userEvent.setup();
    renderConsole();

    // Create lights via the running lifecycle; pointer = generate. The bar
    // sits under the Stepper and quotes the button copy VERBATIM.
    const guide = await screen.findByTestId("lab-action-guide", {}, { timeout: 3_000 });
    await waitFor(() => expect(guide).toHaveTextContent(GUIDE_GENERATE));

    // 三按钮三分立常驻: all three run triggers visible at once, zero mode switch.
    for (const name of RUN_BUTTONS) {
      expect(screen.getByRole("button", { name })).toBeInTheDocument();
    }
    // Primary elevation: the current action (generate) is primary; the rest
    // stay secondary — no ordinal decorations, no confirm dialogs involved.
    expect(primaryState()).toEqual({
      [RUN_BUTTONS[0]]: true,
      [RUN_BUTTONS[1]]: false,
      [RUN_BUTTONS[2]]: false,
      [DIAGNOSE_BUTTON]: false,
      [VERIFY_BUTTON]: false,
    });

    // Generate completes → pointer moves to inject (步完成自动前移).
    await clickAndWaitCompleted(user, RUN_BUTTONS[0], "run-1");
    await waitFor(() => expect(screen.getByTestId("lab-action-guide")).toHaveTextContent(GUIDE_INJECT));
    expect(primaryState()[RUN_BUTTONS[1]]).toBe(true);
    expect(primaryState()[RUN_BUTTONS[0]]).toBe(false);

    // Inject completes → pointer crosses into the diagnose BLOCK: the
    // diagnose button elevates too (主级化跨区块一致).
    await clickAndWaitCompleted(user, RUN_BUTTONS[1], "run-2");
    await waitFor(() => expect(primaryState()[DIAGNOSE_BUTTON]).toBe(true));
    expect(screen.getByTestId("lab-action-guide")).toHaveTextContent("下一步：诊断注入 Run → 点击『对注入 Run 评估（diagnose）』");

    // Diagnose done (+ inspect lit by the journal event) → recover elevates.
    await user.click(screen.getByRole("button", { name: DIAGNOSE_BUTTON }));
    await waitFor(() => expect(primaryState()[RUN_BUTTONS[2]]).toBe(true));

    // Recover completes → pointer lands on verify: the verify button (third
    // block) elevates — same mechanism, cross-block consistent.
    await clickAndWaitCompleted(user, RUN_BUTTONS[2], "run-3");
    await waitFor(() => expect(primaryState()[VERIFY_BUTTON]).toBe(true));
    expect(screen.getByTestId("lab-action-guide")).toHaveTextContent("下一步：提交判定 → 点击『提交判定（verify）』");
    // The bar never disappears (常驻一行) through the whole walk.
    expect(screen.getByTestId("lab-action-guide")).toBeInTheDocument();
  });

  it("Stepper click = locator not punch-card: scrolls to the section, flashes it, submits nothing", async () => {
    // jsdom has no scrollIntoView — inject a spy, restore the prototype after.
    const originalScroll = Element.prototype.scrollIntoView;
    const scrollSpy = vi.fn(function (this: Element) {});
    Element.prototype.scrollIntoView = scrollSpy;
    const user = userEvent.setup();
    renderConsole();

    const guide = await screen.findByTestId("lab-action-guide", {}, { timeout: 3_000 });
    await waitFor(() => expect(guide).toHaveTextContent(GUIDE_GENERATE));

    await user.click(screen.getByTestId("lab-step-verify"));
    expect(scrollSpy).toHaveBeenCalledTimes(1);
    expect(scrollSpy.mock.instances[0]?.getAttribute("data-testid")).toBe("lab-section-verify");
    // Flash highlight on the targeted section (高亮闪示).
    expect(screen.getByTestId("lab-section-verify").className).toContain("dvb-lab-section-flash");

    // A click is NOT a stamp: light-up and the run registry are untouched.
    expect(screen.getByTestId("lab-step-generate")).toHaveTextContent("待办");
    expect(screen.getByTestId("lab-step-verify")).toHaveTextContent("待办");
    expect(mocked.submitRun).not.toHaveBeenCalled();
    expect(screen.getByTestId("lab-action-guide")).toHaveTextContent(GUIDE_GENERATE);

    // Steps map to their blocks: diagnose step → diagnose section.
    scrollSpy.mockClear();
    await user.click(screen.getByTestId("lab-step-diagnose"));
    expect(scrollSpy.mock.instances[0]?.getAttribute("data-testid")).toBe("lab-section-diagnose");
    Element.prototype.scrollIntoView = originalScroll;
  });
});
