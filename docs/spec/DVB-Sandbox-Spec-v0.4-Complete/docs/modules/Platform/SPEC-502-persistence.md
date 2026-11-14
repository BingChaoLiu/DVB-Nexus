---
spec_id: SPEC-502
title: Persistence (SQLite)
version: 0.5.0
status: APPROVED
phase: MVP
owner: Platform
priority: P0
depends_on: [SPEC-003]
requirements: [REQ-PLT-502-001, REQ-PLT-502-002, REQ-PLT-502-003, REQ-PLT-502-004, REQ-PLT-502-005, REQ-PLT-502-006]
---

# SPEC-502 — Persistence (SQLite)

## 1. 目标

定义平台唯一的 SQLite 持久层契约：schema、迁移机制与 Repository 公开接口。本模块是 **`journal_seq` 盖章的唯一落点**（SPEC-301 §5 "durable append 时盖章"的物理实现），是补写契约票据（ticket #13）批准的平台地基之一。

## 2. 范围

### 2.1 In Scope

- SQLite schema v1（六类表）与迁移机制。
- Repository 公开接口（Python Protocol）。
- Event journal 的盖章、去重与查询协议。
- 事务边界与错误语义。

### 2.2 Out of Scope

- Artifact 物理文件存储（SPEC-503）。
- 查询 API 语义与对外 REST（SPEC-305/500）。
- Session 保存、恢复与过期（SPEC-504，P1 非 MVP）。

## 3. 技术姿态

- **stdlib `sqlite3`，无 ORM**（ticket #13 Q5 裁决）：显式 SQL、参数化查询；异步侧经线程池或串行化调用，SQLite 单写者语义与 MVP 单机单用户匹配（Q4：bind 127.0.0.1、无认证）。
- **WAL 模式**开启；`foreign_keys` 开启。
- **迁移**：`PRAGMA user_version` + `migrations/NNN_*.sql` 顺序编号脚本；启动时在单事务内执行未应用脚本；schema v1 即 MVP 首版。
- 单库单文件；库文件路径可配置。

## 4. Schema v1

| 表 | 关键列与约束 | 承载 |
|---|---|---|
| `topologies` | `(topology_id, revision)` 复合唯一；`spec_json`（SPEC-003 §2.1 配置模型，含 schema_version）；`created_at_utc` / `updated_at_utc` | 每 revision 一行，支持 §2.2 `topologyRevision` 防旧配置覆盖 |
| `sessions` | `session_id` PK（uuid4）；`topology_id` + `topology_revision`；`seed`；`deterministic`；`clock_config_json`；`resource_limits_json`；`lifecycle_state`；`revision`（SessionView 单调序）；`scenario_json`（SPEC-205 实验包，nullable）；时间戳 | SPEC-200 §4 |
| `runs` | `run_id` PK（uuid4）；`session_id` FK；RunContext 全字段（mode/fidelity/started_at_utc_ms/generator_version/config_hash/seed）；`status`；`ended_at_utc_ms` | SPEC-003 §2.2 |
| `events` | `(session_id, journal_seq)` 复合 PK；`event_type` / `severity` / `producer_id` 查询列展开；`envelope_json` 全量单列（权威内容）；`(producer_id, event_id)` 部分唯一索引 | SPEC-301 §5 盖章与去重 |
| `artifacts` | `artifact_id` PK（uuid4）；`sha256`（**非唯一**——同内容可被多个 run 引用）；`kind`（SPEC-003 §2.7 六类）；`relative_path`；`byte_size`；`packet_size` / `packet_count` / `generator_version` / `config_hash` / `fault_profile_ids_json`；`run_id` / `session_id`；`created_at_utc_ms` | 索引权威；物理文件归 SPEC-503 |
| `diagnoses` | `diagnosis_id` PK（uuid4）；`session_id` / `run_id`；`rule_id` + `rule_version`；`code`；`severity`；`confidence`（三档枚举 `low/medium/high`，ticket #13 Q3-ii）；`observation_refs_json`；`affected_node_ids_json`；`suggested_actions_json`；`state`（`raised/cleared`）；`raised_at` / `cleared_at` | 对 `diagnosis.raised/updated/cleared` 三事件（SPEC-301 §4） |
| `alerts` | alert-record.schema.json 全字段（`alert_id` PK、`fingerprint`、`rule_id`、`state` 五态、`severity`、`scope`、`time`、`evidence_refs_json`、`suppression_json`） | SPEC-304 §5 记录权威 |

## 5. Repository 公开接口

Python Protocol，建议 `app/adapters/storage/`（ADR-0005 决策 4：`adapters/` 收 storage）：

