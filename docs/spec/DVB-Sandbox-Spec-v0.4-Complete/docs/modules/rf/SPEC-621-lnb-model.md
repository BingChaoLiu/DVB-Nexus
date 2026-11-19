---
spec_id: SPEC-621
title: LNB Model（本振、极化、电压和频段状态）
version: 0.6.0
status: APPROVED
phase: P3
owner: RF
priority: P2
depends_on: [SPEC-003, SPEC-202, SPEC-301]
requirements: [REQ-LNB-621-001, REQ-LNB-621-002, REQ-LNB-621-003, REQ-LNB-621-004, REQ-LNB-621-005, REQ-LNB-621-006]
---

# SPEC-621 — LNB Model（本振、极化、电压和频段状态）

## 1. 目标

定义 `lnb` 拓扑节点的**状态模型与 L0 求值语义**（Phase 3 RF/SEC 沙盘，roadmap §2）：供电电压、22kHz 音调、band/本振选择、短路保护四组状态；14 态真值表（normative 附录）是 band/polarization 选择与 A2 靶场症状链的权威依据。消费方 = SPEC-620（tuner 锁定求值消费 band/LO 输出）、SPEC-204（RF 层故障原语 `TONE_RESIDUE` 的注入缝）、SPEC-403/404/406（状态呈现与空态）、SPEC-305（查询面）、SPEC-307（诊断规则候选）。

