// Journey position derivation (SPEC-408 §4.1/§7.1, REQ-UI-408-002): a PURE
// function from the URL to a seven-area enum. Wayfinding aid only — NEVER
// pass/fail progress: it consumes no Lab stepper facts and no cross-module
// state (no URL tricks beyond location, no query cache, no WS).
// Decision structure mirrors prototype/journeyPrototype.ts (parameter
// EXISTENCE, not non-empty value); the copy fields follow §4.1/§4.2.

export type JourneyArea =
  | "start"
  | "lab-library"
  | "lab-detail"
  | "lab-console"
  | "monitor"
  | "topologies"
  | "other";

export interface JourneyLocation {
  area: JourneyArea;
  /** Short「你在」label shown on the wayfinding bar. */
  label: string;
  /** One-line next-step wayfinding sentence (surfaced as the chip tooltip). */
  next: string;
}

export function deriveJourneyLocation(pathname: string, search: string): JourneyLocation {
  const params = new URLSearchParams(search);
  const scenario = params.get("scenario");
  const session = params.get("session");
  if (pathname === "/") {
    return { area: "start", label: "旅程起点", next: "点「从这里开始：选一个场景」进入 Lab 场景库" };
  }
  if (pathname === "/lab") {
    if (scenario !== null && session !== null) {
      return {
        area: "lab-console",
        label: "Lab·实验台",
        next: "按页面三个 run 按钮顺序推进八步；修复后跑第二次干净 Run 再判定",
      };
    }
    if (scenario !== null) {
      return { area: "lab-detail", label: "Lab·场景详情", next: "看完 objectives 与提示后点「开始实验」开局" };
    }
    return { area: "lab-library", label: "Lab·场景库", next: "选一个场景进入详情页（开局前必见详情）" };
  }
  if (pathname === "/monitor") {
    return {
      area: "monitor",
      label: "Monitor·证据台",
      next: session
        ? "这是自由观测台：围绕当前会话查看真实运行证据"
        : "需先有 session：从 Lab 实验台进入，或一键演示，或在最近列表选择",
    };
  }
  if (pathname === "/topologies") {
    return {
      area: "topologies",
      label: "Topologies·进阶",
      next: "进阶工具；主干旅程用场景自带初始拓扑，拿到第一次 PASS 之后再回来探索",
    };
  }
  return { area: "other", label: "未知页面", next: "回旅程起点（/）" };
}
