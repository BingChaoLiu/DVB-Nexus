// TopologyEditorPage seam tests (SPEC-401 §7.1/§7.4/§7.6 + AC-401-06).
// The api barrel is mocked at the import boundary (the page's single import
// point per SPEC-400 §4.1); assertions pin the save-flow call sequence and
// the in-place violation display without synthetic drag simulation.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
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
      {/* The §4.5 guidance links (<Link>) need a router context; the page
          normally sits inside the app router (createAppRouter). */}
      <MemoryRouter initialEntries={["/topologies"]}>
        <TopologyEditorPage />
      </MemoryRouter>
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
  // #63 accommodation (approved AC-402-04): the save entry is gate-gated now,
  // so the flow leg uses a config_schema=null node (trivially complete); the
  // generator gate behavior is pinned by the dedicated test below and the
  // inspector suite.
  it("palette click adds a registry node; save POSTs then validates then clears dirty", async () => {
    const user = userEvent.setup();
    mocked.createTopology.mockResolvedValue(SAVED);
    renderPage();

    await user.click(await screen.findByRole("button", { name: /TS 监测器/ }));
    const canvasNode = await screen.findByText("ts_monitor", { selector: ".dvb-topo-node-type" });
    expect(canvasNode).toBeInTheDocument();

    const save = screen.getByRole("button", { name: /保存为新 revision/ });
    expect(save).toBeEnabled();
    await user.click(save);

    await waitFor(() => expect(mocked.createTopology).toHaveBeenCalledTimes(1));
    const body = mocked.createTopology.mock.calls[0]![0];
    expect(body.nodes).toHaveLength(1);
    expect(body.nodes![0]).toMatchObject({ node_id: "mon-0", node_type: "ts_monitor" });
    expect(body.nodes![0]!.ports).toEqual([
      { port_id: "ts_in", direction: "input", plane: "MPEG_TS", max_connections: 1 },
    ]);
    // §7.4 fixed third step: validate right after the save
    await waitFor(() => expect(mocked.validateTopology).toHaveBeenCalledWith(SAVED.topology_id, 1));
    await waitFor(() => expect(screen.getByText("无违规")).toBeInTheDocument());
    expect(mocked.saveTopologyRevision).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.getByRole("button", { name: /保存为新 revision/ })).toBeDisabled());
  });

  // #63 (SPEC-402 §7.6 G1): an incomplete generator config keeps the save
  // entry disabled — the 配置待填 edit-state gate, asserted at the page seam.
  it("an added generator with an empty config keeps the save entry disabled (gate G1)", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole("button", { name: /TS 生成器/ }));
    await screen.findByText("ts_generator", { selector: ".dvb-topo-node-type" });
    const save = screen.getByRole("button", { name: /保存为新 revision/ });
    expect(save).toBeDisabled();
    expect(mocked.createTopology).not.toHaveBeenCalled();
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
    // #63 accommodation (approved AC-402-04): with the gate live, a loaded
    // violation report blocks the save — so the in-place display assertion
    // moves to the post-save report (rev 4) while the PUT flow stays intact:
    // load → validate(rev 3) clean → dirty → PUT → validate(rev 4) violation.
    mocked.validateTopology
      .mockResolvedValueOnce({ ok: true, violations: [] } satisfies TopologyValidationDTO)
      .mockResolvedValueOnce({
        ok: false,
        violations: [
          { code: "SIM_TOPO_CARDINALITY", path: "nodes[mux-0].ports[ts_in_1]", message: "port carries 2 connections, above max_connections=1" },
        ],
      } satisfies TopologyValidationDTO);
    mocked.saveTopologyRevision.mockResolvedValue({ ...SAVED, revision: 4 });

    renderPage();
    // auto-load the first listed topology (latest revision — no explicit pin)
    await waitFor(() => expect(mocked.getTopology).toHaveBeenCalledWith(SAVED.topology_id));
    expect(await screen.findByText("无违规")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /TS 监测器/ })); // mark dirty (null-schema type: gate stays open)
    await user.click(screen.getByRole("button", { name: /保存为新 revision/ }));

    await waitFor(() => expect(mocked.saveTopologyRevision).toHaveBeenCalledTimes(1));
    expect(mocked.saveTopologyRevision.mock.calls[0]![0]).toBe(SAVED.topology_id);
    await waitFor(() => expect(mocked.validateTopology).toHaveBeenCalledWith(SAVED.topology_id, 4));
    expect(await screen.findByText("SIM_TOPO_CARDINALITY")).toBeInTheDocument();
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

