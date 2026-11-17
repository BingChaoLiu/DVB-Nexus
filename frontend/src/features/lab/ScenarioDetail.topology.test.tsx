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

// SPEC-406 §Phase2 Lab Pack v2 场景承载 (#110 裁决「零特制」): the SC-06
// three-level subgraph (ts_generator → t2mi_encapsulator → t2mi_demux →
// ts_mux, T2MI-plane ports) renders through the SAME generic mechanism —
// stats line + structured rows + verbatim raw fold, no per-type code path.
const SC06_TOPOLOGY = {
  topology_id: "topo-labpack-v2",
  revision: 1,
  nodes: [
    {
      nodeId: "gen-0",
      nodeType: "ts_generator",
      config: {},
      ports: [{ portId: "ts_out", direction: "output", plane: "MPEG_TS", maxConnections: 1 }],
    },
    {
      nodeId: "enc-0",
      nodeType: "t2mi_encapsulator",
      config: { bbframe_params: { matype_value: "NM", upl: 188, n_ups: 3 }, plp_assignment: [{ plp_id: 0, source_tag: "main" }] },
      ports: [
        { portId: "inner_in", direction: "input", plane: "MPEG_TS", maxConnections: 1 },
        { portId: "t2mi_out", direction: "output", plane: "T2MI", maxConnections: 1 },
      ],
    },
    {
      nodeId: "dmx-0",
      nodeType: "t2mi_demux",
      config: { plp_filter: { mode: "expected", expected_plp: 0 } },
      ports: [
        { portId: "t2mi_in", direction: "input", plane: "T2MI", maxConnections: 1 },
        { portId: "inner_out", direction: "output", plane: "MPEG_TS", maxConnections: 1 },
      ],
    },
    {
      nodeId: "mux-0",
      nodeType: "ts_mux",
      config: {},
      ports: [{ portId: "ts_in_1", direction: "input", plane: "T2MI", maxConnections: 1 }],
    },
  ],
  connections: [
    { connectionId: "cx-0", from: { nodeId: "gen-0", portId: "ts_out" }, to: { nodeId: "enc-0", portId: "inner_in" } },
    { connectionId: "cx-1", from: { nodeId: "enc-0", portId: "t2mi_out" }, to: { nodeId: "dmx-0", portId: "t2mi_in" } },
    { connectionId: "cx-2", from: { nodeId: "dmx-0", portId: "inner_out" }, to: { nodeId: "mux-0", portId: "ts_in_1" } },
  ],
};

const SC06_DETAIL: ScenarioDetailDTO = {
  ...DETAIL,
  scenario_id: "5c010000-0000-4000-8000-000000000006",
  title: "封装错位：T2MI PLP 映射（业务漂移到非期望 PLP）",
  difficulty: "intermediate",
  initial_topology: SC06_TOPOLOGY,
};

describe("ScenarioDetail — Lab Pack v2 承载（SC-06 三级子图零特制）", () => {
  it("renders the SC-06 three-level subgraph through the SAME generic mechanism (统计行 + 结构化渲染)", async () => {
    mocked.getScenario.mockResolvedValue(SC06_DETAIL);
    renderDetail();
    const stats = await screen.findByTestId("lab-topology-stats", {}, { timeout: 3_000 });
    expect(stats).toHaveTextContent("4 节点 · 3 连接 · topology_id topo-labpack-v2/revision 1");
    const structured = await screen.findByTestId("lab-topology-structured", {}, { timeout: 3_000 });
    // The Phase 2 node types render verbatim — no special-casing, no label
    // rewriting (the node-type vocabulary itself is #135's registry face).
    expect(structured).toHaveTextContent("节点 enc-0（t2mi_encapsulator）");
    expect(structured).toHaveTextContent("端口 inner_in · 方向 input · 平面 MPEG_TS · 连接上限 1");
    expect(structured).toHaveTextContent("端口 t2mi_out · 方向 output · 平面 T2MI · 连接上限 1");
    expect(structured).toHaveTextContent("节点 dmx-0（t2mi_demux）");
    expect(structured).toHaveTextContent("端口 t2mi_in · 方向 input · 平面 T2MI · 连接上限 1");
    expect(structured).toHaveTextContent("连接 cx-1：enc-0:t2mi_out → dmx-0:t2mi_in");
  });
});
