# Platform Spec Index

**Package version:** 0.5.0
**Status:** MVP_BASELINE_APPROVED
**Normative parent:** DVB Sandbox SPEC-001/003；错误信封形状沿用 SPEC-305 §7，查询参数基准归 SPEC-305

[ticket #13 补写批准](https://github.com/BingChaoLiu/DVB-Nexus/issues/13)（2026-11-14）：六份规格接口级成文并批准为 MVP 基线（APPROVED 0.5.0）。SPEC-504/507（P1）不在 MVP 基线，随 roadmap。

| Spec ID | Document | Depends on | MVP priority | Primary output |
|---|---|---|---|---|
| SPEC-500 | [REST API](SPEC-500-rest-api.md) | SPEC-001/003 | P0 | 路由权威冻结、Pydantic DTO 权威、错误映射、版本策略 |
| SPEC-501 | [WebSocket](SPEC-501-websocket.md) | SPEC-003/301 | P0 | journal/hint 双帧、cursor 重放恢复、背压 |
| SPEC-502 | [Persistence (SQLite)](SPEC-502-persistence.md) | SPEC-003 | P0 | schema v1、Repository Protocol、journal_seq 盖章唯一落点 |
| SPEC-503 | [Artifact Storage](SPEC-503-artifact-storage.md) | SPEC-003/502 | P0 | 内容寻址布局、tee 双写落点协议、路径安全 |
| SPEC-505 | [Test Architecture](SPEC-505-test-architecture.md) | SPEC-004 | P0 | 四层目录、fixture 六件、CI 门、测试数据纪律 |
| SPEC-506 | [Conformance Suite](SPEC-506-conformance-suite.md) | SPEC-100..108 | P0 | golden 三件套、登记格式、独立验证红线（向量内容归 #14） |

## 批准要点（详见各 spec 与 ticket #13 决议）

- **部署姿态**（ticket #13 Q4）：单机单用户，bind 127.0.0.1、无认证、`tenant_id="local"`、`/api/v1` 冻结 additive-only。
- **持久化技术**（ticket #13 Q5）：stdlib sqlite3 无 ORM，`PRAGMA user_version` + 编号 .sql 迁移，WAL；journal 盖章在 append 事务内，`(producer_id, event_id)` 去重返回原 seq。
- **Artifact 内容寻址平铺**：`artifacts/<aa>/<sha256>.<ext>` + tmp 原子提交 + 启动清扫；去重 = 引用不复制（ADR-0007 第 2 条 tee 双写落点）。
- **REST 由 chatgpt §9 底稿修订**：fault_plan 入 run 请求体（ADR-0007 prepare 绑定，`POST /sessions/{id}/faults` 形态废弃）；runs 异步作业（202 + run_id）。
- **WS = best-effort 通知层**：journal 帧承载体事件、hint 帧指向 REST 拉取（记录型状态不进事件流）；重连 = journal cursor 重放 + REST snapshot。
- **SPEC-506 只定机制**：向量内容与验收策略归 golden streams 与 conformance 策略票（#14）；独立验证红线（同源自证拒绝）升格为条款。
- 单文件上限 `max_bytes`、TSDuck 超时/并发默认值等随 OPEN-006 定档（#16）复核回填。