describe("TopologyEditorPage — AC-402-04 no-session-entry assertion", () => {
  // SPEC-402 §12 AC-402-04（§6.2 实现归属）：编辑器内自身无 session 入口——
  // session/run 控制归 SPEC-403 monitor 与 SPEC-406 lab；本页只导出门判定
  // 纯函数（computeInspectorGate），不出现任何「启动 session」类控件。
  it("exposes no session-start or session-tracking entry points in the editor", async () => {
    renderPage();
    await screen.findByRole("complementary", { name: "节点面板" });
    // The session-entry vocabulary the owner regions use: the lab 开局 flow
    // (开局/开始实验), the monitor tracking entry (session id 以跟踪), and
    // generic 启动/创建 session wording — none may exist here.
    for (const forbidden of [/开局/, /开始实验/, /启动\s*session/i, /创建\s*session/i, /session\s*id/i, /跟踪/]) {
      expect(screen.queryByText(forbidden)).toBeNull();
    }
  });
});

// SPEC-408 §4.5 guidance faces at the page seam (AC-408-08 / AC-401-07):
// banner timing, empty-overlay show/dismiss, the gate-note three states plus
// the saveable zero-noise state, the hover-title removal and the per-save
// declaration. Connection-failure reasons live at the pure seams
// (graphMapping/connectionFeedback) and in e2e — no RF drag simulation here.
describe("TopologyEditorPage — §4.5 guidance faces", () => {
  it("renders the persistent guidance banner (页顶) with path-string links", async () => {
    renderPage();
    const banner = await screen.findByTestId("dvb-topo-guidance");
    expect(banner).toHaveTextContent("进阶工具");
    expect(banner).toHaveTextContent("场景自带的初始拓扑"); // 场景初始拓扑 term
    expect(banner).toHaveTextContent("不会读取这里保存的拓扑"); // 已保存拓扑 side
    expect(banner).toHaveTextContent("拿到第一次 PASS 之后再回来探索不迟");
    expect(screen.getByRole("link", { name: "[去 Lab →]" })).toHaveAttribute("href", "/lab");
    expect(screen.getByRole("link", { name: "[回主页 →]" })).toHaveAttribute("href", "/");
  });

  it("empty canvas shows the three-question overlay; the first node removes it", async () => {
    const user = userEvent.setup();
    renderPage();
    const overlay = await screen.findByTestId("dvb-topo-empty-overlay");
    expect(overlay).toHaveTextContent("这是什么");
    expect(overlay).toHaveTextContent("为什么是空的");
    expect(overlay).toHaveTextContent("下一步");
    expect(screen.getByRole("link", { name: "[去 Lab 开始主干旅程 →]" })).toHaveAttribute("href", "/lab");

    await user.click(await screen.findByRole("button", { name: /TS 监测器/ }));
    await screen.findByText("ts_monitor", { selector: ".dvb-topo-node-type" });
    expect(screen.queryByTestId("dvb-topo-empty-overlay")).toBeNull();
  });

  it("gate states: 无修改 → 没有待保存的修改; 配置待填 gate → 暂不能保存：1 处待处理 with its line only; hover title撤除", async () => {
    const user = userEvent.setup();
    renderPage();
    const note = await screen.findByTestId("dvb-topo-gate-note");
    expect(note).toHaveTextContent("没有待保存的修改");

    await user.click(await screen.findByRole("button", { name: /TS 生成器/ }));
    await screen.findByText("ts_generator", { selector: ".dvb-topo-node-type" });
    expect(screen.getByTestId("dvb-topo-gate-note")).toHaveTextContent("暂不能保存：1 处待处理");
    expect(screen.getByText("配置待填 → 右侧「节点属性」补全")).toBeInTheDocument();
    expect(screen.queryByText("校验违规 → 见下方「校验」面板")).toBeNull();
    expect(screen.queryByText("表单字段有误")).toBeNull();
    // §4.5 item 3: the hover-only title is GONE (invisible on touch = not honest)
    expect(screen.getByRole("button", { name: /保存为新 revision/ })).not.toHaveAttribute("title");
  });

  it("saveable → zero noise; saving → 正在保存…; every save shows its own revision declaration", async () => {
    const user = userEvent.setup();
    let resolveFirst!: (topology: TopologyDTO) => void;
    mocked.createTopology.mockImplementationOnce(
      () => new Promise<TopologyDTO>((resolve) => { resolveFirst = resolve; }),
    );
    renderPage();
    await user.click(await screen.findByRole("button", { name: /TS 监测器/ })); // null-schema type → gate stays open
    await screen.findByText("ts_monitor", { selector: ".dvb-topo-node-type" });
    expect(screen.queryByTestId("dvb-topo-gate-note")).toBeNull(); // saveable = zero noise

    const save = screen.getByRole("button", { name: /保存为新 revision/ });
    expect(save).toBeEnabled();
    await user.click(save);
    expect(await screen.findByTestId("dvb-topo-gate-note")).toHaveTextContent("正在保存…");
    resolveFirst(SAVED);
    const note = await screen.findByTestId("dvb-topo-save-note");
    expect(note).toHaveTextContent("已保存为 revision 1。");
    expect(note).toHaveTextContent("此处保存的拓扑仅供本模块载入与校验；Lab 场景使用场景自带初始拓扑，不会自动使用它。");
    await waitFor(() => expect(screen.getByTestId("dvb-topo-gate-note")).toHaveTextContent("没有待保存的修改"));

    // EVERY save: a second save updates the declaration to the new revision
    mocked.saveTopologyRevision.mockResolvedValue({ ...SAVED, revision: 2 });
    await user.click(screen.getByRole("button", { name: /TS 监测器/ })); // mark dirty again (mon-1)
    await user.click(screen.getByRole("button", { name: /保存为新 revision/ }));
    await waitFor(() => expect(mocked.saveTopologyRevision).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByTestId("dvb-topo-save-note")).toHaveTextContent("已保存为 revision 2。"));
  });
});

