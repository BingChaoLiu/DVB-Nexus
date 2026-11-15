---
spec_id: SPEC-300
title: Observation and Metrics Architecture
version: 0.5.0
status: APPROVED
phase: MVP
owner: Observation
priority: P0
depends_on: [SPEC-003]
requirements: [REQ-OBS-300-001, REQ-OBS-300-002, REQ-OBS-300-003, REQ-OBS-300-004, REQ-OBS-300-005, REQ-OBS-300-006, REQ-OBS-300-007]
---

# SPEC-300 — Observation & Metrics 架构

## 1. 目标

为 DVB Sandbox 提供统一的观测平面：摄入规范化事件与状态快照，派生指标与健康信号，持久化可检索时间轴，并向 UI、诊断模块与训练报告暴露只读查询接口。Observation 是事实记录者，不是根因判定者（CONTEXT.md「观测」）。

## 2. 范围

### 2.1 In Scope

- 事件摄入、校验、规范化与去重。
- 跨 session / 拓扑节点 / TS service/PID / fault 的关联。
- 指标派生与时间窗聚合。
- 时间轴持久化、检查点、导出与确定性时间支持。
- 健康规则与告警生命周期（记录权威，见 SPEC-304）。
- 时间轴、指标、告警与健康摘要的只读查询服务。
- 来源溯源（provenance）、数据质量标志与保留控制。

### 2.2 明确不做

- 创建或突变 simulation session；推进虚拟时间；调度任务。
- 突变拓扑或 L0/L1 状态；注入或移除故障。
- 作为主解析器解析原始 TS 包——TS Core 拥有解析并发规范化观测（OBSERVATION-INTEGRATION-CONTRACT §3）。
- 根因判定——Diagnosis Engine（SPEC-306/307）消费观测数据。
- 前端渲染与交互。
- 实况设备接入；Live adapter 未来经同一事件契约发布。

## 3. 架构位置

```text
 TS Core ─────────────┐
 Simulation Engine ───┼──> Event Gateway ──> Event Journal ──┬──> Metrics Engine
 Live Adapter (远期) ─┘                                      ├──> Timeline Recorder
                                                             ├──> Health/Alert Engine
                                                             └──> Read Query API
                                                                      │
                                                         UI / Diagnosis / Reports
```

Observation 位于生产者下游。**摄入与求值期间绝不调用生产者的突变 API**（观察者边界纪律，OBSERVATION-INTEGRATION-CONTRACT §8 非协商边界）。

## 4. 组件

### 4.1 Event Gateway

职责：
- 校验 schema 版本与必填字段（信封校验 = SPEC-301 + `event-envelope.schema.json`）。
- 强制 payload 大小与支持的事件类型（注册表见 SPEC-301 §4）。
- 生产者未提供 `time.observed` 时补填（wall:utc）。
- 保留来源时间戳与时钟域元数据。
- 按 `(producer_id, event_id)` 去重。
- 将接受的事件路由至 journal 与订阅者。

必须以结构化错误拒绝畸形事件，**不得静默修复语义非法的 payload**（无隐式修复原则）。

### 4.2 Event Journal

职责：
- 按摄入序追加已接受事件。
- 支持 cursor 读取。
- 按配置保留不可变事件记录。
- 维护独立于来源时间戳的单调 **journal_seq**（全序权威，ADR-0006 第 2 条；journal 在 durable append 时盖章，信封可见、生产者永不填）。
- 摄入失败记入独立诊断流，**不得**递归发布为普通领域事件。

### 4.3 Metrics Engine

消费事件与周期性状态快照，更新指标序列与聚合窗口。必须保留来源事件 ID 或派生水位（watermark）以解释每个聚合值（SPEC-302）。

### 4.4 Timeline Recorder

构建跨事件、状态快照、故障生命周期与检查点的统一时间轴。支持查询与导出，**不支持**仿真重放执行（SPEC-303）。

### 4.5 Health & Alert Engine

