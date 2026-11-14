# Observation & Metrics Spec Index

**Package version:** 0.5.0  
**Status:** MVP_BASELINE_APPROVED  
**Normative parent:** DVB Sandbox SPEC-003；事件信封本包 SPEC-301 为全平台权威（ADR-0006）

[ticket #12 缝合批准](https://github.com/BingChaoLiu/DVB-Nexus/issues/12)（2026-11-14）：六份规格逐份修订后批准为 MVP 基线。SPEC-306～309（Diagnosis/Rules/TSDuck Adapter/Comparator）不在本包，文本随 [补写 MVP P0 缺失契约 #13] 编写。

| Spec ID | Document | Depends on | MVP priority | Primary output |
|---|---|---|---|---|
| SPEC-300 | [Observation Architecture](SPEC-300-observation-architecture.md) | SPEC-003 | P0 | 观测平面架构、Gateway/Journal、时钟模型、背压 |
| SPEC-301 | [Canonical Event Contract](SPEC-301-event-contract.md) | SPEC-003 | P0 | 权威事件信封、journal_seq 全序、事件注册表 |
| SPEC-302 | [Metrics Engine](SPEC-302-metrics-engine.md) | SPEC-300/301/100/105 | P0 | 指标目录、聚合、revision/is_final、查询契约 |
| SPEC-303 | [Timeline Recorder](SPEC-303-timeline-recorder.md) | SPEC-300/301 | P0 | 时间轴、检查点、cursor 分页、导出 |
| SPEC-304 | [Health & Alert Engine](SPEC-304-health-and-alerts.md) | SPEC-302/303 | P0 | 规则模型、告警生命周期（记录权威）、健康 roll-up |
| SPEC-305 | [Observation Query API](SPEC-305-query-api.md) | SPEC-300/303 | P0 | 只读查询契约、扁平参数基准、WS 通知提示 |

集成契约：[OBSERVATION-INTEGRATION-CONTRACT.md](OBSERVATION-INTEGRATION-CONTRACT.md)（spec_id `OBSERVATION-IC-001`，APPROVED 0.5.0）——生产者义务、事件映射表、幂等/背压、非协商边界。

Schema 族（同批批准，0.5.0）：

- [`schemas/event-envelope.schema.json`](schemas/event-envelope.schema.json) — 信封 v1.0（多文档版本策略，ADR-0006 第 4 条）
- [`schemas/alert-record.schema.json`](schemas/alert-record.schema.json) — 告警记录（inactive/suppressed、timepoint 显式语义）
- [`schemas/metric-sample.schema.json`](schemas/metric-sample.schema.json) — 指标样本（revision/is_final、timepoint 显式语义）

## 批准要点（详见各 spec 与 ticket #12 决议）

- 信封修订落地 ADR-0006：uuid4 opaque ID、scope.run_id、correlation.port_id、journal_seq optional、additionalProperties 翻 true（payload 除外）。
- 事件注册表重整：fault 四事件对四态、run_* 家族补入、snapshot.updated 撤出事件流、diagnosis.* 纠偏命名、observation.alert_* MVP 置空。
- 告警生命周期 = alert record 权威 + WS 通知提示 + REST 拉取，MVP 零信封事件。
- 查询参数形状基准 = 扁平标量（start_ns/end_ns/step_ns + clock_domain）；ISO-8601 仅限 wall:utc 域。
- 记录级 timepoint 显式携带 clock_epoch + semantics；信封 timepoint 语义由字段名承载。
- SPEC-003 §2.3 RuntimeEvent 改为指向 SPEC-301 的一致性指针（含三方映射表），RunContext 不动。