// SPEC-401 §Phase3 card summary + SPEC-404 §Phase3 detail panel (ticket #169):
// the ?session=<id> deep link wires the page-level state faces — the
// registry-derived SPEC-305 §Phase3 query (namespace rf/sec + the three
// state-domain node types), the card status summary from the merged snapshot
// stream, and the always-present detail panel (honest no-session face when
// absent). The stream module is stubbed (no WS in jsdom; the journal tail
// rides the cache the stream would update).
vi.mock("../monitor/stream/useSessionStream", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../monitor/stream/useSessionStream")>();
  return {
    ...actual,
    useSessionStream: () => ({ status: "idle" as const, closeCode: null }),
  };
});

vi.mock("../../api/endpoints/observation", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api/endpoints/observation")>();
  return {
    ...actual,
    queryStateObservedEvents: vi.fn(),
  };
});

import { queryStateObservedEvents } from "../../api/endpoints/observation";

const queryStateObservedEventsMock = vi.mocked(queryStateObservedEvents);

/** A tuner snapshot for the palette-dropped node id (tuner-0) — rf.state_observed
 * envelope, NodeEvalResult-shaped JSON-safe payload (SPEC-303 §Phase3). */
const TUNER_ENVELOPE = {
  event_type: "rf.state_observed",
  journal_seq: 10,
  severity: "info",
  correlation: { node_id: "tuner-0" },
  payload: {
    node_id: "tuner-0",
    health: "error",
    causes: [{ node_id: "lnb-0" }],
    source: "state_evaluator",
    confidence: "simulated",
    lock_state: "unlocked",
    ber_state: "severe",
  },
};

describe("TopologyEditorPage — §Phase3 session state faces (ticket #169)", () => {
  function renderPageAt(search: string) {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[`/topologies${search}`]}>
          <TopologyEditorPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );
  }

  it("without a tracked session the detail panel renders the honest no-session note", async () => {
    renderPageAt("");
    expect(await screen.findByTestId("dvb-state-panel")).toBeInTheDocument();
    expect(screen.getByTestId("dvb-state-panel-empty")).toHaveTextContent("未携带 session 深链");
    expect(queryStateObservedEventsMock).not.toHaveBeenCalled();
  });

  it("with ?session the state_observed read path fires with the registry-derived filter face", async () => {
    queryStateObservedEventsMock.mockResolvedValue({
      request_id: "r",
      scope: { tenant_id: "local", session_id: "s-9" },
      data: { sort: "journal_desc", items: [TUNER_ENVELOPE] },
    } as never);
    renderPageAt("?session=s-9");
    await waitFor(() => expect(queryStateObservedEventsMock).toHaveBeenCalled());
    expect(queryStateObservedEventsMock.mock.calls[0]![0]).toBe("s-9");
    expect(queryStateObservedEventsMock.mock.calls[0]![1]).toMatchObject({
      namespace: ["rf", "sec"],
      node_type: ["lnb", "tuner", "diseqc_switch"],
    });
  });

  it("the tuner card renders the health badge + registry status_metrics from the merged snapshot stream", async () => {
    const user = userEvent.setup();
    queryStateObservedEventsMock.mockResolvedValue({
      request_id: "r",
      scope: { tenant_id: "local", session_id: "s-9" },
      data: { sort: "journal_desc", items: [TUNER_ENVELOPE] },
    } as never);
    renderPageAt("?session=s-9");
    // let the snapshot query settle first (the immediate re-render churn can
    // otherwise detach the palette button mid-click)
    await waitFor(() => expect(queryStateObservedEventsMock).toHaveBeenCalled());
    await user.click(screen.getByRole("button", { name: /卫星调谐器/ }));
    await screen.findByText("tuner", { selector: ".dvb-topo-node-type" }); // wire node_type verbatim (id rides data-node-id)
    // card status summary: health badge (wire value verbatim) + the two
    // registry-declared keys only (ber_state yes, causes no)
    expect(await screen.findByTestId("dvb-topo-node-health")).toHaveTextContent("error");
    expect(screen.getByTestId("dvb-topo-node-metric-lock_state")).toHaveTextContent("unlocked");
    expect(screen.getByTestId("dvb-topo-node-metric-ber_state")).toHaveTextContent("severe");
  });
});
