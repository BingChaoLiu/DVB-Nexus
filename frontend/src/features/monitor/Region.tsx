// Monitor route region — placeholder shell; the Stream Monitor (control bar,
// overview card, metrics/diagnoses/verify) lands with SPEC-403 (#64), which
// owns this directory (SPEC-404 evidence drill-down enters from here too).
import { EmptyState, Panel } from "../../components/ui";

export default function MonitorRegion() {
  return (
    <Panel title="Monitor">
      <EmptyState
        title="Stream Monitor 落地中"
        note="本路由区由 SPEC-403（#64）实现：运行控制条 + 概览卡 + 指标/诊断/verify 呈现。"
      />
    </Panel>
  );
}
