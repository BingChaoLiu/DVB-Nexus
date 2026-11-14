---
spec_id: SIMULATION-IC-001
title: Simulation Engine Integration Contract
version: 0.5.0
status: APPROVED
phase: MVP
owner: Simulation Engine
applies_to: SPEC-200..SPEC-206
depends_on: [SPEC-001, SPEC-003, SPEC-301]
---

# Simulation Engine 跨模块集成契约

## 1. 目的与权威性

本文定义 SPEC-200~206 之间必须一致的依赖方向、ID 策略、事件义务、快照/Artifact 契约与版本策略。**事件信封权威在 SPEC-301**（ADR-0006 第 1 条）：本文只承载 simulation 包对信封的**发射义务**与包内约定，不定义信封字段。冲突处理同 TS-CORE-INTEGRATION-CONTRACT §1：标记冲突提交 Change Request，不得自行取舍。

## 2. 依赖方向

API/UI → Runtime(200) → Clock(201) / L0(202) / L1 adapter(203) → TS Core(100..108)；Scenario(205) → 200/204；Verification(206) → 205/306/308。包级依赖方向表见 REGISTRY §B 与 SPEC-INDEX-SIMULATION（两处一致，[缝合批准 #12] Q5 裁决）。**TS Core 不得 import Simulation Engine**；Observation/Diagnosis 只消费事件与 Artifact。

## 3. ID 策略（ADR-0006 第 3 条）

- `session_id` / `run_id` / `fault_id` / `scenario_id` / `artifact_id` / `event_id`：**uuid4 opaque**，消费方不得解析语义；ULID 废弃。
- **例外**：`node_id`（TopologyNode.nodeId）是拓扑内稳定**语义 slug**（建拓扑时生成，如 `demux-0`）——节点是配置身份不是机器实体。
- target 寻址双形式：`node_id` 单独 = 节点级（状态面/画布映射），`node_id + pid` = 流级（SIM_TS，pid 0~8191）；`correlation.port_id` 承载端口级寻址。
- revision 每 session 单调递增。

## 4. 事件义务（信封 = SPEC-301）

生产者义务：经 SPEC-301 信封发布；`event_id` 首发前生成、重试稳定；来源时钟域/时间戳必填；producer 身份/版本/实例必填；禁密钥与高基数标签。

本包事件类型（注册表权威清单 = SPEC-301 §4）：

- 生命周期：`simulation.session_created/started/paused/resumed/stopped`（SPEC-200）
- Run 家族：`simulation.run_started/run_progress/run_completed/run_failed`（run_progress 可合并限流）
- 时钟：`simulation.clock_advanced`（可合并限流；默认不逐调度 tick 发射）
- 拓扑：`topology.state_changed`（SPEC-202）
- 故障：`fault.injected/activated/applied/cleared`（四事件对四态，ADR-0007 §6 / ADR-0006 第 5 条；SPEC-204 §8/§9）
- 场景：`scenario.step_started/step_completed`（SPEC-205）
- 验证：`recovery.verification_completed`（SPEC-206；权威名）

**已废除的乙方事件**：`lifecycle.changed`（session 态走 session_*、run 态走 run_*）；`fault.scheduled/applied/removed` 旧名并入四事件权威名；`verification.completed` 改用 recovery 权威名。全序由 gateway `journal_seq` 盖章——**生产者不自造全序号**。

## 5. Snapshot 与 Artifact

- **Snapshot 是拉取状态 API**（ADR-0006 第 5 条）：全量替换视图 + `journal_seq` cursor 参数；`snapshot.updated` 已撤出事件注册表，**不以事件发布全状态大对象**。重连恢复协议 = 拉取 snapshot + journal_seq cursor 追 journal（SPEC-301 §5）。
- Artifact 记录：ID（uuid4）、kind（generated_ts/faulted_ts/log，SPEC-203 §5.2）、status（complete/partial/failed）、相对 URI、大小、SHA-256、producing run_id、config_hash 与元数据。**永不接受客户端文件系统路径**；路径安全归 SPEC-503。

## 6. 背压（细则归 SPEC-301 §5）

progress/metrics 类事件可合并限流；fault、lifecycle、terminal run、verification 事件禁静默丢弃；WebSocket best-effort，客户端以 snapshot + journal_seq cursor 恢复。原始包经有界 evidence API 拉取，**不逐包广播**。仿真时钟线程不得阻塞于慢消费端（SPEC-300 §8 同源）。

## 7. 版本策略

每个事件/场景带 schema_version。additive optional 字段兼容；语义/单位变更或删除须破坏性版本 + 迁移说明（SPEC-301 §8 多文档策略同样适用于 payload schema）。

## 8. 安全

事件 payload、日志、mutation log、场景文档禁含密钥（BISS 等）与凭证；学习者动作白名单归 SPEC-205 §4；MVP 故障只作用于本地合成码流（SPEC-204 §10）。
