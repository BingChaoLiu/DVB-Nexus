// NodeStateDetailPanel seam tests (SPEC-404 §Phase3 节点详情面板, ticket #169):
// full metrics generic list rendering (no skeuomorphic controls), CauseRef
// chain with canvas-locate jumps, honesty rows verbatim (source/confidence
// wire values — the presentation layer never relabels parsed/measured), and
// the honest empty faces (缺失 ≠ 零). Presentational seam: data flows in via
// props (the page owns the query/subscription wiring — useNodeStateSnapshots).
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  extractStateObservedSnapshots,
  type StateObservedSnapshot,
} from "./nodeStateSummary";
import { NodeStateDetailPanel } from "./NodeStateDetailPanel";

function tunerEnvelope(seq: number, payload: Record<string, unknown>): Record<string, unknown> {
  return {
    event_type: "rf.state_observed",
    journal_seq: seq,
    correlation: { node_id: "tuner-a" },
    payload: { node_id: "tuner-a", health: "ok", causes: [], source: "state_evaluator", confidence: "simulated", ...payload },
  };
}

function snapshotsOf(items: Record<string, unknown>[]): StateObservedSnapshot[] {
  return extractStateObservedSnapshots(items);
}

const baseSnapshots = snapshotsOf([
  tunerEnvelope(10, { lock_state: "locked", if_frequency_khz: 1250000, ber_state: "normal", locked_transponder_id: "tp-1" }),
]);

describe("NodeStateDetailPanel — honest non-ready faces (no fake panel)", () => {
  it("no tracked session → explicit wayfinding note (no snapshot list)", () => {
    render(<NodeStateDetailPanel sessionId={null} node={null} snapshots={[]} />);
    const empty = screen.getByTestId("dvb-state-panel-empty");
    expect(empty).toHaveTextContent("未携带 session 深链");
    expect(empty).toHaveTextContent("?session=");
  });

  it("no selected node → the click-a-RF/SEC-node pointer", () => {
    render(<NodeStateDetailPanel sessionId="s-1" node={null} snapshots={[]} />);
    expect(screen.getByTestId("dvb-state-panel-empty")).toHaveTextContent("未选中节点");
  });

  it("a non-state-domain node → honest 非状态域 note (no invented snapshot)", () => {
    render(<NodeStateDetailPanel sessionId="s-1" node={{ node_id: "mon-0", node_type: "ts_monitor" }} snapshots={baseSnapshots} />);
    expect(screen.getByTestId("dvb-state-panel-empty")).toHaveTextContent("非状态域节点");
    expect(screen.getByTestId("dvb-state-panel-empty")).toHaveTextContent("ts_monitor");
  });

  it("state-domain node with no snapshot yet → 缺失 ≠ 零 honest empty", () => {
    render(<NodeStateDetailPanel sessionId="s-1" node={{ node_id: "tuner-b", node_type: "tuner" }} snapshots={[]} />);
    const empty = screen.getByTestId("dvb-state-panel-empty");
    expect(empty).toHaveTextContent("尚无 state_observed 快照");
    expect(empty).toHaveTextContent("缺失 ≠ 零");
  });
});

