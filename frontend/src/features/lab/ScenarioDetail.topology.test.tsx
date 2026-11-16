// Scenario detail initial_topology readability (SPEC-408 §4.4
// REQ-UI-408-012 部分 / AC-408-07): stats line + Chinese-labelled structured
// rows + the raw camelCase document folded back verbatim inside <details>
// (键名原样 — layout translation only, NO key-name semantic translation, NO
// SVG). The lab-topology-view container keeps its test id; the raw fold
// keeps the authored 「{key} {value}」 lines visible to text (E2E wire-key
// assertions inside the container stay meaningful — #101 owns the spec).
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ScenarioDetailDTO } from "../../api";

vi.mock("../../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api")>();
  return {
    ...actual,
    getScenario: vi.fn(),
  };
});

import { getScenario } from "../../api";
import { ScenarioDetail } from "./ScenarioDetail";

const mocked = { getScenario: vi.mocked(getScenario) };

const TOPOLOGY = {
  topology_id: "topo-sc-01",
  revision: 1,
  nodes: [
    {
      nodeId: "gen-0",
      nodeType: "ts_generator",
      ports: [{ portId: "ts_out", direction: "out", plane: "MPEG_TS", maxConnections: 1 }],
    },
    {
      nodeId: "mux-0",
      nodeType: "ts_mux",
      ports: [{ portId: "pat_in", direction: "in", plane: "MPEG_TS", maxConnections: 2 }],
    },
  ],
  connections: [
    { connectionId: "c-0", from: { nodeId: "gen-0", portId: "ts_out" }, to: { nodeId: "mux-0", portId: "pat_in" } },
  ],
};

const DETAIL: ScenarioDetailDTO = {
  schema_version: "1.0",
  scenario_id: "5c010000-0000-4000-8000-000000000001",
  version: "1.0.0",
  content_hash: "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  title: "认识闭环：PAT 缺失",
  difficulty: "intro",
  initial_topology: TOPOLOGY,
  simulation_config: {},
  fault_plan: [],
  objectives: [],
  hints: [],
  pass_criteria: [{ criterion_id: "fault-cleared" }],
};

function renderDetail() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <ScenarioDetail scenarioId="5c010000-0000-4000-8000-000000000001" onBack={() => {}} onStart={() => {}} starting={false} startError={null} />
    </QueryClientProvider>,
  );
}

describe("ScenarioDetail — initial_topology readability (AC-408-07)", () => {
  it("renders the stats line 「N 节点 · M 连接 · topology_id/revision」", async () => {
    mocked.getScenario.mockResolvedValue(DETAIL);
    renderDetail();
    const stats = await screen.findByTestId("lab-topology-stats", {}, { timeout: 3_000 });
    expect(stats).toHaveTextContent("2 节点 · 1 连接 · topology_id topo-sc-01/revision 1");
  });

  it("renders Chinese-labelled structured rows (节点/端口/连接) with authored values verbatim", async () => {
    mocked.getScenario.mockResolvedValue(DETAIL);
    renderDetail();
    const structured = await screen.findByTestId("lab-topology-structured", {}, { timeout: 3_000 });
    expect(structured).toHaveTextContent("节点 gen-0（ts_generator）");
    expect(structured).toHaveTextContent("端口 ts_out · 方向 out · 平面 MPEG_TS · 连接上限 1");
    expect(structured).toHaveTextContent("节点 mux-0（ts_mux）");
    expect(structured).toHaveTextContent("端口 pat_in · 方向 in · 平面 MPEG_TS · 连接上限 2");
    expect(structured).toHaveTextContent("连接 c-0：gen-0:ts_out → mux-0:pat_in");
    // No SVG thumbnail (视觉美化出局).
    expect(structured.querySelector("svg")).toBeNull();
  });

  it("folds the raw camelCase document verbatim inside <details> 「查看原始文档（键名原样）」", async () => {
    mocked.getScenario.mockResolvedValue(DETAIL);
    renderDetail();
    const raw = await screen.findByTestId("lab-topology-raw", {}, { timeout: 3_000 });
    expect(raw).toHaveTextContent("查看原始文档（键名原样）");
    // 键名原样: the authored 「{key} {value}」 pairs stay present (as text
    // inside the fold — the #45 canonical-example keys are NOT rewritten).
    for (const wire of ["nodeId gen-0", "nodeType ts_generator", "nodeType ts_mux", "portId ts_out", "maxConnections 1", "connectionId c-0"]) {
      expect(raw).toHaveTextContent(wire);
    }
    // The raw fold lives INSIDE the lab-topology-view container (existing
    // container-scoped E2E assertions keep their scope).
    expect(screen.getByTestId("lab-topology-view")).toContainElement(raw);
  });
});
