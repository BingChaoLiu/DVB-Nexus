// state_observed 快照解析契约(#170, SPEC-406 §Phase3「生成过程」折叠区状态域
// 形态 = L0 求值摘要): 数据源 = journal 快照事件(rf./sec. state_observed)——
// 不冒充构造事件。纯函数, 与 genEvents.ts 同款防御式解析姿态: 形状违规行
// 跳过(诚实缺席, 绝不造行), wire 值原样(无别名/无大小写转换), 同节点多条
// 快照 = journal 序后者胜(镜像最新 journal 真相)。
import { describe, expect, it } from "vitest";
import { parseStateSnapshotSummary, STATE_SNAPSHOT_EVENT_TYPES } from "./stateEvents";

const envelope = (
  eventType: string,
  payload: Record<string, unknown>,
  seq: number,
): Record<string, unknown> => ({
  journal_seq: seq,
  event_type: eventType,
  severity: "info",
  payload,
  scope: { session_id: "s-1", run_id: "run-1" },
});

describe("STATE_SNAPSHOT_EVENT_TYPES — the state-domain REST query filter", () => {
  it("is exactly the two #164 state_observed wire names (verbatim)", () => {
    expect([...STATE_SNAPSHOT_EVENT_TYPES]).toEqual(["rf.state_observed", "sec.state_observed"]);
  });
});

describe("parseStateSnapshotSummary — the L0 求值摘要 face", () => {
  it("counts rf./sec. snapshot events and derives per-node latest health (journal order: last wins)", () => {
    const items = [
      envelope("rf.state_observed", { node_id: "tuner-a", health: "ok", source: "state_evaluator", confidence: "simulated" }, 1),
      envelope("rf.state_observed", { node_id: "tuner-b", health: "error", source: "state_evaluator", confidence: "simulated" }, 2),
      envelope("sec.state_observed", { node_id: "lnb-0", health: "ok", source: "state_evaluator", confidence: "simulated" }, 3),
      // tuner-a degrades later in the journal — the latest truth wins.
      envelope("rf.state_observed", { node_id: "tuner-a", health: "warn", source: "state_evaluator", confidence: "simulated" }, 4),
    ];
    const summary = parseStateSnapshotSummary(items);
    expect(summary.rfCount).toBe(3);
    expect(summary.secCount).toBe(1);
    expect(summary.nodes).toEqual([
      { nodeId: "tuner-a", health: "warn" },
      { nodeId: "tuner-b", health: "error" },
      { nodeId: "lnb-0", health: "ok" },
    ]);
    // 恒定配对的诚实口径面(首见值原样呈现, 恒定 = state_evaluator/simulated).
    expect(summary.source).toBe("state_evaluator");
    expect(summary.confidence).toBe("simulated");
  });

  it("ignores foreign event types (gen.*/fault.*/topology.state_changed are not snapshots)", () => {
    const items = [
      envelope("gen.stage_started", { layer: "TS" }, 1),
      envelope("fault.applied", { fault_id: "f-1" }, 2),
      envelope("topology.state_changed", { changed: [{ node_id: "tuner-a", health: "ok" }] }, 3),
      envelope("rf.state_observed", { node_id: "tuner-a", health: "ok" }, 4),
    ];
    const summary = parseStateSnapshotSummary(items);
    expect(summary.rfCount).toBe(1);
    expect(summary.secCount).toBe(0);
    expect(summary.nodes).toEqual([{ nodeId: "tuner-a", health: "ok" }]);
  });

  it("skips shape-violating rows (honest absence — never a fabricated node row)", () => {
    const items = [
      // missing node_id
      envelope("rf.state_observed", { health: "ok" }, 1),
      // missing health
      envelope("sec.state_observed", { node_id: "lnb-0" }, 2),
      // non-record payload
      { journal_seq: 3, event_type: "rf.state_observed", payload: "junk" },
      // empty-string health
      envelope("rf.state_observed", { node_id: "tuner-b", health: "" }, 4),
      // a well-formed row survives
      envelope("rf.state_observed", { node_id: "tuner-c", health: "idle" }, 5),
    ];
    const summary = parseStateSnapshotSummary(items);
    expect(summary.nodes).toEqual([{ nodeId: "tuner-c", health: "idle" }]);
    expect(summary.rfCount).toBe(1);
    expect(summary.secCount).toBe(0);
  });

  it("answers the empty summary for zero snapshot items (the honest empty input)", () => {
    const summary = parseStateSnapshotSummary([]);
    expect(summary.nodes).toEqual([]);
    expect(summary.rfCount).toBe(0);
    expect(summary.secCount).toBe(0);
    expect(summary.source).toBeNull();
    expect(summary.confidence).toBeNull();
  });
});
