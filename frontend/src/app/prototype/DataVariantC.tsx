// PROTOTYPE (issue #87, variant C「示例骨架填充空面板」): static example
// previews, rendered through the SAME presentational components the real
// panels use (OverviewCard / AlertsPanel / DiagnosisList) so the shapes are
// faithful. Three-layer labeling per #85: 命名层 = 「示例」 badges everywhere;
// 入口层 = rendered only inside empty states; 生命层 = the whole preview
// disappears the moment real data exists (site-level condition, no cleanup
// action needed). Nothing here is interactive: no drill-down, no navigation.
import { Badge } from "../../components/ui";
import { Panel } from "../../components/ui";
import { AlertsPanel } from "../../features/monitor/alerts/AlertsPanel";
import { OverviewCard } from "../../features/monitor/overview/OverviewCard";
import { DiagnosisList } from "../../features/monitor/components";
import {
  EXAMPLE_ALERTS,
  EXAMPLE_DIAGNOSES,
  EXAMPLE_JOURNAL_LINES,
  EXAMPLE_SNAPSHOT,
  EXAMPLE_SUMMARY,
} from "./exampleMockData";
import "./exampleDataPrototype.css";

function ExampleHead({ what }: { what: string }) {
  return (
    <p className="dvb-proto-dv-c-head">
      <Badge tone="info">示例</Badge> {what}
    </p>
  );
}

/** Monitor guide-page example preview (entry: no session tracked yet). */
export function MonitorExamplePreview() {
  return (
    <section className="dvb-proto-dv-preview" data-testid="proto-example-preview">
      <Panel title="示例预览(静态,非实时)——真实数据开局后自动让位">
        <p className="dvb-proto-dv-c-note">
          以下所有行均为<b>静态示例</b>(纯前端):用与真实面板相同的组件渲染,字段值仅为形状示意,
          不可下钻、不参与任何查询。真实会话数据到达后,本面板整段消失(空态入口随真实数据让位)。
          叙事沿用 SC-01(PAT 缺失)的真实词汇,帮你先认识面板形状。
        </p>
        <ExampleHead what="概览卡会长这样:" />
        <OverviewCard summary={EXAMPLE_SUMMARY} snapshot={EXAMPLE_SNAPSHOT} />
        <ExampleHead what="告警面板会长这样:" />
        <AlertsPanel alerts={EXAMPLE_ALERTS} total={EXAMPLE_ALERTS.length} />
        <ExampleHead what="诊断列表会长这样(置信度=诊断轴 low/medium/high,非观测四值轴):" />
        <DiagnosisList diagnoses={EXAMPLE_DIAGNOSES} />
        <ExampleHead what="journal 尾窗会长这样:" />
        <ul className="dvb-proto-dv-c-journal">
          {EXAMPLE_JOURNAL_LINES.map((line) => (
            <li key={line} className="dvb-proto-dv-c-journal-line">
              {line}
            </li>
          ))}
        </ul>
        <p className="dvb-proto-dv-c-note">
          下一步:去 <b>Lab</b> 选一个场景「开始实验」——真实数据会以同样的形状出现在这些面板里。
        </p>
      </Panel>
    </section>
  );
}

/** Lab console run-section example (entry: registry still empty). */
export function LabRunExampleRow() {
  return (
    <div className="dvb-proto-dv-c-labrow" data-testid="proto-example-run">
      <ExampleHead what="Run 注册表会长这样(真实 Run 按注册表呈现,Generate → Inject → Recover):" />
      <ul className="dvb-lab-list">
        <li className="dvb-lab-row">
          <span className="dvb-lab-mono">示例-run-id</span>
          <Badge tone="good">completed</Badge>
          <span className="dvb-lab-ref-chip">generated_ts</span>
          <Badge tone="info">示例</Badge>
        </li>
      </ul>
      <p className="dvb-proto-dv-c-note">示例行不可交互;点上方「生成基线」跑出第一条真实 Run。</p>
    </div>
  );
}
