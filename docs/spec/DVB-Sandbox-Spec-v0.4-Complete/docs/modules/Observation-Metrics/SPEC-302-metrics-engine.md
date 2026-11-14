---
spec_id: SPEC-302
title: Metrics Engine
version: 0.5.0
status: APPROVED
phase: MVP
owner: Observation
priority: P0
depends_on: [SPEC-300, SPEC-301, SPEC-100, SPEC-105]
requirements: [REQ-OBS-302-001, REQ-OBS-302-002, REQ-OBS-302-003, REQ-OBS-302-004, REQ-OBS-302-005, REQ-OBS-302-006]
---

# SPEC-302 — Metrics Engine

## 1. 目标

定义 TS、simulation、拓扑与观测健康域的派生指标序列与聚合语义。指标是可解释的派生记录：每个聚合值都能追溯到来源事件或水位。

## 2. 范围

### 2.1 In Scope

- 指标定义模型与初始指标目录。
- 维度白名单与基数控制。
- 聚合操作、时间窗与迟到样本处理。
- 保留分层与降采样。
- 查询契约（形状基准与 SPEC-305 §4 一致）。

### 2.2 Out of Scope

- 原始事件的产生与摄入（SPEC-301/SPEC-300）。
- 根因归因（SPEC-306/307）。
- 存储后端实现（可替换；SPEC-502/503 承载持久化）。

## 3. 指标模型

指标定义（metric definition）包含：

- `metric_name`：稳定点分标识。
- `value_type`：`counter|gauge|histogram`。
- `unit`：显式单位。
- `description`。
- `allowed_dimensions`：有限维度白名单。
- `source_event_types` 和/或快照来源。
- `aggregation`：支持的聚合操作。
- `temporality`：`cumulative|delta|instant`。
- `quality_policy`：缺口、迟到与非法样本的处理策略。

样本（sample）包含：指标名、时间戳（timepoint：`value_ns + clock_domain + clock_epoch + semantics`，见 `schemas/metric-sample.schema.json`）、值、维度、来源事件 ID 或来源水位、质量标志、`revision` 与 `is_final`（迟到重聚合见 §5.2）。

## 4. 初始指标目录

| 指标 | 类型 | 单位 | 来源/派生 |
|---|---|---|---|
| `ts.packet_rate` | gauge | packets/s | 包批计数 / source 时间差 |
| `ts.bitrate` | gauge | bit/s | bytes × 8 / source 时间差 |
| `ts.continuity_error_total` | counter | errors | `ts.continuity_error` |
| `ts.pcr_jitter_ns` | histogram | ns | PCR 观测 |
| `ts.pcr_repetition_gap_ns` | gauge | ns | PCR 观测 |
| `ts.null_packet_ratio` | gauge | ratio | PID 0x1FFF 包数 / 总数 |
| `ts.scrambled_packet_ratio` | gauge | ratio | TS scrambling control 位 |
| `psi.section_repetition_gap_ms` | gauge | ms | section 观测 |
| `simulation.virtual_time_ns` | gauge | ns | 虚拟时钟 |
| `simulation.event_lag_ns` | gauge | ns | observed/source 映射差（仅当映射存在） |
| `topology.degraded_node_count` | gauge | nodes | 拓扑快照 |
| `observation.ingest_events_total` | counter | events | gateway |
| `observation.duplicate_events_total` | counter | events | gateway |
| `observation.consumer_lag_events` | gauge | events | journal_seq − 检查点 |
| `observation.alerts_active` | gauge | alerts | 告警存储（记录态，SPEC-304） |

**禁止高基数维度**：任意 payload 文本、原始 URL、BISS 密钥、不可信来源的完整 service 名、事件 ID。

## 5. 维度

基线维度白名单：`session_id`、`scenario_id`、`source_id`、`service_id`、`pid`（有界数值维度，可选）、`node_id`、`fault_type`、`severity`、`stream_id`。

- 每个指标必须声明其允许维度。
- 未知维度按严格度配置拒绝或丢弃；**默认拒绝**。
- `session_id` 维度对 session 域指标必填（记录归属纪律，scope 由维度承载、不另设 scope 字段）。

## 6. 聚合

### 6.1 操作与窗口

- 操作：`sum`、`min`、`max`、`avg`、`last`；histogram 的 `count`、`sum` 与配置桶的 quantiles；counter 的 `rate` 与 `increase`。
- 时间窗半开 `[start, end)`；`step` 显式；响应必须标识实际桶边界约定与时钟域。