对事件/指标输入执行配置规则并管理告警生命周期。它不做根因判定，也不自动修复系统。**告警状态迁移以 alert record 持久化为权威，经 SPEC-305 WebSocket 通知提示 + REST 拉取暴露；MVP 不产生信封事件**（`observation.*` 事件命名空间留给未来观测面阈值告警的信封化，ADR-0006 第 5 条 + [缝合批准 #12] 裁决；SPEC-304 §8）。

### 4.6 Query API

面向 UI 与下游分析的只读接口（SPEC-305）：过滤器、有界时间范围、分页、显式时钟域。

## 5. 数据所有权

| 数据 | 权威归属 | Observation 行为 |
|---|---|---|
| Session 生命周期 | Simulation Runtime | 镜像为事件 |
| 虚拟时钟 | Simulation Clock | 保留时钟域/时间 |
| 拓扑状态 | L0 State Engine | 存快照/事件 |
| TS 语法/连续性事实 | TS Core | 摄入规范化事实 |
| 故障生命周期 | Fault Injection | 记录事件 |
| 场景进度 | Scenario Engine | 记录进度事件 |
| 通关判定 | Recovery Verification | 记录 verdict/证据 |
| 指标与时间轴 | Observation | **权威**派生记录 |
| 告警生命周期 | Observation | **权威**告警记录 |

## 6. 时钟模型

每个时间戳必须携带：

- `value_ns`：有符号 64 位整数纳秒。
- `clock_domain`：稳定标识，如 `sim:<session_id>` 或 `wall:utc`。
- `semantics`：`source` / `observed` / `derived`（**信封 timepoint 例外**：SPEC-301 信封的 `time.source`/`time.observed` 语义由字段名承载，schema 不另加 semantics 字段；独立记录的 timepoint——告警、指标样本、检查点——必须显式携带，[缝合批准 #12] 裁决）。

规则：

1. `sim:<session_id>` 值仅在同 session 同 clock epoch 内可比较。
2. 墙钟 UTC 独立表达，**不得**用于仿真事件定序。
3. 跨域关联用显式映射元数据，禁止隐式算术。
4. journal 序列是权威摄入序。
5. 生产者时钟重启必须递增 `clock_epoch`。

## 7. 数据流

1. 生产者发布符合 SPEC-301 的事件。
2. Gateway 校验信封与事件 payload。
3. Gateway 检查幂等键 `(producer_id, event_id)`。
4. Journal 追加事件并盖章 `journal_seq`。
5. 内部消费者接收已提交事件。
6. 指标、时间轴与告警组件幂等更新。
7. Query API 只暴露已提交记录。

消费者必须对其最后完整处理的 journal_seq 做检查点；重启恢复从该序号继续并安全容忍重复投递。

## 8. 可靠性与背压

- 摄入由可配置的队列与 payload 上限约束（背压/合并限流细则归 SPEC-301 §5，权威信封条款）。
- 下游消费者滞后时，journal 仍是事实源。
- 消费者可暂停并从检查点重放。
- Gateway 必须暴露队列深度、拒绝数、重复数与消费者滞后。
- **任何事件不得被静默丢弃**；fault/lifecycle/terminal run/verification 类事件禁合并限流（SPEC-301 §5）。
- journal 无法提交时摄入返回 `OBS_STORAGE_UNAVAILABLE`；生产者重试策略由 OBSERVATION-INTEGRATION-CONTRACT §5 定义。
- 背压必须显式暴露给调用方；**不得让仿真时钟线程阻塞在慢 UI/查询客户端上**。

## 9. 安全与隔离

- 每条记录按 `tenant_id`（MVP 恒为 `"local"`，ADR-0006）与 `session_id` 划界。
- 查询过滤器在返回前强制 scope。
- 原始 payload 有大小上限，不得含凭证、私钥或解密密钥。
- BISS 密钥等机密**永不**进入事件、标签、日志或指标维度。
- 导出支持脱敏策略钩子。

## 10. 性能目标（初始值，随基准实测修订）

| 工作负载 | 目标 |
|---|---:|
| Gateway 持续摄入 | 20,000 events/s per process |
| Gateway 突发 | 50,000 events/s 持续 10 s |
| 接受事件追加 p95 延迟 | ≤ 20 ms |
| 指标查询（1 h / ≤ 20 序列） | ≤ 300 ms |
| 时间轴页（≤ 500 记录） | ≤ 250 ms |
| 告警评估滞后 | ≤ 2 s 墙钟或 1 个虚拟时间 tick 批 |
| 内存上界 | 可配置；无无界内存事件历史 |

这些是**工程目标而非保证**；须在目标部署档位上基准实测并记录软硬件细节。取值口径与 OPEN-006 定档（[OPEN-006 定档：MVP 性能目标与文件大小上限](https://github.com/BingChaoLiu/DVB-Nexus/issues/16)）联动复核——若定档的码率/文件上限显著低于本表假设，本表随之修订而非硬守。

## 11. 配置

全部配置启动时校验；strict 模式下未知键必须失败。

```yaml
observation:
  journal:
    backend: sqlite
    path: ./data/observation.db
    max_event_bytes: 262144
    retention_days: 30
  ingestion:
    queue_capacity: 10000
    duplicate_cache_size: 100000
  metrics:
    enabled: true
    default_step_ms: 1000
    retention:
      raw_seconds: 86400
      1m_seconds: 2592000
      1h_seconds: 31536000
  timeline:
    checkpoint_interval_events: 5000
  alerts:
    enabled: true
    evaluation_batch_size: 1000
```

具体持久化后端是可替换实现细节；逻辑契约保持后端中立。

## 12. 必需接口

Python 包必须暴露协议级接口（名称经批准的 Change Request 才可偏离）：

- `EventPublisher.publish(event) -> PublishReceipt`
- `EventGateway.accept(event) -> IngestResult`
- `EventJournal.append(event) -> JournalRecord`
- `EventJournal.read(cursor, limit, filters) -> Page[JournalRecord]`
- `MetricsService.query(request) -> MetricQueryResult`
- `TimelineService.query(request) -> TimelinePage`
- `AlertService.list(request) -> AlertPage`
- `ObservationQueryService.get_session_summary(session_id) -> SessionObservationSummary`

## 13. 失败模型

错误统一 `error_code` / `message` / `retryable` / `details`。最低集合：

- `OBS_INVALID_ENVELOPE` / `OBS_UNSUPPORTED_SCHEMA` / `OBS_UNSUPPORTED_EVENT_TYPE`
- `OBS_PAYLOAD_TOO_LARGE` / `OBS_DUPLICATE_EVENT` / `OBS_STORAGE_UNAVAILABLE`
- `OBS_QUERY_RANGE_TOO_LARGE` / `OBS_CURSOR_EXPIRED` / `OBS_SCOPE_FORBIDDEN`
- `OBS_CONSUMER_LAGGING` / `OBS_METRIC_NOT_FOUND`
- `OBS_INVALID_TIME_DOMAIN`（跨时钟域时间戳做比较/算术的入口显式拒绝，non-retryable；§6 时钟模型规则 1/3/5，REQ-OBS-300-004 + orchestrator #15 修复轮 scoped append 实现登记）
- `OBS_QUEUE_FULL`（gateway 有界摄入队列已满且事件不可合并限流时的显式拒绝，retryable；§8 背压条款，[缝合批准 #12] + ticket #47 实现登记）

重复提交在 API 边界是幂等成功，必须返回原 `journal_seq`。

## 14. 验收标准

- `REQ-OBS-300-001`：所有生产者不经 Observation 内部实现即可发布事件。
- `REQ-OBS-300-002`：事件保留来源/观测双时间戳与时钟域；重复提交不产生第二条 journal 记录且返回原 journal_seq。
- `REQ-OBS-300-003`：消费者重启与追赶确定性且幂等（检查点语义）。
- `REQ-OBS-300-004`：虚拟时间与墙钟不可被意外比较（跨域比较显式拒绝）。
- `REQ-OBS-300-005`：指标暴露 provenance 与质量标志。
- `REQ-OBS-300-006`：时间轴导出稳定且脱敏感知。
- `REQ-OBS-300-007`：读 API 强制 tenant/session scope 与有界查询；任何 Observation 组件不突变 simulation/TS Core 状态。

## 15. 非目标与风险

- 不做根因判定与自动修复。
- 不做实时流渲染（前端经 SPEC-305 拉取 + WS 通知提示）。
- 风险：SQLite journal 在突发摄入下的写入放大——性能目标表随基准复核；不达标时先调 batch/queue 参数，不轻言换后端（后端可替换但契约不变）。

## 16. 交付要求

建议文件：`app/observation/`（gateway.py / journal.py / consumers/）；schema 文件位于本包 `schemas/`。契约测试与生产者（simulation/ts-core 包）共享 fixture。

## 17. 参考

- SPEC-301（权威信封）、SPEC-302~305（派生组件）。
- ADR-0006（信封统一、journal_seq、ID 策略）。
- OBSERVATION-INTEGRATION-CONTRACT（生产者义务、映射表、非协商边界）。
