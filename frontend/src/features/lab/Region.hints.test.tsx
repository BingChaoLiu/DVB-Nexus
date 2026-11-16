// LabRegion hints persistence (SPEC-408 §4.4 REQ-UI-408-011 / AC-408-06):
// the reveal record lives under the single per-scenario localStorage key
// `dvb-lab-hints:{scenario_id}` (hintsStorage seam) and ONE shared state
// source in Region feeds BOTH the detail page ladder and the console's
// collapsible 「分阶段提示」 block (same-key read/write asserted here; no
// deep link — the console URL carries ?session=). Storage-unusable
// degradation keeps page memory and says so honestly (SPEC-408 §8). Walks
// are driven through mocked api seams at the Region boundary (jsdom has no
// backend); live composition is E2E's job (#101).
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DiagnosisDTO, ScenarioDetailDTO, SnapshotDTO } from "../../api";

vi.mock("../../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api")>();
  return {
    ...actual,
    getScenario: vi.fn(),
    getSnapshot: vi.fn(),
    queryEvents: vi.fn(),
    listDiagnoses: vi.fn(),
  };
});

import { getScenario, getSnapshot, listDiagnoses, queryEvents } from "../../api";
import { hintsStorageKey } from "./hintsStorage";
import LabRegion from "./Region";

const SID = "5c010000-0000-4000-8000-000000000001";

const HINTS = [
  {
    hint_id: "h-1",
    trigger: "experiment opened",
    level: "nudge",
    content: "第一层提示内容",
    requirement_ids: [],
    standard_ref: null,
  },
  {
    hint_id: "h-2",
    trigger: "after Inject",
    level: "direction",
    content: "第二层提示内容",
    requirement_ids: [],
    standard_ref: null,
  },
  {
    hint_id: "h-3",
    trigger: "before Verify",
    level: "walkthrough",
    content: "第三层提示内容",
    requirement_ids: [],
    standard_ref: null,
  },
];

const SCENARIO: ScenarioDetailDTO = {
  schema_version: "1.0",
  scenario_id: SID,
  version: "1.0.0",
  content_hash: "sha256:hint-fixture",
  title: "CC 不连续训练",
  difficulty: "intro",
  initial_topology: {
    topology_id: "topo-1",
    revision: 1,
    nodes: [],
    connections: [],
  },
  simulation_config: {},
  fault_plan: [{ fault_id: "fd000000-0000-4000-8000-00000000f103" }],
  objectives: [],
  hints: HINTS,
  pass_criteria: [{ criterion_id: "cc-ok" }],
};

const mocked = {
  getScenario: vi.mocked(getScenario),
  getSnapshot: vi.mocked(getSnapshot),
  queryEvents: vi.mocked(queryEvents),
  listDiagnoses: vi.mocked(listDiagnoses),
};

function setupApiMocks() {
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
  window.localStorage.clear();
  vi.restoreAllMocks();
  setupApiMocks();
});

describe("LabRegion — hints persistence (SPEC-408 §4.4 REQ-UI-408-011)", () => {
  it("detail reveal writes the per-scenario key and discloses 已揭示 N/M（本地记录，非服务端事实）", async () => {
    const user = userEvent.setup();
    renderLab(`/lab?scenario=${SID}`);
    const status = await screen.findByTestId("lab-hints-status", {}, { timeout: 3_000 });
    expect(status).toHaveTextContent("已揭示 0/3（本地记录，非服务端事实）");
    await user.click(screen.getByRole("button", { name: /揭示下一条提示/ }));
    expect(status).toHaveTextContent("已揭示 1/3（本地记录，非服务端事实）");
    expect(screen.getByText("第一层提示内容")).toBeInTheDocument();
    expect(window.localStorage.getItem(hintsStorageKey(SID))).toBe("1");
  });

  it("a fresh Region instance hydrates the same key (刷新不丢 — cross-mount 同源)", async () => {
    window.localStorage.setItem(hintsStorageKey(SID), "2");
    renderLab(`/lab?scenario=${SID}`);
    expect(await screen.findByTestId("lab-hints-status", {}, { timeout: 3_000 })).toHaveTextContent("已揭示 2/3");
    expect(screen.getByText("第二层提示内容")).toBeInTheDocument();
    expect(screen.queryByText("第三层提示内容")).not.toBeInTheDocument();
    cleanup();
    // Second instance — same key, same state (同源).
    renderLab(`/lab?scenario=${SID}`);
    expect(await screen.findByTestId("lab-hints-status", {}, { timeout: 3_000 })).toHaveTextContent("已揭示 2/3");
  });

  it("重置提示 clears the per-scenario key and zeroes the ladder", async () => {
    window.localStorage.setItem(hintsStorageKey(SID), "2");
    const user = userEvent.setup();
    renderLab(`/lab?scenario=${SID}`);
    expect(await screen.findByTestId("lab-hints-status", {}, { timeout: 3_000 })).toHaveTextContent("已揭示 2/3");
    await user.click(screen.getByTestId("lab-hints-reset"));
    expect(screen.getByTestId("lab-hints-status")).toHaveTextContent("已揭示 0/3（本地记录，非服务端事实）");
    expect(window.localStorage.getItem(hintsStorageKey(SID))).toBeNull();
    expect(screen.queryByText("第一层提示内容")).not.toBeInTheDocument();
  });

  it("console collapsible 分阶段提示 block reads/writes the SAME key (同源, no deep link)", async () => {
    window.localStorage.setItem(hintsStorageKey(SID), "1");
    const user = userEvent.setup();
    renderLab(`/lab?scenario=${SID}&session=s-1`);
    // The collapsible block is its own anchor — a SIBLING of the five
    // locator sections (none of them occupied or displaced).
    const block = await screen.findByTestId("lab-hints-section", {}, { timeout: 3_000 });
    await user.click(screen.getByText("分阶段提示")); // open the fold
    expect(block).toBeInTheDocument();
    expect(screen.getByTestId("lab-hints-status")).toHaveTextContent("已揭示 1/3（本地记录，非服务端事实）");
    expect(screen.getByText("第一层提示内容")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /揭示下一条提示/ }));
    expect(screen.getByTestId("lab-hints-status")).toHaveTextContent("已揭示 2/3");
    // Same-key write-through from the console side.
    expect(window.localStorage.getItem(hintsStorageKey(SID))).toBe("2");
    // The five locator anchors remain intact for Stepper locating.
    for (const section of ["run", "diagnose", "inspect", "verify", "solution"]) {
      expect(screen.getByTestId(`lab-section-${section}`)).toBeInTheDocument();
    }
  });

  it("storage unavailable: reveal degrades to page memory with the honest note", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("denied", "SecurityError");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("denied", "SecurityError");
    });
    const user = userEvent.setup();
    renderLab(`/lab?scenario=${SID}`);
    const status = await screen.findByTestId("lab-hints-status", {}, { timeout: 3_000 });
    expect(screen.getByTestId("lab-hints-storage-unavailable")).toHaveTextContent("本地记录不可用，刷新将复位");
    expect(status).not.toHaveTextContent("本地记录，非服务端事实");
    await user.click(screen.getByRole("button", { name: /揭示下一条提示/ }));
    expect(status).toHaveTextContent("已揭示 1/3");
    expect(screen.getByText("第一层提示内容")).toBeInTheDocument();
    vi.restoreAllMocks();
    // Nothing was persisted (honest degradation, 伪装持久化 forbidden).
    expect(window.localStorage.getItem(hintsStorageKey(SID))).toBeNull();
  });
});
