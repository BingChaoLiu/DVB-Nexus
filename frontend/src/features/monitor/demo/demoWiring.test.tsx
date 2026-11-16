// Shell-level demo wiring integration tests (SPEC-408 §4.3/§7.4, ticket #99):
// AppShell owns the demo state (React state + context callbacks — zero new
// dependencies, zero global store) and hosts the demo session bar under the
// journey bar. Both entry buttons (home Monitor card + Monitor guide seat)
// drive the SAME orchestration; landing navigates to /monitor with the
// pre-anchor triple; cleanup disposes the session and clears the local demo
// state; a failure stops in place and keeps the created session cleanable.
// The api barrel is mocked at the boundary (jsdom has no backend); the real
// chain is the E2E suite's job (e2e/demo-session.spec.ts).
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../api")>();
  return {
    ...actual,
    listScenarios: vi.fn(),
    getScenario: vi.fn(),
    createSession: vi.fn(),
    startSession: vi.fn(),
    submitRun: vi.fn(),
    getRun: vi.fn(),
    diagnoseRun: vi.fn(),
    disposeSession: vi.fn(),
    listSessions: vi.fn(),
    getSnapshot: vi.fn(),
    getSessionDetail: vi.fn(),
    listSessionRuns: vi.fn(),
    querySummary: vi.fn(),
    queryAlerts: vi.fn(),
    listDiagnoses: vi.fn(),
    verifyRun: vi.fn(),
  };
});

vi.mock("../stream/useSessionStream", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../stream/useSessionStream")>();
  return {
    ...actual,
    useSessionStream: vi.fn(),
  };
});

import type { ScenarioDetailDTO, ScenarioSummaryDTO, SessionViewDTO } from "../../../api";
import { ApiError } from "../../../api/client";
import { useSessionStream } from "../stream/useSessionStream";
import { AppShell } from "../../../app/AppShell";
import { appRoutes } from "../../../app/routes";
import {
  createSession,
  diagnoseRun,
  disposeSession,
  getRun,
  getScenario,
  getSnapshot,
  getSessionDetail,
  listDiagnoses,
  listScenarios,
  listSessionRuns,
  listSessions,
  queryAlerts,
  querySummary,
  startSession,
  submitRun,
  verifyRun,
} from "../../../api";

const listScenariosMock = vi.mocked(listScenarios);
const getScenarioMock = vi.mocked(getScenario);
const createSessionMock = vi.mocked(createSession);
const startSessionMock = vi.mocked(startSession);
const submitRunMock = vi.mocked(submitRun);
const getRunMock = vi.mocked(getRun);
const diagnoseRunMock = vi.mocked(diagnoseRun);
const disposeSessionMock = vi.mocked(disposeSession);
const listSessionsMock = vi.mocked(listSessions);
const getSnapshotMock = vi.mocked(getSnapshot);
const getSessionDetailMock = vi.mocked(getSessionDetail);
const listSessionRunsMock = vi.mocked(listSessionRuns);
const querySummaryMock = vi.mocked(querySummary);
const queryAlertsMock = vi.mocked(queryAlerts);
const listDiagnosesMock = vi.mocked(listDiagnoses);
const verifyRunMock = vi.mocked(verifyRun);
const useSessionStreamMock = vi.mocked(useSessionStream);

const SESSION = "aa990000-0000-4000-8000-000000009901";
const SCENARIO_ID = "5c010000-0000-4000-8000-000000000001";

const SC01_SUMMARY = { scenario_id: SCENARIO_ID, title: "认识闭环：PAT 缺失" } as ScenarioSummaryDTO;

const SC01_DETAIL = {
  scenario_id: SCENARIO_ID,
  title: "认识闭环：PAT 缺失",
  version: "1.0.0",
  simulation_config: { seed: 1234567, mode: "deterministic", clock: { mode: "deterministic", start_time_ns: 0, speed_num: 1, speed_den: 1, tick_quantum_ns: 1_000_000 } },
  initial_topology: { topology_id: "topo-1", revision: 1 },
  fault_plan: [
    {
      fault_id: "fd000000-0000-4000-8000-00000000f1a1",
      fault_type: "PAT_MISSING",
      target_id: "mux-0:pid:0x0000",
      parameters: {},
      activation: { kind: "packet_index", packet_index: 202 },
      expected_observations: ["ts.psi_section_observed"],
    },
  ],
} as unknown as ScenarioDetailDTO;

function view(lifecycle: string): SessionViewDTO {
  return { session_id: SESSION, revision: 1, lifecycle, virtual_time_ns: 0, topology_revision: 1 } as SessionViewDTO;
}

