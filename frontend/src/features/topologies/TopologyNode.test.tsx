// TopologyNode rendering seam tests (SPEC-401 §5.1/§7.4): the port template
// drives Handle rendering (Handle id = port_id, input left / output right),
// violations light the node body and the violated Handle in place. Handles
// need the React Flow context, so renders wrap ReactFlowProvider.
import { ReactFlowProvider } from "@xyflow/react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { IllegalEndHandlesContext, illegalHandleKey } from "./connectionFeedback";

import type { TopologyFlowNode } from "./graphMapping";
import { TopologyNode, handlesForNode } from "./TopologyNode";

function nodeFixture(overrides?: Partial<TopologyFlowNode["data"]>): TopologyFlowNode {
  return {
    id: "gen-0",
    type: "topology",
    position: { x: 0, y: 0 },
    data: {
      node: {
        node_id: "gen-0",
        node_type: "ts_generator",
        config: {},
        ports: [
          { port_id: "ts_out", direction: "output", plane: "MPEG_TS", max_connections: 1 },
        ],
      },
      violationCodes: [],
      violationPorts: [],
      ...overrides,
    },
  };
}

const props = (node: TopologyFlowNode) => ({ id: node.id, data: node.data, type: "topology" as const, selected: false, dragging: false, zIndex: 0, isConnectable: true, positionAbsoluteX: 0, positionAbsoluteY: 0, dragHandle: undefined, waiter: undefined, draggable: false, selectable: false, deletable: false });

function renderNode(node: TopologyFlowNode) {
  return render(
    <ReactFlowProvider>
      <TopologyNode {...props(node)} />
    </ReactFlowProvider>,
  );
}

describe("TopologyNode — port template handles (Handle id = port_id)", () => {
  it("renders one handle per template port with the registry positions", () => {
    const node = nodeFixture();
    const handles = handlesForNode(node.data.node.ports);
    expect(handles).toEqual([
      { port_id: "ts_out", direction: "output", plane: "MPEG_TS", max_connections: 1, handleType: "source", position: "right" },
    ]);
  });

  it("renders input ports as target handles on the left", () => {
    const node = nodeFixture({
      node: {
        node_id: "mon-0",
        node_type: "ts_monitor",
        config: {},
        ports: [{ port_id: "ts_in", direction: "input", plane: "MPEG_TS", max_connections: 1 }],
      },
    });
    const handles = handlesForNode(node.data.node.ports);
    expect(handles[0]).toMatchObject({ port_id: "ts_in", handleType: "target", position: "left" });
    renderNode(node);
    expect(screen.getByTestId("dvb-topo-handle-ts_in")).toBeInTheDocument();
  });

  it("labels the node with its display name and wire node_type (declarative from the registry)", () => {
    renderNode(nodeFixture());
    expect(screen.getByText("TS 生成器")).toBeInTheDocument(); // registry label
    expect(screen.getByText("ts_generator")).toBeInTheDocument(); // wire node_type verbatim
  });

  it("lights the node body and the violated handle in place (§7.4)", () => {
    const node = nodeFixture({ violationCodes: ["SIM_TOPO_CARDINALITY"], violationPorts: ["ts_out"] });
    const { container } = renderNode(node);
    expect(container.querySelector(".dvb-topo-node.dvb-topo-node-violation")).not.toBeNull();
    expect(container.querySelector(".dvb-topo-handle.dvb-topo-handle-violation")).not.toBeNull();
  });

  it("renders the config pointer hint for types with a config_schema (#63 entry point)", () => {
    renderNode(nodeFixture());
    expect(screen.getByText("GeneratorConfigDTO")).toBeInTheDocument();
  });
});

// §7.6 拖拽预览全量降透明 (review-fix F2): the page computes the per-handle
// ILLEGAL END set during a drag and hands it down through
// IllegalEndHandlesContext — a handle in the set carries the
// dvb-topo-handle-illegal-end class (CSS dims it), one outside stays lit.
describe("TopologyNode — §7.6 illegal-end preview class (context consumption)", () => {
  const node = nodeFixture();

  it("a handle inside the illegal set carries dvb-topo-handle-illegal-end", () => {
    const { container } = render(
      <IllegalEndHandlesContext.Provider value={new Set([illegalHandleKey("gen-0", "ts_out")])}>
        <ReactFlowProvider>
          <TopologyNode {...props(node)} />
        </ReactFlowProvider>
      </IllegalEndHandlesContext.Provider>,
    );
    expect(container.querySelector(".dvb-topo-handle.dvb-topo-handle-illegal-end")).not.toBeNull();
  });

  it("a handle outside the illegal set (or idle: default empty context) stays un-classed", () => {
    const { container } = render(
      <IllegalEndHandlesContext.Provider value={new Set<string>()}>
        <ReactFlowProvider>
          <TopologyNode {...props(node)} />
        </ReactFlowProvider>
      </IllegalEndHandlesContext.Provider>,
    );
    expect(container.querySelector(".dvb-topo-handle-illegal-end")).toBeNull();
    // Default context (no provider) behaves the same idle way.
    const idle = renderNode(nodeFixture());
    expect(idle.container.querySelector(".dvb-topo-handle-illegal-end")).toBeNull();
  });
});

