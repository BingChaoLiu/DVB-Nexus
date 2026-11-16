---
spec_id: SPEC-003
title: Domain Model and Shared Contracts
version: 0.6.0
status: APPROVED
phase: BASELINE
owner: Architecture
depends_on:
  - SPEC-001
---

# SPEC-003 — 领域模型与共享契约

## 1. 目标

定义跨模块共享的最小概念，避免 Topology、Runtime、Observation、Diagnosis、API 和前端分别维护不兼容的数据结构。具体字段最终由对应 Module Spec 扩展和冻结。

## 2. 核心实体

### 2.1 Topology

描述用户设计的节点、端口和连接，是配置模型，不是运行状态。

```typescript
type SignalPlane = 'RF' | 'SEC_CONTROL' | 'MPEG_TS' | 'T2MI' | 'IP';
type PortDirection = 'input' | 'output' | 'bidirectional';

interface Topology {
  topologyId: string;
  revision: number;
  nodes: TopologyNode[];
  connections: TopologyConnection[];
}

interface TopologyNode {
  nodeId: string;
  nodeType: string;
  config: Record<string, unknown>;
  ports: TopologyPort[];
}

interface TopologyPort {
  portId: string;
  direction: PortDirection;
  plane: SignalPlane;
  protocol?: string;
  maxConnections?: number;
}

interface TopologyConnection {
  connectionId: string;
  from: { nodeId: string; portId: string };
  to: { nodeId: string; portId: string };
  plane: SignalPlane;
}
```

约束：配置模型需做版本化和 schema 校验。不同信号平面不能仅凭 UI 连线建立有效连接；由后端 Validator 检查端口 plane、方向、容量和协议兼容性。MVP 实际启用 `MPEG_TS`。

### 2.2 RunContext

```typescript
interface RunContext {
  runId: string;
  sessionId: string;
  topologyId: string;
  topologyRevision: number;
  sequenceNumber: number;
  mode: 'sandbox' | 'live';
  fidelity: 'SIM_STATE' | 'SIM_TS' | 'LIVE';
  startedAtUtcMs: number;
  generatorVersion?: string;
  configHash?: string;
  seed?: number;
}
```

- `sequenceNumber` 在同一 Run 内单调递增。
- `topologyRevision` 用于防止旧配置计算结果覆盖新配置状态。
- `startedAtUtcMs` 是 UTC Unix epoch 毫秒；协议仿真时间另行表达，不混用墙钟。
- `LIVE` 是未来模式，MVP 不要求实现。

### 2.3 RuntimeEvent Envelope（一致性指针）

全平台唯一事件信封的**权威契约是 SPEC-301 + `schemas/event-envelope.schema.json`**（[ADR-0006](../../adr/0006-canonical-event-envelope.md) 第 1 条裁决：不制造第四方信封）。本节原 `RuntimeEvent` 接口废除，各模块不得再按旧形态实现事件；跨 WebSocket/持久化边界的字段兼容性由 SPEC-501 定义。

原甲方字段与乙方（SIMULATION-INTEGRATION-CONTRACT）、丙方（SPEC-301）的映射：

| 甲方 RuntimeEvent（废除） | 乙方旧信封（废除） | 丙方 SPEC-301（权威） |
|---|---|---|
| `eventId` | `event_id` | `event_id`（uuid4 opaque，重试稳定） |
| `runId` | `run_id` | `scope.run_id`（nullable，session 级事件为 null） |
| `sequenceNumber`（per Run） | `sequence`（per session） | **废除**；全序 = `journal_seq`（gateway 盖章，per session 单调，生产者永不填） |
| `eventType` | `event_type` | `event_type`（注册表 = SPEC-301 §4） |
| `emittedAtUtcMs` | `wall_time`（operational-only） | `time.observed`（wall:utc，gateway 补填） |
| `simulationTimeTicks` | `virtual_time_ns` | `time.source`（`sim:<session_id>` 时钟域） |
| `schemaVersion`（number） | `schema_version`（per event/scenario） | `schema_version`（"1.0" 字符串，多 schema 文档族） |
| `payload` | `payload` | `payload`（信封松、负载紧：per-event-type schema 严格校验） |

`RunContext`（§2.2）**保留不动**；其 `sequenceNumber` 是 Run 自身的序（非事件全序），`startedAtUtcMs` 是 operational 元数据——两者均不参与事件定序。

### 2.4 Observation

Observation 表示被测量、解析、模拟或推断的事实，不直接等同于根因。

```typescript
type ObservationSource =
  | 'generator' | 'internal_parser' | 'tsduck' | 'hardware' | 'rule_engine';
type ConfidenceKind = 'simulated' | 'parsed' | 'measured' | 'inferred';

interface Observation {
  observationId: string;
  runId: string;
  source: ObservationSource;
  confidence: ConfidenceKind;
  type: string;
  observedAtUtcMs: number;
  simulationTimeTicks?: number;
  pid?: number;
  packetIndex?: number;
  value?: unknown;
  unit?: string;
  artifactId?: string;
  evidenceRefs?: string[];
}
```

禁止规则：`source='tsduck'` 的结果不得标成 `measured`；`SIM_STATE` 生成的结果不得标成 `parsed`；硬件测量值不得与模拟值混为同一可信类别。

