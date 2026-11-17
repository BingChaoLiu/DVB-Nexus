// ExperimentConsole × GenerationFold wiring (SPEC-406 §Phase2): the fold
// mounts inside the Inspect section; a packet card's jump navigates to the
// #132 Monitor deep link with the view parameter appended — the Lab side
// builds the parameter string (string contract, no inspector import beyond
// the read-only view vocabulary). URL shape asserted, values shape-checked —
// never pinned to environment literals (§5-9/§5-10).
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider, useLocation } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { RunStatusDTO, ScenarioDetailDTO } from "../../api";

vi.mock("../../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api")>();
  return {
    ...actual,
    getScenario: vi.fn(),
    getSnapshot: vi.fn(),
    queryEvents: vi.fn(),
    listDiagnoses: vi.fn(),
    listSessionRuns: vi.fn(),
    getRun: vi.fn(),
  };
});

import { getRun, getScenario, getSnapshot, listDiagnoses, listSessionRuns, queryEvents } from "../../api";
import type { RunListItemDTO } from "../../api";
import { ExperimentConsole } from "./ExperimentConsole";

const mocked = {
  getScenario: vi.mocked(getScenario),
  getSnapshot: vi.mocked(getSnapshot),
  queryEvents: vi.mocked(queryEvents),
  listDiagnoses: vi.mocked(listDiagnoses),
  listSessionRuns: vi.mocked(listSessionRuns),
  getRun: vi.mocked(getRun),
};

const SID = "5c010000-0000-4000-8000-000000000001";
const SESSION = "6c020000-0000-4000-8000-000000000002";
const RUN = "run-1";
const SHA = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2";

const SCENARIO: ScenarioDetailDTO = {
  schema_version: "1.0",
  scenario_id: SID,
  version: "1.0.0",
  content_hash: "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  title: "封装错位：T2MI PLP 映射（业务漂移到非期望 PLP）",
  difficulty: "intermediate",
  initial_topology: { topology_id: "topo-labpack-v2", revision: 1, nodes: [], connections: [] },
  simulation_config: {},
  fault_plan: [{ fault_id: "fd000000-0000-4000-8000-00000000f6a6" }],
  objectives: [],
  hints: [],
  pass_criteria: [{ criterion_id: "fault-cleared" }],
};

/** The layered-run gen.* stream attributed to run-1 (payload keys per
 * #128/#129 — synthetic fixture, values pinned here are literals by
 * construction, not environment claims). */
const LAYERED_STREAM = [
  {
    journal_seq: 1,
    event_type: "gen.stage_started",
    severity: "info",
    payload: { layer: "TS" },
    scope: { session_id: SESSION, run_id: RUN },
  },
  {
    journal_seq: 2,
    event_type: "gen.stage_completed",
    severity: "info",
    payload: { layer: "TS", item_count: 188 },
    scope: { session_id: SESSION, run_id: RUN },
  },
  {
    journal_seq: 3,
    event_type: "gen.packet_sampled",
    severity: "info",
    payload: { layer: "T2MI", packet_index: 7, byte_size: 194, sha256: SHA },
    scope: { session_id: SESSION, run_id: RUN },
  },
];

const LAYERED_RUN: RunStatusDTO = {
  run_id: RUN,
  status: "completed",
  artifacts: [
    { artifact_id: "art-faulted-1", kind: "faulted_ts", sha256: "ab", byte_size: 1000, partial: false },
    { artifact_id: "art-log-1", kind: "log", sha256: "cd", byte_size: 10, partial: false },
  ],
};

