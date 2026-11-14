---
spec_id: OBSERVATION-IC-001
title: Observation Integration Contract
version: 0.5.0
status: APPROVED
phase: MVP
owner: Observation
applies_to: SPEC-300..SPEC-305
depends_on: [SPEC-003, SPEC-301]
---

# Observation 跨模块集成契约

## 1. 目的与权威性

定义生产者（TS Core / Simulation Engine / 未来 Live adapter）与 Observation 之间的发布义务、事件映射、幂等与背压纪律。事件信封权威在 SPEC-301；本文承载**生产者侧义务**与映射表。冲突提交 Change Request，不得自行取舍。

## 2. 生产者义务

每个生产者必须：

1. 按 SPEC-301 信封 v1.0 发布。
2. 首次发布前生成稳定 `event_id` 并在重试时复用。
3. 提供来源时钟域与时间戳（虚拟时间事件用 `sim:<session_id>` 域，禁墙钟顶替）。
4. 提供 producer 身份/版本/实例。
5. 禁密钥与无界/高基数标签。
6. 把 Observation 当下游 sink；不依赖其私有类。
7. 处理显式的 retryable/non-retryable 发布错误。

## 3. Simulation Engine 映射

| Simulation 来源 | Observation 事件 |
|---|---|
| Runtime 生命周期 | `simulation.session_*` |
| Run 执行 | `simulation.run_started/progress/completed/failed`（run_progress 可合并限流） |
| 虚拟时钟 | `simulation.clock_advanced`（批量/合并；默认不逐调度 tick 发射） |
| L0 状态变化 | `topology.state_changed` |
| 故障注入 | `fault.injected`、`fault.activated`、`fault.applied`（L1 专用，状态级可省略）、`fault.cleared`（四事件对四态，ADR-0006 第 5 条） |
| Scenario Engine | `scenario.step_started`、`scenario.step_completed` |
| Recovery Verification | `recovery.verification_completed` |

会话/时钟/拓扑/故障的权威状态仍在 Simulation Engine；Observation 存副本供分析。告警生命周期**不是**信封事件——alert record 为权威（SPEC-304 §5）。

## 4. TS Core 映射

| TS Core 事实 | Observation 事件 |
|---|---|
| 包批统计 | `ts.packet_batch_observed` |
| CC 失配 | `ts.continuity_error` |
| PCR 采样/抖动 | `ts.pcr_jitter_observed` |
| PSI/SI section 解析 | `ts.psi_section_observed` |
| Service/PID 状态 | `ts.service_state_changed` |

TS Core 必须以显式单位与解析器/版本溯源发布规范化事实；高频包统计应批量；**默认不得逐包发事件**。

## 5. 幂等

生产者事件身份必须跨重试与进程级重试队列存活；无法保证 event_id 稳定的生产者不合规。重复提交幂等返回原 `journal_seq`（SPEC-300 §13）。

## 6. 背压

- Observation 返回 accepted/duplicate/rejected 结构化结果。
- 可重试存储错误在生产者侧用带抖动的有界指数退避。
- 生产者队列必须有界并暴露 dropped/rejected 计数。
- **仿真虚拟时钟线程不得阻塞于同步磁盘 IO**。
- 关键生命周期事件应使用持久化 producer outbox 或等价机制。
- 合并限流与禁丢清单的权威条款 = SPEC-301 §5。

## 7. 契约冻结清单

- [x] 事件信封 schema v1.0 批准（[缝合批准 #12]，APPROVED 0.5.0）。
- [x] 时钟域命名与 epoch 行为批准（SPEC-300 §6）。
- [x] 初始事件类型注册表批准（SPEC-301 §4，含撤出类型与 packet 级构造预留）。
- [x] 生产者重试与 outbox 行为批准（§5/§6）。
- [x] 安全/脱敏策略批准（SPEC-300 §9）。
- [ ] TS 包批事件 payload schema 批准（随实现按 SPEC-301 §7 注册，conformance 验证）。
- [ ] 拓扑快照版本与身份细则批准（SPEC-502 批准时收口）。
- [ ] 性能档位与保留取值批准（挂 [OPEN-006 定档 #16]）。

## 8. 集成顺序

1. 与生产者共享契约测试。
2. Event Gateway + Journal。
3. Simulation Engine 生命周期/故障事件。
4. TS Core 规范化事件。
5. Metrics 与 Timeline。
6. Health/Alerts。
7. Query API 与前端集成。
8. 负载、重放确定性与保留验证。

## 9. 非协商边界

Observation **绝不** import 或调用 Simulation Engine 突变接口、TS Core 解析器内部、Diagnosis Engine 判定 API。集成只经已发布契约（观察者边界纪律，SPEC-300 §3）。
