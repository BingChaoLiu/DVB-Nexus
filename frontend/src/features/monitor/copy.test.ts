// 钉扎:MONITOR_EMPTY_STATE_COPY 必须与 SPEC-408 §4.6 Monitor 组(SPEC-408
// :150-162)逐字一致——期望值是规格表的程序化提取物(独立事实源,含全角
// 标点),不是实现常量的回抄。 markdown 强调符号(**)按渲染语义剥除。
import { describe, expect, it } from "vitest";
import { EVENT_HONESTY_COPY, HONESTY_DISCIPLINE_PHRASES, MONITOR_EMPTY_STATE_COPY } from "./copy";

const SPEC_TABLE = {
  "unknownSession": {
    "what": "当前跟踪的 session 在服务端不存在",
    "why": "可能已清理、已过期或 id 输入有误",
    "next": "从下方最近列表重新选择；或回 Lab 开新实验"
  },
  "entry": {
    "what": "Monitor 是自由观测台（free observation deck），按 session 作用域展示八步闭环的真实运行证据",
    "why": "尚未选择任何 session",
    "next": "从 Lab 选场景开始实验后自动进入；或一键演示；或在最近列表选择；或手输 UUID"
  },
  "overview": {
    "what": "该会话的生命周期与快照摘要（lifecycle / snapshot）",
    "why": "快照数据未到达（会话不存在、未启动或后端未运行）",
    "next": "查看运行控制面板的生命周期状态；确认后端已启动（仓库根 `start.cmd`）"
  },
  "runTrigger": {
    "what": "向该会话提交 Generate Run 的入口（空 plan 或含配置）",
    "why": "本页尚无已注册的 run",
    "next": "提交基线 Run 观察码流生成；或回 Lab 走主干旅程"
  },
  "metrics": {
    "what": "MPEG-TS 包级指标序列查询窗口（PID = Packet Identifier）",
    "why": "该窗口内查询无返回序列；当前后端阶段不产 ts.* 观测流（缺失 ≠ 零）",
    "next": "先走 Generate/Inject 拿到 artifact；指标分析属进阶观测"
  },
  "alerts": {
    "what": "规则引擎产出的告警记录列表",
    "why": "无告警记录 ≠ 干净：MVP 阶段告警泵未接入（无观测）",
    "next": "排障以诊断候选与包检查为准"
  },
  "diagnosis": {
    "what": "诊断规则产出的根因候选列表（候选 ≠ 事实）",
    "why": "该会话尚无 diagnose 报告（不代表码流干净）",
    "next": "从 run 列表选 id 提交 diagnose；或从 Lab 诊断步深链进入"
  },
  "packetInspector": {
    "what": "诊断定位器指向的 artifact 字节切片与结构解析",
    "why": "尚未从诊断候选点「定位」进入",
    "next": "先提交 diagnose，再点候选行的定位按钮"
  },
  "verify": {
    "what": "通关判定提交口：以修复后新 Run 的证据换取服务端三态判定（PASS/FAIL/INCONCLUSIVE）",
    "why": "尚无判定结果",
    "next": "跑基线+注入+恢复三个 Run 后提交；场景身份可自动预填"
  },
  "journal": {
    "what": "该会话的 journal 流水尾窗（事件信封，per-session 单调流水号）",
    "why": "WS 未连接或该会话尚无事件",
    "next": "启动会话或跑一个 Run，观察帧流入"
  },
  "cli": {
    "what": "该会话的 TSDuck 调用记录与来源区分（来源标识 ≠ 双解析器 diff）",
    "why": "MVP 生产栈不产生真实 TSDuck 调用；空列表不是「无问题」信号",
    "next": "无需动作；接入实机/fixture 种子后此面板才有行"
  }
} as const;

describe("MONITOR_EMPTY_STATE_COPY — SPEC-408 §4.6 Monitor 组逐字钉扎", () => {
  it("all 11 rows match the spec table verbatim (what/why/next)", () => {
    expect(MONITOR_EMPTY_STATE_COPY).toEqual(SPEC_TABLE);
  });

  it("keeps the honesty discipline phrases via their §4.6 carriers (AC-408-09)", () => {
    const flat = JSON.stringify(MONITOR_EMPTY_STATE_COPY);
    // 行 4 / 行 6:逐字在表内。
    expect(flat).toContain("缺失 ≠ 零");
    expect(flat).toContain("候选 ≠ 事实");
    // 行 5:无观测 ≠ 干净纪律的 Monitor 组承载句(无告警记录 ≠ 干净:…（无观测）)。
    expect(flat).toContain("无告警记录 ≠ 干净");
    expect(flat).toContain("（无观测）");
  });
});

// SPEC-403 §Phase2(L320)诚实纪律句逐字提取物(独立事实源 = 规格原文,
// 引号内两句,空格为半角):「解扰失败 ≠ 码流损坏」「缺失 ≠ 零」。
// 键 = 事件类型 wire 名(#129 注册表条目);map 的期望值不是实现回抄。
const SPEC_PHASE2_DISCIPLINE = {
  "biss.descramble_failed": "解扰失败 ≠ 码流损坏",
  "t2mi.plp_mismatch": "缺失 ≠ 零",
} as const;

describe("EVENT_HONESTY_COPY — SPEC-403 §Phase2 诚实纪律句随事件文案落位(逐字)", () => {
  it("attaches each spec sentence to its carrier event type verbatim", () => {
    expect(EVENT_HONESTY_COPY["biss.descramble_failed"]).toBe(SPEC_PHASE2_DISCIPLINE["biss.descramble_failed"]);
    expect(EVENT_HONESTY_COPY["t2mi.plp_mismatch"]).toBe(SPEC_PHASE2_DISCIPLINE["t2mi.plp_mismatch"]);
  });

  it("carries exactly the two spec-anchored sentences (no invented copy)", () => {
    expect(Object.keys(EVENT_HONESTY_COPY).sort()).toEqual(
      Object.keys(SPEC_PHASE2_DISCIPLINE).sort(),
    );
  });

  it("shares the 缺失 ≠ 零 phrase with the existing AC-408-09 phrase set", () => {
    expect(HONESTY_DISCIPLINE_PHRASES).toContain("缺失 ≠ 零");
    expect(Object.values(EVENT_HONESTY_COPY)).toContain("缺失 ≠ 零");
  });
});
