---
spec_id: SPEC-622
title: DiSEqC Controller（命令模型、端口和控制状态）
version: 0.6.0
status: APPROVED
phase: P3
owner: RF
priority: P2
depends_on: [SPEC-003, SPEC-202, SPEC-301, SPEC-621]
requirements: [REQ-DSC-622-001, REQ-DSC-622-002, REQ-DSC-622-003, REQ-DSC-622-004]
---

# SPEC-622 — DiSEqC Controller（命令模型、端口和控制状态）

## 1. 目标

定义 `diseqc_switch` 拓扑节点的**命令词汇与控制状态模型**（Phase 3 RF/SEC 沙盘，roadmap §2）：DiSEqC 1.x 单向命令子集的帧词汇、committed/uncommitted 双寄存器状态与端口选择派生。**首版只收 1.x 单向命令子集**（[#150](https://github.com/BingChaoLiu/DVB-Nexus/issues/150) Q2：1.x 无 reply 无反馈环，天然适配终态求值；2.x 仲裁是过程语义出界）。消费方 = SPEC-623（调谐消息复用 framing 族）、SPEC-621（legacy_cascade 的 Satellite A/B 联动）、SPEC-307（规则候选输入）、SPEC-403/404（呈现）。

依据：roadmap §2 Phase 3 行；[细裁 #150](https://github.com/BingChaoLiu/DVB-Nexus/issues/150)（本票切分）、[#147](https://github.com/BingChaoLiu/DVB-Nexus/issues/147)（L0 形态：命令效果终态化）、[#148](https://github.com/BingChaoLiu/DVB-Nexus/issues/148)（节点三类/平面启用）、[#144](https://github.com/BingChaoLiu/DVB-Nexus/issues/144) 研究证据（research/diseqc-command-model 分支（#144）：Eutelsat Bus Functional Specification v4.2 免费权威、framing/地址/命令表、时序常量族、「至多一条 DC 通路」硬约束）。

## 2. 范围

### 2.1 In Scope

- DiSEqC 1.x 单向命令子集帧词汇：framing byte 族（E0~E7 八态词汇，本子集 normative 值 = 0xE0/0xE1）、address 族常用子集（本子集 normative 值 = 0x10）、命令注册表首版 = {0x38 Write N0（Committed Switch Option，M/1.0），0x39 Write N1（Uncommitted Switch Option，M/1.1）}。
- `diseqc_switch` 节点状态模型：`committed_switch_state` / `uncommitted_switch_state` 双寄存器 + 派生 `port_selected`；`power_pass` config 透传。
- 命令效果**终态化求值语义**：命令序列终态 = 最后生效命令（[#150](https://github.com/BingChaoLiu/DVB-Nexus/issues/150) Q4）。
- `SwitchConfigDTO` 与 metrics 键清单（`sec.state_observed` payload 字段映射，[#152](https://github.com/BingChaoLiu/DVB-Nexus/issues/152)）。
- Write Port Group 位语义：高 nibble 先清后低 nibble 置位（[#144](https://github.com/BingChaoLiu/DVB-Nexus/issues/144) 命令模型素材）。
- 时序常量**参考表**（不进求值，§7）。

### 2.2 Out of Scope

- DiSEqC 2.x（reply/碰撞仲裁/异步应答）——候选扩展，spec 诚实标注（[#150](https://github.com/BingChaoLiu/DVB-Nexus/issues/150) Q2）。
- 位置器命令族（0x6x）——无 A1/A2 场景支撑，候选扩展（[#150](https://github.com/BingChaoLiu/DVB-Nexus/issues/150) Q6）。
- Tone Burst（mini-DiSEqC SA/SB）语义——归 SPEC-621（供电/22kHz 交界，[#144](https://github.com/BingChaoLiu/DVB-Nexus/issues/144) 下游建议）。
- Unicable 调谐消息（SPEC-623）；电源域求值（归 SPEC-621 lnb）。
- 命令历史过程仿真（先 A 后 B 的时序重放）——终态 = 最后生效命令。

## 3. 术语

| 术语 | 定义 |
|---|---|
| framing byte | DiSEqC 帧首字节 E0~E7 八态词汇（framing/master-slave/reply 三字段组合）；本子集 normative：0xE0 = master command/no reply/first transmission，0xE1 = repeated（[#145](https://github.com/BingChaoLiu/DVB-Nexus/issues/145) §2.1 引文） |
| address 0x10 | 「any LNB, switcher or SMATV」子地址（MuMuDVB 注释原词，[#145](https://github.com/BingChaoLiu/DVB-Nexus/issues/145) 引文） |
| committed / uncommitted 寄存器 | Write N0（0x38）/ Write N1（0x39）命令的目标锁存位组 |
| port_selected | 由双寄存器 nibble 位派生的开关端口选择（派生值非独立状态） |
| 命令意图 | tuner/上游节点 config 声明的结构化命令效果（求值器输入；帧字节编码见 §5） |
| 「至多一条 DC 通路」 | DiSEqC 总线硬约束（[#144](https://github.com/BingChaoLiu/DVB-Nexus/issues/144) 总线语义）——拓扑层由 SPEC-003 连接基数表达 |

## 4. 架构

- `diseqc_switch_evaluator` 以 SPEC-202 `NodeEvaluator` 协议注册（SPEC-003 §6；[#147](https://github.com/BingChaoLiu/DVB-Nexus/issues/147) Q3：metrics 承载、接口零变更）。
- 命令效果终态化（[#150](https://github.com/BingChaoLiu/DVB-Nexus/issues/150) Q4）：switch 求值器输入 = 上游 tuner 声明的命令意图（config / fault context 求值前纯变换），输出 = 寄存器终态 metrics；1.x 单向无 reply → 无反馈环，纯函数成立。
- 求值产物 → `sec.state_observed` 事件 payload（[#152](https://github.com/BingChaoLiu/DVB-Nexus/issues/152)）；来源 = `state_evaluator`、置信度 = simulated。
- fault 挂钩：SEC 层原语的求值前变换（[#151](https://github.com/BingChaoLiu/DVB-Nexus/issues/151)）；候选池 `SWITCH_MISCONFIG`（寄存器错配）不进首版。
- 依赖方向遵守 ADR-0005。

## 5. 数据模型

- `SwitchConfigDTO`（wire snake_case）：`power_pass`（{on, off}，config 透传——电源域求值归 SPEC-621）。
- 命令意图（上游 tuner config 字段 `diseqc_commands`，结构化）：{target_register: {committed, uncommitted}, nibble_writes: [{register, nibble, value}]}——帧编码词汇 = 本规格 §6；语义 = Write Port Group 高 nibble 先清后低 nibble 置位。
- metrics 键清单（`sec.state_observed` payload，[#152](https://github.com/BingChaoLiu/DVB-Nexus/issues/152)）：
  - `committed_switch_state`（4 bit nibble 位组）
  - `uncommitted_switch_state`（4 bit nibble 位组）
  - `port_selected`（派生：f(committed nibbles)，值域 = 节点 config 声明的端口面）
  - `power_pass`（config 透传）
- health 映射：port_selected 缺失（无命令意图）→ idle（SPEC-202 §5 语义）；命令意图与端口面不符 → error。

## 6. 公开接口（接口级契约）

- `diseqc_switch_evaluator.evaluate(node, inputs, context) -> NodeEvalResult`：纯函数确定性（SPEC-202 §3/6.1）。
- 寄存器终态纯函数：`(diseqc_commands) → (committed_switch_state, uncommitted_switch_state, port_selected)`——多条命令按声明序应用、终态 = 最后生效（高 nibble 清 → 低 nibble 置位语义逐条）。
- 帧编码词汇（normative 子集）：framing {0xE0, 0xE1} × address {0x10} × command {0x38, 0x39}；完整八态 framing 词汇表与地址族**引用** research/diseqc-command-model 分支（#144）（#144 §命令模型，Eutelsat BFS v4.2 权威）——本子集外的值 prepare 拒绝。
- 观测发射：`sec.state_observed`（[#152](https://github.com/BingChaoLiu/DVB-Nexus/issues/152)）；REST/WS 无新增端点。

## 7. 处理算法（接口级行为义务）

- **终态化**：命令意图序列 → 逐条位语义应用（高 nibble 先清后低 nibble 置位）→ 终态寄存器；无时序重放（[#150](https://github.com/BingChaoLiu/DVB-Nexus/issues/150) Q4）。
- **时序常量参考表**（normative 数值、不进求值）：PWK 500µs / 消息间静默 ≥6ms / 消息间隙 >15ms / 级联命令间隔 ≥100ms / 2.x reply ≤150ms——权威 = Eutelsat BFS v4.2（[#144](https://github.com/BingChaoLiu/DVB-Nexus/issues/144) 时序常量族）。
- **「至多一条 DC 通路」**：拓扑表达 = SPEC-003 连接基数（#148 机制面零扩展）；validator 层由 SPEC-003 修订承载（成文归 #156）。
- fault：`SWITCH_MISCONFIG` 候选（[#151](https://github.com/BingChaoLiu/DVB-Nexus/issues/151) 候选池）预留寄存器错配变换缝，语义随候选毕业再定。

## 8. 错误处理

| 场景 | 处理 |
|---|---|
| 命令意图引用子集外 framing/address/command 值 | prepare 拒绝（§6 normative 子集受控） |
| nibble_writes 引用不存在的寄存器/nibble | prepare 拒绝 |
| 无命令意图 | port_selected 缺失 → idle（非错误） |
| 求值器内部异常 | `SIM_EVAL_NODE_FAILED` 节点级隔离（SPEC-202 §8） |
| 2.x 词汇出现（reply 要求位等） | prepare 拒绝（首版子集不含，诚实拒绝优于静默） |

## 9. 资源约束

- L0 求值复杂度上界：单节点 O(1)；全拓扑（≤100 节点）单遍 ≤1ms 量级（[#147](https://github.com/BingChaoLiu/DVB-Nexus/issues/147) Q7）。
- 无新增运行时依赖；实现归 M7 实施票图。

## 10. 依赖

| 依赖 | 性质 | 消费点 |
|---|---|---|
| SPEC-003 §2.4 / §6 | 来源枚举 + NodeType 注册表 + 平面启用（#148） | switch 节点接入 |
| SPEC-202 §6 | 冻结求值接口 | diseqc_switch_evaluator 注册 |
| SPEC-301 + ADR-0006 | 事件信封 | sec.* 命名空间 additive（[#152](https://github.com/BingChaoLiu/DVB-Nexus/issues/152)） |
| SPEC-621 | 交界语义 | Tone Burst 归属、供电域、legacy_cascade Satellite A/B |
| SPEC-623 | framing 复用 | EN 50494 调谐消息构建于本规格帧词汇 |
| Eutelsat BFS v4.2（免费镜像，[#144](https://github.com/BingChaoLiu/DVB-Nexus/issues/144) 已核验） | 标准权威 | 帧词汇/命令表/时序常量 |
| #144 findings 分支 | 向量素材 | 命令位语义/八态词汇表 |

## 11. 测试向量

### 11.1 golden 计划（状态域）

- 0x38/0x39 单命令终态用例（高 nibble 清 + 低 nibble 置位位语义逐位断言）。
- 多命令序列终态 = 最后生效（声明序确定性）。
- port_selected 派生用例（寄存器位组 → 端口）。
- 子集外值 prepare 拒绝用例（0x5A 等非本子集命令、2.x framing）。
- `power_pass` 透传用例。

### 11.2 独立验证

- 位语义表先于实现钉扎（向量独立于实现）；同 config 双跑逐字段一致（确定性复现纪律）。

### 11.3 性能基准

- 全拓扑求值耗时进实现票验收（tests/README §6 纪律）。

## 12. 验收标准

- AC-622-01：Write N0/N1 位语义（高 nibble 清/低 nibble 置位）逐位断言。
- AC-622-02：命令序列终态化（无历史过程产物）。
- AC-622-03：normative 子集受控（子集外值 prepare 拒绝）。
- AC-622-04：`sec.state_observed` payload 与 §5 metrics 键清单逐字段一致（state_evaluator + simulated）。
- AC-622-05：时序常量表作为参考数据存在且不进求值产物。
- AC-622-06：确定性复现——同 config + fault plan 双跑逐字段一致。

## 13. 非目标与风险

- 2.x 双向协议、位置器、Tone Burst 均出界（候选扩展已标注）；风险：2.x 若后续 effort 启用，本规格 framing 词汇表需扩容（additive）。

## 14. 交付要求

- 实现落位 src/simulation/state/evaluators/（与 SPEC-620/621 同包族）；DTO 生成链权威 SPEC-500。
- 本规格 APPROVED 为 M7 开工前置。

## 15. 参考

- roadmap §2；#144 findings（research/diseqc-command-model 分支）；#145 §2.1（framing 0xE0/0xE1、address 0x10 引文）；#147/#148/#150/#151/#152 决议。
- Eutelsat DiSEqC Bus Functional Specification v4.2（免费镜像已核验完整）；EN 50494/50607 付费条款号「待原文核对」。
