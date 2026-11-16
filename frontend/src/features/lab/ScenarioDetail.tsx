// Scenario detail (SPEC-406 §4.3, REQ-UI-406-002; initial_topology
// readability per SPEC-408 §4.4 REQ-UI-408-012): the exported document
// rendered read-only — objectives as the numbered step list, the hints
// ladder (§4.4, localStorage-backed via useHintsReveal — the SAME shared
// per-scenario key the console's collapsible block reads/writes), pass_
// criteria rows (the six-kind closed enum strings verbatim + mandatory +
// fault_id), and the initial_topology island as a READABLE view: a stats
// line + Chinese-labelled structured rows (layout translation only — NO
// key-name semantic translation, NO SVG), with the raw camelCase document
// folded back verbatim inside <details> (键名原样, the #45 canonical-example
// authority). The 开局 action runs the §7.1 two-hop orchestration (create
// 201 ready → start running).
import { useQuery } from "@tanstack/react-query";
import { Badge, EmptyState, Panel } from "../../components/ui";
import { getScenario, type ScenarioDetailDTO } from "../../api";
import { qk } from "../../query/keys";
import { useHintsReveal } from "./hintsStorage";
import { HintsLadder, type LabHintWire } from "./HintsLadder";
import { summarizeInitialTopology } from "./initialTopology";

export function ScenarioDetail({
  scenarioId,
  onBack,
  onStart,
  starting,
  startError,
}: {
  scenarioId: string;
  onBack: () => void;
  onStart: () => void;
  starting: boolean;
  startError: { message: string; violations?: ReadonlyArray<{ code: string; path: string; message: string }> } | null;
}) {
  const query = useQuery({ queryKey: qk.scenario(scenarioId), queryFn: () => getScenario(scenarioId) });
  // Shared localStorage-backed reveal source (SPEC-408 §4.4 REQ-UI-408-011).
  const hints = useHintsReveal(scenarioId);
  return (
    <Panel title={`场景详情 ${scenarioId}`}>
      <button type="button" onClick={onBack}>
        返回场景库
      </button>
      {query.isPending ? (
        <EmptyState title="加载中" note="读取场景导出面…" />
      ) : query.isError ? (
        <EmptyState
          title="场景读取失败"
          note={query.error instanceof Error ? query.error.message : "网络错误"}
        />
      ) : (
        <ScenarioDetailBody
          detail={query.data}
          revealedCount={hints.count}
          onRevealNext={hints.revealNext}
          onResetHints={hints.resetHints}
          hintsStorageOk={hints.storageOk}
          onStart={onStart}
          starting={starting}
          startError={startError}
        />
      )}
    </Panel>
  );
}

function ScenarioDetailBody({
  detail,
  revealedCount,
  onRevealNext,
  onResetHints,
  hintsStorageOk,
  onStart,
  starting,
  startError,
}: {
  detail: ScenarioDetailDTO;
  revealedCount: number;
  onRevealNext: () => void;
  onResetHints: () => void;
  hintsStorageOk: boolean;
  onStart: () => void;
  starting: boolean;
  startError: { message: string; violations?: ReadonlyArray<{ code: string; path: string; message: string }> } | null;
}) {
  const topology = summarizeInitialTopology(detail.initial_topology);
  return (
    <div className="dvb-lab-detail">
      <div className="dvb-lab-detail-head">
        <span className="dvb-lab-title">{detail.title}</span>
        <Badge tone="neutral">{detail.difficulty}</Badge>
        <Badge tone="info">v{detail.version}</Badge>
      </div>
      <div className="dvb-lab-line dvb-lab-mono">{detail.scenario_id}</div>

      <section>
        <h3 className="dvb-lab-h3">目标 / 步骤（objectives）</h3>
        <ol className="dvb-lab-objectives">
          {detail.objectives.map((objective, index) => (
            <li key={index}>{objective}</li>
          ))}
        </ol>
      </section>

      <section>
        <h3 className="dvb-lab-h3">分阶段提示（hints）</h3>
        <HintsLadder
          hints={detail.hints as unknown as LabHintWire[]}
          revealedCount={revealedCount}
          onRevealNext={onRevealNext}
          onResetHints={onResetHints}
          storageAvailable={hintsStorageOk}
        />
      </section>

      <section>
        <h3 className="dvb-lab-h3">通关判据（pass_criteria 声明）</h3>
        <ul className="dvb-lab-criteria">
          {(detail.pass_criteria as { criterion_id: string; kind: string; mandatory: boolean; fault_id?: string }[]).map(
            (criterion) => (
              <li key={criterion.criterion_id} className="dvb-lab-criterion">
                <span className="dvb-lab-code">{criterion.criterion_id}</span>
                <Badge tone="info">{criterion.kind}</Badge>
                <Badge tone={criterion.mandatory ? "bad" : "neutral"}>
                  {criterion.mandatory ? "mandatory" : "optional"}
                </Badge>
                {criterion.fault_id !== undefined && criterion.fault_id !== null && (
                  <span className="dvb-lab-mono">fault_id {criterion.fault_id}</span>
                )}
              </li>
            ),
          )}
        </ul>
      </section>

      <section>
        <h3 className="dvb-lab-h3">初始拓扑（initial_topology 只读视图）</h3>
        <div className="dvb-lab-topology" data-testid="lab-topology-view">
          {topology !== null ? (
            <>
              {/* Stats line + Chinese-labelled structured rows (SPEC-408
                  §4.4): layout translation only — values stay authored-
                  verbatim; the raw document folds back below (键名原样). */}
              <div className="dvb-lab-topology-stats" data-testid="lab-topology-stats">
                {topology.statsLine}
              </div>
              <ul className="dvb-lab-topology-structured" data-testid="lab-topology-structured">
                {topology.nodes.map((node) => (
                  <li key={node.nodeId}>
                    {node.line}
                    <ul>
                      {node.ports.map((port) => (
                        <li key={port.portId}>{port.line}</li>
                      ))}
                    </ul>
                  </li>
                ))}
                {topology.connections.map((connection) => (
                  <li key={connection.connectionId}>{connection.line}</li>
                ))}
              </ul>
            </>
          ) : null}
          <details className="dvb-lab-topology-raw" data-testid="lab-topology-raw">
            <summary>查看原始文档（键名原样）</summary>
            {topology !== null ? (
              <ul className="dvb-lab-mono">
                {topology.rawLines.map((line, index) => (
                  <li key={index}>{line}</li>
                ))}
              </ul>
            ) : (
              <pre className="dvb-lab-mono">{JSON.stringify(detail.initial_topology, null, 2)}</pre>
            )}
          </details>
        </div>
      </section>

      <section>
        <h3 className="dvb-lab-h3">开局实验</h3>
        <button type="button" onClick={onStart} disabled={starting}>
          {starting ? "开局中…" : "开始实验"}
        </button>
        {startError !== null && (
          <div className="dvb-lab-start-error" data-testid="lab-start-error">
            <div>{startError.message}</div>
            {(startError.violations ?? []).map((violation, index) => (
              <div key={index} className="dvb-lab-line dvb-lab-mono">
                {violation.code} @ {violation.path}: {violation.message}
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
