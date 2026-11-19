---
spec_id: SPEC-620
title: RF Simulation（RF 参数和质量状态模型）
version: 0.6.0
status: APPROVED
phase: P3
owner: RF
priority: P2
depends_on: [SPEC-621, SPEC-003, SPEC-202, SPEC-301]
requirements: [REQ-RF-620-001, REQ-RF-620-002, REQ-RF-620-003, REQ-RF-620-004, REQ-RF-620-005]
---

# SPEC-620 — RF Simulation（RF 参数和质量状态模型）

## 1. 目标

定义 `tuner` 拓扑节点的**状态模型与 L0 求值语义**（Phase 3 RF/SEC 沙盘，roadmap §2）：调谐请求、锁定状态、IF 频率、BER 状态档位与错锁判定素材五组状态。**不做连续 BER 数值仿真**（[#149](https://github.com/BingChaoLiu/DVB-Nexus/issues/149) Q2：simulated 域无 BER 真值依据，枚举档位由可判定事实推导——No fake evidence）。消费方 = SPEC-621（上游 band/LO 输入）、SPEC-204（SEC 层原语 `UB_SLOT_CONFLICT` 的症状承载）、SPEC-403/404/406（状态呈现与空态）、SPEC-305（查询面）、SPEC-307（诊断规则候选 TONE_RESIDUE_SUSPECT / UB_CONFLICT_SUSPECT）。

依据：roadmap §2 Phase 3 行 / §4 领域 A；[细裁 #147](https://github.com/BingChaoLiu/DVB-Nexus/issues/147)（L0 形态）、[#148](https://github.com/BingChaoLiu/DVB-Nexus/issues/148)（节点三类）、[#149](https://github.com/BingChaoLiu/DVB-Nexus/issues/149)（本票范围裁决）、[#150](https://github.com/BingChaoLiu/DVB-Nexus/issues/150)（UB 冲突判定语义）、[#151](https://github.com/BingChaoLiu/DVB-Nexus/issues/151)（原语清单）、[#152](https://github.com/BingChaoLiu/DVB-Nexus/issues/152)（rf.* 事件面）；研究证据 #144/#146 research findings（分支 research/diseqc-command-model、research/lnb-power-chain）。

## 2. 范围

### 2.1 In Scope

- `tuner` 节点五组状态字段语义（§5）：tuning_request / lock_state / if_frequency_khz / ber_state / locked_transponder_id。
- `tuner_evaluator`（`NodeEvaluator` 协议注册，SPEC-202 §6 冻结接口零变更）。
- `TunerConfigDTO` 与 metrics 键清单（`rf.state_observed` payload 字段映射，[#152](https://github.com/BingChaoLiu/DVB-Nexus/issues/152)）。
- 锁定求值语义：调谐意图 × 上游 LNB band/LO 输出（SPEC-621）→ 锁定/失锁/错锁素材。
- ber_state 三档枚举的**可判定事实推导规则表**（§7）。
- 错锁判定语义：locked + transponder 身份不符 = 组合事实（供 SPEC-307 规则消费），不设独立状态。

### 2.2 Out of Scope

- LNB 域（SPEC-621）；DiSEqC 命令与 switch（SPEC-622）；UB 调谐消息与槽位结构（SPEC-623）。
- 连续 BER 数值仿真、信噪比/信号强度模拟（无真值依据）；scanning 等时序过程态（终态求值）。
- 射频物理层仿真（OFDM/信道模型）——Phase 3 状态域不含物理层（[#148](https://github.com/BingChaoLiu/DVB-Nexus/issues/148) Q3 诚实边界）。
- SPEC-304 告警注册（TUNER_UNLOCKED/BER_SEVERE 归 [#152](https://github.com/BingChaoLiu/DVB-Nexus/issues/152) Q4 成文链）。

## 3. 术语

| 术语 | 定义 |
|---|---|
| lock_state | 终态锁定判定 ∈ {unlocked, locked}；无 scanning 态（[#149](https://github.com/BingChaoLiu/DVB-Nexus/issues/149) Q2） |
| 错锁 | locked 且 locked_transponder_id ≠ tuning_request 目标——组合事实非独立状态（[#149](https://github.com/BingChaoLiu/DVB-Nexus/issues/149) Q2） |
| ber_state | 三档枚举 {normal, elevated, severe}，由可判定事实推导（§7 规则表） |
| IF 槽位 | 转发器经 LNB 变换后的 IF 频率落位；低/高频段 IF 区间重叠 1100–1950 MHz（SPEC-621 附录 A）——tone 是唯一消歧器 |
| state_observed | per-node 状态快照事件（[#152](https://github.com/BingChaoLiu/DVB-Nexus/issues/152) Q2） |

## 4. 架构

- `tuner_evaluator` 以 SPEC-202 `NodeEvaluator` 协议注册（SPEC-003 §6；[#147](https://github.com/BingChaoLiu/DVB-Nexus/issues/147) Q3：metrics 承载、接口零变更）。
- 求值输入 = node config（`TunerConfigDTO`）+ 上游 lnb/switch 的 metrics（band_selected/lo_frequency_khz/tone_actual/short_circuit_state，拓扑因果序自然满足）+ EvalContext；fault 经求值前纯变换进入。
- 求值产物 → `rf.state_observed` 事件 payload（[#152](https://github.com/BingChaoLiu/DVB-Nexus/issues/152)）；来源 = `state_evaluator`、置信度 = simulated。
- 依赖方向遵守 ADR-0005；`SPEC-620 depends_on SPEC-621`（[#149](https://github.com/BingChaoLiu/DVB-Nexus/issues/149) Q8）。

## 5. 数据模型

- `TunerConfigDTO`（wire snake_case）：`tuning_request`（{frequency_khz, polarization}）/ `ub_slot`（结构归 SPEC-623）。
- metrics 键清单（`rf.state_observed` payload）：
  - `lock_state` ∈ {unlocked, locked}
  - `if_frequency_khz`（经上游 LO 变换后的实际 IF；无锁定也可计算——|tuning_freq − lo_delivered|）
  - `ber_state` ∈ {normal, elevated, severe}
  - `locked_transponder_id`（锁定时命中的转发器标识；unlocked = null）
- health 映射：unlocked → error（健康求值）；locked → 由 ber_state 传导（elevated → warn，severe → error）。

## 6. 公开接口（接口级契约）

- `tuner_evaluator.evaluate(node, inputs, context) -> NodeEvalResult`：纯函数，确定性（SPEC-202 §3/6.1）。
- 锁定求值纯函数：`(tuning_request, ub_slot, upstream_lnb_metrics, upstream_switch_metrics) → (lock_state, if_frequency_khz, locked_transponder_id, causes)`；UB 有效性消费 SPEC-623 冲突判定（同 UB 堆叠互扰 → unlocked + CauseRef 冲突对，[#150](https://github.com/BingChaoLiu/DVB-Nexus/issues/150) Q3）。
- ber_state 推导规则表（§7）为 normative；观测发射 `rf.state_observed`（[#152](https://github.com/BingChaoLiu/DVB-Nexus/issues/152)）。
- fault 挂钩：SEC 层原语 `UB_SLOT_CONFLICT`（SPEC-204，[#151](https://github.com/BingChaoLiu/DVB-Nexus/issues/151)）经求值前变换改写 ub_slot；求值器不感知 fault 概念。
- REST/WS 面无新增端点（SPEC-305 查询面扩容承载状态读）。

## 7. 处理算法（接口级行为义务）

- **锁定判定**：IF = |tuning_frequency − lo_delivered|（lo_delivered 来自上游 SPEC-621 metrics）；IF 落入目标转发器槽位且上游链路正常 → locked（locked_transponder_id = 目标）；UB 冲突（CauseRef 自上游或本节点冲突检测）→ unlocked + CauseRef 指向冲突对；IF 未落任何槽位 → unlocked。
- **错锁**：IF 落入**另一**转发器槽位（低/高频段 IF 重叠区，SPEC-621 附录 A 算术）→ locked 且 locked_transponder_id ≠ 目标——组合事实，供 SPEC-307 规则消费。
- **ber_state 推导规则表**（normative，可判定事实 → 档位）：
  1. 上游链路全部正常且 IF 对齐目标槽位中心 → `normal`；
  2. 上游任一异常字段（tone_actual ≠ tone_commanded / short_circuit_state ≠ normal / UB 冲突 CauseRef）且 IF 仍落在某槽位 → `severe`（A2 症状：残留 tone → IF 偏移 850MHz ≫ 捕获范围 → 失锁或错锁，[#146](https://github.com/BingChaoLiu/DVB-Nexus/issues/146) 结论 6）；
  3. IF 落在目标槽位**保护带**（槽位边缘邻域，具体宽度由实现票 golden 向量钉扎，不钉数值字面值）→ `elevated`；
  4. unlocked 态不产 ber_state 档位（保持上次值语义由 §8 显式标注）。
- **spec 不定义**：连续 BER 数值、信噪比、捕获范围数值——全部留空并诚实标注（无 simulated 域真值依据）。

## 8. 错误处理

| 场景 | 处理 |
|---|---|
| config 缺 tuning_request / ub_slot | prepare 拒绝（AC-204-01 纪律） |
| tuning_request.polarization 与上游 polarization_delivered 不符 | locked 前提不成立 → unlocked（极化失配是可判定事实，非数值仿真） |
| unlocked 态的 ber_state | 保留档位值 + 事件 payload 标注 `stale: true`（不静默） |
| 求值器内部异常 | `SIM_EVAL_NODE_FAILED` 节点级隔离（SPEC-202 §8） |
| 上游 metrics 缺失（拓扑断裂） | 输入态 idle 传播（SPEC-202 §5 isolated-node 语义）→ unlocked |

## 9. 资源约束

- L0 求值复杂度上界：单节点 O(1)；全拓扑（≤100 节点）单遍 ≤1ms 量级（[#147](https://github.com/BingChaoLiu/DVB-Nexus/issues/147) Q7）。
- 无新增运行时依赖；实现归 M7 实施票图。

## 10. 依赖

| 依赖 | 性质 | 消费点 |
|---|---|---|
| SPEC-621 | 上游状态 | band/LO/tone_actual/polarization_delivered metrics |
| SPEC-623 | UB 结构与冲突判定 | ub_slot 有效性、同 UB 堆叠互扰语义 |
| SPEC-003 §2.4 / §6 | 来源枚举 + NodeType 注册表 + 平面启用 | tuner 节点接入 |
| SPEC-202 §6 | 冻结求值接口 | tuner_evaluator 注册 |
| SPEC-301 + ADR-0006 | 事件信封 | rf.* 命名空间 additive（[#152](https://github.com/BingChaoLiu/DVB-Nexus/issues/152)） |
| SPEC-204（#151 修订后） | 作用层路由 | SEC 层 UB_SLOT_CONFLICT 症状承载 |
| SPEC-307 | 诊断规则消费 | TONE_RESIDUE_SUSPECT / UB_CONFLICT_SUSPECT 输入面 |
| #144/#146 findings | 向量素材 | A2 症状链算术 / 真值表 |

## 11. 测试向量

### 11.1 golden 计划（状态域）

- 正常锁定：合法 UB + 对齐 tuning + 上游正常 → locked + normal + locked_transponder_id = 目标。
- A2 症状链：`TONE_RESIDUE`（tone_actual=continuous ≠ commanded=none）→ band 错 → IF 偏移 850MHz → unlocked 或错锁（locked_transponder_id ≠ 目标）+ severe——断言不对称性（高频段请求正常，[#146](https://github.com/BingChaoLiu/DVB-Nexus/issues/146) 结论 6）。
- A1 症状链：`UB_SLOT_CONFLICT` → unlocked + CauseRef 冲突对。
- 邻槽保护带 → elevated（宽度由向量钉扎）。
- 极化失配 / 拓扑断裂 → unlocked 传播。

### 11.2 独立验证

- 规则表逐条独立于实现产出（向量表先于实现钉扎）；同 config 双跑逐字段一致（确定性复现纪律）。

### 11.3 性能基准

- 全拓扑求值耗时进实现票验收（tests/README §6 纪律）。

## 12. 验收标准

- AC-620-01：§7 锁定判定四分支（locked/unlocked/错锁素材/冲突）逐条断言。
- AC-620-02：ber_state 三档推导规则表逐条断言；无任何连续 BER 数值进产物（No fake evidence）。
- AC-620-03：错锁 = locked + locked_transponder_id ≠ 目标的组合事实可被 SPEC-307 规则消费。
- AC-620-04：`rf.state_observed` payload 与 §5 metrics 键清单逐字段一致（state_evaluator + simulated）。
- AC-620-05：A1/A2 症状链端到端（原语注入 → 求值 → 事件 → 规则候选输入）golden 绿。
- AC-620-06：确定性复现——同 config + fault plan 双跑逐字段一致。

## 13. 非目标与风险

- 连续 BER 数值/物理层仿真永久出本 spec（数值伪造违反 No fake evidence；物理层属 Later 物理沙盘 effort）。
- 风险：保护带宽度未定值——由实现票 golden 向量钉扎并回填注记，规格不预设数值。

## 14. 交付要求

- 实现落位 src/simulation/state/evaluators/（与 SPEC-621 同包族）；DTO 生成链权威 SPEC-500。
- 本规格 APPROVED 为 M7 开工前置。

## 15. 参考

- roadmap §2/§4；#144/#146 findings；#147/#148/#149/#150/#151/#152 决议；SPEC-621 附录 A（频段计划与 850MHz 算术）。
- ETSI TS 101 964 §A.1（22kHz 物理层，引用自 SPEC-621）；EN 50494/50607 付费条款号「待原文核对」。
