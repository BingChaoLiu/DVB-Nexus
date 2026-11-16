// Eight-step stepper (SPEC-406 §7.3, REQ-UI-406-006; clickable-locator
// layer SPEC-408 §4.4 REQ-UI-408-009): the CONTEXT.md closed loop as a top
// indicator strip. State comes exclusively from deriveStepState(facts) —
// the pure §7.3 table; this component only renders it. Analyze renders as
// the declared-gap step (不可用 — in-process bridge, no HTTP face, M4 裁定
// B), NEVER as pending progress. The strip carries the "stepper 进度 ≠ 通
// 关判定" disclaimer: stepping is not evidence.
//
// SPEC-408 §4.4「Stepper 可点击 = 定位非打卡」: every step except Analyze
// is a button reporting onStepSelect(key) — a scroll-locator affordance
// ONLY. A click never mutates light-up (点亮只来自服务端事实; there is no
// local click state in this component). The current-action pointer step is
// additionally marked dvb-lab-step-current (render-layer orientation aid,
// derived via the §7.2 deriveCurrentAction pointer — also not a fact).
import { Badge } from "../../components/ui";
import { deriveCurrentAction, type CurrentActionKey } from "./currentAction";
import type { EightStepBooleans } from "./stepperState";

const STEPS: ReadonlyArray<{ key: keyof EightStepBooleans; label: string; doneLabel: string }> = [
  { key: "create", label: "Create", doneLabel: "开局完成" },
  { key: "generate", label: "Generate", doneLabel: "基线完成" },
  { key: "inject", label: "Inject", doneLabel: "注入完成" },
  { key: "analyze", label: "Analyze", doneLabel: "" },
  { key: "diagnose", label: "Diagnose", doneLabel: "已诊断" },
  { key: "inspect", label: "Inspect", doneLabel: "已取证" },
  { key: "recover", label: "Recover", doneLabel: "恢复完成" },
  { key: "verify", label: "Verify", doneLabel: "已判定" },
];

export function Stepper({
  steps,
  onStepSelect,
}: {
  steps: EightStepBooleans;
  /** Locator callback (定位非打卡): fires with the step key on click. */
  onStepSelect?: (key: CurrentActionKey) => void;
}) {
  const current = deriveCurrentAction(steps);
  return (
    <div className="dvb-lab-stepper" data-testid="lab-stepper">
      {STEPS.map((step, index) => {
        const done = steps[step.key];
        const unavailable = step.key === "analyze";
        const isCurrent = step.key === current;
        const className = `dvb-lab-step${done ? " dvb-lab-step-done" : ""}${unavailable ? " dvb-lab-step-gap" : ""}${isCurrent ? " dvb-lab-step-current" : ""}`;
        const title = unavailable
          ? "Analyze：进程内分析桥，无 HTTP 面（M4 裁定 B，REST analyze 冻结 501）——本步不可用，非待办"
          : `定位到「${step.label}」对应区块（定位不改变点亮状态）`;
        return unavailable ? (
          <span key={step.key} data-testid={`lab-step-${step.key}`} className={className} title={title}>
            <span className="dvb-lab-step-index">{index + 1}</span>
            {step.label}
            <Badge tone="neutral">不可用</Badge>
          </span>
        ) : (
          <button
            key={step.key}
            type="button"
            data-testid={`lab-step-${step.key}`}
            className={className}
            title={title}
            onClick={() => onStepSelect?.(step.key as CurrentActionKey)}
          >
            <span className="dvb-lab-step-index">{index + 1}</span>
            {step.label}
            {done ? <Badge tone="good">{step.doneLabel}</Badge> : <Badge tone="neutral">待办</Badge>}
          </button>
        );
      })}
      <span className="dvb-lab-stepper-note">stepper 进度 ≠ 通关判定（判定只来自 verify 服务端应答）</span>
    </div>
  );
}