function setupApiMocks(events: ReadonlyArray<unknown>) {
  mocked.getScenario.mockResolvedValue(SCENARIO);
  mocked.getSnapshot.mockResolvedValue({
    session_id: SESSION,
    revision: 1,
    lifecycle: "running",
    virtual_time_ns: 0,
    topology_revision: 1,
  });
  mocked.queryEvents.mockResolvedValue({ data: { sort: "journal_asc", items: [...events] } } as never);
  mocked.listDiagnoses.mockResolvedValue([]);
  mocked.listSessionRuns.mockResolvedValue([
    {
      run_id: RUN,
      status: "completed",
      submitted_at_ms: 1,
      fault_plan_present: true,
    } satisfies RunListItemDTO,
  ]);
  mocked.getRun.mockResolvedValue(LAYERED_RUN);
}

/** Navigation probe: the jump's landing URL rendered as text (URL shape
 * assertions read it — no Monitor mounting, that page is #134's seam). */
function LocationProbe() {
  const location = useLocation();
  return <div data-testid="probe-location">{`${location.pathname}${location.search}`}</div>;
}

function renderConsole() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(
    [
      {
        path: "/lab",
        element: (
          <ExperimentConsole
            scenarioId={SID}
            sessionId={SESSION}
            onBack={() => {}}
            // The layered run rides the page as a live row (the §7.3 carrier
            // posture) — the poller then pulls the REAL artifacts face from
            // getRun into page memory (derived §6.3 rows honestly carry no
            // artifact face — review-fix F1).
            initialRuns={[{ run_id: RUN, status: "running" }]}
          />
        ),
      },
      { path: "/monitor", element: <LocationProbe /> },
    ],
    { initialEntries: ["/lab"] },
  );
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { router };
}

beforeEach(() => {
  setupApiMocks(LAYERED_STREAM);
});

describe("ExperimentConsole — the 生成过程折叠区 wiring (SPEC-406 §Phase2)", () => {
  it("mounts the fold inside the console (summary signpost present without disturbing the eight-step sections)", async () => {
    renderConsole();
    expect(await screen.findByTestId("lab-gen-summary")).toHaveTextContent("生成过程");
    // The five locator sections survive untouched (八步闭环结构零改动).
    expect(screen.getByTestId("lab-section-run")).toBeInTheDocument();
    expect(screen.getByTestId("lab-section-inspect")).toBeInTheDocument();
    expect(screen.getByTestId("lab-section-verify")).toBeInTheDocument();
  });

  it("v1 face: zero gen.* events answers the honest empty face inside the fold", async () => {
    setupApiMocks([]);
    renderConsole();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("lab-gen-summary"));
    const empty = await screen.findByTestId("lab-gen-empty");
    expect(empty).toHaveTextContent("尚无分层生成事件");
    expect(empty).toHaveTextContent("无记录 ≠ 干净");
  });

  it("layered face: stage rows and sampled packets render; the jump lands on the Monitor deep link with the view parameter", async () => {
    const { router } = renderConsole();
    const user = userEvent.setup();
    // The poller pulls the completed layered run (with its artifacts face)
    // into page memory before the fold is opened.
    await waitFor(() => expect(screen.getByTestId(`lab-run-row-${RUN}`)).toHaveTextContent("completed"), {
      timeout: 3_000,
    });
    await user.click(await screen.findByTestId("lab-gen-summary"));
    expect(await screen.findByTestId("lab-gen-stage-TS")).toHaveTextContent("已完成 188 项");
    expect(screen.getByTestId("lab-gen-sample-3")).toHaveTextContent("T2MI");

    await user.click(screen.getByTestId("lab-gen-jump-3"));
    await screen.findByTestId("probe-location");
    const url = screen.getByTestId("probe-location").textContent ?? "";
    // The #132 string contract: /monitor?session=<uuid>&inspect_artifact=…&
    // inspect_pid=0&inspect_packet=<n>&view=<mapped> — shape asserted,
    // ids not pinned.
    expect(url).toMatch(/^\/monitor\?session=[0-9a-f-]{36}&inspect_artifact=art-faulted-1&inspect_pid=0&inspect_packet=7&view=t2mi$/);
    expect(url).toContain(encodeURIComponent(SESSION));
    void router;
  });
});
