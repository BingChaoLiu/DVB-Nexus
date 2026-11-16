// Scenario library list (SPEC-406 §4.2 row order; single-entry + honest
// empty states per SPEC-408 §4.4 REQ-UI-408-012 and §4.6 Lab 组 rows 1-2):
// GET /scenarios rendered in the server's filename-ASC registry order (NO
// client re-sort — one ordering semantic, 裁定 F determinism). The row's
// ONLY action is 「查看详情」 — the former 「开始实验」 button was removed (it
// never started anything: SPEC-406 §4.2「列表行不直接开局、开局前必见详情」,
// the 开局 entry stays the detail page's 开局区). Empty registry = the §4.6
// verbatim honest empty state (an empty registry is not an error, and NOT a
// clean signal of anything); read failure names the request and offers
// [重试] (失败 ≠ 空库).
import { useQuery } from "@tanstack/react-query";
import { Badge, EmptyState, Panel } from "../../components/ui";
import { listScenarios } from "../../api";
import { qk } from "../../query/keys";

export function ScenarioLibrary({ onOpenDetail }: { onOpenDetail: (scenarioId: string) => void }) {
  const query = useQuery({ queryKey: qk.scenarios(), queryFn: listScenarios });
  return (
    <Panel title="场景库">
      {query.isPending ? (
        <EmptyState title="加载中" note="读取场景注册表…" />
      ) : query.isError ? (
        <div className="dvb-lab-error-state">
          <EmptyState
            title="场景注册表读取失败"
            note="失败 ≠ 空库：GET /scenarios 请求失败。下一步：确认后端已运行"
          />
          {query.error instanceof Error && query.error.message !== "" && (
            <div className="dvb-lab-line dvb-lab-mono">{query.error.message}</div>
          )}
          <button type="button" data-testid="lab-scenario-retry" onClick={() => void query.refetch()}>
            重试
          </button>
        </div>
      ) : query.data.length === 0 ? (
        <EmptyState
          title="注册表暂无场景文档"
          note="空库 ≠ 错误：服务端场景注册表为空。下一步：`start.cmd` 一键启动后端并完成场景扫描"
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
              </div>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