### 6.2 迟到样本与 revision

- 可配置的迟到窗口（lateness window）。
- 定稿（finalization）后到达的样本保留在原始 journal，但**不得静默改写已定稿聚合**。
- 启用回填（backfill）时，修订后的聚合**必须递增 `revision`** 并保持 `is_final=false` 直至重新定稿。样本 schema 的 `revision`/`is_final` 字段与本条款一一对应。

### 6.3 缺口

- 缺样本默认**不补零**。
- 查询响应包含 `null` + 质量 `missing`，除非指标定义显式声明 zero-fill。
- "缺失 ≠ 零"与 SPEC-206 §6 判定纪律同源。

## 7. 基数与保留

- 每指标活跃序列数上限强制。
- 超维度/基数策略的样本拒绝或隔离。
- 保留分层：raw / 1-minute / 1-hour。
- 降采样必须保持聚合语义；counter 重置必须被检测。
- 保留删除异步且可观测。

## 8. 查询契约

**请求形状基准 = SPEC-305 §4 扁平标量**（[缝合批准 #12] 裁决：查询参数一律扁平 ns 整数 + 顶层时钟域；timepoint 对象形状只用于记录，不用于查询参数）：

- `metric_names[]`
- `start_ns` / `end_ns` / `step_ns`：整数纳秒
- `clock_domain`：必填（仿真时间查询）；`wall:utc` 域查询允许 ISO-8601 字符串替代 `*_ns`（同一请求内不得混用）
- `filters`：仅允许维度
- `max_points`
- optional `aggregation_override`（仅限允许操作）

服务必须拒绝：

- `start_ns >= end_ns`
- 时钟域缺失/歧义
- 范围或点数超限
- 未知指标（除非 `allow_unknown=true`）
- 对非允许维度的过滤

响应包含：序列元数据、点列、单位、聚合、时钟域、`revision`、provenance 摘要与质量标志。示例见 `examples/metric-query-example.json`（扁平形状）。

## 9. 确定性

- 仿真指标的计算基于虚拟时间戳与稳定事件序：重放同一事件 journal + 相同指标定义必须得到相同指标值与桶边界。
- 墙钟操作指标是独立序列，**不得**并入虚拟时间序列。

## 10. 错误与诊断码

复用 SPEC-300 §13 中 `OBS_METRIC_NOT_FOUND`、`OBS_INVALID_TIME_DOMAIN`、`OBS_QUERY_RANGE_TOO_LARGE`；本模块新增：

| Code | 条件 |
|---|---|
| `OBS_METRIC_DIMENSION_REJECTED` | 非允许维度（strict 默认） |
| `OBS_METRIC_CARDINALITY_EXCEEDED` | 活跃序列超限 |

## 11. 测试规格

- counter increase/rate 含重置检测。
- histogram 聚合与 quantiles。
- 缺失桶质量语义（null + missing，不补零）。
- 迟到样本与 revision/is_final 行为（定稿前后）。
- 基数强制（拒绝与隔离两模式）。
- 确定性重放等价。
- 单位与时钟域校验；扁平查询形状与示例 JSON 互证。

## 12. 验收标准

- `REQ-OBS-302-001`：指标目录可注册、可校验、维度白名单强制。
- `REQ-OBS-302-002`：聚合操作与半开窗语义实现并有向量测试。
- `REQ-OBS-302-003`：迟到样本按 revision/is_final 语义处理，无静默改写。
- `REQ-OBS-302-004`：缺口默认不补零且质量标志正确。
- `REQ-OBS-302-005`：仿真指标重放确定性。
- `REQ-OBS-302-006`：查询契约为扁平标量形状并与 SPEC-305 §4、示例 JSON 三处一致。

## 13. 非目标与风险

- 不做指标告警判定（规则归 SPEC-304）；不做根因（SPEC-306）。
- 风险：histogram 桶配置不当会造成基数爆炸——桶配置纳入启动校验与基数上限。

## 14. 交付要求

建议文件：`app/observation/metrics/`（registry.py / aggregator.py / service.py）；schema：`schemas/metric-sample.schema.json`。

## 15. 参考

- SPEC-300（组件与数据流）、SPEC-301（事件来源）。
- `examples/metric-query-example.json`（查询形状示例）。