function mockHappyOrchestration(): void {
  listScenariosMock.mockResolvedValue([SC01_SUMMARY]);
  getScenarioMock.mockResolvedValue(SC01_DETAIL);
  createSessionMock.mockResolvedValue(view("ready"));
  startSessionMock.mockResolvedValue(view("running"));
  let call = 0;
  submitRunMock.mockImplementation(async () => {
    call += 1;
    return { run_id: `run-${call}`, status: "running", config_hash: "abc" };
  });
  getRunMock.mockImplementation(async (_sessionId, runId) =>
    runId === "run-2"
      ? {
          run_id: runId,
          status: "completed",
          packet_count: 600,
          artifacts: [{ artifact_id: "art-faulted-1", kind: "faulted_ts", sha256: "f".repeat(64), byte_size: 112800, partial: false }],
          warnings: [],
        }
      : { run_id: runId, status: "completed", packet_count: 600, artifacts: [], warnings: [] },
  );
  diagnoseRunMock.mockResolvedValue({ session_id: SESSION, run_id: "run-2", evaluated_at_utc_ms: 1, candidates: [] });
}

function mockLandedMonitorFaces(): void {
  getSnapshotMock.mockResolvedValue({ session_id: SESSION, revision: 1, lifecycle: "running", virtual_time_ns: 0, topology_revision: 1 });
  getSessionDetailMock.mockResolvedValue({ session_id: SESSION, revision: 1, lifecycle: "running", virtual_time_ns: 0, topology_revision: 1, scenario_id: SCENARIO_ID, created_at_ms: 1 });
  listSessionRunsMock.mockResolvedValue([]);
  querySummaryMock.mockResolvedValue({ data: { tenant_id: "t", session_id: SESSION, journal_seq_watermark: 0, event_count: 0, active_alert_count: 0, schema_version: "1" } } as never);
  queryAlertsMock.mockResolvedValue({ data: { items: [], total: 0 } } as never);
  listDiagnosesMock.mockResolvedValue([]);
}

function renderShellAt(path: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(
    [
      {
        element: (
          <QueryClientProvider client={queryClient}>
            <AppShell />
          </QueryClientProvider>
        ),
        children: [...appRoutes.map((route) => ({ path: route.path, element: <route.element /> }))],
      },
    ],
    { initialEntries: [path] },
  );
  return render(<RouterProvider router={router} />);
}

beforeEach(() => {
  vi.clearAllMocks();
  useSessionStreamMock.mockReturnValue({ status: "idle", closeCode: null });
  listSessionsMock.mockResolvedValue([]);
});

describe("AppShell demo wiring — home entry (§4.2 Monitor card demo gate)", () => {
  it("orchestrates on click, lands the bar under the journey bar, and navigates to the pre-anchored Monitor view", async () => {
    const user = userEvent.setup();
    mockHappyOrchestration();
    mockLandedMonitorFaces();
    renderShellAt("/");

    const entry = await screen.findByTestId("home-monitor-demo-start");
    expect(entry).toBeEnabled();
    await user.click(entry);

    // Landed: the demo bar carries the frozen declaration and the bar sits in
    // the shell (journey bar still present above it).
    const bar = await screen.findByTestId("demo-session-bar");
    await waitFor(() => expect(bar).toHaveAttribute("data-demo-status", "landed"));
    expect(screen.getByTestId("demo-declaration")).toHaveTextContent("数据 = 沙盘真实生成；与真实会话唯一差别是入口");
    expect(screen.getByTestId("journey-bar")).toBeInTheDocument();

    // Landing navigation: the Monitor page tracks the demo session.
    expect(await screen.findByText(`session: ${SESSION}`)).toBeInTheDocument();

    // The landed Monitor page's verify face never auto-submits (§4.3): the
    // orchestration itself made zero verify calls.
    expect(verifyRunMock).not.toHaveBeenCalled();
  });

  it("cleanup disposes the demo session and clears the local demo state (bar gone, back to the guide seat)", async () => {
    const user = userEvent.setup();
    mockHappyOrchestration();
    mockLandedMonitorFaces();
    disposeSessionMock.mockResolvedValue(undefined);
    renderShellAt("/");

    await user.click(await screen.findByTestId("home-monitor-demo-start"));
    const cleanup = await screen.findByTestId("demo-cleanup");
    await waitFor(() => expect(cleanup).toBeEnabled());
    await user.click(cleanup);

    expect(disposeSessionMock).toHaveBeenCalledWith(SESSION);
    await waitFor(() => expect(screen.queryByTestId("demo-session-bar")).not.toBeInTheDocument());
    // post-dispose: no session param → the 会话列表区 guide seat is the honest view
    expect(await screen.findByTestId("monitor-entry-guide")).toBeInTheDocument();
  });

  it("double-click guard: one orchestration at a time (the in-flight click is a no-op)", async () => {
    const user = userEvent.setup();
    let releaseScenario!: (value: ScenarioSummaryDTO[]) => void;
    listScenariosMock.mockReturnValue(
      new Promise((resolve) => {
        releaseScenario = resolve;
      }),
    );
    renderShellAt("/");

    await user.click(await screen.findByTestId("home-monitor-demo-start"));
    await user.click(screen.getByTestId("home-monitor-demo-start"));
    releaseScenario([SC01_SUMMARY]);

    // exactly one orchestration ran
    await screen.findByTestId("demo-session-bar");
    expect(listScenariosMock).toHaveBeenCalledTimes(1);
  });

  it("entry buttons disable while an orchestration is in flight (demoBusy)", async () => {
    const user = userEvent.setup();
    let releaseScenario!: (value: ScenarioSummaryDTO[]) => void;
    listScenariosMock.mockReturnValue(
      new Promise((resolve) => {
        releaseScenario = resolve;
      }),
    );
    renderShellAt("/");

    await user.click(await screen.findByTestId("home-monitor-demo-start"));
    expect(screen.getByTestId("home-monitor-demo-start")).toBeDisabled();
    releaseScenario([]);
    // failure path from the empty registry → buttons re-enable (no demo landed)
    await screen.findByTestId("demo-failure-hint");
    await waitFor(() => expect(screen.getByTestId("home-monitor-demo-start")).toBeEnabled());
  });
});

