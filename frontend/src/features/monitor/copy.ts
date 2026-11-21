// SPEC-408 §4.6 Monitor 组空态三问文案(11 面板全组,SPEC-408:150-162 逐字;
// 落笔权威 = 该表,实施禁改写)。三问句式 = 这是什么 · 为什么空(空/失败
// ≠ 干净)· 下一步去哪(CONTEXT.md「空态三问」词条)。诚实纪律句(无观测
// ≠ 干净、候选 ≠ 事实、缺失 ≠ 零)逐字保留。
//
// 逐字保障:本文件字符串由规格表程序化提取生成(含全角标点),并由
// copy.test.ts 以独立提取物钉扎——手工编辑需先对规格。
import type { Phase2EventType } from "./types";

export interface ThreeQuestionCopy {
  /** 这是什么 */
  what: string;
  /** 为什么空(空/失败 ≠ 干净) */
  why: string;
  /** 下一步去哪 */
  next: string;
}

export const MONITOR_EMPTY_STATE_COPY = {
  unknownSession: {
    what: "当前跟踪的 session 在服务端不存在",
    why: "可能已清理、已过期或 id 输入有误",
    next: "从下方最近列表重新选择；或回 Lab 开新实验",
  },
  entry: {
    what: "Monitor 是自由观测台（free observation deck），按 session 作用域展示八步闭环的真实运行证据",
    why: "尚未选择任何 session",
    next: "从 Lab 选场景开始实验后自动进入；或一键演示；或在最近列表选择；或手输 UUID",
  },
  overview: {
    what: "该会话的生命周期与快照摘要（lifecycle / snapshot）",
    why: "快照数据未到达（会话不存在、未启动或后端未运行）",
    next: "查看运行控制面板的生命周期状态；确认后端已启动（仓库根 `start.cmd`）",
  },
  runTrigger: {
    what: "向该会话提交 Generate Run 的入口（空 plan 或含配置）",
    why: "本页尚无已注册的 run",
    next: "提交基线 Run 观察码流生成；或回 Lab 走主干旅程",
  },
  metrics: {
    what: "MPEG-TS 包级指标序列查询窗口（PID = Packet Identifier）",
    why: "该窗口内查询无返回序列；当前后端阶段不产 ts.* 观测流（缺失 ≠ 零）",
    next: "先走 Generate/Inject 拿到 artifact；指标分析属进阶观测",
  },
  alerts: {
    what: "规则引擎产出的告警记录列表",
    why: "无告警记录 ≠ 干净：MVP 阶段告警泵未接入（无观测）",
    next: "排障以诊断候选与包检查为准",
  },
  diagnosis: {
    what: "诊断规则产出的根因候选列表（候选 ≠ 事实）",
    why: "该会话尚无 diagnose 报告（不代表码流干净）",
    next: "从 run 列表选 id 提交 diagnose；或从 Lab 诊断步深链进入",
  },
  packetInspector: {
    what: "诊断定位器指向的 artifact 字节切片与结构解析",
    why: "尚未从诊断候选点「定位」进入",
    next: "先提交 diagnose，再点候选行的定位按钮",
  },
  verify: {
    what: "通关判定提交口：以修复后新 Run 的证据换取服务端三态判定（PASS/FAIL/INCONCLUSIVE）",
    why: "尚无判定结果",
    next: "跑基线+注入+恢复三个 Run 后提交；场景身份可自动预填",
  },
  journal: {
    what: "该会话的 journal 流水尾窗（事件信封，per-session 单调流水号）",
    why: "WS 未连接或该会话尚无事件",
    next: "启动会话或跑一个 Run，观察帧流入",
  },
  cli: {
    what: "该会话的 TSDuck 调用记录与来源区分（来源标识 ≠ 双解析器 diff）",
    why: "MVP 生产栈不产生真实 TSDuck 调用；空列表不是「无问题」信号",
    next: "无需动作；接入实机/fixture 种子后此面板才有行",
  },
} satisfies Record<string, ThreeQuestionCopy>;

/**
 * The honesty discipline phrases (AC-408-09; §8 诚实态纪律). In the §4.6
 * Monitor 组 the 无观测 ≠ 干净 discipline is carried by row 5
 * (无告警记录 ≠ 干净:…（无观测）), rows 4/6 carry 缺失 ≠ 零 / 候选 ≠ 事实
 * verbatim — the copy test pins all three carriers.
 */
export const HONESTY_DISCIPLINE_PHRASES = ["无观测 ≠ 干净", "候选 ≠ 事实", "缺失 ≠ 零"] as const;

/**
 * SPEC-403 §Phase2(L320)诚实纪律句随事件文案落位(逐字,键 = 事件类型
 * wire 名,#129 注册表条目):「解扰失败 ≠ 码流损坏」挂在 biss.descramble_failed
 * (候选 ≠ 事实的解扰面——解扰证据 ≠ 码流损坏判定,ADR-0011 §4),「缺失 ≠ 零」
 * 挂在 t2mi.plp_mismatch(期望 PLP 不在流内 = 显式缺失,诚实空 ≠ 零流量)。
 * 规格只锚定这两句——不为其余事件发明文案(诚实禁令:规格外不落句)。
 * 注册表驱动渲染(journal 尾窗行 + 诊断明细 ref chip)按键查此表;键未命中
 * = 无纪律句,零渲染副作用。本文件 = 纪律句唯一归属面(票 #134)。
 */
export const EVENT_HONESTY_COPY: Partial<Record<Phase2EventType, string>> = {
  "biss.descramble_failed": "解扰失败 ≠ 码流损坏",
  "t2mi.plp_mismatch": "缺失 ≠ 零",
};

/**
 * AlertsPanel 的 rule_id→文案映射(#170;SPEC-304 §Phase3 两条告警注册)。
 * 键 = rule_id wire 名原样(TUNER_UNLOCKED warning / BER_SEVERE error,#166
 * default_rule_set 注册);文案 = 诚实 wire 事实句(照 EVENT_HONESTY_COPY
 * 先例:键未命中 = 无文案,零渲染副作用——未映射规则原样呈现 rule_id,不为
 * 规格外规则发明文案)。BER_SEVERE 行内携带「elevated 档不告警」两轴纪律
 * (304 阈值告警与 307 根因候选不混)。
 */
export const ALERT_RULE_COPY: Partial<Record<string, string>> = {
  TUNER_UNLOCKED: "RF 信号：tuner 快照 lock_state=unlocked（失锁）",
  BER_SEVERE: "RF 信号：tuner 快照 ber_state=severe；elevated 档不告警（组合判定归诊断规则）",
};
