// Monitor guidance layer at the Region boundary (SPEC-408 §4.3, ticket #95):
// the session-list guide seat (row-1 copy verbatim, demo-button placeholder,
// manual-UUID fallback), the unknown-session explicit state (row-0 copy via
// BOTH signal routes — snapshot 404 and WS 4404), the source-scenario header
// link (zero-state params only), and the verify prefill wiring. API is
// mocked at the barrel boundary (jsdom has no backend); the live faces are
// the E2E suite's job on the real backend. Composition harness mirrors
// Region.test.tsx (AppShell + appRoutes over createMemoryRouter).
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../api/client";
import type { RunListItemDTO, ScenarioDetailDTO, SessionDetailDTO, SnapshotDTO } from "../../api";
import { DemoContext, type DemoController } from "./demo/DemoSessionContext";

vi.mock("../../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api")>();
  return {
    ...actual,
    getSnapshot: vi.fn(),
    querySummary: vi.fn(),
    queryAlerts: vi.fn(),
    listDiagnoses: vi.fn(),
    getSessionDetail: vi.fn(),
    getScenario: vi.fn(),
    listSessionRuns: vi.fn(),
    listSessions: vi.fn(),
  };
});

vi.mock("./stream/useSessionStream", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./stream/useSessionStream")>();
  return {
    ...actual,
    useSessionStream: vi.fn(),
  };
});

import {
  getSessionDetail,
  getScenario,
  getSnapshot,
  listDiagnoses,
  listSessionRuns,
  listSessions,
  queryAlerts,
  querySummary,
} from "../../api";
import { useSessionStream } from "./stream/useSessionStream";
import { AppShell } from "../../app/AppShell";
import { appRoutes } from "../../app/routes";
import { MONITOR_EMPTY_STATE_COPY } from "./copy";
import MonitorRegion from "./Region";

const getSnapshotMock = vi.mocked(getSnapshot);
const querySummaryMock = vi.mocked(querySummary);
const queryAlertsMock = vi.mocked(queryAlerts);
const listDiagnosesMock = vi.mocked(listDiagnoses);
const getSessionDetailMock = vi.mocked(getSessionDetail);
const getScenarioMock = vi.mocked(getScenario);
const listSessionRunsMock = vi.mocked(listSessionRuns);
const listSessionsMock = vi.mocked(listSessions);
const useSessionStreamMock = vi.mocked(useSessionStream);

const SESSION = "0aa0a0a0-0a0a-4a00-8000-00000000a001";
const SCENARIO = "5c010000-0000-4000-8000-000000000001";

const SNAPSHOT: SnapshotDTO = {
  session_id: SESSION,
  revision: 1,
  lifecycle: "created",
  virtual_time_ns: 0,
  topology_revision: 1,
};

function resolveHappyPath(detail: SessionDetailDTO): void {
  getSnapshotMock.mockResolvedValue(SNAPSHOT);
  querySummaryMock.mockResolvedValue({
    data: { tenant_id: "t", session_id: SESSION, journal_seq_watermark: 0, event_count: 0, active_alert_count: 0, schema_version: "1" },
  } as never);
  queryAlertsMock.mockResolvedValue({ data: { items: [], total: 0 } } as never);
  listDiagnosesMock.mockResolvedValue([]);
  getSessionDetailMock.mockResolvedValue(detail);
  listSessionRunsMock.mockResolvedValue([]);
}

const DETAIL_PLAIN: SessionDetailDTO = {
  session_id: SESSION,
  revision: 1,
  lifecycle: "running",
  virtual_time_ns: 0,
  topology_revision: 1,
  scenario_id: null,
  created_at_ms: 1_700_000_000_000,
};

const DETAIL_SCENARIO: SessionDetailDTO = { ...DETAIL_PLAIN, scenario_id: SCENARIO };

