// PROTOTYPE (issue #87, variant C): static example rows that fill EMPTY
// states with plausible shapes. Discipline (ticket hard constraint + #85
// three-layer labeling):
//   命名层 — every render site badges these rows 「示例」;
//   入口层 — they appear ONLY in empty states (never mixed into real lists);
//   生命层 — they vanish entirely the moment a real session/run arrives.
// Values are shape illustrations only (字段值仅为形状示意) — plausible but not
// authoritative; the narrative mirrors SC-01 (PAT missing) so the shapes
// teach the real vocabulary. Never wire these to drill-down: no locator,
// no fetch, no interaction.
import type {
  AlertRecordDTO,
  DiagnosisDTO,
  SnapshotDTO,
  SummaryDataDTO,
} from "../../features/monitor/types";

export const EXAMPLE_SUMMARY: SummaryDataDTO = {
  tenant_id: "示例·本地单机",
  session_id: "示例·待开局后替换为真实 session",
  journal_seq_watermark: 42,
  event_count: 42,
  active_alert_count: 1,
  schema_version: "1.0",
};

export const EXAMPLE_SNAPSHOT: SnapshotDTO = {
  session_id: "示例",
  revision: 7,
  lifecycle: "running",
  virtual_time_ns: 1_998_000_000,
  topology_revision: 1,
  node_states: {
    "gen-0": { node_id: "gen-0", health: "healthy" },
    "mux-0": { node_id: "mux-0", health: "degraded" },
    "mon-0": { node_id: "mon-0", health: "healthy" },
  },
};

export const EXAMPLE_ALERTS: AlertRecordDTO[] = [
  {
    alert_id: "示例-alert-1",
    fingerprint: "示例:psi-pat-silence@pid0",
    rule_id: "psi_pat_silence(示例)",
    rule_version: "1.0.0",
    state: "active",
    severity: "warning",
    scope: { tenant_id: "示例", session_id: "示例" },
    time: { simulated_ns: 1_998_000_000 },
    summary: "示例行:PID 0 上 PAT 段停发(激活槽位之后)——形状示意,非当前会话数据。",
    evidence_refs: ["示例:artifact/pid0/packet202"],
    suppressed: false,
  },
  {
    alert_id: "示例-alert-2",
    fingerprint: "示例:cc-continuity@pid257",
    rule_id: "cc_continuity_error(示例)",
    rule_version: "1.0.0",
    state: "cleared",
    severity: "info",
    scope: { tenant_id: "示例", session_id: "示例" },
    time: { simulated_ns: 1_200_000_000 },
    summary: "示例行:连续性计数跳变已随新 Run 清除——「已清除」也是观测事实。",
    evidence_refs: [],
    suppressed: false,
  },
];

export const EXAMPLE_DIAGNOSES: DiagnosisDTO[] = [
  {
    diagnosis_id: "示例-diag-1",
    session_id: "示例",
    run_id: "示例-run-inject",
    rule_id: "psi_pat_silence_rule(示例)",
    rule_version: "1.0.0",
    code: "PSI_PAT_SILENCE",
    severity: "error",
    // 诊断置信度轴 = low/medium/high(规则静态声明),与观测四值轴不同。
    confidence: "high",
    observation_refs: [
      { journal_seq: 37, event_type: "ts.psi_section_observed(示例)" },
      { journal_seq: 41, event_type: "ts.psi_silence_detected(示例)" },
    ],
    affected_node_ids: ["mux-0(示例)"],
    suggested_actions: ["示例行动:对照激活槽位前后的 PSI 重复节奏", "示例行动:确认注入 fault_id 后提交恢复 Run"],
    state: "raised",
    raised_at: 1_998_000_000,
    cleared_at: null,
  },
];

/** journal 尾窗的示例行(示例尾窗不接 WS,纯静态)。 */
export const EXAMPLE_JOURNAL_LINES: ReadonlyArray<string> = [
  "seq 41 · ts.psi_silence_detected · source=rule_engine · confidence=inferred(示例)",
  "seq 40 · fault.activated · fault_id=fd…f1a1(示例·结构化证据,无来源/置信度轴)",
  "seq 37 · ts.psi_section_observed · source=internal_parser · confidence=parsed(示例)",
  "seq 36 · run.completed · artifacts=[generated_ts](示例)",
];