// SPEC-401 §Phase3 card status summary (ticket #169): health badge + key
// metrics — REGISTRY-driven (the card renders exactly the entry's
// status_metrics keys out of data.statusMetrics; no per-type card logic).
// Absent status data (idle canvas, no session face) renders nothing — the
// pre-Phase3 card face is byte-identical.
describe("TopologyNode — §Phase3 card status summary (health badge + key metrics)", () => {
  function tunerFixture(data: Partial<TopologyFlowNode["data"]> = {}): TopologyFlowNode {
    return {
      id: "tuner-a",
      type: "topology",
      position: { x: 0, y: 0 },
      data: {
        node: {
          node_id: "tuner-a",
          node_type: "tuner",
          config: {},
          ports: [{ port_id: "rf_in", direction: "input", plane: "SEC_CONTROL", max_connections: 1 }],
        },
        violationCodes: [],
        violationPorts: [],
        ...data,
      },
    };
  }

  it("renders the health badge with the wire enum value verbatim (ok/warn/error/idle)", () => {
    renderNode(tunerFixture({ health: "error" }));
    const badge = screen.getByTestId("dvb-topo-node-health");
    expect(badge).toHaveTextContent("error");
    expect(badge).toHaveAttribute("data-health", "error");
  });

  it("renders the registry status_metrics keys from the snapshot data (tuner: lock_state/ber_state)", () => {
    renderNode(
      tunerFixture({
        health: "ok",
        statusMetrics: { lock_state: "locked", ber_state: "normal", if_frequency_khz: 1250000 },
      }),
    );
    // only the registry-declared keys render (if_frequency_khz is NOT a card key)
    expect(screen.getByTestId("dvb-topo-node-metric-lock_state")).toHaveTextContent("locked");
    expect(screen.getByTestId("dvb-topo-node-metric-ber_state")).toHaveTextContent("normal");
    expect(screen.queryByTestId("dvb-topo-node-metric-if_frequency_khz")).toBeNull();
  });

  it("renders the lnb card keys (voltage/tone_actual/band_selected) from the same registry mechanism", () => {
    const lnb: TopologyFlowNode = {
      id: "lnb-0",
      type: "topology",
      position: { x: 0, y: 0 },
      data: {
        node: {
          node_id: "lnb-0",
          node_type: "lnb",
          config: {},
          ports: [{ port_id: "coax_out", direction: "output", plane: "SEC_CONTROL", max_connections: 2 }],
        },
        violationCodes: [],
        violationPorts: [],
        health: "warn",
        statusMetrics: { voltage: "13V", tone_actual: "continuous", band_selected: "high", tone_commanded: "none" },
      },
    };
    renderNode(lnb);
    expect(screen.getByTestId("dvb-topo-node-metric-voltage")).toHaveTextContent("13V");
    expect(screen.getByTestId("dvb-topo-node-metric-tone_actual")).toHaveTextContent("continuous");
    expect(screen.getByTestId("dvb-topo-node-metric-band_selected")).toHaveTextContent("high");
    expect(screen.queryByTestId("dvb-topo-node-metric-tone_commanded")).toBeNull();
  });

  it("renders the switch card key (port_selected) with a structured value as canonical JSON", () => {
    const sw: TopologyFlowNode = {
      id: "sw-0",
      type: "topology",
      position: { x: 0, y: 0 },
      data: {
        node: {
          node_id: "sw-0",
          node_type: "diseqc_switch",
          config: {},
          ports: [{ port_id: "coax_in", direction: "input", plane: "SEC_CONTROL", max_connections: 1 }],
        },
        violationCodes: [],
        violationPorts: [],
        health: "idle",
        statusMetrics: { port_selected: 2 },
      },
    };
    renderNode(sw);
    expect(screen.getByTestId("dvb-topo-node-metric-port_selected")).toHaveTextContent("2");
  });

  it("omits a metric row whose key is absent from the snapshot (missing ≠ zero, no invented value)", () => {
    renderNode(tunerFixture({ health: "idle", statusMetrics: {} }));
    expect(screen.queryByTestId("dvb-topo-node-metric-lock_state")).toBeNull();
    expect(screen.queryByTestId("dvb-topo-node-metric-ber_state")).toBeNull();
    expect(screen.getByTestId("dvb-topo-node-health")).toHaveTextContent("idle");
  });

  it("renders no status section without status data (idle canvas face unchanged)", () => {
    const { container } = renderNode(tunerFixture());
    expect(container.querySelector(".dvb-topo-node-status")).toBeNull();
    expect(screen.queryByTestId("dvb-topo-node-health")).toBeNull();
  });

  it("renders no status section for types without registry status_metrics (MVP/Phase 2 cards unchanged)", () => {
    const gen = nodeFixture({ health: "ok", statusMetrics: { lock_state: "locked" } });
    const { container } = renderNode(gen);
    expect(container.querySelector(".dvb-topo-node-status")).toBeNull();
  });
});
