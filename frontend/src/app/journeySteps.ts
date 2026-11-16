// Shared journey content constants (SPEC-408 §1 eight-step overview table,
// L23-32 — the content authority for both the home journey map and the shell
// mini wayfinding bar). zh names and one-line descriptions are the spec
// table's own cells, verbatim; Analyze is the declared permanent gap and is
// rendered as unavailable, never as pending progress (§4.2).
export interface JourneyStep {
  key: string;
  index: number;
  /** English step name — CONTEXT.md 八步闭环 wording (Create → … → Verify). */
  en: string;
  /** Chinese name per the §1 table. */
  zh: string;
  /** One-line description per the §1 table. */
  what: string;
  /** Where the step happens, per the §1 table's 发生在哪 column. */
  where: string;
  /** Declared permanent gap (Analyze only) — honest unavailable, pointer skips. */
  gap: boolean;
}

export const JOURNEY_STEPS: ReadonlyArray<JourneyStep> = [
  {
    key: "create",
    index: 1,
    en: "Create",
    zh: "建会话",
    what: "选一个场景开局，得到 RUNNING 会话",
    where: "Lab·场景详情 → 实验台",
    gap: false,
  },
  {
    key: "generate",
    index: 2,
    en: "Generate",
    zh: "生成基线",
    what: "空 plan 跑出第一批真实码流（开局自动基线可代跑）",
    where: "Lab·实验台",
    gap: false,
  },
  {
    key: "inject",
    index: 3,
    en: "Inject",
    zh: "注入故障",
    what: "按场景 fault_plan 注入，产出 faulted artifact",
    where: "Lab·实验台",
    gap: false,
  },
  {
    key: "analyze",
    index: 4,
    en: "Analyze",
    zh: "分析",
    what: "深度分析面（MVP REST 冻结 501，诚实呈现，指针跳过）",
    where: "Lab·实验台",
    gap: true,
  },
  {
    key: "diagnose",
    index: 5,
    en: "Diagnose",
    zh: "诊断",
    what: "对注入 Run 出根因候选",
    where: "Lab·实验台",
    gap: false,
  },
  {
    key: "inspect",
    index: 6,
    en: "Inspect",
    zh: "检查证据",
    what: "从候选定位直达包字节切片",
    where: "Monitor/包检查器（Lab 深链进入）",
    gap: false,
  },
  {
    key: "recover",
    index: 7,
    en: "Recover",
    zh: "恢复重跑",
    what: "故障清除后新 Run——通关证据的载体",
    where: "Lab·实验台",
    gap: false,
  },
  {
    key: "verify",
    index: 8,
    en: "Verify",
    zh: "通关判定",
    what: "服务端三态判定；PASS 只认修复后新 Run 证据",
    where: "Lab·实验台（Monitor 同口径可用）",
    gap: false,
  },
];

/** Frozen annotation for gap rows (SPEC-408 §4.2 L98, verbatim). */
export const ANALYZE_GAP_NOTE = "不可用（REST 冻结 501），旅程自动跳过";

/** Usage-guide link target: the repo's docs/user-guide (SPEC-408 §4.1 L92
 * 「外链 docs/user-guide」; URL form follows prototype GUIDE_URL). */
export const GUIDE_URL =
  "https://github.com/BingChaoLiu/DVB-Nexus/blob/main/docs/user-guide/README.zh-CN.md";