function renderAppAt(path: string, demo?: Partial<DemoController>) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const demoController: DemoController = { startDemo: demo?.startDemo ?? (() => {}), demoBusy: demo?.demoBusy ?? false };
  const router = createMemoryRouter(
    [
      {
        element: (
          <QueryClientProvider client={queryClient}>
            <DemoContext.Provider value={demoController}>
              <AppShell />
            </DemoContext.Provider>
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
});

describe("MonitorRegion — 会话列表区 guide seat (row 1)", () => {
  it("renders the row-1 three-question copy verbatim, the wired demo button (#99), and the manual-UUID fallback", async () => {
    listSessionsMock.mockResolvedValue([]);
    renderAppAt("/monitor");

    const guide = await screen.findByTestId("monitor-entry-guide");
    expect(guide.textContent).toContain(MONITOR_EMPTY_STATE_COPY.entry.what);
    expect(guide.textContent).toContain(MONITOR_EMPTY_STATE_COPY.entry.why);
    expect(guide.textContent).toContain(`下一步:${MONITOR_EMPTY_STATE_COPY.entry.next}`);

    // 演示一键主按钮位(#99 已接线):默认(无 shell 编排进行中)可点——点击经
    // DemoContext 驱动 AppShell 的编排,行为断言见下。
    const demo = screen.getByTestId("monitor-demo-start");
    expect(demo).toBeEnabled();
    expect(demo.textContent).toContain("一键演示");

    // 手输 UUID 兜底仍在(输入 session id 即跟踪)。
    expect(screen.getByLabelText("session id")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "跟踪" })).toBeInTheDocument();

    // panels never mount in the guide seat
    expect(screen.queryByRole("heading", { name: "运行控制" })).not.toBeInTheDocument();
  });

  it("tracks a complete pasted UUID immediately (输入即跟踪)", async () => {
    resolveHappyPath(DETAIL_PLAIN);
    renderAppAt("/monitor");
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("session id"), SESSION);
    expect(await screen.findByText(`session: ${SESSION}`)).toBeInTheDocument();
  });
});

describe("MonitorRegion — 一键演示 wiring (ticket #99)", () => {
  /** The wiring seam here is the button → demo-controller contract; the
   * region renders directly under a STUB provider (AppShell contributes its
   * own real provider around the outlet, which would shadow an outer stub). */
  function renderRegionAt(demo: Partial<DemoController>) {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const demoController: DemoController = { startDemo: demo.startDemo ?? (() => {}), demoBusy: demo.demoBusy ?? false };
    const router = createMemoryRouter(
      [
        {
          path: "/monitor",
          element: (
            <QueryClientProvider client={queryClient}>
              <DemoContext.Provider value={demoController}>
                <MonitorRegion />
              </DemoContext.Provider>
            </QueryClientProvider>
          ),
        },
      ],
      { initialEntries: ["/monitor"] },
    );
    return render(<RouterProvider router={router} />);
  }

  it("clicking the demo button fires the shell-owned startDemo (same orchestration as the home card)", async () => {
    listSessionsMock.mockResolvedValue([]);
    const startDemo = vi.fn();
    renderRegionAt({ startDemo });
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("monitor-demo-start"));
    expect(startDemo).toHaveBeenCalledTimes(1);
  });

  it("demoBusy (an orchestration in flight) disables the entry button — no parallel demo", async () => {
    listSessionsMock.mockResolvedValue([]);
    renderRegionAt({ demoBusy: true });
    expect(await screen.findByTestId("monitor-demo-start")).toBeDisabled();
  });
});

describe("MonitorRegion — 未知会话态 (row 0, both routes)", () => {
  it("snapshot/detail REST 404 renders the explicit unknown-session state (row-0 copy verbatim), not panels", async () => {
    getSnapshotMock.mockRejectedValue(new ApiError({ status: 404, errorCode: "SIM_SESSION_NOT_FOUND", message: "unknown session" }));
    getSessionDetailMock.mockRejectedValue(new ApiError({ status: 404, errorCode: "SIM_SESSION_NOT_FOUND", message: "unknown session" }));
    listSessionsMock.mockResolvedValue([]);
    renderAppAt(`/monitor?session=${SESSION}`);

    const unknown = await screen.findByTestId("monitor-unknown-session");
    expect(unknown.textContent).toContain(MONITOR_EMPTY_STATE_COPY.unknownSession.what);
    expect(unknown.textContent).toContain(MONITOR_EMPTY_STATE_COPY.unknownSession.why);
    expect(unknown.textContent).toContain(`下一步:${MONITOR_EMPTY_STATE_COPY.unknownSession.next}`);

    // action: 回 Lab 开新实验;reselection: the recent list is below.
    expect(screen.getByRole("link", { name: "回 Lab 开新实验" })).toHaveAttribute("href", "/lab");
    expect(screen.getByTestId("monitor-entry-guide")).toBeInTheDocument();

    // the panel stack is replaced by the explicit state
    expect(screen.queryByRole("heading", { name: "运行控制" })).not.toBeInTheDocument();
  });

  it("WS 4404 (permanent session-unknown close) renders the same explicit state even with successful REST reads", async () => {
    resolveHappyPath(DETAIL_PLAIN);
    useSessionStreamMock.mockReturnValue({ status: "closed", closeCode: 4404 });
    renderAppAt(`/monitor?session=${SESSION}`);

    const unknown = await screen.findByTestId("monitor-unknown-session");
    expect(unknown.textContent).toContain(MONITOR_EMPTY_STATE_COPY.unknownSession.what);
    expect(screen.queryByRole("heading", { name: "运行控制" })).not.toBeInTheDocument();
  });

  it("transient WS closes (e.g. 1006) do NOT trigger the unknown state", async () => {
    resolveHappyPath(DETAIL_PLAIN);
    useSessionStreamMock.mockReturnValue({ status: "reconnecting", closeCode: 1006 });
    renderAppAt(`/monitor?session=${SESSION}`);

    expect(await screen.findByRole("heading", { name: "运行控制" })).toBeInTheDocument();
    expect(screen.queryByTestId("monitor-unknown-session")).not.toBeInTheDocument();
  });
});