**payload 映射指针**（ticket #13 Q3-i 裁决）：观测类事件（`ts.*` 家族等，SPEC-301 §4）的 payload schema 必须携带 `source`（五值 `ObservationSource`）与 `confidence`（四值 `ConfidenceKind`）——信封不动（信封松负载紧，[ADR-0006](../../adr/0006-canonical-event-envelope.md) 第 4 条），本接口是观测记录的逻辑模型，事件 payload 是其传输/持久形态。注意此轴与 Diagnosis 的规则置信度（SPEC-306/307 的三档声明）是**两条不同的轴**。

### 2.5 Metric

```typescript
interface Metric {
  metricId: string;
  runId: string;
  name: string;
  value: number | string | boolean;
  unit?: string;
  source: ObservationSource;
  quality: 'valid' | 'unavailable' | 'estimated' | 'invalid';
  observedAtUtcMs: number;
  windowStartUtcMs?: number;
  windowEndUtcMs?: number;
  pid?: number;
}
```

不同指标的采样窗口、聚合方式、有效范围和单位由 SPEC-302 定义。不能把未知值强制填成 0。

### 2.6 Diagnosis

Diagnosis 表示规则或分析逻辑产生的根因候选，不是原始事实。

```typescript
interface Diagnosis {
  diagnosisId: string;
  runId: string;
  ruleId: string;
  code: string;
  severity: 'info' | 'warning' | 'error' | 'critical';
  title: string;
  summary: string;
  confidence: 'low' | 'medium' | 'high';
  observationIds: string[];
  affectedNodeIds?: string[];
  suggestedActions?: string[];
  createdAtUtcMs: number;
}
```

`confidence` 是规则的**静态三档声明**（ticket #13 Q3-ii 裁决：`low/medium/high`，由规则定义方声明、引擎不计算连续分，语义归 SPEC-307）；不得在没有校准依据时宣称统计概率。连续置信分与概率校准进 roadmap。

### 2.7 TSArtifact

```typescript
interface TSArtifact {
  artifactId: string;
  runId: string;
  kind: 'input_ts' | 'generated_ts' | 'faulted_ts' | 'report' | 'log' | 'evidence';
  relativePath: string;
  packetSize?: 188 | 204;
  packetCount?: number;
  byteSize: number;
  sha256: string;
  generatorVersion?: string;
  configHash?: string;
  faultProfileIds?: string[];
  createdAtUtcMs: number;
}
```

`relativePath` 必须相对应用管理的 Artifact 根目录。不能把任意绝对文件路径直接暴露给 API 客户端。

## 3. 状态模型

建议将状态拆开，不用单一 `health` 表达所有语义：

- `lifecycleState`：created / starting / running / stopping / stopped / failed。
- `operationalState`：active / idle / unavailable。
- `health`：ok / warn / error / unknown。
- `lockState`：locked / unlocked / acquiring / not_applicable（仅适用有 Lock 语义的设备）。

各节点类型允许的状态组合由 SPEC-003 后续修订或节点 Module Spec 定义。

## 4. 时间模型

必须区分：

1. `observedAtUtcMs`：现实世界 UTC 时间，用于日志和排序。
2. `simulationTimeTicks`：仿真虚拟时间，单位和时钟频率由 Simulation Clock Spec 定义。
3. PCR/PTS/DTS：MPEG-TS 协议时钟域，按标准定义的回绕和时基处理。

不得用系统当前毫秒时间直接代替 PCR 或 PTS。

## 5. 版本与兼容

- 对外 JSON Schema 必须有版本策略。
- 添加可选字段通常可兼容；删除、改名、改变单位或枚举语义属于破坏性变化。
- 所有持久化的 Run、Event、Artifact 必须能关联 schema/generator/analyzer 版本。
- 前端不得自行推导未提供的协议测量值。

## 6. 待模块 Spec 明确

- 完整 NodeType 注册表和每种节点 Config Schema。
- Runtime 生命周期状态机。
- EventType 注册表和事件 payload schema。
- Observation/Metric 的单位与枚举注册表。
- Diagnosis 规则优先级、抑制、关联和置信度语义。
- Artifact 保留、清理、访问和校验策略。

## Phase 2 定点修订（随落笔票 #117，DRAFT_FOR_REVIEW 0.6.0；依据：Phase 2 地图细裁 [#110](https://github.com/BingChaoLiu/DVB-Nexus/issues/110)，[ADR-0010](../../../../../docs/adr/0010-phase2-t2mi-integration-path.md)）

- **平面启用**：`MVP_ENABLED_PLANES` 由 {MPEG_TS} 扩容为 {MPEG_TS, T2MI}；`RF`/`SEC_CONTROL`/`IP` 维持禁用（Phase 3/4）。
- **NodeType 注册表新增两类型**：`t2mi_encapsulator`（in MPEG_TS / out T2MI，内部含 BBFrame 封装段）、`t2mi_demux`（in T2MI / out MPEG_TS，PLP 过滤入 config）——机制零新增（§6 既有注册表）。
- **BBFrame 定位**：节点内部层次，**非独立信号平面**（五平面枚举无 BBFrame，不新增第六平面）；BBHEADER 语义（EN 302 755 §5.1.7）属内部结构面。
- **端口模型零扩展**：既有 direction/plane/protocol/max_connections 四属性足够；BBFrame 层参数入节点 config。
- 等位替换不变式延展出**逐层语义**（layer ∈ {TS, BBFRAME, T2MI, BISS}，SPEC-204 同批修订）。