describe("AppShell demo wiring — failure keeps the session cleanable (§8 row 1)", () => {
  it("a mid-chain failure stops in place, keeps the created session id, and cleanup disposes it", async () => {
    const user = userEvent.setup();
    mockHappyOrchestration();
    // failure at start: the session EXISTS (created) but never starts
    startSessionMock.mockRejectedValue(new ApiError({ status: 409, errorCode: "SIM_INVALID_LIFECYCLE_TRANSITION", message: "bad transition" }));
    disposeSessionMock.mockResolvedValue(undefined);
    renderShellAt("/");

    await user.click(screen.getByTestId("home-monitor-demo-start"));
    const bar = await screen.findByTestId("demo-session-bar");
    await waitFor(() => expect(bar).toHaveAttribute("data-demo-status", "failed"));

    // honest failure: explicit reason row + the frozen start.cmd hint
    const startRow = screen.getByTestId("demo-phase-row-start");
    expect(startRow).toHaveAttribute("data-phase-state", "failed");
    expect(startRow.textContent).toContain("SIM_INVALID_LIFECYCLE_TRANSITION");
    expect(screen.getByTestId("demo-failure-hint")).toHaveTextContent(/后端未运行？`start.cmd`/);

    // NO landing: still on the home foyer (no Monitor page mounted), no
    // fabricated success.
    expect(screen.queryByText(`session: ${SESSION}`)).not.toBeInTheDocument();

    // 已建会话保留可手动清理: kept id visible, cleanup disposes it.
    expect(bar.textContent).toContain(SESSION);
    await user.click(screen.getByTestId("demo-cleanup"));
    expect(disposeSessionMock).toHaveBeenCalledWith(SESSION);
    await waitFor(() => expect(screen.queryByTestId("demo-session-bar")).not.toBeInTheDocument());
  });

  it("cleanup failure surfaces an explicit inline line and keeps the bar", async () => {
    const user = userEvent.setup();
    mockHappyOrchestration();
    mockLandedMonitorFaces();
    disposeSessionMock.mockRejectedValue(new ApiError({ status: 503, errorCode: "SIM_BACKEND_UNAVAILABLE", message: "backend down" }));
    renderShellAt("/");

    await user.click(await screen.findByTestId("home-monitor-demo-start"));
    const cleanup = await screen.findByTestId("demo-cleanup");
    await waitFor(() => expect(cleanup).toBeEnabled());
    await user.click(cleanup);

    expect(await screen.findByTestId("demo-cleanup-error")).toBeInTheDocument();
    expect(screen.getByTestId("demo-session-bar")).toBeInTheDocument();
  });
});

describe("AppShell demo wiring — Monitor guide-seat entry (same orchestration)", () => {
  it("the monitor-demo-start button drives the same orchestration and lands", async () => {
    const user = userEvent.setup();
    mockHappyOrchestration();
    mockLandedMonitorFaces();
    renderShellAt("/monitor");

    const entry = await screen.findByTestId("monitor-demo-start");
    expect(entry).toBeEnabled();
    await user.click(entry);

    const bar = await screen.findByTestId("demo-session-bar");
    await waitFor(() => expect(bar).toHaveAttribute("data-demo-status", "landed"));
    expect(await screen.findByText(`session: ${SESSION}`)).toBeInTheDocument();
  });
});
