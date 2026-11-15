// Eight-step stepper (SPEC-406 §7.3, REQ-UI-406-006): the CONTEXT.md closed
// loop as a top indicator strip. State comes exclusively from
// deriveStepState(facts) — the pure §7.3 table; this component only renders
// it. Analyze renders as the declared-gap step (不可用 — in-process bridge,
// no HTTP face, M4 裁定 B), NEVER as pending progress. The strip carries
// the "stepper 进度 ≠ 通关判定" disclaimer: stepping is not evidence.
import { Badge } from "../../components/ui";
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

export function Stepper({ steps }: { steps: EightStepBooleans }) {
  return (
    <div className="dvb-lab-stepper" data-testid="lab-stepper">
      {STEPS.map((step, index) => {
        const done = steps[step.key];
        const unavailable = step.key === "analyze";
        return (
          <span
            key={step.key}
            data-testid={`lab-step-${step.key}`}
            className={`dvb-lab-step${done ? " dvb-lab-step-done" : ""}${unavailable ? " dvb-lab-step-gap" : ""}`}
            title={
              unavailable
                ? "Analyze：进程内分析桥，无 HTTP 面（M4 裁定 B，REST analyze 冻结 501）——本步不可用，非待办"
                : undefined
            }
          >
            <span className="dvb-lab-step-index">{index + 1}</span>
            {step.label}
            {unavailable ? (
              <Badge tone="neutral">不可用</Badge>
            ) : done ? (
              <Badge tone="good">{step.doneLabel}</Badge>
            ) : (
              <Badge tone="neutral">待办</Badge>
            )}
          </span>
        );
      })}
      <span className="dvb-lab-stepper-note">stepper 进度 ≠ 通关判定（判定只来自 verify 服务端应答）</span>
    </div>
  );
}
