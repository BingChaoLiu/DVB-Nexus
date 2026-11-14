---
status: accepted
date: 2026-11-14
---

# 事件信封统一裁决：SPEC-301 权威信封、journal_seq 全序、opaque UUID + 语义 node_id

裁决三方事件信封冲突：甲方 SPEC-003 §2.3 RuntimeEvent、乙方 SIMULATION-INTEGRATION-CONTRACT、丙方 SPEC-301 + `schemas/event-envelope.schema.json`。三方互不兼容（乙方无法通过丙方 schema 校验），事件命名交集几乎为零，序列号语义三义（per Run / per session / per producer instance）。裁决过程见 [#8](https://github.com/BingChaoLiu/DVB-Nexus/issues/8)。本 ADR 只定契约语义；文件重写随 [simulation + observation 缝合批准](https://github.com/BingChaoLiu/DVB-Nexus/issues/12) 落地，不静默改归档底稿。

## 决定（逐条）

### 1. 权威信封 = SPEC-301 + event-envelope.schema.json（不制造第四方）

丙方为唯一有 JSON Schema 的一方，双时间点（source/observed + clock_domain/clock_epoch）与 CONTEXT.md 时间模型吻合，交付语义（at-least-once、幂等去重、journal 落库序）最完整。不重写混合体——那等于制造第四方信封。

- 甲方 SPEC-003 §2.3 RuntimeEvent 改写为**指向 SPEC-301 的一致性指针**（RunContext 保留不动）。
- 乙方 SIMULATION-INTEGRATION-CONTRACT 事件章节对齐 SPEC-301，其交付语义精华**嫁接**进 SPEC-301：
  1. **backpressure/限流**：progress/metrics 类事件可合并（coalesce）限流；fault/lifecycle/terminal run/verification 事件禁静默丢弃；WebSocket best-effort，客户端以 snapshot + journal_seq cursor 恢复。
  2. **scope.run_id**：Run 是八步闭环（ADR-0002）的事件归属单位，而丙方 scope 缺 run_id——补 nullable 字段（session 级事件为 null）。
  3. journal_seq 信封可见（见第 2 条）。
- `tenant_id` 保留，MVP 恒为 `"local"`（多用户/分布式已出 scope，ADR-0002；改字段名反多一次 schema 变更）。

### 2. 全序 = journal_seq（per session）

- 唯一全序字段 **`journal_seq`（int64，per session 单调）**：journal 在 durable append 时统一盖章，作为信封字段可见（schema 标 optional；生产者永不填，gateway 落库时填）。全序号天然不属于生产者字段。
- WebSocket 重连恢复 cursor = snapshot + journal_seq（吸收乙方恢复协议）。
- 废除：甲方 per-Run `sequenceNumber`、乙方 per-session flat `sequence`（并入 journal_seq）；丙方 `producer_seq` 降级 optional（生产者内部序，MVP 可不填）。
- 来源时间戳不定义全序（SPEC-301 §5 原文维持）。

### 3. ID 策略 = opaque UUID 机器实体 + 拓扑内语义 node_id

- **机器实体 ID（session/run/fault/scenario/artifact/event）= opaque UUID（uuid4，标准库）**，消费方不得解析语义；**ULID 废弃**（排序优势被 journal_seq 完全覆盖，uuid4 零依赖）。event_id 仍须重试稳定，去重键 `(producer_id, event_id)` 维持。
- **`TopologyNode.nodeId` = 拓扑内稳定语义 slug**（建拓扑时生成，如 `demux-0`）：节点是配置身份不是机器实体，SPEC-003 §2.1 `nodeId: string` 本就如此。乙方契约条款改写为"机器实体 ID opaque，node_id 例外为拓扑内语义 ID"。三方示例中的语义名即此层。
- **target 寻址双形式**：`correlation.node_id` 单独出现 = 节点级（状态面寻址、画布"Run 状态 + 诊断映射"，ADR-0005 决策 2）；`node_id + pid` = 流级（SIM_TS，pid 0~8191）。
- correlation 增 nullable **`port_id`**：Mux 天然多端口（ADR-0005 决策 5），端口级故障寻址将来必需；本轮 schema 反正要动，现在加避免再 bump 一次 minor。

### 4. 前向兼容 = 多 schema 文档兑现 + 信封松负载紧

- `schema_version` 保持 major.minor 字符串；**`const: "1.0"` 保留在这一份 schema 文档里**（它描述的就是 1.0）；发 1.1 = **新 schema 文档 + 新 `$id`**（additive optional only），major 才破坏性——兼容承诺由"文档族"兑现，不由单文档内放宽 const 兑现。
- 信封各层 `additionalProperties: false` → **`true`**（顶层 + producer/scope/time/correlation/timepoint），兑现 §8 "Consumers MUST ignore unknown optional fields"（原 false 使其物理不可能）。
- **payload 除外**：per-event-type payload schema 独立版本化并保持严格校验（§8 原文维持）——信封松、负载紧。
- 由此引申：`confidence` 等业务字段属 payload 层（diagnosis.* 的 payload schema），**不入信封**。

### 5. 事件注册表重整

- **故障生命周期 4 事件对 4 态**（SCHEDULED→ACTIVE→APPLIED→REMOVED）：
  - `fault.injected` = SCHEDULED（吸收乙方 `fault.scheduled`）
  - `fault.activated` = ACTIVE（吸收乙方 `fault.applied` 的"生效"义）
  - **新增 `fault.applied`** = APPLIED（L1 专用：故障字节已进入产物流的确认；状态级场景与 activated 同时发生，applied 可省略）
  - `fault.cleared` = REMOVED（吸收乙方 `fault.removed`）
- **补 run 家族**：`simulation.run_started / run_progress / run_completed / run_failed`（丙方只有 session_*；run_progress 允许合并限流，走第 1 条嫁接的 backpressure 规则）。
- **`snapshot.updated` 撤出事件注册表**：snapshot 定为重连/大幅变更时拉取的状态 API（带 `journal_seq` cursor 参数）——全状态大对象不进事件流；乙方自己的恢复协议本就是拉取语义。
- 乙方 `lifecycle.changed` 废除：session 态走 `session_*`、run 态走 `run_*`、节点态随 L0 进 roadmap（ADR-0005 决策 2 已裁决画布降级）。
- 乙方 `verification.completed` 权威名定为丙方 **`recovery.verification_completed`**（与 CONTEXT.md 通关/Recovery Verification 术语吻合）。
- **命名纠偏：`observation.alert_*` → `diagnosis.raised / diagnosis.updated / diagnosis.cleared`**——SPEC-003 §2.6 与 CONTEXT.md 均明确 Diagnosis（根因候选）≠ Observation（事实），诊断结果不得挂 observation 命名空间；`observation.*` 留给未来观测面阈值告警。
- 原样保留：`topology.state_changed`、`simulation.clock_advanced`、`ts.*` 家族（packet_batch_observed/continuity_error/pcr_jitter_observed/psi_section_observed/service_state_changed）、`scenario.step_*`。
- Packet 级构造可视化事件（ADR-0005 决策 3）的具体类型留 [ts-core 修订批准](https://github.com/BingChaoLiu/DVB-Nexus/issues/11) 裁定；信封只需容忍高频事件（合并限流）。

## Consequences

- **文件重写清单**（随 #12 缝合批准落地，不静默改归档底稿；provenance 不动）：
  1. `docs/spec/DVB-Sandbox-Spec-v0.4-Complete/docs/modules/Observation-Metrics/SPEC-301-event-contract.md`：§5 嫁接 backpressure/合并限流与 snapshot + cursor 恢复；scope 加 run_id；§4 注册表按第 5 条重整；§2 示例重写（uuid4、journal_seq、tenant_id=local）。
  2. `docs/spec/DVB-Sandbox-Spec-v0.4-Complete/schemas/event-envelope.schema.json`：additionalProperties 翻 true（payload 除外）；scope.run_id、correlation.port_id、journal_seq（optional）三字段；`$id` 注明多文档版本策略。
  3. `docs/spec/DVB-Sandbox-Spec-v0.4-Complete/docs/modules/simulation/SIMULATION-INTEGRATION-CONTRACT.md`：Event envelope 章节对齐 SPEC-301；snapshot 改拉取 API + cursor 语义；backpressure 条款并入 SPEC-301 后保留引用。
  4. `docs/spec/DVB-Sandbox-Spec-v0.4-Complete/docs/architecture/SPEC-003-domain-model.md` §2.3：RuntimeEvent 改一致性指针（含三方映射表），RunContext 不动。
- **下游**：[缝合批准](https://github.com/BingChaoLiu/DVB-Nexus/issues/12) 修订清单已含信封项并补挂 SPEC-003 §2.3；[补写契约](https://github.com/BingChaoLiu/DVB-Nexus/issues/13) 按权威信封起草 WS/REST（重连 = snapshot + journal_seq cursor；confidence 入 payload 不入信封）；[故障管线裁决](https://github.com/BingChaoLiu/DVB-Nexus/issues/9) 直接引用 fault.* 4 事件名。
- CONTEXT.md 增词条：事件信封（Event Envelope）、流水号（Journal Seq）。
