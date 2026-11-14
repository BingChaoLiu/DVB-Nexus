---
spec_id: SPEC-301
title: Canonical Event Contract
version: 0.5.0
status: APPROVED
phase: MVP
owner: Observation
priority: P0
depends_on: [SPEC-003]
requirements: [REQ-OBS-301-001, REQ-OBS-301-002, REQ-OBS-301-003, REQ-OBS-301-004, REQ-OBS-301-005, REQ-OBS-301-006]
---

# SPEC-301 — 权威事件信封契约

## 1. 目的与权威性

定义全平台唯一事件信封，TS Core、Simulation Engine 与 Observation 共用（Live adapter 远期同构接入）。payload 按事件类型各异；信封与投递语义全局唯一。

**权威来源**：本文件 + `schemas/event-envelope.schema.json`（[ADR-0006](../../../../adr/0006-canonical-event-envelope.md) 第 1 条裁决）。不制造第四方信封；`SPEC-003` §2.3 的 RuntimeEvent 是指向本契约的一致性指针；`SIMULATION-INTEGRATION-CONTRACT` 事件章节对本契约保持一致。若本文与单模块 Spec 冲突，提交 Spec Change Request，不得自行取舍。

## 2. 信封示例

下例是 **journal 落库后的记录视图**（`journal_seq` 已盖章；生产者发布时不携带该字段）：

```json
{
  "schema_version": "1.0",
  "event_id": "7e6c8e17-6f4e-4f6a-9a34-2b9d1c9a5f21",
  "event_type": "ts.continuity_error",
  "producer": {
    "producer_id": "ts-core",
    "producer_version": "0.5.0",
    "instance_id": "ts-core-1",
    "producer_seq": 42
  },
  "scope": {
    "tenant_id": "local",
    "session_id": "0f0e8d1c-2b3a-4c5d-8e9f-0a1b2c3d4e5f",
    "run_id": "11a2b3c4-d5e6-47f8-8a9b-0c1d2e3f4a5b",
    "scenario_id": null
  },
  "time": {
    "source":   {"value_ns": 1200000000, "clock_domain": "sim:0f0e8d1c-2b3a-4c5d-8e9f-0a1b2c3d4e5f", "clock_epoch": 0},
    "observed": {"value_ns": 1790000000000000000, "clock_domain": "wall:utc", "clock_epoch": 0}
  },
  "correlation": {
    "trace_id": "trace-demo",
    "span_id": null,
    "parent_event_id": null,
    "fault_id": "21b3c4d5-e6f7-4809-9a0b-1c2d3e4f5a6b",
    "node_id": "demux-0",
    "port_id": null,
    "service_id": "service-100",
    "pid": 256
  },
  "journal_seq": 1042,
  "severity": "warning",
  "payload": {
    "expected_cc": 4,
    "actual_cc": 6,
    "discontinuity_indicator": false,
    "packet_index": 12000,
    "source": "internal_parser",
    "confidence": "parsed"
  },
  "tags": ["ts", "continuity", "training"]
}
```

要点（ADR-0006 裁决落地）：`event_id`/`session_id`/`run_id`/`scenario_id`/`fault_id` 为 **uuid4 opaque**（ULID 废弃）；`node_id` 是拓扑内语义 slug；`tenant_id` 恒为 `"local"`；`scope.run_id` 为 nullable（session 级事件为 null）；`correlation.port_id` 为 nullable（端口级寻址，ADR-0005 决策 5 多端口 Mux）；`journal_seq` 由 gateway 落库时盖章。

## 3. 必填字段

- `schema_version`：major.minor 字符串；本 schema 文档为 `"1.0"`（多文档版本策略见 §8）。
- `event_id`：全局唯一、重试稳定（去重键 `(producer_id, event_id)` 的一半）。
- `event_type`：小写点分标识（§4 注册表）。
- `producer.producer_id` / `producer.producer_version` / `producer.instance_id`；`producer_seq` optional（生产者内部序，MVP 可不填）。
- `scope.tenant_id` 必填；`scope.session_id` nullable（仅 system-level 事件为 null）；`scope.run_id` nullable；`scope.scenario_id` nullable。
- `time.source` 与 `time.observed` 必填（timepoint：`value_ns` + `clock_domain` + `clock_epoch`；语义由字段名承载——source=来源时钟、observed=摄入观测，不另设 semantics 字段）。
- `correlation` optional，字段全 nullable：`trace_id` / `span_id` / `parent_event_id` / `fault_id` / `node_id` / `port_id` / `service_id` / `pid`（0..8191）。target 寻址双形式：`node_id` 单独 = 节点级（状态面），`node_id + pid` = 流级（SIM_TS）。
- `severity`：`debug|info|notice|warning|error|critical`。
- `payload`：JSON object，按事件类型 schema 由注册表严格校验（信封松、负载紧）。
- `tags`：有界字符串数组（≤ 32 项，单项 ≤ 64 字符）。
- `journal_seq`：**optional int64**；生产者永不填，gateway durable append 时盖章；同 session 单调，唯一全序凭据（CONTEXT.md「流水号」）。