describe("MonitorRegion — 来源场景 header link", () => {
  it("renders 来源场景:<scenario_id> ↗ back to /lab?scenario=<id> with zero state params", async () => {
    resolveHappyPath(DETAIL_SCENARIO);
    getScenarioMock.mockResolvedValue({
      scenario_id: SCENARIO,
      version: "1.0.0",
      title: "认识闭环:PAT 缺失",
      difficulty: "introductory",
      content_hash: "a".repeat(64),
    } as ScenarioDetailDTO);
    renderAppAt(`/monitor?session=${SESSION}`);

    const link = await screen.findByTestId("monitor-source-scenario");
    expect(link.textContent).toContain(`来源场景:${SCENARIO}`);
    expect(link.getAttribute("href")).toBe(`/lab?scenario=${SCENARIO}`);
  });

  it("renders no source link for a plain session (scenario_id null)", async () => {
    resolveHappyPath(DETAIL_PLAIN);
    renderAppAt(`/monitor?session=${SESSION}`);
    await screen.findByRole("heading", { name: "运行控制" });
    expect(screen.queryByTestId("monitor-source-scenario")).not.toBeInTheDocument();
  });
});

describe("MonitorRegion — verify prefill wiring (three sources)", () => {
  it("prefills scenario_id from session detail, version/content_hash from scenario detail, and datalist from the run list", async () => {
    resolveHappyPath(DETAIL_SCENARIO);
    getScenarioMock.mockResolvedValue({
      scenario_id: SCENARIO,
      version: "1.0.0",
      title: "t",
      difficulty: "d",
      content_hash: "b".repeat(64),
    } as ScenarioDetailDTO);
    const RUNS: RunListItemDTO[] = [
      { run_id: "r-server-2", status: "completed", submitted_at_ms: 2, fault_plan_present: false, fidelity: "SIM_TS", packet_count: 600 },
      { run_id: "r-server-1", status: "completed", submitted_at_ms: 1, fault_plan_present: false, fidelity: "SIM_TS", packet_count: null },
    ];
    listSessionRunsMock.mockResolvedValue(RUNS);

    renderAppAt(`/monitor?session=${SESSION}`);

    expect(await screen.findByLabelText("recovery_run_id")).toHaveValue("");
    // async detail/scenario/runs read-backs land — waitFor the values.
    await waitFor(() => {
      expect(screen.getByLabelText("scenario_id")).toHaveValue(SCENARIO);
      expect(screen.getByLabelText("version")).toHaveValue("1.0.0");
      expect(screen.getByLabelText("content_hash")).toHaveValue("b".repeat(64));
    });

    // the run datalist carries the server run list (contract order, never
    // re-sorted); runs are candidates only — inputs stay empty (no auto-guess).
    await waitFor(() => {
      const options = Array.from(document.getElementById("verify-run-candidates")?.querySelectorAll("option") ?? []);
      expect(options.map((o) => o.getAttribute("value"))).toEqual(["r-server-2", "r-server-1"]);
      const diagnoseOptions = Array.from(document.getElementById("monitor-run-candidates")?.querySelectorAll("option") ?? []);
      expect(diagnoseOptions.map((o) => o.getAttribute("value"))).toEqual(["r-server-2", "r-server-1"]);
    });
  });

  it("keeps the honesty discipline phrases intact on the page", async () => {
    resolveHappyPath(DETAIL_PLAIN);
    const { container } = renderAppAt(`/monitor?session=${SESSION}`);
    await screen.findByRole("heading", { name: "运行控制" });
    const text = container.textContent ?? "";
    // 行 4 缺失 ≠ 零 / 行 6 候选 ≠ 事实(逐字);行 5 承载无观测 ≠ 干净。
    expect(text).toContain("缺失 ≠ 零");
    expect(text).toContain("候选 ≠ 事实");
    expect(text).toContain("无告警记录 ≠ 干净");
    expect(text).toContain("（无观测）");
  });
});
