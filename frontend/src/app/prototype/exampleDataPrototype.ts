// PROTOTYPE (issue #87, throwaway — do not review as production code):
// example-data suite. Question being answered: 「新工程师如何在最短时间看到
// 真实数据在流动」. Three structurally different options, switchable via
// ?data=A|B|C (storage fallback survives in-app navigation that drops the
// param):
//   A 演示 Session 一键开门 — Monitor-first: one click runs a REAL backend
//     orchestration (scenario session + 3 runs + diagnose) and lands the
//     engineer on a fully populated evidence deck.
//   B Lab 开局即得 baseline — Lab start's orchestration gains a third hop:
//     the empty-plan baseline run is auto-submitted, so the console opens
//     with Generate already in flight and panels filling naturally.
//   C 示例骨架填充 — pure frontend: static, clearly-badged example rows in
//     empty states; shape without flow.
//
// DEV-only: every consumer gates on readExampleDataVariant (null outside DEV
// / when off), so stock render paths stay byte-identical to pre-prototype.
//
// Independent of the #86 journey suite (?variant=): both suites can be on at
// once; this suite's pill is click-only so the ←/→ keys stay owned by the
// journey switcher.

export type ExampleDataVariantKey = "A" | "B" | "C";

const STORAGE_KEY = "dvb-proto-data-variant";

/** URL param wins (shareable), localStorage survives in-app navigation.
 * Impure by design (PROTOTYPE): a variant seen in the URL is persisted so
 * stock in-app links that drop the param keep the prototype alive. */
export function readExampleDataVariant(search: string): ExampleDataVariantKey | null {
  if (!import.meta.env.DEV) return null;
  const param = new URLSearchParams(search).get("data");
  if (param === "A" || param === "B" || param === "C") {
    writeExampleDataVariant(param);
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

export function writeExampleDataVariant(variant: "off" | ExampleDataVariantKey): void {
  try {
    if (variant === "off") localStorage.removeItem(STORAGE_KEY);
    else localStorage.setItem(STORAGE_KEY, variant);
  } catch {
    // ignore — prototype-only persistence
  }
}

/** Append the ?data= param so in-prototype links stay shareable. */
export function withDataParam(to: string, variant: ExampleDataVariantKey): string {
  const joiner = to.includes("?") ? "&" : "?";
  return `${to}${joiner}data=${variant}`;
}

export interface ExampleDataPlan {
  key: ExampleDataVariantKey;
  label: string;
  tagline: string;
  /** 体验路径 — what the reviewer should try. */
  experience: string;
  /** 后端增量 — per the ticket's hard constraint (逐项,纯前端优先). */
  backend: ReadonlyArray<string>;
  /** 诚实纪律核对 — CONTEXT.md observation/source/confidence discipline. */
  honesty: string;
  /** 对「30 分钟走通」目标的贡献路径. */
  contribution: string;
}

export const DATA_PLANS: Record<ExampleDataVariantKey, ExampleDataPlan> = {
  A: {
    key: "A",
    label: "A·演示 Session 一键开门",
    tagline: "Monitor 先行:一键真实编排,落地即见真实证据",
    experience:
      "Monitor 空态(或首页 Monitor 卡)点「打开演示 Session」→ 真实后端编排(场景会话 + 基线/注入/恢复三 Run + 诊断)→ 落地 Monitor:概览/运行控制已填充,journal 里是完整故障生命周期(fault.injected→activated→applied→cleared,真实结构化证据),包检查器已预锚定在注入槽位的真实字节上;点「再跑一个 Run」可看 journal 实时流动;演示条可一键清理。",
    backend: [
      "零(本原型即证:全部用现有端点编排,纯前端)",
      "可选小增量①:服务端预热一个 demo session(启动时编排一次)→ 免等待",
      "可选小增量②:session 元数据加演示标识并在页眉回显「演示」徽(命名层)",
      "可选小增量③:session 列表端点(与 Monitor 引导票 #88 合流讨论,不在本票裁决)",
    ],
    honesty:
      "数据非摆设:全部走真实生成链,fault.* 是结构化证据、journal 有全序流水号;告警/诊断表行为空是诚实态而非缺陷(无观测 ≠ 干净,MVP 阶段不产 ts.* 观测流);「演示」只标注入口与生命期,不碰观测来源/置信度轴;verify 判定故意留空——PASS 要你自己走。",
    contribution:
      "最快路径:不看 Lab 也能先「看见真实证据长什么样」,建立面板与证据直觉;主旅程仍由首页 CTA 进 Lab,演示是旁路不是替代。",
  },
  B: {
    key: "B",
    label: "B·Lab 开局即得 baseline",
    tagline: "主旅程内零门槛:开始实验即自动跑出第一批真实数据",
    experience:
      "Lab 详情点「开始实验」→ §7.1 两跳编排追加第三跳:自动提交空 plan 基线 Run → 落地实验台时 Run 注册表已有 baseline(完成后 Generate 步自亮),事件/快照随真实数据自然填充;常驻告示声明这一自动化事实。",
    backend: [
      "零(纯前端,复用 POST /runs)",
      "可选(非必需):「开局+预热」复合端点省一次 RTT",
    ],
    honesty:
      "全真实数据,无标注问题;自动化事实以常驻告示声明(不藏);stepper 进度 ≠ 通关判定纪律不变(footer 原文保留)。",
    contribution:
      "数据在主旅程语境中出现:Generate 门槛消失,新工程师直奔 Inject;Monitor 取证延后但不缺(诊断候选仍可深链)。",
  },
  C: {
    key: "C",
    label: "C·示例骨架填充空面板",
    tagline: "纯前端静态示例:看得见形状,看不见流动",
    experience:
      "Monitor 无 session 空态/Lab 空 Run 列表 → 以「示例」徽标填充静态示例行:用与真实面板相同的 DTO 渲染组件,字段值仅为形状示意,不可下钻;真实数据到达时整段让位(空态入口随真实数据消失)。",
    backend: ["零,永远零(纯前端静态常量)"],
    honesty:
      "三层标注齐全(命名=示例徽标;入口=只在空态出现;生命=真实数据到达即消失);示例预览是独立面板,不与真实列表混排,不冒充观测。",
    contribution:
      "最弱——看得见形状看不见流动;适合作为空态三问(这是什么·为什么空·下一步去哪)的补充,不适合单独扛「最快看到数据流动」。",
  },
};

export const DATA_PLANS_FOOTER =
  "三案不互斥:A/B 各解决一个入口(Monitor 旁路 vs Lab 主干),C 可作空态补充。裁决可单选可组合——由 repo 主定。";
