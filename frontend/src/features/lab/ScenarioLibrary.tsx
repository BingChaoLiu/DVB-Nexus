// Scenario library list (SPEC-406 §4.2, REQ-UI-406-001): GET /scenarios
// rendered in the server's filename-ASC registry order (NO client re-sort —
// one ordering semantic, 裁定 F determinism). Empty registry = explicit
// honest empty state (an empty registry is not an error, and NOT a clean
// signal of anything). Rows render the summary projection's four wire
// fields verbatim.
import { useQuery } from "@tanstack/react-query";
import { Badge, EmptyState, Panel } from "../../components/ui";
import { listScenarios } from "../../api";
import { qk } from "../../query/keys";

export function ScenarioLibrary({
  onOpenDetail,
  onStart,
}: {
  onOpenDetail: (scenarioId: string) => void;
  onStart: (scenarioId: string) => void;
}) {
  const query = useQuery({ queryKey: qk.scenarios(), queryFn: listScenarios });
  return (
    <Panel title="场景库">
      {query.isPending ? (
        <EmptyState title="加载中" note="读取场景注册表…" />
      ) : query.isError ? (
        <EmptyState
          title="场景注册表读取失败"
          note={query.error instanceof Error ? query.error.message : "网络错误（失败 ≠ 空库）"}
        />
      ) : query.data.length === 0 ? (
        <EmptyState
          title="注册表暂无场景文档"
          note="空库 ≠ 错误：repo 顶层 scenarios/ 尚无可扫描文件（Lab Pack v1 落位后此处列出 SC-01~05）。"
        />
      ) : (
        <ul className="dvb-lab-list">
          {query.data.map((summary) => (
            <li key={summary.scenario_id} className="dvb-lab-row" data-testid={`lab-scenario-${summary.scenario_id}`}>
              <div className="dvb-lab-row-head">
                <span className="dvb-lab-title">{summary.title}</span>
                <Badge tone="neutral">{summary.difficulty}</Badge>
                <Badge tone="info">v{summary.version}</Badge>
              </div>
              <div className="dvb-lab-line dvb-lab-mono">{summary.scenario_id}</div>
              <div className="dvb-lab-row-actions">
                <button type="button" onClick={() => onOpenDetail(summary.scenario_id)}>
                  查看详情
                </button>
                <button type="button" onClick={() => onStart(summary.scenario_id)}>
                  开始实验
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
