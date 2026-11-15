// PID/metrics table (SPEC-403 §4.4, AC-403-03): the SPEC-302 §4 catalog as
// the default query set, the flat body with the mandatory sim clock domain,
// and the missing≠zero presentation via format.pointDisplay.
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { MetricsResponseDTO } from "../types";
import { METRIC_CATALOG, MetricsPanel } from "./MetricsPanel";

const response = (series: MetricsResponseDTO["data"]["series"]): MetricsResponseDTO => ({
  request_id: "req-1",
  scope: { tenant_id: "local", session_id: "s-1" },
  data: { series, bucket_convention: "[start,end)", clock_domain: "sim:s-1" },
});

const base = {
  request_id: "req-1",
  scope: { tenant_id: "local", session_id: "s-1" },
  data: { series: [], bucket_convention: "[start,end)", clock_domain: "sim:s-1" },
} satisfies MetricsResponseDTO;

describe("METRIC_CATALOG — the 15-item SPEC-302 §4 catalog (verbatim)", () => {
  it("is exactly the frozen MVP metric name set", () => {
    expect([...METRIC_CATALOG].sort()).toEqual(
      [
        "ts.packet_rate",
        "ts.bitrate",
        "ts.continuity_error_total",
        "ts.pcr_jitter_ns",
        "ts.pcr_repetition_gap_ns",
        "ts.null_packet_ratio",
        "ts.scrambled_packet_ratio",
        "psi.section_repetition_gap_ms",
        "simulation.virtual_time_ns",
        "simulation.event_lag_ns",
        "topology.degraded_node_count",
        "observation.ingest_events_total",
        "observation.duplicate_events_total",
        "observation.consumer_lag_events",
        "observation.alerts_active",
      ].sort(),
    );
  });
});

describe("MetricsPanel — default query body", () => {
  it("emits the flat body with the sim clock domain on mount", () => {
    const onQueryChange = vi.fn();
    render(<MetricsPanel sessionId="s-1" virtualTimeNs={5_000_000_000} data={undefined} onQueryChange={onQueryChange} />);
    expect(onQueryChange).toHaveBeenCalledExactlyOnceWith({
      metric_names: expect.any(Array),
      start_ns: 0,
      end_ns: 5_000_000_000,
      step_ns: expect.any(Number),
      clock_domain: "sim:s-1",
      allow_unknown: false,
    });
    const body = onQueryChange.mock.calls[0]![0] as { metric_names: string[] };
    expect(body.metric_names.sort()).toEqual([...METRIC_CATALOG].sort());
  });

  it("emits a changed window when the user edits end_ns", async () => {
    const onQueryChange = vi.fn();
    render(
      <MetricsPanel sessionId="s-1" virtualTimeNs={5_000_000_000} data={undefined} onQueryChange={onQueryChange} />,
    );
    await userEvent.type(screen.getByLabelText("end_ns"), "0");
    const last = onQueryChange.mock.lastCall![0] as { end_ns: number; clock_domain: string };
    expect(last.end_ns).toBe(5_000_000_000_0); // typed extra 0 appended
    expect(last.clock_domain).toBe("sim:s-1");
  });
});

describe("MetricsPanel — series presentation", () => {
  it("renders metric_name/unit/aggregation verbatim per series row", () => {
    render(
      <MetricsPanel
        sessionId="s-1"
        virtualTimeNs={1_000}
        onQueryChange={vi.fn()}
        data={response([
          {
            metric_name: "ts.bitrate",
            unit: "bit/s",
            value_type: "gauge",
            aggregation: "avg",
            clock_domain: "sim:s-1",
            points: [{ start_ns: 0, end_ns: 1_000, value: 3_008_000, quality: ["good"], revision: 1, is_final: true }],
          },
        ])}
      />,
    );
    expect(screen.getByText("ts.bitrate")).toBeInTheDocument();
    expect(screen.getByText("bit/s")).toBeInTheDocument();
    expect(screen.getByText("avg")).toBeInTheDocument();
    expect(screen.getByText("3008000")).toBeInTheDocument();
  });

  it("renders a missing point as 缺失 — never 0, never dropped", () => {
    render(
      <MetricsPanel
        sessionId="s-1"
        virtualTimeNs={2_000}
        onQueryChange={vi.fn()}
        data={response([
          {
            metric_name: "ts.pcr_jitter_ns",
            unit: "ns",
            value_type: "histogram",
            aggregation: "avg",
            clock_domain: "sim:s-1",
            points: [
              { start_ns: 0, end_ns: 1_000, value: null, quality: ["missing"], revision: 1, is_final: true },
              { start_ns: 1_000, end_ns: 2_000, value: 0, quality: ["good"], revision: 1, is_final: true },
            ],
          },
        ])}
      />,
    );
    expect(screen.getByText("缺失")).toBeInTheDocument();
    // the genuine zero in the second point still renders as 0
    expect(screen.getByText("0")).toBeInTheDocument();
  });

  it("marks non-final points and revisions", () => {
    render(
      <MetricsPanel
        sessionId="s-1"
        virtualTimeNs={1_000}
        onQueryChange={vi.fn()}
        data={response([
          {
            metric_name: "observation.consumer_lag_events",
            unit: "events",
            value_type: "gauge",
            aggregation: "last",
            clock_domain: "sim:s-1",
            points: [{ start_ns: 0, end_ns: 1_000, value: 3, quality: ["good"], revision: 2, is_final: false }],
          },
        ])}
      />,
    );
    expect(screen.getByText(/非终值/)).toBeInTheDocument();
    expect(screen.getByText(/rev 2/)).toBeInTheDocument();
  });

  it("groups series carrying a pid dimension under a PID label", () => {
    render(
      <MetricsPanel
        sessionId="s-1"
        virtualTimeNs={1_000}
        onQueryChange={vi.fn()}
        data={response([
          {
            metric_name: "ts.packet_rate",
            unit: "packets/s",
            value_type: "gauge",
            aggregation: "avg",
            clock_domain: "sim:s-1",
            dimensions: { pid: 256 },
            points: [{ start_ns: 0, end_ns: 1_000, value: 100, quality: ["good"], revision: 1, is_final: true }],
          },
        ])}
      />,
    );
    expect(screen.getByText("PID 256")).toBeInTheDocument();
  });

  it("renders an explicit empty state when the answer carries no series", () => {
    render(<MetricsPanel sessionId="s-1" virtualTimeNs={1_000} onQueryChange={vi.fn()} data={base} />);
    expect(screen.getByText(/无指标序列/)).toBeInTheDocument();
  });
});