## 4. 事件类型注册表（权威清单）

**simulation 家族**（生产者 Simulation Engine）：

- `simulation.session_created` / `session_started` / `session_paused` / `session_resumed` / `session_stopped`
- `simulation.run_started` / `run_progress` / `run_completed` / `run_failed`（run_progress 允许合并限流，§5）
- `simulation.clock_advanced`

**topology / ts 家族**：

- `topology.state_changed`
- `ts.packet_batch_observed` / `ts.continuity_error` / `ts.pcr_jitter_observed` / `ts.psi_section_observed` / `ts.service_state_changed`

> 观测记录义务（ticket #13 Q3-i 裁决）：`ts.*` 观测类事件的 payload schema 必须携带 `source`（五值 ObservationSource）与 `confidence`（四值 ConfidenceKind，SPEC-003 §2.4 模型）——信封不动（信封松负载紧，ADR-0006 第 4 条）；诊断侧规则置信度（SPEC-307 三档）是另一条轴，不得混用。

**fault 家族**（四事件对四态，SCHEDULED→ACTIVE→APPLIED→REMOVED，ADR-0006 第 5 条；语义详见 SPEC-204 §8）：

- `fault.injected` = SCHEDULED（prepare 校验通过）
- `fault.activated` = ACTIVE（窗口起点）
- `fault.applied` = APPLIED（**L1 专用**：故障字节进入产物流的确认；状态级场景与 activated 同时发生时可省略）
- `fault.cleared` = REMOVED（窗口终点或 run 结束）

**scenario / recovery 家族**：

- `scenario.step_started` / `scenario.step_completed`
- `recovery.verification_completed`（权威名；乙方 `verification.completed` 废除）

