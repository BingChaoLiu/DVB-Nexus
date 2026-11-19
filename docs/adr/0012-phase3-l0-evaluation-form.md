---
status: accepted
date: 2026-11-20
---

# Phase 3 L0 求值引擎形态：在 SPEC-202 冻结骨架上注册 RF/SEC 求值器，不新建引擎；SIM_STATE Run 一等公民且不门控 L1

裁决 Phase 3（RF/SEC 沙盘）L0（SIM_STATE）求值引擎的形态。裁决过程 = Phase 3 地图 [#143](https://github.com/BingChaoLiu/DVB-Nexus/issues/143) 细裁票 [#147](https://github.com/BingChaoLiu/DVB-Nexus/issues/147)（自动推进授权「按推荐处理」，决议评论留全量审计记录）；证据 = 验证层 research 票 [#144](https://github.com/BingChaoLiu/DVB-Nexus/issues/144)/[#145](https://github.com/BingChaoLiu/DVB-Nexus/issues/145)/[#146](https://github.com/BingChaoLiu/DVB-Nexus/issues/146)（DiSEqC 命令模型/Unicable 消息层/LNB 14 态真值表，findings 分支留档）+ 现状盘点（SPEC-202 §6 冻结骨架，票 #40 交付）。规格承载 = SPEC-620/621/622/623（modules/rf/）。

## 背景：ADR-0005 砍掉的是什么、留下的是什么

[ADR-0005](0005-architecture-baseline.md) 决策 2 以「八步闭环无 SIM_STATE 依赖 + 第二通路工程成本」为由，将 MVP 的完整 L0 节点语义求值 defer：**被砍的是「每节点求值器语义 + 第二观测通路 + 诊断双路径 + 拓扑健康求值 UI」**。而 SPEC-202 §6（票 #40）落地的是**冻结接口 + 确定性骨架**：`NodeEvaluator` 注册制协议、确定性拓扑遍历（REQ-SIM-202-002/003）、`SIM_EVAL_NODE_FAILED` 节点级隔离、严重度优先序、下游 CauseRef 因果链线程（REQ-SIM-202-004）、纯度纪律（无 IO/墙钟/随机，`virtual_time_ns` 为 committed 整数）、`topology.state_changed` 纯 diff 半。未注册节点类型求值为 idle（`L0_DEFERRED_RATIONALE` 留档）。

Phase 3 三张研究票的产出（DiSEqC 1.x 单向命令语义、Unicable 用户态消息构造层、LNB 14 态供电真值表）全部是**节点级状态机语义**——恰是「注册求值器」粒度的输入。

## 决定（逐条）

### 1. 形态：最小状态求值器 = 既有骨架上注册求值器（拒绝新建引擎与 SIM_TS 化）

- **采纳**：RF/SEC 域求值器以 SPEC-202 `NodeEvaluator` 协议注册（NodeType 注册表机制，SPEC-003 §6）；确定性遍历/健康聚合/因果链/纯度纪律**零新机制**。
- **拒绝**：完整第二通路（候选 a）——骨架现状证明其成本构成的大半（确定性遍历/健康聚合/因果链）已免费存在，重建即浪费；诊断双路径明确不要（§4）。
- **拒绝**：SIM_TS 化编码（候选 c）——无法锁定/失锁/BER 飙升是接收状态概念，硬塞 TS 字节层只能伪造证据（No fake evidence 红线）。
- 接口零变更：状态语义经 `NodeEvalResult.metrics` 承载（JSON-safe 键值）；若后续证明不足，走 SPEC-202 定点修订并单独论证（本 Phase 未触发）。

### 2. Run 形态：SIM_STATE Run 一等公民，L0 不门控 L1

- SIM_STATE Run 为 Phase 3 一等公民（三保真级枚举既定预留）；Lab Pack v3 场景声明 SIM_STATE Run，八步闭环走状态域等价链：Generate = L0 状态求值产出状态观测流（`rf.*/sec.*`，[#152](https://github.com/BingChaoLiu/DVB-Nexus/issues/152)）、Inject = 状态级 fault（[#151](https://github.com/BingChaoLiu/DVB-Nexus/issues/151)）、Analyze = 既有 SPEC-307 规则引擎吃 simulated 观测、Verify = 修复后新 Run 状态证据（三态判定不变）。
- **L0 独立求值、不门控 L1 生成**：无锁不产码流的跨保真级门控留 Later effort——A1/A2 症状链不需要，门控引入两层耦合。
- SIM_STATE Run 无 gen.* 构造事件、无 TS artifact（状态域不冒充构造事件，诚实区分两条 Run 产物面）。

### 3. fault 进求值：求值前纯变换

- state 层（RF/SEC）fault 以「求值前纯变换」进入：fault plan 对 node config/context 做确定性变换后求值，**求值器不感知 fault 概念**；包级 layer（TS/BBFRAME/T2MI/BISS）维持 ADR-0007 过滤器契约——同一 FaultDefinition 按 layer 路由两条执行通路（[#151](https://github.com/BingChaoLiu/DVB-Nexus/issues/151) Q1）。
- 状态域等位替换 = 声明字段级改写 + baseline/faulted 观测流字段级对齐；不承诺包级不变式（无包流可保持，诚实标注）。

### 4. 诊断路径：不建第二引擎

- 状态级诊断规则候选进 SPEC-307 既有规则引擎（`TONE_RESIDUE_SUSPECT` medium / `UB_CONFLICT_SUSPECT high`，[#151](https://github.com/BingChaoLiu/DVB-Nexus/issues/151) Q4）；Diagnosis/Observation 两轴纪律不变。候选 a 的「诊断双路径」成本主因就此砍掉。

### 5. 健康显示收编

- canvas 节点 health 徽标数据源 = L0 求值产物（`TopologyEvalResult` 节点 health + graph_health 聚合）；CauseRef 因果链直达根因的既有能力成为 RF/SEC 排查教学的可视化素材；`L0_DEFERRED_RATIONALE` 记录的降级路径退役。UI 呈现归 SPEC-401/403/404/406 定点修订（[#153](https://github.com/BingChaoLiu/DVB-Nexus/issues/153)，成文票 #158）。

### 6. 性能与触发

- 不设新 envelope 预算条目：L0 求值 O(节点数) 纯内存计算，规格只写复杂度上界（≤100 节点 ≤1ms 量级）。
- 求值触发点 = Run prepare 与 fault 注入后重求值（编排归 M7 实施票图）；确定性复现契约（同 config + fault plan + 版本 → 同终态）不变。

## 后果

- 实现票需落三节点求值器（lnb/tuner/diseqc_switch）+ `state_evaluator` 观测来源 + `rf.*/sec.*` 事件桥（SPEC-003/303/304/305 定点修订与 SPEC-620~623 规格已就绪，0.6.0/0.7.0 APPROVED）；`L0_DEFERRED_RATIONALE` 注释在求值器注册齐备后移除（stub 收编）。
- 后续翻转成本：若 Phase 4（Live Mode）需要真实硬件状态源，注册制接口不变——新来源（hardware）按既有 source 枚举接入，求值器语义可复用；决策可逆性高。
- 明确不做：诊断双路径、L1 门控、时序过程仿真（hiccup 节奏/tone 波形）、连续 BER 数值——全部留痕于各规格「非目标」章，后续 effort 若需另启裁决。