```python
class TopologyRepository(Protocol):
    def save(self, topology_id: str, revision: int, spec_json: str) -> None: ...
    def get(self, topology_id: str, revision: int | None = None) -> TopologyRow | None: ...

class SessionRepository(Protocol):
    def create(self, spec: SimulationSessionSpec) -> None: ...
    def update_state(self, session_id: str, *, lifecycle: str, revision: int,
                     virtual_time_ns: int) -> None: ...
    def get(self, session_id: str) -> SessionRow | None: ...

class RunRepository(Protocol):
    def create(self, ctx: RunContext) -> None: ...
    def finish(self, run_id: str, *, status: str, ended_at_utc_ms: int) -> None: ...

class EventJournal(Protocol):
    def append(self, envelope: dict) -> tuple[int, bool]:
        """返回 (journal_seq, duplicate)。唯一盖章入口。"""
    def query(self, session_id: str, *, after_seq: int = 0,
              limit: int = 100) -> list[EventRow]: ...

class ArtifactRepository(Protocol):
    def register(self, meta: ArtifactMeta) -> None: ...
    def get(self, artifact_id: str) -> ArtifactRow | None: ...
    def find_by_sha256(self, sha256: str) -> list[ArtifactRow]: ...

class DiagnosisRepository(Protocol):
    def upsert(self, d: DiagnosisRecord) -> None: ...
    def clear(self, diagnosis_id: str, *, cleared_at_utc_ms: int) -> None: ...
    def query(self, session_id: str) -> list[DiagnosisRecord]: ...

class AlertRepository(Protocol):
    def upsert(self, a: AlertRecord) -> None: ...
    def query(self, session_id: str) -> list[AlertRecord]: ...
```

## 6. Journal 盖章与去重

- `append` 在**单事务**内：`journal_seq = max(seq) + 1`（per session）→ 插入行 → 提交；盖章后序号即全序权威（ADR-0006 第 2 条）。
- 投递 at-least-once：`(producer_id, event_id)` 冲突时返回**原** `journal_seq` 且 `duplicate=true`，不产生新行（SPEC-301 §5）。
- 高频事件（`run_progress` / metrics 类）允许**批量 flush**（可配置窗口）；`fault.*` / `session_*` / terminal run / `recovery.verification_completed` **禁静默丢弃**，同事务直写。
- `query(session_id, after_seq, limit)` 按序返回，供 SPEC-305 事件查询与 SPEC-501 重连恢复（snapshot + cursor 协议）。

## 7. 错误处理

| 场景 | 语义 |
|---|---|
| 库不可用 / 磁盘故障 | 存储不可用——HTTP 503（对齐 SPEC-305 §7 映射） |
| journal append 失败 | `OBS_STORAGE_WRITE_FAILURE`（对齐 SPEC-304 §8 规则名） |
| 唯一约束冲突（非去重路径） | 409 |
| 迁移失败 | 启动失败（fail-fast），不降级运行 |

事务边界：append + 盖章同事务；约束校验在事务内完成，不依赖应用层先查后插。

## 8. 资源约束

- 事件表 `(session_id, journal_seq)` 为主键序；`event_type` 上索引供过滤查询。
- 单次 `query` 上限遵循 SPEC-305 §5（`limit` 默认 100、硬上限 2000）。
- 写并发 = SQLite 单写者；asyncio 侧经队列串行化，写队列深度上限与 OPEN-006 定档票据（[#16](https://github.com/BingChaoLiu/DVB-Nexus/issues/16)）复核对齐。

## 9. 测试规格

- 迁移：空库升级到 v1；重复执行幂等；user_version 断言。
- 盖章：并发 append（同 session）序号无洞无重；跨 session 序号独立。
- 去重：同 `(producer_id, event_id)` 二次 append 返回原 seq + `duplicate=true`。
- 禁丢弃事件直写 vs 可合并事件 flush 窗口行为。
- Repository CRUD + 约束冲突路径。

## 10. 验收标准

- `REQ-PLT-502-001`：schema v1 六类表 + 迁移机制落地，空库可一键升级。
- `REQ-PLT-502-002`：`journal_seq` 由 `append` 事务内盖章，per session 单调无洞无重。
- `REQ-PLT-502-003`：`(producer_id, event_id)` 去重返回原 seq + `duplicate=true`。
- `REQ-PLT-502-004`：禁丢弃事件类不经 flush 窗口。
- `REQ-PLT-502-005`：错误语义与 HTTP 映射一致（503 / 409）。
- `REQ-PLT-502-006`：Repository 接口以 Protocol 表达，API/Application 不触 SQL（import-linter 可验证）。

## 11. 非目标与风险

- 不做全文搜索、ORM、远程数据库、加密。
- 不含 session 恢复/过期（SPEC-504，P1）。
- 风险：事件表膨胀——MVP 靠 run 级清理指引（roadmap），schema 已含按 session 查询/删除的键序。

## 12. 交付要求

建议文件：`app/adapters/storage/`（`db.py` / `repositories.py` / `journal.py` / `migrations/0001_init.sql`…）。契约测试 fixture 与 SPEC-305/501 共享。

## 13. 参考

- SPEC-301 §5（排序、投递与背压）、SPEC-200 §4（SessionView）、SPEC-003 §2.1/2.2/2.6/2.7。
- SPEC-304 §5/§8（告警记录权威与写失败规则名）、SPEC-305 §5/§7（查询上限与错误映射）。
- [ADR-0005](../../../../adr/0005-architecture-baseline.md) 决策 4（adapters/storage）、[ADR-0006](../../../../adr/0006-canonical-event-envelope.md) 第 2 条（journal_seq）。