**diagnosis 家族**（生产者 Diagnosis Engine，SPEC-306/307；payload schema 含 `confidence` 三档枚举等，**属 payload 层不入信封**，已随 [补写 MVP P0 缺失契约](https://github.com/BingChaoLiu/DVB-Nexus/issues/13) 批准落地——形状见 SPEC-306 §7）：

- `diagnosis.raised` / `diagnosis.updated` / `diagnosis.cleared`

**已撤出/废除**（不得再注册）：

- `snapshot.updated`：撤出事件流——snapshot 定为带 `journal_seq` cursor 的拉取状态 API（SPEC-200 §4）。
- 乙方 `lifecycle.changed`：废除——session 态走 `session_*`、run 态走 `run_*`。
- `observation.alert_*`：MVP 无此事件——告警生命周期以 alert record 持久化为权威、经通知提示 + REST 暴露（SPEC-304 §8）；`observation.*` 命名空间留给未来观测面阈值告警的信封化。

**预留**：packet 级构造可视化事件族（ADR-0005 决策 3）的具体类型**未裁决**（[ts-core 修订批准 #11] 未裁定）；信封须容忍高频事件的合并限流，类型清单随前端/生成可视化范围评审补入注册表。

新增事件类型须注册 payload schema 并过兼容性评审。

## 5. 排序、投递与背压

- 生产者必须在首次发布前生成稳定 `event_id`，重试复用。
- 投递 **at-least-once**；Observation 按 `(producer_id, event_id)` 去重；重复提交返回原 `journal_seq` 且 `duplicate=true`。
- `journal_seq` 仅在 durable append 后盖章；**来源时间戳不定序**；生产者自造全序字段（per-Run sequenceNumber、per-session sequence）废除。
- 因果关系用 `parent_event_id` 与 trace 标识表达。
- **背压与合并限流**（自 SIMULATION-INTEGRATION-CONTRACT 嫁接，ADR-0006 第 1 条）：
  - `run_progress` / metrics 类高扇出事件**可合并限流**（coalesce：新值覆盖未投递旧值）；
  - `fault.*` / `session_*` / terminal run（`run_completed`/`run_failed`）/ `recovery.verification_completed` 事件**禁静默丢弃**；
  - 消费端慢时 journal 仍是事实源，消费者从检查点追赶。
- **WebSocket 通知是 best-effort 提示**，不是持久事件存储；客户端恢复协议 = **拉取 snapshot + `journal_seq` cursor**（WS 断线重连后先取 snapshot，再从 cursor 起追 journal；WS 通知主题归 SPEC-305 §7）。
- 消费者必须幂等。

## 6. 时钟语义

- `time.source` 是事件来源时钟；确定性仿真的 source 时间必须用会话虚拟时钟域（`sim:<session_id>`），epoch 变化递增 `clock_epoch`（SPEC-300 §6 规则 5）。
- `time.observed` 是摄入观测时间（wall:utc），生产者缺席时由 gateway 补填。
- 生产者**不得**因图省事用墙钟给虚拟时间事件盖章。
- 信封 timepoint 不设 `semantics` 字段——`source`/`observed` 字段名即语义；独立记录的 timepoint（告警/指标/检查点）须显式 `semantics`（SPEC-300 §6）。

## 7. payload 规则

- payload 是 JSON object，不是自由字符串。
- 序列化后默认上限 256 KiB。
- 二进制数据出链存储，以 scoped content id 引用。
- 禁密钥、BISS 密钥、凭证、私钥。
- 单位必须在字段名或 schema 元数据显式（`*_ns`、`*_bps`、`*_count`）。
- 缺失、未知、不适用三态可区分；仅 schema 允许处用 null。

## 8. 兼容性（多 schema 文档策略）

- `schema_version` 保持 major.minor 字符串；**`const: "1.0"` 保留在本 schema 文档内**（它描述的就是 1.0）。
- 发 1.1 = **新 schema 文档 + 新 `$id`**，additive optional only；major 变更 = 破坏性，需迁移计划。
- 信封各层 `additionalProperties: true`（顶层 + producer/scope/time/correlation/timepoint）——消费者**必须忽略未知可选字段**；**payload 除外**：per-event-type payload schema 独立版本化并保持严格校验（信封松、负载紧）。
- 不支持 major 版本与未知必填字段 → 拒绝。

## 9. 错误处理

畸形事件在 journal 提交前拒绝，生产者收结构化错误（错误码归 SPEC-300 §13：`OBS_INVALID_ENVELOPE` / `OBS_UNSUPPORTED_SCHEMA` / `OBS_PAYLOAD_TOO_LARGE` / `OBS_DUPLICATE_EVENT` 等）。重复 event_id 幂等返回原 `journal_seq`。

## 10. 必需测试

- 每个必填/nullable 字段的信封校验矩阵。
- 重复重试幂等（同 event_id 二次投递返回原 journal_seq）。
- 乱序来源时间戳行为（不影响全序）。
- 时间范围查询的时钟域失配拒绝。
- 未知可选字段前向兼容（additionalProperties: true 生效）。
- 不支持的 major schema 拒绝。
- payload 大小与密钥字段策略。
- 合并限流：run_progress 可合并、fault/session/terminal/verification 不被丢弃。
- §4 注册表负向：未注册事件类型拒绝；已撤出类型（snapshot.updated / lifecycle.changed / observation.alert_*）拒绝。

## 11. 验收标准

- `REQ-OBS-301-001`：信封 schema 与本文件字段契约一一对应，且通过注册表校验。
- `REQ-OBS-301-002`：journal_seq 全序语义（gateway 盖章、per session 单调、生产者不填）实现并有测试。
- `REQ-OBS-301-003`：ID 策略合规（uuid4 opaque + node_id 语义 slug + port_id 寻址）。
- `REQ-OBS-301-004`：多文档兼容策略落地（1.0 文档 const、新版本新文档、信封松负载紧）。
- `REQ-OBS-301-005`：背压/合并限流与 snapshot + cursor 恢复协议可测。
- `REQ-OBS-301-006`：§4 注册表为唯一合法事件类型清单，含撤出类型的拒绝路径。

## 12. 非目标与风险

- 不定义 WS 传输细节（SPEC-501）与 REST 路由（SPEC-500，对齐 SPEC-108 §4 映射表——500 系批准时复核）。
- 不为 MVP 定义 diagnosis payload schema（随 #13）。
- 风险：packet 级构造事件类型未裁决（§4 预留）——前端可视化范围评审时补注册表，信封层无需变更。

## 13. 交付要求

schema 文件：`schemas/event-envelope.schema.json`（随本 spec 同版批准）。payload schema 注册表随实现按事件类型补齐；契约测试与生产者共享。

## 14. 参考

- ADR-0006（全部裁决）、ADR-0007 §6（fault 事件引用）。
- SIMULATION-INTEGRATION-CONTRACT（simulation 侧映射）、OBSERVATION-INTEGRATION-CONTRACT（生产者义务）。
- SPEC-003 §2.3（一致性指针与三方映射表）。