依据：roadmap §2 Phase 3 行 / §4 领域 A；[细裁 #147](https://github.com/BingChaoLiu/DVB-Nexus/issues/147)（L0 形态：SPEC-202 冻结骨架上注册求值器、metrics 承载、SIM_STATE Run 一等公民）、[#148](https://github.com/BingChaoLiu/DVB-Nexus/issues/148)（节点三类、config 词汇、平面启用）、[#149](https://github.com/BingChaoLiu/DVB-Nexus/issues/149)（本票范围裁决）、[#151](https://github.com/BingChaoLiu/DVB-Nexus/issues/151)（tone_commanded/tone_actual 分离注入缝）、[#152](https://github.com/BingChaoLiu/DVB-Nexus/issues/152)（sec.* 事件面、state_evaluator 来源）；研究证据 research/lnb-power-chain 分支（#146）（#146：14 态逐格核实四源一致、TS 101 964 + TI SLVA863 免费权威、短路保护状态机、A2 症状链算术）。

## 2. 范围

### 2.1 In Scope

- `lnb` 节点四组状态字段语义（§5）：供电（voltage + short_circuit_state）、tone（tone_commanded + tone_actual 分离）、band/LO（band_selected + lo_frequency_khz，由真值表推导）、`lnb_kind` 变体。
- 14 态真值表（附录 A，normative）：voltage 3 态 × tone 4 模式 + 2 复合态，逐格 band/polarization/LO 选择。
- `lnb_evaluator`（`NodeEvaluator` 协议注册，SPEC-202 §6 冻结接口零变更）。
- `lnb` 节点 config schema（`LnbConfigDTO`）与 metrics 键清单（`sec.state_observed` payload 字段映射，[#152](https://github.com/BingChaoLiu/DVB-Nexus/issues/152)）。
- SCR 能力段（`scr` config 子段）的**存在性声明**——结构语义（ub_assignments）归 SPEC-623。
- `tone_commanded` / `tone_actual` 双字段分离（A2 故障注入缝，[#149](https://github.com/BingChaoLiu/DVB-Nexus/issues/149) Q3 / [#151](https://github.com/BingChaoLiu/DVB-Nexus/issues/151) Q3）。

### 2.2 Out of Scope

- tuner 域状态（SPEC-620）；DiSEqC 命令帧与 switch（SPEC-622）；UB 调谐消息与槽位结构（SPEC-623）。
- 时序迁移过程仿真：短路保护 hiccup 节奏（128ms 重试间隔）、tone 时序波形——SIM_STATE Run 是终态求值（[#147](https://github.com/BingChaoLiu/DVB-Nexus/issues/147) Q8），状态集收编、迁移过程不仿真（§7 诚实边界）。
- `legacy_cascade` 变体全语义（§7 仅简版：tone → Satellite A/B 选择；与 SPEC-622 级联开关联动）。
- 22kHz 信号完整性仿真（电平/容差为参考表，不进求值）。

## 3. 术语

| 术语 | 定义 |
|---|---|
| Universal LNB | 具备低/高频段双本振（9750/10600 MHz）的 LNB；tone 语义 = 频段选择 |
| legacy_cascade | band-fixed LNB + 老式级联架构；tone 语义 = Satellite A/B 选择（[#146](https://github.com/BingChaoLiu/DVB-Nexus/issues/146) 结论 3：tone 语义上下文相关） |
| tone_commanded / tone_actual | 接收端命令的音调模式 / LNB 侧实际呈现的音调模式；二者分离是状态域等位替换的注入缝（[#151](https://github.com/BingChaoLiu/DVB-Nexus/issues/151)） |
| 等位替换（状态域） | fault 仅改写参数指定的状态字段，其余传播路径不变（[#151](https://github.com/BingChaoLiu/DVB-Nexus/issues/151) Q2） |
| 短路保护五态 | normal / clamping / hiccup / thermal_fault / fault_latched（TI TPS65235 状态机终态集，[#146](https://github.com/BingChaoLiu/DVB-Nexus/issues/146) 结论 4） |
| state_evaluator | 观测来源枚举新增值：L0 求值产物专用，恒配 simulated 置信度（[#152](https://github.com/BingChaoLiu/DVB-Nexus/issues/152) Q1，SPEC-003 §2.4 修订） |

## 4. 架构

- `lnb_evaluator` 以 SPEC-202 `NodeEvaluator` 协议注册（NodeType 注册表机制，SPEC-003 §6；[#147](https://github.com/BingChaoLiu/DVB-Nexus/issues/147) Q1/Q3：冻结接口零变更，状态语义经 `NodeEvalResult.metrics` 承载）。
- 求值输入 = node config（`LnbConfigDTO`）+ 上游输入端口状态（tuner 侧供电/tone 命令经 `bidirectional` 端口语义进入）+ EvalContext；fault 经求值前纯变换进入（[#147](https://github.com/BingChaoLiu/DVB-Nexus/issues/147) Q4）。
- 求值产物 = `NodeEvalResult`（health + metrics）→ `sec.state_observed` 事件 payload（[#152](https://github.com/BingChaoLiu/DVB-Nexus/issues/152) Q2）；来源 = `state_evaluator`、置信度 = simulated（恒定配对）。
- 依赖方向遵守 ADR-0005（不反向依赖 simulation/faults 域）。

## 5. 数据模型

- `LnbConfigDTO`（wire snake_case）：`lnb_kind`（{universal, legacy_cascade}）/ `lo_frequencies`（{low_khz, high_khz}，universal 默认 {9750, 10600}）/ `scr`（可选子段，结构归 SPEC-623）。
- metrics 键清单（`sec.state_observed` payload，[#152](https://github.com/BingChaoLiu/DVB-Nexus/issues/152)）：
  - `voltage` ∈ {off, 13V, 18V}
  - `tone_commanded` ∈ {none, continuous, tone_burst, data_burst}
  - `tone_actual` ∈ 同上值域（+ 复合标记 `tone_composite` ∈ {none, continuous_plus_data_burst}）
  - `band_selected` ∈ {low, high, none}（none = 未供电）
  - `lo_frequency_khz`（9750/10600，未供电 = null）
  - `polarization_delivered` ∈ {vertical, horizontal, none}（由 voltage 推导：13V→V、18V→H，附录 A）
  - `short_circuit_state` ∈ {normal, clamping, hiccup, thermal_fault, fault_latched}
- health 映射：short_circuit_state ∈ {clamping, hiccup} → warn；{thermal_fault, fault_latched} → error；normal → 由下游传播。

## 6. 公开接口（接口级契约）

- `lnb_evaluator.evaluate(node, inputs, context) -> NodeEvalResult`：纯函数；同输入必同输出（无 IO/墙钟/随机，`virtual_time_ns` 由 orchestrator 提交，SPEC-202 §3/6.1）。
- band 选择纯函数：`(lnb_kind, voltage, tone_actual, tone_composite) → (band_selected, lo_frequency_khz, polarization_delivered)`，逐格语义 = 附录 A。
- 观测发射：`sec.state_observed`（per-node 快照，[#152](https://github.com/BingChaoLiu/DVB-Nexus/issues/152)）；health/CauseRef 走 SPEC-202 既有语义。
- fault 挂钩：RF 层原语 `TONE_RESIDUE`（SPEC-204，[#151](https://github.com/BingChaoLiu/DVB-Nexus/issues/151)）经求值前变换改写 `tone_actual`；本规格求值器不感知 fault 概念。
- REST/WS 面无新增端点（状态经 SPEC-305 查询面 + 既有 journal）。

## 7. 处理算法（接口级行为义务）

- **band 选择确定性**：附录 A 真值表逐格实现；`tone_burst`（A/B）对 band/polarization 正交（仅开关选择位，SA/SB 语义归 SPEC-622 引用）；复合态「continuous + data_burst」按 data_burst 寻址 + 持续 tone 的 band 语义叠加（附录 A #13/#14）。
- **0V 语义**：未供电 → 无 IF 输出（band=none、lo=null）；tone 无叠加载体（附录 A #1~#4）。
- **短路保护终态语义**：五态为终态集；进入保护态的触发 = fault（短路注入为候选原语，[#151](https://github.com/BingChaoLiu/DVB-Nexus/issues/151) 候选池）或上游事件；hiccup 自动重试节奏（128ms）与热关断温度（160°C 关/140°C 开）记为**参考表**不进求值——终态求值不仿真时序过程（诚实边界）；`fault_latched` 仅经显式清除复位。
- **legacy_cascade 简版**：tone → Satellite A/B 选择（sat_selected ∈ {A, B}）；band 由 tuning 频率与单本振直接推导（无 tone 频段切换）；与 SPEC-622 级联开关联动，A1/A2 场景不涉及。
- **22kHz 物理参数引用落点**：载波 22kHz±20%、电平 650mVpp±250mV、位定义 '0'=1.0ms+0.5ms / '1'=0.5ms+1.0ms——权威 = **ETSI TS 101 964 §A.1 + TI SLVA863**（免费，[#146](https://github.com/BingChaoLiu/DVB-Nexus/issues/146) 结论 2：Eutelsat 原版已无免费官方入口，禁引未核条款号）。

## 8. 错误处理

| 场景 | 处理 |
|---|---|
| config 缺 `lnb_kind` / `lo_frequencies` | prepare 拒绝（对齐 AC-204-01 session 变异前拒绝纪律） |
| tone_actual 出现复合态但 `lnb_kind=universal` 且无消息上下文 | 求值照附录 A 复合态行处理（复合态是合法状态不是错误） |
| 求值器内部异常 | `SIM_EVAL_NODE_FAILED` 节点级隔离（SPEC-202 §8，error health + NodeFailure） |
| 短路保护五态外值 | prepare 拒绝（状态词表受控） |
| `legacy_cascade` 携 `scr` 子段 | prepare 拒绝（SCR 仅 universal 语境，SPEC-623） |

## 9. 资源约束

- L0 求值复杂度上界：单节点 O(1) 纯内存计算；全拓扑（≤100 节点）单遍 ≤1ms 量级（[#147](https://github.com/BingChaoLiu/DVB-Nexus/issues/147) Q7：不设新 envelope 预算条目，规格只写复杂度上界）。
- 无新增运行时依赖；实现归 M7 实施票图（milestone 由 #159 产出）。

## 10. 依赖

| 依赖 | 性质 | 消费点 |
|---|---|---|
| SPEC-003 §2.4 / §6 | 来源枚举（state_evaluator）+ NodeType 注册表 + 平面启用（#148） | lnb 节点接入 |
| SPEC-202 §6 | 冻结求值接口 | lnb_evaluator 注册 |
| SPEC-301 + ADR-0006 | 事件信封 | sec.* 命名空间 additive（[#152](https://github.com/BingChaoLiu/DVB-Nexus/issues/152)） |
| SPEC-204（#151 修订后） | 作用层路由 | RF 层 TONE_RESIDUE 注入缝 |
| SPEC-623 | SCR 结构语义 | scr 子段结构（本票仅存在性） |
| ETSI TS 101 964 §A.1 / TI SLVA863 | 标准权威（免费） | 22kHz 物理参数 / 14 态表素材 |
| research/lnb-power-chain 分支（#146）（#146） | 向量素材 | 附录 A 逐格依据 + A2 症状链算术 |

## 11. 测试向量

### 11.1 golden 计划（状态域）

- 附录 A 14 态逐格用例：每格 (config, voltage, tone_commanded[, fault]) → (band_selected, lo_frequency_khz, polarization_delivered) 断言。
- `lnb_kind` 两变体分支用例（universal 全语义 / cascade 简版）。
- 短路五态用例（终态集 + fault_latched 显式清除）。
- `TONE_RESIDUE` 注入用例：tone_actual=continuous ≠ tone_commanded=none → 下游 SPEC-620 IF 偏移 850MHz 症状链（A2 素材，[#146](https://github.com/BingChaoLiu/DVB-Nexus/issues/146) 结论 6）。

### 11.2 独立验证

- 14 态表逐格**四源一致性**已在 #146 完成（TI SLVA863 / pabr / Inverto / Kathrein）——规格附录 A 每格标注来源行号；实现对拍 = 向量表本身（独立于实现产出）。
- L0 求值产物对拍：同 config 双跑逐字段一致（确定性复现纪律）。

### 11.3 性能基准

- 全拓扑求值耗时进实现票验收（不钉环境字面值，tests/README §6 纪律）。

## 12. 验收标准

- AC-621-01：附录 A 14 态逐格断言全绿（band/LO/polarization 三字段）。
- AC-621-02：`tone_commanded`/`tone_actual` 双字段独立可注入（TONE_RESIDUE 变换后求值产物反映错配）。
- AC-621-03：短路五态词表受控 + fault_latched 显式清除语义。
- AC-621-04：`sec.state_observed` payload 与 §5 metrics 键清单逐字段一致（state_evaluator 来源 + simulated 置信度）。
- AC-621-05：确定性复现——同 config + fault plan 双跑状态流逐字段一致。
- AC-621-06：legacy_cascade 简版语义 + cascade 携 scr 段 prepare 拒绝。

## 13. 非目标与风险

- 时序过程（hiccup 节奏/tone 波形）不仿真——若后续 effort 需要过程语义，另启（SIM_STATE 终态模型不变）。
- 风险：cascade 简版与 SPEC-622 联动语义在首版最薄——诚实标注，A1/A2 不涉及。

## 14. 交付要求

- 实现落位 src/simulation/state/evaluators/（包族与 SPEC-202 同域）；DTO 生成链权威 SPEC-500。
- ADR-0012 记录 L0 形态裁决（成文归 #156）；本规格 APPROVED 为 M7 开工前置。

## 15. 参考

- roadmap §2/§4；#146 findings（research/lnb-power-chain 分支）；#147/#148/#149/#151/#152 决议。
- ETSI TS 101 964 §A.1；TI SLVA863；TI TPS65235（短路保护状态机）；Inverto/Kathrein 手册（四格矩阵多源一致）。
- EN 50494/50607、EN 60728 族：付费，条款号「待原文核对」（#146 结论 5）。

## 附录 A — 14 态真值表（normative）

枚举逻辑：voltage 3 态 × tone 4 模式 = 12 态，「持续 22kHz」与「data burst」可复合（音调与消息复用同一 22kHz 载波，TI SLVA863 Figure 3 / TPS65235 §7.3.7）补 2 复合态，共 14 态。ToneBurst A/B 仅开关选择位（SA/SB），对 band/polarization 正交，语义对称不单列。

| # | voltage | tone | band_selected | lo_frequency_khz | polarization_delivered | 依据 |
|---|---|---|---|---|---|---|
| 1 | off | none | none | null | none | 未供电无 IF（pabr §3.2 / TPS65235 Table 7-3） |
| 2 | off | continuous | none | null | none | tone 叠加在电压上，无电压无载体（TPS65235 §7.3.7，推断） |
| 3 | off | tone_burst | none | null | none | 同 #2 |
| 4 | off | data_burst | none | null | none | 同 #2 |
| 5 | 13V | none | low | 9750 | vertical | TI Table 3 / pabr §3.2 / Inverto（3 源一致） |
| 6 | 13V | continuous | high | 10600 | vertical | 同上（3 源一致） |
| 7 | 13V | tone_burst | low | 9750 | vertical | burst = SA 开关位，不改 band（SLVA863 Figure 2） |
| 8 | 13V | data_burst | low | 9750 | vertical | data burst = DiSEqC 寻址，不改 band |
| 9 | 18V | none | low | 9750 | horizontal | TI Table 3 / pabr / Inverto（3 源一致） |
| 10 | 18V | continuous | high | 10600 | horizontal | 同上（3 源一致） |
| 11 | 18V | tone_burst | low | 9750 | horizontal | 同 #7 |
| 12 | 18V | data_burst | low | 9750 | horizontal | 同 #8 |
| 13 | 13V | continuous + data_burst（复合） | high | 10600 | vertical | SLVA863 Figure 3 + TPS65235 §7.3.7（同一载波复用） |
| 14 | 18V | continuous + data_burst（复合） | high | 10600 | horizontal | 同 #13 |

频段计划（universal）：低 10.70–11.70 GHz → LO 9750 → IF 950–1950 MHz；高 11.70–12.75 GHz → LO 10600 → IF 950–1950 MHz；重叠区 1100–1950 MHz 同 IF 槽位对应两 RF 相差 **850 MHz**（10600−9750），tone 是唯一消歧器——A2 症状链（残留 tone → LO 停 10600 → 低频段请求 IF 偏移 850MHz ≫ LO 漂移 ±3MHz → 失锁或错锁同槽高频段转发器）的算术依据（[#146](https://github.com/BingChaoLiu/DVB-Nexus/issues/146) 结论 6）。
