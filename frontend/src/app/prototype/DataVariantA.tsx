// PROTOTYPE (issue #87, variant A「演示 Session 一键开门」): the one-click
// demo entry (button + honest progress list) and the tracked-session demo
// banner (lifecycle visibility + one-click cleanup). The orchestration hits
// the REAL backend — zero mock data in this variant.
import { useState } from "react";
import { useNavigate } from "react-router";
import { Badge } from "../../components/ui";
import { disposeSession } from "../../api";
import {
  initialDemoSteps,
  orchestrateDemoSession,
  type DemoStep,
} from "./exampleDataOrchestrate";
import "./exampleDataPrototype.css";

const STEP_GLYPH: Record<DemoStep["state"], string> = {
  pending: "·",
  active: "…",
  done: "✓",
  failed: "✗",
};

/** One-click entry: runs the real orchestration, then lands on Monitor. */
export function DemoSessionLauncher({ compact = false }: { compact?: boolean }) {
  const navigate = useNavigate();
  const [steps, setSteps] = useState<DemoStep[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const launch = () => {
    setError(null);
    setSteps(initialDemoSteps());
    void (async () => {
      try {
        const result = await orchestrateDemoSession((current) => setSteps(current));
        // Land with the packet inspector seeded at the REAL fault locus so
        // the first screen already shows genuine stream bytes.
        const loc = result.inspectLocator;
        const inspect = loc
          ? `&inspect_artifact=${encodeURIComponent(loc.artifact_id)}&inspect_pid=${loc.pid}&inspect_packet=${loc.packet_index}`
          : "";
        navigate(`/monitor?session=${encodeURIComponent(result.sessionId)}${inspect}`);
      } catch (caught) {
        setError(
          caught instanceof Error
            ? `${caught.message}(后端未运行?仓库根 start.cmd 一键启动后重试)`
            : String(caught),
        );
      }
    })();
  };

  const running = steps !== null && error === null;
  return (
    <div className={compact ? "dvb-proto-dv-launcher dvb-proto-dv-launcher-compact" : "dvb-proto-dv-launcher"}>
      <button type="button" className="dvb-proto-dv-cta" onClick={launch} disabled={running}>
        ▶ 打开演示 Session(一键看真实数据流动)
      </button>
      {steps !== null && (
        <ul className="dvb-proto-dv-steps" aria-label="演示开局进度">
          {steps.map((step) => (
            <li key={step.key} className={`dvb-proto-dv-step dvb-proto-dv-step-${step.state}`}>
              <span className="dvb-proto-dv-step-glyph">{STEP_GLYPH[step.state]}</span> {step.label}
              {step.detail !== undefined && <span className="dvb-proto-dv-step-detail"> — {step.detail}</span>}
            </li>
          ))}
        </ul>
      )}
      {error !== null && <div className="dvb-proto-dv-error">{error}</div>}
    </div>
  );
}

/** Tracked-session banner (variant A): declares the demo entry + lifecycle
 * visibility + one-click cleanup, and offers a live replay run so the
 * journal tail visibly streams (the pre-seeded events predate the WS join —
 * an honest stock behavior this button turns into a live flow demo). */
export function DemoSessionBanner({
  sessionId,
  onUntrack,
  onReplayRun,
  replayBusy,
}: {
  sessionId: string;
  onUntrack: () => void;
  onReplayRun?: () => void;
  replayBusy?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const cleanup = () => {
    setBusy(true);
    void (async () => {
      try {
        await disposeSession(sessionId);
      } catch {
        // already gone / recycled — the honest post-dispose view is the guide
      } finally {
        onUntrack();
      }
    })();
  };
  return (
    <div className="dvb-proto-dv-banner" data-testid="proto-demo-banner">
      <Badge tone="info">演示</Badge>
      <span>
        演示会话(方案 A·一键开门):这是为你预置的开局——数据全部为<b>沙盘真实生成</b>
        (来源/置信度如实标注,可下钻取证);与真实会话的唯一差别是入口。包检查器已预锚定在故障激活槽位的真实字节上;
        告警/诊断表行为空是诚实态(无观测 ≠ 干净)。判定(Verify)故意留空:PASS 要你自己走完八步。
      </span>
      {onReplayRun !== undefined && (
        <button type="button" onClick={onReplayRun} disabled={replayBusy === true}>
          {replayBusy === true ? "Run 进行中…" : "▶ 再跑一个 Run(看 journal 实时流动)"}
        </button>
      )}
      <button type="button" onClick={cleanup} disabled={busy}>
        {busy ? "清理中…" : "结束演示并清理"}
      </button>
    </div>
  );
}
