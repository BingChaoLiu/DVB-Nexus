---
spec_id: SPEC-304
title: Health and Alert Engine
version: 0.5.0
status: APPROVED
phase: MVP
owner: Observation
priority: P0
depends_on: [SPEC-302, SPEC-303]
requirements: [REQ-OBS-304-001, REQ-OBS-304-002, REQ-OBS-304-003, REQ-OBS-304-004, REQ-OBS-304-005, REQ-OBS-304-006]
---

# SPEC-304 — Health & Alert Engine

## 1. 目标

从观测数据提供透明的健康摘要与规则告警。**告警是证据支撑的信号，不是诊断结论**（Diagnosis ≠ Observation，CONTEXT.md）：告警说"某指标越界且有证据"，不说"根因是什么"。

## 2. 范围

### 2.1 In Scope

- 六个健康维度与健康状态枚举。
- 声明式规则模型（禁 eval）。
- 告警生命周期、去重指纹与分组。
- 健康 roll-up 的确定性规则。
- 告警记录权威与暴露方式（记录 + 通知提示，见 §8）。

### 2.2 Out of Scope

- 根因判定、修复建议与 `diagnosis.*` 事件（SPEC-306/307，文本随 #13）。
- 外部通知投递（email/webhook/push——通知 adapter 域）。
- 自动故障清除、拓扑修复或任何仿真状态突变。
- 规则优先级与置信度语义（SPEC-003 §6 遗留项归 SPEC-306/307）。

## 3. 健康维度

初始维度：

- `transport`：连续性、包率、码率、null/scrambled 比。
- `timing`：PCR 重复间隔与抖动。
- `service`：PAT/PMT/service 存在性与 PSI/SI 新鲜度。
- `topology`：L0 快照的节点状态与路径可用性。
- `simulation`：session/clock/消费者运行状态。
- `observation`：摄入失败、消费者滞后、存储状态。

健康状态枚举：`unknown|healthy|degraded|critical`。

健康结果必含：`evaluated_at`（timepoint 显式语义）、`clock_domain`、规则集版本、贡献证据 ID 与原因码。

## 4. 规则模型

规则包含：`rule_id`、`version`、`name`、`description`、输入指标/事件选择器、条件与阈值（显式单位）、评估窗口与最小样本数、severity 与目标健康维度、开/合迟滞（hysteresis）、缺数据行为、证据捕获策略、enabled 标志。

- 规则**声明式**并经校验；**禁止**任意 Python 表达式或 eval。
- 阈值是 profile 特定的，**不得**硬编码为普适 DVB 合规限值（#6 标准核查纪律）。

## 5. 告警生命周期

```text
inactive -> pending -> firing -> resolving -> resolved
                     \-> inactive（条件在 pending 阈值前清除）
```

- `inactive`：条件未满足的预实例状态（指纹槽位存在，记录可不在库）。
- `pending`：条件已满足但 `for_duration` 未达。
- `firing`：条件满足满时长。
- `resolving`：条件已清除但解除保持期未满。
- `resolved`：解除保持期满。
- `resolved` 后再触发：除非去重策略明确在配置区间内重开（reopen），否则创建**新告警实例**。
- **抑制（suppressed）不是生命周期迁移态**：它是告警记录上的修饰属性（`suppression` 元数据）；被抑制的告警保持查询可见，解抑制恢复先前生命周期态（schema `state` 枚举中的 `suppressed` 即此修饰态）。
- 每次迁移持久化：时间戳（显式时钟域）、规则版本、证据引用。

**暴露方式（权威裁决）**：告警生命周期以 **alert record**（`schemas/alert-record.schema.json`）持久化为权威；状态变化经 SPEC-305 WebSocket `observation.alert_changed` **通知提示** + REST 拉取暴露。**MVP 不产生信封事件**——`observation.*` 事件命名空间留给未来观测面阈值告警的信封化；`diagnosis.raised/updated/cleared` 归 SPEC-306（SPEC-301 §4）。

