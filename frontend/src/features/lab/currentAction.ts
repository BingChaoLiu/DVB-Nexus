// Current-action pointer (SPEC-408 §4.4/§7.2, REQ-UI-408-008; CONTEXT.md
// 词条「当前动作」). A single pointer layer stacked ON TOP of the §7.3
// deriveStepState mapping — the input is that function's EightStepBooleans
// output and this file adds NO fact inference of its own: the pointer is
// the first NOT-done step in the canonical order, out-of-order completions
// light their step but never drag the pointer past an incomplete earlier
// step (事实就是事实, 指针不回退), all lit → Verify, and Analyze (the
// declared in-process gap) is NEVER a candidate. The pointer is a
// navigation/guidance aid, NEVER pass/fail evidence (判定只来自 verify
// 服务端应答).
import type { EightStepBooleans } from "./stepperState";

/** Canonical §7.2 order — Analyze is excluded (永久缺口, pointer skips it). */
export const CURRENT_ACTION_ORDER = [
  "create",
  "generate",
  "inject",
  "diagnose",
  "inspect",
  "recover",
  "verify",
] as const;

export type CurrentActionKey = (typeof CURRENT_ACTION_ORDER)[number];

/** The §7.2 pointer rule as a pure function (exhaustively unit-tested). */
export function deriveCurrentAction(steps: EightStepBooleans): CurrentActionKey {
  for (const key of CURRENT_ACTION_ORDER) {
    if (!steps[key]) return key;
  }
  // All lit → the pointer falls on Verify (§7.2「全部点亮时指针落在 Verify」).
  return "verify";
}

/**
 * Guidance bar copy (SPEC-408 §4.4「下一步名称 + 精确到按钮文案」). Button
 * texts are VERBATIM copies of the ExperimentConsole button labels (incl.
 * full-width punctuation) — rewriting them here is forbidden.
 */
const CURRENT_ACTION_GUIDES: Record<CurrentActionKey, { name: string; action: string }> = {
  // The console holds no start control (opening happens in the two-hop
  // start flow), so the honest Create guidance names the lifecycle fact.
  create: {
    name: "开局（Create）",
    action: "等待会话 lifecycle 进入 running（未就绪时点「返回场景库」重新开局）",
  },
  generate: { name: "生成基线", action: "点击『生成基线（Generate，空 plan）』" },
  inject: { name: "注入故障", action: "点击『注入故障（Inject，场景 fault_plan）』" },
  diagnose: { name: "诊断注入 Run", action: "点击『对注入 Run 评估（diagnose）』" },
  // Inspect has no dedicated trigger: journal events arrive from runs.
  inspect: {
    name: "取证（Inspect）",
    action: "触发一个 Run 后在「证据 / 事件（Inspect）」区块查看 journal 事件",
  },
  recover: { name: "恢复重跑", action: "点击『恢复重跑（Recover，空 plan）』" },
  verify: { name: "提交判定", action: "点击『提交判定（verify）』" },
};

/** One-line guidance sentence for the always-on bar under the Stepper. */
export function currentActionGuide(steps: EightStepBooleans): string {
  if (CURRENT_ACTION_ORDER.every((key) => steps[key])) {
    return "下一步：闭环已完成（判定以 verify 服务端应答为准）";
  }
  const guide = CURRENT_ACTION_GUIDES[deriveCurrentAction(steps)];
  return `下一步：${guide.name} → ${guide.action}`;
}
