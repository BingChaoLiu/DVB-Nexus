---
spec_id: SPEC-602
title: PLP Extractor（PLP 过滤与提取）
version: 0.5.1
status: APPROVED
phase: P2
owner: T2MI
priority: P2
depends_on: [SPEC-600, SPEC-601]
requirements: [REQ-602-001, REQ-602-002, REQ-602-003]
---

# SPEC-602 — PLP Extractor（PLP 过滤与提取）

## 1. 目标

定义 T2-MI 流中 **PLP（Physical Layer Pipe）的过滤与提取语义**：demux 侧按期望 PLP 过滤（消费方 = SPEC-603 Inner TS 重建）、encapsulator 侧 PLP 分配（构造方 = t2mi_encapsulator config）。靶场 B1（T2MI PLP 映射错位）的语义主场（[#111](https://github.com/BingChaoLiu/DVB-Nexus/issues/111) 原语 T2MI_PLP_MISMATCH）。

依据：[#107](https://github.com/BingChaoLiu/DVB-Nexus/issues/107)（crate `new_for_plp`/`plps_seen` API 面佐证 PLP 过滤为独立语义层）、[#110](https://github.com/BingChaoLiu/DVB-Nexus/issues/110)（不设独立 plp_filter 节点——PLP 语义入 t2mi_demux config 与 encapsulator PLP 分配表）、[#113](https://github.com/BingChaoLiu/DVB-Nexus/issues/113)。

## 2. 范围

### 2.1 In Scope

- 解析侧：PLP 识别（流内出现过的 PLP 集合 `plps_seen`）、按期望 PLP 过滤（`expected_plp` 模式）、全量不过滤模式。
- 构造侧：PLP 分配表（`plp_assignment`：业务/流到 PLP ID 的映射）与封装时的 PLP 标注。
- B1 原语注入点：T2MI_PLP_MISMATCH（expected_plp/actual_plp 错位对 + 可选 plp_version_switch）。
- `t2mi.plp_mismatch` 事件 payload（[#113](https://github.com/BingChaoLiu/DVB-Nexus/issues/113)）。

### 2.2 Out of Scope

- T2-MI 包/BBFrame 层结构（SPEC-600/601）；Inner TS 输出（SPEC-603）；射频 PLP 物理语义（Phase 3 RF 面）；FEFC 多 PLP 调度全策略（MVP = 单流少量 PLP 的教学面）。

## 3. 术语

| 术语 | 定义 |
|---|---|
| PLP | Physical Layer Pipe：DVB-T2 的逻辑数据管道；T2-MI 流中随包标注 |
| PLP 分配表 | encapsulator config：业务流 → PLP ID 映射（构造侧事实源） |
| 期望 PLP | demux config：观测/重建侧选择的 PLP（B1 症状入口） |
| PLP 分布 | per Run 的 PLP → 包数统计（stage_summary 摘要，#113） |

## 4. 架构

- 无独立节点/平面（#110 裁决）：过滤语义 = t2mi_demux config（期望 PLP）；分配语义 = t2mi_encapsulator config（PLP 分配表）；fault 注入走作用层 T2MI 的原语。
- 数据流：SPEC-600 解析出的 T2-MI 包携带 PLP 标注 → 本规格过滤 → SPEC-603 重建；封装方向反向对称。

## 5. 数据模型

- `PlpAssignmentDTO`（encapsulator config 段）：`entries: [{plp_id, source_tag}]`（source_tag 对齐场景/业务标识）。
- `PlpFilterConfigDTO`（demux config 段）：`mode: expected | all`、`expected_plp: int | null`。
- `PlpSeenDTO`：`plps_seen: [int]`（流内实际出现集合，供 stage_summary 与诊断证据）。
- `t2mi.plp_mismatch` payload：`expected_plp / actual_plp / business_absent_evidence`（locator 引 Inner TS 业务缺失位置）。

## 6. 公开接口（接口级契约）

- `plp.filter(packets, config) -> Sequence[T2miPacket]`：确定性；期望 PLP 不存在于流 → 显式空结果 + plp_mismatch 候选事件（非静默空）。
- `plp.assign(sources, assignment) -> tagged stream`：封装侧 PLP 标注注入。
- `plp.plps_seen(packets) -> PlpSeenDTO`：流内实际 PLP 集合（诊断与教学证据）。

## 7. 处理算法（接口级行为义务）

- 过滤确定性：同流同 config 同结果。
- B1 注入路径：faulted run 中 encapsulator 按 actual_plp 分配（漂移自场景声明 expected_plp），demux 侧仍按 expected_plp 过滤 → Inner TS 业务缺失 + plp_mismatch 候选（症状链忠实 roadmap §4 B1：外层锁定正常、T2-MI 节点绿灯、内层无业务）。
- plp_version_switch 变体：packet_index 激活的中途切换（#111）。

## 8. 错误处理

| 场景 | 处理 |
|---|---|
| 期望 PLP 不在流内 | 显式空结果 + t2mi.plp_mismatch 候选（诚实「缺失 ≠ 零」纪律） |
| 分配表冲突（同 source 双 PLP） | prepare 前拒绝 |
| PLP ID 越出值域 | prepare 前拒绝（schema 校验） |

## 9. 资源约束

- 纯 Python；过滤为线性遍历（O(n)），预算并入 SPEC-600 吞吐面。

## 10. 依赖

| 依赖 | 性质 | 消费点 |
|---|---|---|
| SPEC-600 | 包模型与 PLP 标注 | 过滤输入 |
| SPEC-603 | 下游 | 过滤输出消费 |
| SPEC-204（#111 修订后） | 原语契约 | T2MI_PLP_MISMATCH |
| SPEC-301/ADR-0006 | 事件注册表 | t2mi.plp_mismatch |
| roadmap §4 B1（订正后） | 教学语义权威 | 症状链 |

## 11. 测试向量

- 正向：单 PLP / 多 PLP 流过滤 round-trip；plps_seen 统计一致。
- 负向：期望 PLP 缺失（B1 形态）、分配表冲突、PLP ID 越界。
- B1 场景向量：expected/actual 错位对 faulted 形态 + plp_version_switch 中途切换形态。

## 12. 验收标准

- **AC-602-01**（REQ-001/002）：过滤/分配/统计三接口在位，确定性钉扎。
- **AC-602-02**（REQ-003）：B1 原语全链绿（注入 → t2mi.plp_mismatch 事件 → 诊断候选 → 包检查器证据）；「缺失 ≠ 零」诚实态渲染（文案归 SPEC-403/404 修订面）。

## 13. 非目标

- RF 层 PLP 物理语义；多 PLP 调度优化策略；PLP 与 L1 信令联动（全部 Phase 3+ 或超出教学面）。

## 14. 兼容性与交付要求

- additive-only；批准流 DRAFT_FOR_REVIEW → repo 主通读确认 → APPROVED。
- B1 症状链的教学文案（外层绿灯但无业务）归 Lab Pack v2 场景（#118）与包检查器文案（#119）承载。
