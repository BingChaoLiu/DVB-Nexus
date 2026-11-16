// Overview card + run trigger (SPEC-403 §4.3, REQ-UI-403-002): the summary
// five-field card (SummaryDataDTO) and the session full view (SnapshotDTO
// fields — virtual time, node health, active faults, latest artifact refs).
// The run trigger is the E2E Generate/Recover UI anchor: an empty-plan run
// submission (config editable, fault_plan always [] — the fault-plan editor
// is SPEC-406 scenario context). Presentation is controlled; the page owns
// queries, submission and polling.
import { useState } from "react";
import type { ReactNode } from "react";
import type { RunStatusDTO, SnapshotDTO, SummaryDataDTO } from "../types";
import { Badge, Panel } from "../../../components/ui";
import { MONITOR_EMPTY_STATE_COPY } from "../copy";
import { ThreeQuestionState } from "../ThreeQuestionState";

/**
 * The frozen golden geometry (#58 pull-safe config, SPEC-108 §4 wire shape)
 * as the page default — identical values to e2e/helpers GOLDEN_RUN_CONFIG so
 * UI-driven and REST-driven runs exercise the same generator face.
 */
export const DEFAULT_RUN_CONFIG_JSON = JSON.stringify({
  schema_version: 1,
  profile: "analysis_only",
  deterministic: true,
  seed: 1234567,
  initial_media_clock_27mhz: 0,
  target_bitrate_bps: 3008000,
  output_packet_count: 600,
  program: {
    transport_stream_id: 1,
    program_number: 1,
    pmt_pid: 4096,
    pcr_pid: 256,
    version_number: 0,
    program_descriptors: "",
    streams: [
      { pid: 256, stream_type: 27, stream_id: 224, bitrate_bps: 120320, payload_profile: "synthetic_test_data", payload_seed_offset: 0 },
      { pid: 257, stream_type: 3, stream_id: 192, bitrate_bps: 60160, payload_profile: "synthetic_test_data", payload_seed_offset: 1 },
    ],
  },
  pat_period_ms: 101,
  pmt_period_ms: 103,
  pcr_interval_ms: 40,
  pcr_insertion_policy: "payload_packet_first",
});

const HEALTH_TONE: Record<string, "good" | "warn" | "bad" | "neutral"> = {
  healthy: "good",
  degraded: "warn",
  failed: "bad",
};

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <span className="dvb-mon-field">
      <span className="dvb-mon-field-label">{label}</span> {children}
    </span>
  );
}

export function OverviewCard({
  summary,
  snapshot,
}: {
  summary: SummaryDataDTO | undefined;
  snapshot: SnapshotDTO | undefined;
}) {
  if (summary === undefined && snapshot === undefined) {
    // §4.6 Monitor 组行 2(文案逐字):快照数据未到达是诚实态,非缺陷。
    return <ThreeQuestionState copy={MONITOR_EMPTY_STATE_COPY.overview} />;
  }
  const nodeStates = Object.values(snapshot?.node_states ?? {});
  return (
    <div className="dvb-mon-overview">
      {summary !== undefined && (
        <div className="dvb-mon-row-head">
          <Field label="tenant_id">{summary.tenant_id}</Field>
          <Field label="session_id">{summary.session_id}</Field>
          <Field label="journal_seq_watermark">{summary.journal_seq_watermark}</Field>
          <Field label="event_count">{summary.event_count}</Field>
          <Field label="active_alert_count">{summary.active_alert_count}</Field>
          <Field label="schema_version">{summary.schema_version}</Field>
        </div>
      )}
      {snapshot !== undefined && (
        <>
          <div className="dvb-mon-line">
            <Field label="virtual_time_ns">{snapshot.virtual_time_ns}</Field>
            <Field label="revision">{snapshot.revision}</Field>
          </div>
          <div className="dvb-mon-line">
            {nodeStates.map((node) => (
              <span key={node.node_id} className="dvb-mon-node">
                {node.node_id} <Badge tone={HEALTH_TONE[node.health] ?? "neutral"}>{node.health}</Badge>
              </span>
            ))}
          </div>
          {(snapshot.active_faults?.length ?? 0) > 0 && (
            <div className="dvb-mon-line">
              active_faults:{" "}
              {(snapshot.active_faults ?? []).map((fault) => (
                <span key={fault.fault_id} className="dvb-mon-node">
                  {fault.fault_id} <Badge tone="warn">{fault.state}</Badge>
                </span>
              ))}
            </div>
          )}
          {(snapshot.latest_artifact_refs?.length ?? 0) > 0 && (
            <div className="dvb-mon-line">
              latest_artifact_refs:{" "}
              {(snapshot.latest_artifact_refs ?? []).map((ref) => (
                <span key={ref.artifact_id} className="dvb-mon-node">
                  {ref.artifact_id} <Badge tone="info">{ref.kind}</Badge> <Badge tone="neutral">{ref.status}</Badge>
                </span>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

export function RunTrigger({
  onSubmit,
  runs,
  busy,
}: {
  /** Called with the parsed config object; fault_plan is always [] here. */
  onSubmit: (config: unknown) => void;
  /** Run statuses observed on the page (the run registry). */
  runs: readonly RunStatusDTO[];
  busy?: boolean;
}) {
  const [configJson, setConfigJson] = useState(DEFAULT_RUN_CONFIG_JSON);
  const [error, setError] = useState<string | null>(null);

  const submit = () => {
    try {
      const config = JSON.parse(configJson) as unknown;
      setError(null);
      onSubmit(config);
    } catch {
      setError("config JSON 解析失败——请检查形状（SPEC-108 §4 wire shape）");
    }
  };

  return (
    <div className="dvb-mon-runtrigger">
      <label>
        config
        <textarea
          aria-label="config"
          className="dvb-mon-config"
          rows={6}
          value={configJson}
          onChange={(e) => setConfigJson(e.target.value)}
          spellCheck={false}
        />
      </label>
      {error !== null && <p className="dvb-mon-error">{error}</p>}
      <button type="button" disabled={busy === true} onClick={submit}>
        提交 Run（empty plan）
      </button>
      {runs.length === 0 && <ThreeQuestionState copy={MONITOR_EMPTY_STATE_COPY.runTrigger} />}
      <ul className="dvb-mon-rows">
        {runs.map((run) => (
          <li key={run.run_id} data-testid={`run-row-${run.run_id}`} className="dvb-mon-row">
            <div className="dvb-mon-row-head">
              <span className="dvb-mon-code">{run.run_id}</span>
              <Badge tone={run.status === "completed" ? "good" : run.status === "failed" ? "bad" : "info"}>
                {run.status}
              </Badge>
              {run.packet_count !== null && run.packet_count !== undefined && (
                <Badge tone="neutral">packets {run.packet_count}</Badge>
              )}
            </div>
            {(run.artifacts ?? []).map((artifact) => (
              <span
                key={artifact.artifact_id}
                data-testid={`run-artifact-${artifact.artifact_id}`}
                className="dvb-mon-node"
              >
                {artifact.artifact_id} <Badge tone="info">{artifact.kind}</Badge>
              </span>
            ))}
          </li>
        ))}
      </ul>
    </div>
  );
}

// Panel re-export guard: the page composes these inside a Panel title.
export const OverviewPanel = Panel;
