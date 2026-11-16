// Alerts panel (SPEC-403 §4.7): alerts rendered inline on the monitor page —
// there is no standalone alert center page (不做清单). Data = GET .../alerts
// (AlertsDataDTO); freshness = the observation.alert_changed hint invalidating
// qk.alerts via the shared bridge. The empty state is explicit: "no alert
// records" is NOT "clean" (SPEC-206 §6 absence-vs-clean duality).
import type { AlertRecordDTO } from "../types";
import { Badge } from "../../../components/ui";
import { MONITOR_EMPTY_STATE_COPY } from "../copy";
import { ThreeQuestionState } from "../ThreeQuestionState";

const SEVERITY_TONE: Record<string, "bad" | "warn" | "info" | "neutral"> = {
  critical: "bad",
  error: "bad",
  warning: "warn",
  info: "info",
};

export function AlertsPanel({ alerts, total }: { alerts: readonly AlertRecordDTO[]; total: number }) {
  return (
    <div className="dvb-mon-alerts">
      <p className="dvb-mon-total">共 {total} 条（显示 {alerts.length}）</p>
      {alerts.length === 0 ? (
        // §4.6 Monitor 组行 5(文案逐字):无告警记录 ≠ 干净。
        <ThreeQuestionState copy={MONITOR_EMPTY_STATE_COPY.alerts} />
      ) : (
        <ul className="dvb-mon-rows">
          {alerts.map((a) => (
            <li key={a.alert_id} data-testid={`alert-row-${a.alert_id}`} className="dvb-mon-row">
              <div className="dvb-mon-row-head">
                <span className="dvb-mon-code">{a.rule_id}</span>
                <Badge tone={SEVERITY_TONE[a.severity] ?? "neutral"}>{a.severity}</Badge>
                <Badge tone={a.state === "active" ? "warn" : "neutral"}>{a.state}</Badge>
                {a.suppressed && <Badge tone="neutral">suppressed</Badge>}
              </div>
              {a.summary !== null && a.summary !== undefined && <div className="dvb-mon-line">{a.summary}</div>}
              <div className="dvb-mon-line dvb-mon-note">fingerprint {a.fingerprint}</div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
