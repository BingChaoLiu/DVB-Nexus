// Demo session bar (SPEC-408 §4.3 演示会话条 + §8 failure row, ticket #99):
// AppShell-level, permanent for the whole demo period, inserted directly
// under the journey wayfinding bar. Three landed elements: the frozen
// declaration (「数据 = 沙盘真实生成；与真实会话唯一差别是入口」), the rerun
// action (「再跑一个 Run（看 journal 实时流动）」) and the one-click cleanup
// (「结束演示并清理」= DELETE session + local demo state clear). During the
// orchestration (and after a failure) the bar shows the honest per-phase
// rows — active/done/failed — and a failure carries the explicit reason plus
// the frozen §8 hint (「后端未运行？`start.cmd`」) while a created session
// stays kept and cleanable (已建会话保留可手动清理). Pure display: every
// action arrives as a callback from the shell (the state owner).
import type { DemoPhaseState, DemoSessionState } from "./demoOrchestrate";
import "./demo.css";

/** The four honest row states; 等待 is the pre-start display of the §7.4
 * phase table (never rendered as progress). */
const PHASE_STATE_WORD: Record<DemoPhaseState, string> = {
  pending: "等待",
  active: "进行中",
  done: "完成",
  failed: "失败",
};

export interface DemoSessionBarProps {
  demo: DemoSessionState;
  rerunBusy: boolean;
  cleanupBusy: boolean;
  rerunError: string | null;
  cleanupError: string | null;
  onRerun: () => void;
  onCleanup: () => void;
}

export function DemoSessionBar({
  demo,
  rerunBusy,
  cleanupBusy,
  rerunError,
  cleanupError,
  onRerun,
  onCleanup,
}: DemoSessionBarProps) {
  const sessionKnown = demo.sessionId !== null;
  const showActions = sessionKnown;
  return (
    <section
      className="dvb-demo-bar"
      data-testid="demo-session-bar"
      data-demo-status={demo.status}
      aria-label="演示会话"
    >
      {demo.status !== "landed" ? (
        <>
          <p className="dvb-demo-bar-title" data-testid="demo-progress-title">
            {demo.status === "orchestrating" ? "一键演示编排中(真实后端,逐 phase 诚实进度):" : "一键演示失败(停在原地,不落地、不伪装成功):"}
          </p>
          <ul className="dvb-demo-phase-list" data-testid="demo-phase-list">
            {demo.phases.map((phase) => (
              <li
                key={phase.key}
                className={`dvb-demo-phase-row dvb-demo-phase-${phase.state}`}
                data-testid={`demo-phase-row-${phase.key}`}
                data-phase-state={phase.state}
              >
                <span className="dvb-demo-phase-label">{phase.label}</span>
                <span className="dvb-demo-phase-state">{PHASE_STATE_WORD[phase.state]}</span>
                {phase.detail !== undefined && (
                  <span className="dvb-demo-phase-detail">{phase.detail}</span>
                )}
              </li>
            ))}
          </ul>
        </>
      ) : null}

      {demo.status === "failed" ? (
        <p className="dvb-demo-failure-hint" data-testid="demo-failure-hint">
          失败 ≠ 干净:任一 phase 失败即停在原地,已建会话保留可手动清理。后端未运行？`start.cmd`
        </p>
      ) : null}

      {demo.status === "landed" ? (
        <p className="dvb-demo-declaration" data-testid="demo-declaration">
          数据 = 沙盘真实生成；与真实会话唯一差别是入口
        </p>
      ) : null}

      {showActions ? (
        <div className="dvb-demo-actions">
          <span className="dvb-demo-session-id">
            演示会话:{demo.sessionId}
            {demo.scenarioTitle !== null ? ` · ${demo.scenarioTitle}` : ""}
          </span>
          <button
            type="button"
            data-testid="demo-rerun-run"
            disabled={rerunBusy || demo.sessionId === null}
            onClick={onRerun}
          >
            再跑一个 Run（看 journal 实时流动）
          </button>
          <button
            type="button"
            data-testid="demo-cleanup"
            disabled={cleanupBusy || demo.sessionId === null}
            onClick={onCleanup}
          >
            结束演示并清理
          </button>
        </div>
      ) : null}

      {rerunError !== null && (
        <p className="dvb-demo-error" data-testid="demo-rerun-error">
          再跑 Run 失败:{rerunError}
        </p>
      )}
      {cleanupError !== null && (
        <p className="dvb-demo-error" data-testid="demo-cleanup-error">
          清理失败(会话未删除,可重试):{cleanupError}
        </p>
      )}
    </section>
  );
}