## 6. 去重与分组

- 告警指纹 = 规则 ID + 配置的稳定维度派生；**不含**易变值或原始 payload 文本。
- 分组可用 session、service、PID、node 或 fault ID；分组必须遵守 tenant/session scope。

## 7. 健康 roll-up（确定性）

- 任一 required critical 规则 firing ⇒ `critical`。
- 存在 degraded 规则 firing 且无 critical ⇒ `degraded`。
- 必需输入齐全且无规则 firing ⇒ `healthy`。
- 必需输入缺失或过期（超出配置新鲜度）⇒ `unknown`。

响应必含 roll-up 策略与规则集版本。

## 8. 默认规则示例

- `TS_CC_ERROR_RATE_HIGH`：窗口内 per service/PID 连续错误率越阈值。
- `PCR_JITTER_HIGH`：PCR jitter p95 越阈值。
- `PSI_STALE`：PAT/PMT 超配置间隔未刷新。
- `TOPOLOGY_PATH_DOWN`：拓扑快照中必需路径不可用。
- `OBS_CONSUMER_LAG_HIGH`：消费者滞后超事件数。
- `OBS_STORAGE_WRITE_FAILURE`：journal 追加失败。

## 9. 安全

- 无自动故障清除、拓扑修复或仿真状态突变。
- 告警消息必须区分**测得事实**与**推断解释**（观测来源纪律）。
- 告警证据永不暴露密钥。
- 抑制告警保持可查询并带抑制元数据。

## 10. 错误与诊断码

复用 SPEC-300 §13；本模块新增：

| Code | 条件 |
|---|---|
| `OBS_RULE_INVALID` | 规则声明不过校验 |
| `OBS_RULE_INPUT_STALE` | 输入超出新鲜度（roll-up 入 unknown） |

## 11. 测试规格

- pending/firing/resolving/resolved 全迁移链（含虚拟时间驱动的 for_duration/保持期）。
- inactive 分支：pending 阈值前清除回 inactive。
- 迟滞与缺数据行为（入 unknown 不误报）。
- 重放下的确定性评估。
- 指纹去重与 reopen 策略。
- 证据引用可解析到不可变源记录。
- roll-up 全分支与 unknown/stale 行为。
- 记录权威：告警迁移零信封事件（对照 SPEC-301 §4 撤出清单），通知提示 + REST 拉取路径可用。

## 12. 验收标准

- `REQ-OBS-304-001`：规则声明式且禁 eval；阈值不硬编码普适合规限值。
- `REQ-OBS-304-002`：生命周期全迁移（含 inactive 分支与 reopen 策略）正确持久化。
- `REQ-OBS-304-003`：告警记录权威 + 通知提示 + REST 拉取；MVP 零 `observation.*` 信封事件。
- `REQ-OBS-304-004`：指纹去重确定且不含易变值。
- `REQ-OBS-304-005`：roll-up 确定性且策略/版本随响应返回。
- `REQ-OBS-304-006`：证据引用可解析、无密钥、事实/推断可区分。

## 13. 非目标与风险

- 不做诊断结论（`confidence` 语义归 SPEC-306/307）。
- 不承诺通知投递。
- 风险：告警风暴（如长流 persistent CRC 故障）——评估批量化 + 指纹去重 + 抑制元数据兜底；风暴本身是 SPEC-204 场景设计责任。

## 14. 交付要求

建议文件：`app/observation/alerts/`（engine.py / rules.py / store.py）；schema：`schemas/alert-record.schema.json`；示例：`examples/alert-pcr-jitter-example.json`。

## 15. 参考

- SPEC-302（指标输入）、SPEC-303（时间轴证据）、SPEC-305（暴露接口）。
- ADR-0006 第 5 条（命名纠偏与 `observation.*` 预留）、[缝合批准 #12] Q3 裁决（告警不发信封事件）。
