// PID/metrics table (SPEC-403 §4.4, REQ-UI-403-003): presentation + the
// flat-scalar query body builder. The sim clock domain is MANDATORY
// (`sim:<session_id>`) — mixed-shape requests are a server 422, never a
// client guess. Series render wire names verbatim; points render via
// format.pointDisplay (missing ≠ zero). The page owns the query execution —
// this component emits the body (controlled presentation).
import { useEffect, useState } from "react";
import type { MetricsResponseDTO } from "../types";
import { Badge, EmptyState } from "../../../components/ui";
import { pointDisplay } from "./format";

/** The 15-item MVP metric catalog (SPEC-302 §4, names verbatim). */
export const METRIC_CATALOG: readonly string[] = [
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
];

/** Default bucket width for the page's first query (1 virtual second). */
const DEFAULT_STEP_NS = 1_000_000_000;

export function MetricsPanel({
  sessionId,
  virtualTimeNs,
  data,
  onQueryChange,
}: {
  sessionId: string;
  /** The session's virtual time (snapshot) — the default window end. */
  virtualTimeNs: number;
  data: MetricsResponseDTO | undefined;
  /** Emits the flat body whenever the query shape changes (page executes it). */
  onQueryChange: (body: {
    metric_names: string[];
    start_ns: number;
    end_ns: number;
    step_ns: number;
    clock_domain: string;
    allow_unknown: boolean;
  }) => void;
}) {
  const [endNs, setEndNs] = useState(String(virtualTimeNs));
  const [stepNs, setStepNs] = useState(String(DEFAULT_STEP_NS));

  useEffect(() => {
    onQueryChange({
      metric_names: [...METRIC_CATALOG],
      start_ns: 0,
      end_ns: Number(endNs) || 0,
      step_ns: Number(stepNs) || DEFAULT_STEP_NS,
      clock_domain: `sim:${sessionId}`,
      allow_unknown: false,
    });
  }, [sessionId, endNs, stepNs, onQueryChange]);

  const series = data?.data.series ?? [];

  return (
    <div className="dvb-mon-metrics">
      <div className="dvb-mon-querybar">
        <label>
          end_ns
          <input aria-label="end_ns" value={endNs} onChange={(e) => setEndNs(e.target.value)} />
        </label>
        <label>
          step_ns
          <input aria-label="step_ns" value={stepNs} onChange={(e) => setStepNs(e.target.value)} />
        </label>
        <span className="dvb-mon-note">clock_domain sim:{sessionId}（必填，缺省/混形状由服务端 422 拒绝）</span>
      </div>
      {series.length === 0 ? (
        <EmptyState title="无指标序列" note="该窗口内查询无返回序列（不代表指标为零）。" />
      ) : (
        <ul className="dvb-mon-rows">
          {series.map((s) => {
            const pid = s.dimensions?.pid;
            return (
              <li key={`${s.metric_name}@${s.aggregation}@${String(pid)}`} className="dvb-mon-row">
                <div className="dvb-mon-row-head">
                  <span className="dvb-mon-code">{s.metric_name}</span>
                  <Badge tone="neutral">{s.unit}</Badge>
                  <Badge tone="info">{s.aggregation}</Badge>
                  {typeof pid === "number" ? (
                    <Badge tone="neutral">PID {pid}</Badge>
                  ) : (
                    <Badge tone="neutral">会话级</Badge>
                  )}
                </div>
                <ul className="dvb-mon-points">
                  {(s.points ?? []).map((p) => {
                    const display = pointDisplay(p);
                    return (
                      <li key={display.start_ns} className="dvb-mon-point">
                        <span className="dvb-mon-point-window">
                          [{display.start_ns}, {display.end_ns}]
                        </span>
                        {display.kind === "missing" ? (
                          <span className="dvb-mon-missing">
                            <Badge tone="warn">缺失</Badge>
                          </span>
                        ) : (
                          <span className="dvb-mon-value">{display.text}</span>
                        )}
                        {display.flags.includes("nonfinal") && <Badge tone="warn">非终值</Badge>}
                        {display.flags.includes("revised") && <Badge tone="neutral">rev {p.revision}</Badge>}
                      </li>
                    );
                  })}
                </ul>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
