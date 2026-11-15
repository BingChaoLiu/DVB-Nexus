// TopologyEditorPage seam tests (SPEC-401 §7.1/§7.4/§7.6 + AC-401-06).
// The api barrel is mocked at the import boundary (the page's single import
// point per SPEC-400 §4.1); assertions pin the save-flow call sequence and
// the in-place violation display without synthetic drag simulation.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { TopologyDTO, TopologySummaryDTO, TopologyValidationDTO } from "../../api";

vi.mock("../../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api")>();
  return {
    ...actual,
    listTopologies: vi.fn(),
    getTopology: vi.fn(),
    createTopology: vi.fn(),
    saveTopologyRevision: vi.fn(),
    validateTopology: vi.fn(),
  };
});

import { createTopology, getTopology, listTopologies, saveTopologyRevision, validateTopology } from "../../api";
import { TopologyEditorPage } from "./TopologyEditorPage";

const mocked = {
  listTopologies: vi.mocked(listTopologies),
  getTopology: vi.mocked(getTopology),
  createTopology: vi.mocked(createTopology),
  saveTopologyRevision: vi.mocked(saveTopologyRevision),
  validateTopology: vi.mocked(validateTopology),
};

// React Flow v12 needs ResizeObserver in jsdom (the canvas measures panes).
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
beforeEach(() => {
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
  vi.clearAllMocks();
  mocked.listTopologies.mockResolvedValue([]);
  mocked.validateTopology.mockResolvedValue({ ok: true, violations: [] } satisfies TopologyValidationDTO);
});

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <TopologyEditorPage />
    </QueryClientProvider>,
  );
}

const SAVED: TopologyDTO = {
  topology_id: "5f0e3d5e-1e2d-4c3b-9a8f-6b5a4c3d2e1f",
  revision: 1,
  nodes: [],
  connections: [],
};

describe("TopologyEditorPage — shell (§7.6)", () => {
  it("renders the declarative palette, canvas, panel and the save affordance", async () => {
    renderPage();
    expect(await screen.findByRole("complementary", { name: "节点面板" })).toBeInTheDocument();
    expect(screen.getByText("ts_generator")).toBeInTheDocument();
    expect(screen.getByText("ts_mux")).toBeInTheDocument();
    expect(screen.getByText("ts_demux")).toBeInTheDocument();
    expect(screen.getByText("ts_monitor")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "新建拓扑" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /保存为新 revision/ })).toBeDisabled();
    expect(screen.getByText("尚未校验")).toBeInTheDocument();
    expect(screen.getByTestId("dvb-topo-canvas")).toBeInTheDocument();
  });
});

describe("TopologyEditorPage — click-to-add and the fixed-step save flow (§7.4)", () => {
  it("palette click adds a registry node; save POSTs then validates then clears dirty", async () => {
    const user = userEvent.setup();
    mocked.createTopology.mockResolvedValue(SAVED);
    renderPage();

    await user.click(await screen.findByRole("button", { name: /TS 生成器/ }));
    const canvasNode = await screen.findByText("ts_generator", { selector: ".dvb-topo-node-type" });
    expect(canvasNode).toBeInTheDocument();

    const save = screen.getByRole("button", { name: /保存为新 revision/ });
    expect(save).toBeEnabled();
    await user.click(save);

    await waitFor(() => expect(mocked.createTopology).toHaveBeenCalledTimes(1));
    const body = mocked.createTopology.mock.calls[0]![0];
    expect(body.nodes).toHaveLength(1);
    expect(body.nodes![0]).toMatchObject({ node_id: "gen-0", node_type: "ts_generator" });
    expect(body.nodes![0]!.ports).toEqual([
      { port_id: "ts_out", direction: "output", plane: "MPEG_TS", max_connections: 1 },
    ]);
    // §7.4 fixed third step: validate right after the save
    await waitFor(() => expect(mocked.validateTopology).toHaveBeenCalledWith(SAVED.topology_id, 1));
    await waitFor(() => expect(screen.getByText("无违规")).toBeInTheDocument());
    expect(mocked.saveTopologyRevision).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.getByRole("button", { name: /保存为新 revision/ })).toBeDisabled());
  });

  it("a loaded topology saves via PUT and the panel shows path-addressed violations in place", async () => {
    const user = userEvent.setup();
    mocked.listTopologies.mockResolvedValue([{ topology_id: SAVED.topology_id, revision: 3 }] satisfies TopologySummaryDTO[]);
    mocked.getTopology.mockResolvedValue({
      ...SAVED,
      revision: 3,
      nodes: [
        {
          node_id: "mux-0",
          node_type: "ts_mux",
          config: {},
          ports: [
            { port_id: "ts_in_1", direction: "input", plane: "MPEG_TS", max_connections: 1 },
            { port_id: "ts_in_2", direction: "input", plane: "MPEG_TS", max_connections: 1 },
            { port_id: "ts_out", direction: "output", plane: "MPEG_TS", max_connections: 1 },
          ],
        },
      ],
    });
    mocked.validateTopology.mockResolvedValue({
      ok: false,
      violations: [
        { code: "SIM_TOPO_CARDINALITY", path: "nodes[mux-0].ports[ts_in_1]", message: "port carries 2 connections, above max_connections=1" },
      ],
    });
    mocked.saveTopologyRevision.mockResolvedValue({ ...SAVED, revision: 4 });

    renderPage();
    // auto-load the first listed topology (latest revision — no explicit pin)
    await waitFor(() => expect(mocked.getTopology).toHaveBeenCalledWith(SAVED.topology_id));
    expect(await screen.findByText("SIM_TOPO_CARDINALITY")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /TS 监测器/ })); // mark dirty
    await user.click(screen.getByRole("button", { name: /保存为新 revision/ }));

    await waitFor(() => expect(mocked.saveTopologyRevision).toHaveBeenCalledTimes(1));
    expect(mocked.saveTopologyRevision.mock.calls[0]![0]).toBe(SAVED.topology_id);
    await waitFor(() => expect(mocked.validateTopology).toHaveBeenCalledWith(SAVED.topology_id, 4));
  });
});

describe("TopologyEditorPage — AC-401-06 negative surface", () => {
  it("exposes no undo/redo, copy, multi-tab, plane-switch or diff entry points", async () => {
    renderPage();
    await screen.findByRole("complementary", { name: "节点面板" });
    for (const forbidden of [/撤销/, /重做/, /复制/, /粘贴/, /多标签|multi-tab/i, /切换平面|平面切换/, /对比|diff/i]) {
      expect(screen.queryByText(forbidden)).toBeNull();
    }
  });
});
