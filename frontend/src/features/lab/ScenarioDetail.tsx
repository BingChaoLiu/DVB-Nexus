// Scenario detail (SPEC-406 §4.3, REQ-UI-406-002): the exported document
// rendered read-only — objectives as the numbered step list, the hints
// ladder (§4.4, localStorage-backed via useHintsReveal — the SAME shared
// per-scenario key the console's collapsible block reads/writes), pass_
// criteria rows (the six-kind closed enum strings verbatim + mandatory +
// fault_id), and the initial_topology camelCase island as a read-only
// structure view (the #45 canonical-example keys are rendered AS AUTHORED —
// no key-name translation). The 开局 action runs the §7.1 two-hop
// orchestration (create 201 ready → start running).
import { useQuery } from "@tanstack/react-query";
import { Badge, EmptyState, Panel } from "../../components/ui";
import { getScenario, type ScenarioDetailDTO } from "../../api";
import { qk } from "../../query/keys";
import { useHintsReveal } from "./hintsStorage";
import { HintsLadder, type LabHintWire } from "./HintsLadder";

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
  const topology = detail.initial_topology as {
    topology_id: string;
    revision: number;
    nodes: { nodeId: string; nodeType: string; ports: { portId: string; direction: string; plane: string; maxConnections: number }[] }[];
    connections: { connectionId: string; from: { nodeId: string; portId: string }; to: { nodeId: string; portId: string } }[];
  };
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
        <div className="dvb-lab-topology dvb-lab-mono" data-testid="lab-topology-view">
          topology_id: {topology.topology_id} · revision: {topology.revision}
          <ul>
            {topology.nodes.map((node) => (
              <li key={node.nodeId}>
                nodeId {node.nodeId} · nodeType {node.nodeType}
                <ul>
                  {node.ports.map((port) => (
                    <li key={port.portId}>
                      portId {port.portId} · direction {port.direction} · plane {port.plane} · maxConnections{" "}
                      {port.maxConnections}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
            {topology.connections.map((connection) => (
              <li key={connection.connectionId}>
                connectionId {connection.connectionId} · from {connection.from.nodeId}/{connection.from.portId} → to{" "}
                {connection.to.nodeId}/{connection.to.portId}
              </li>
            ))}
          </ul>
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
