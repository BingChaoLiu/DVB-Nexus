// PROTOTYPE (issue #86, throwaway — do not review as production code):
// journey-start & global wayfinding variants for the shell. Question being
// answered: 「新工程师第一眼从哪开始、全程路标长什么样」. Switchable via
// ?variant=A|B|C (storage fallback survives in-app navigation that drops the
// param). DEV-only: every consumer gates on import.meta.env.DEV and falls
// back to the stock shell when off, so the default render path (and the
// AppShell seam tests) is byte-identical to pre-prototype.
//
// Plan line: three structurally different journey-start/wayfinding variants
// (A 门厅首页 / B Lab即起点 / C 全局主干带), switchable via ?variant= on the
// AppShell chrome + the `/` route, DEV-gated.

export type JourneyVariantKey = "A" | "B" | "C";

const STORAGE_KEY = "dvb-proto-journey-variant";

/** URL param wins (shareable), localStorage survives in-app navigation.
 * Impure by design (PROTOTYPE): a variant seen in the URL is persisted so
 * stock in-app links that drop the param keep the prototype alive. */
export function readJourneyVariant(search: string): JourneyVariantKey | null {
  if (!import.meta.env.DEV) return null;
  const param = new URLSearchParams(search).get("variant");
  if (param === "A" || param === "B" || param === "C") {
    writeJourneyVariant(param);
    return param;
  }
  if (param === "off") return null;
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "A" || stored === "B" || stored === "C") return stored;
  } catch {
    // storage unavailable — prototype simply stays off
  }
  return null;
}

export function writeJourneyVariant(variant: "off" | JourneyVariantKey): void {
  try {
    if (variant === "off") localStorage.removeItem(STORAGE_KEY);
    else localStorage.setItem(STORAGE_KEY, variant);
  } catch {
    // ignore — prototype-only persistence
  }
}

/** Append the variant param so in-prototype links stay shareable. */
export function withVariant(to: string, variant: JourneyVariantKey): string {
  const joiner = to.includes("?") ? "&" : "?";
  return `${to}${joiner}variant=${variant}`;
}

export interface JourneyStep {
  key: string;
  index: number;
  en: string;
  zh: string;
  hint: string;
  gap: boolean;
}

// Eight-step closed loop (CONTEXT.md 词汇表). zh labels follow the existing
// Stepper's doneLabel semantics; Analyze is the declared gap (M4 裁定 B) —
// rendered as 不可用, never as pending progress.
export const JOURNEY_STEPS: ReadonlyArray<JourneyStep> = [
  { key: "create", index: 1, en: "Create", zh: "创建会话", hint: "在 Lab 选场景开局:创建并启动一个实验会话", gap: false },
  { key: "generate", index: 2, en: "Generate", zh: "生成基线", hint: "跑第一次 Run,生成干净基线码流", gap: false },
  { key: "inject", index: 3, en: "Inject", zh: "注入故障", hint: "按场景档案注入故障,跑出 faulted 码流", gap: false },
  { key: "analyze", index: 4, en: "Analyze", zh: "分析", hint: "进程内分析桥:当前版本无 HTTP 面,本步不可用(非待办)", gap: true },
  { key: "diagnose", index: 5, en: "Diagnose", zh: "诊断", hint: "拉取诊断报告,看根因候选(Lab 内联动证据台)", gap: false },
  { key: "inspect", index: 6, en: "Inspect", zh: "取证", hint: "下钻观测/事件/包检查器,取可追溯证据(证据台 Monitor)", gap: false },
  { key: "recover", index: 7, en: "Recover", zh: "修复恢复", hint: "修复后重跑第二次干净 Run", gap: false },
  { key: "verify", index: 8, en: "Verify", zh: "判定通关", hint: "以修复后新 Run 证据判定 PASS/FAIL——UI 变绿不算证据", gap: false },
];

export const GUIDE_URL =
  "https://github.com/BingChaoLiu/DVB-Nexus/blob/main/docs/user-guide/README.zh-CN.md";

export interface JourneyLocation {
  area: "start" | "lab-library" | "lab-detail" | "lab-console" | "monitor" | "topologies" | "other";
  /** Short 「你在哪」 label for wayfinding chips. */
  label: string;
  /** One-line next-step wayfinding sentence. */
  next: string;
}

/** URL-derived navigation position — a wayfinding aid, NEVER pass/fail progress. */
export function deriveJourneyLocation(pathname: string, search: string): JourneyLocation {
  const params = new URLSearchParams(search);
  const scenario = params.get("scenario");
  const session = params.get("session");
  if (pathname === "/") {
    return { area: "start", label: "旅程起点", next: "点「从这里开始」进入 Lab 选一个场景" };
  }
  if (pathname === "/lab") {
    if (scenario !== null && session !== null) {
      return {
        area: "lab-console",
        label: "Lab·实验台",
        next: "按页面 run 按钮顺序推进八步;完成修复后跑第二次干净 Run 再判定",
      };
    }
    if (scenario !== null) {
      return { area: "lab-detail", label: "Lab·场景详情", next: "看完提示梯子后点「开始实验」开局" };
    }
    return { area: "lab-library", label: "Lab·场景库", next: "选一个场景进入详情页(开局前必看详情)" };
  }
  if (pathname === "/monitor") {
    return {
      area: "monitor",
      label: "Monitor·证据台",
      next: session
        ? "这是自由观测台:围绕当前会话取证"
        : "需要会话才有内容:从 Lab 实验台进入,或粘贴 session UUID",
    };
  }
  if (pathname === "/topologies") {
    return { area: "topologies", label: "Topologies·进阶", next: "进阶工具,主干旅程用不到;想自定义拓扑再回来" };
  }
  return { area: "other", label: "未知页面", next: "回旅程起点(/)" };
}