describe("NodeStateDetailPanel — full metrics generic list (registry-driven, 非拟物)", () => {
  it("renders the node header with health badge + honesty source/confidence row verbatim", () => {
    render(<NodeStateDetailPanel sessionId="s-1" node={{ node_id: "tuner-a", node_type: "tuner" }} snapshots={baseSnapshots} />);
    expect(screen.getByTestId("dvb-state-panel")).toHaveTextContent("tuner-a");
    expect(screen.getByTestId("dvb-state-panel")).toHaveTextContent("tuner");
    expect(screen.getByTestId("dvb-state-panel-health")).toHaveTextContent("ok");
    const honesty = screen.getByTestId("dvb-state-panel-honesty");
    expect(honesty).toHaveTextContent("source: state_evaluator");
    expect(honesty).toHaveTextContent("confidence: simulated");
  });

  it("renders EVERY payload metric key (全量) as a generic key/value row", () => {
    render(<NodeStateDetailPanel sessionId="s-1" node={{ node_id: "tuner-a", node_type: "tuner" }} snapshots={baseSnapshots} />);
    expect(screen.getByTestId("dvb-state-panel-metric-lock_state")).toHaveTextContent("locked");
    expect(screen.getByTestId("dvb-state-panel-metric-if_frequency_khz")).toHaveTextContent("1250000");
    expect(screen.getByTestId("dvb-state-panel-metric-ber_state")).toHaveTextContent("normal");
    expect(screen.getByTestId("dvb-state-panel-metric-locked_transponder_id")).toHaveTextContent("tp-1");
  });

  it("renders wire null metrics as null (honest null ≠ zero)", () => {
    const snapshots = snapshotsOf([
      tunerEnvelope(11, { lock_state: "unlocked", if_frequency_khz: 1250000, ber_state: "severe", locked_transponder_id: null, stale: true }),
    ]);
    render(<NodeStateDetailPanel sessionId="s-1" node={{ node_id: "tuner-a", node_type: "tuner" }} snapshots={snapshots} />);
    expect(screen.getByTestId("dvb-state-panel-metric-locked_transponder_id")).toHaveTextContent("null");
    expect(screen.getByTestId("dvb-state-panel-metric-stale")).toHaveTextContent("true");
    // latest snapshot wins (seq 11 over seq-less fixtures)
    expect(screen.getByTestId("dvb-state-panel-metric-lock_state")).toHaveTextContent("unlocked");
  });

  it("renders the lnb sec.* payload with its full key set through the same generic list", () => {
    const snapshots = snapshotsOf([
      {
        event_type: "sec.state_observed",
        journal_seq: 20,
        correlation: { node_id: "lnb-0" },
        payload: {
          node_id: "lnb-0",
          health: "warn",
          causes: [],
          source: "state_evaluator",
          confidence: "simulated",
          voltage: "13V",
          tone_commanded: "none",
          tone_actual: "continuous",
          tone_composite: "none",
          band_selected: "high",
          lo_frequency_khz: 10600,
          polarization_delivered: "vertical",
          short_circuit_state: "normal",
          ub_assignments: [],
        },
      },
    ]);
    render(<NodeStateDetailPanel sessionId="s-1" node={{ node_id: "lnb-0", node_type: "lnb" }} snapshots={snapshots} />);
    for (const key of ["voltage", "tone_commanded", "tone_actual", "tone_composite", "band_selected", "lo_frequency_khz", "polarization_delivered", "short_circuit_state"]) {
      expect(screen.getByTestId(`dvb-state-panel-metric-${key}`)).toBeInTheDocument();
    }
    expect(screen.getByTestId("dvb-state-panel-metric-ub_assignments")).toHaveTextContent("[]");
  });
});

describe("NodeStateDetailPanel — CauseRef chain (指向根因节点可跳转画布定位)", () => {
  it("renders cause entries with node_id (+port_id) and jumps to canvas locate on click", async () => {
    const onLocate = vi.fn();
    const snapshots = snapshotsOf([
      tunerEnvelope(12, {
        lock_state: "unlocked",
        ber_state: "severe",
        causes: [
          { node_id: "lnb-0", port_id: "coax_out" },
          { node_id: "sw-0" },
        ],
      }),
    ]);
    render(
      <NodeStateDetailPanel
        sessionId="s-1"
        node={{ node_id: "tuner-a", node_type: "tuner" }}
        snapshots={snapshots}
        onLocate={onLocate}
      />,
    );
    expect(screen.getByTestId("dvb-state-panel-causes")).toBeInTheDocument();
    expect(screen.getByTestId("dvb-state-panel-cause-0")).toHaveTextContent("lnb-0");
    expect(screen.getByTestId("dvb-state-panel-cause-0")).toHaveTextContent("coax_out");
    expect(screen.getByTestId("dvb-state-panel-cause-1")).toHaveTextContent("sw-0");
    await userEvent.click(screen.getByTestId("dvb-state-panel-locate-0"));
    expect(onLocate).toHaveBeenCalledWith("lnb-0");
    await userEvent.click(screen.getByTestId("dvb-state-panel-locate-1"));
    expect(onLocate).toHaveBeenCalledWith("sw-0");
  });

  it("no causes in the payload → explicit 无 CauseRef 记录 line (not silence)", () => {
    render(<NodeStateDetailPanel sessionId="s-1" node={{ node_id: "tuner-a", node_type: "tuner" }} snapshots={baseSnapshots} />);
    expect(screen.getByTestId("dvb-state-panel-causes")).toHaveTextContent("无 CauseRef 记录");
  });

  it("locate is optional — causes render without a jump control when no onLocate is wired", () => {
    const snapshots = snapshotsOf([tunerEnvelope(12, { lock_state: "unlocked", causes: [{ node_id: "lnb-0" }] })]);
    render(<NodeStateDetailPanel sessionId="s-1" node={{ node_id: "tuner-a", node_type: "tuner" }} snapshots={snapshots} />);
    expect(screen.getByTestId("dvb-state-panel-cause-0")).toHaveTextContent("lnb-0");
    expect(screen.queryByTestId("dvb-state-panel-locate-0")).toBeNull();
  });
});
