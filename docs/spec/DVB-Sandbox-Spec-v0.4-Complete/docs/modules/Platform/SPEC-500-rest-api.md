---
spec_id: SPEC-500
title: REST API
version: 0.5.0
status: APPROVED
phase: MVP
owner: Platform
priority: P0
depends_on: [SPEC-001, SPEC-003]
requirements: [REQ-API-500-001, REQ-API-500-002, REQ-API-500-003, REQ-API-500-004, REQ-API-500-005, REQ-API-500-006, REQ-API-500-007]
---

# SPEC-500 — REST API

## 1. 目标

对外 REST 路由与 DTO 的**权威冻结点**：路由清单、Pydantic DTO、错误响应与版本策略。SPEC-305 §4 明示路由对外冻结归本规格；SPEC-108 §4 指定 Pydantic DTO 权威定义在本文件。端点从 chatgpt-v04 §9 底稿 + SPEC-305 逻辑端点 + SPEC-200 生命周期穷举推导（补写契约票据 ticket #13 Q-C ③ 确认）。

## 2. 范围

### 2.1 In Scope

- 路由清单与 HTTP 语义。
- Pydantic DTO（JSON 字段 snake_case，与 SPEC-108 §4 映射表逐字段对齐）。
- 错误信封（全平台统一形状）与错误码 → HTTP 映射。
- 版本策略与部署姿态。

### 2.2 Out of Scope

- 查询参数形状与查询语义（SPEC-305 扁平标量基准，本文件引用不重定义）。
- WS 传输协议（SPEC-501）。
- 持久化与文件存储（SPEC-502/503）。
- 鉴权与多租户（Q4 裁决：MVP 无认证）。

## 3. 部署姿态与版本策略

- **单机单用户**（ticket #13 Q4）：服务绑定 `127.0.0.1`，无认证，`tenant_id` 恒为 `"local"`；token/多租户/远程访问为 non-goal。
- 版本路径 `/api/v1` **冻结**：只增不改——新增可选字段为 additive；删字段、改名、改枚举语义属破坏性变化，须开 `/api/v2`。
- 错误信封沿用 SPEC-305 §7 形状，推广为**全平台统一**；错误码注册表归 SPEC-300 §13。

## 4. 路由清单

### 4.1 Topology

| Method | Path | 语义 |
|---|---|---|
| POST | `/api/v1/topologies` | 创建拓扑（新 topology_id，revision=1） |
| GET | `/api/v1/topologies` | 列表（分页） |
| GET | `/api/v1/topologies/{id}` | 读指定 revision（默认最新） |
| PUT | `/api/v1/topologies/{id}` | 修改 = 新 revision 行（不可变追加，SPEC-502） |
| POST | `/api/v1/topologies/{id}/validate` | 拓扑校验（SPEC-202 path-addressed 结构化错误） |

### 4.2 Session（SPEC-200 生命周期穷举表的一一映射）

| Method | Path | 语义 |
|---|---|---|
| POST | `/api/v1/sessions` | 创建（topology_id+revision、seed、clock_config、resource_limits、scenario_id 可选） |
| POST | `/api/v1/sessions/{id}/validate` | `VALIDATING`（SPEC-200 §6 validate_session） |
| POST | `/api/v1/sessions/{id}/start` | `READY → RUNNING` |
| POST | `/api/v1/sessions/{id}/pause` | `RUNNING → PAUSED`（与时钟同临界区，SPEC-200 §5.1） |
| POST | `/api/v1/sessions/{id}/resume` | `PAUSED → RUNNING` |
| POST | `/api/v1/sessions/{id}/stop` | `* → STOPPING`（幂等） |
| DELETE | `/api/v1/sessions/{id}` | dispose（回收任务与 TSDuck 子进程） |
| GET | `/api/v1/sessions/{id}/snapshot` | 全量拉取状态 API，`journal_seq_cursor` 可选参数（SPEC-200 §4） |

生命周期非法迁移 → 409（`InvalidLifecycleTransition`）。

### 4.3 Run（ticket #13 Q-C-①）

| Method | Path | 语义 |
|---|---|---|
| POST | `/api/v1/sessions/{id}/runs` | **异步作业**：请求体 = `TSGeneratorConfig`（SPEC-108 §4 JSON↔DTO 映射）+ `fault_plan[]`（SPEC-204 FaultDefinition）；**202 + run_id**；进度走 `run_progress` 事件 |
| GET | `/api/v1/sessions/{id}/runs/{run_id}` | TSRunResult（artifacts 列表、config_hash、status） |

- **fault_plan 入 run 请求体**：ADR-0007 第 2 条 prepare 绑定裁决——chatgpt §9 的 `POST /sessions/{id}/faults` 运行时注入形态**废弃**。
- prepare 拒绝（SPEC-204 错误码表）→ 422（语义非法）附 schema path；fault_plan 校验在 run 提交时同步完成（AC-204-01）。

### 4.4 Diagnosis / Recovery

| Method | Path | 语义 |
|---|---|---|
| GET | `/api/v1/sessions/{id}/diagnoses` | 诊断列表（SPEC-502 diagnoses 表） |
| POST | `/api/v1/sessions/{id}/runs/{run_id}/diagnose` | 幂等重评估（SPEC-306 evaluate） |
| POST | `/api/v1/sessions/{id}/runs/{run_id}/verify` | 通关判定（SPEC-206 三态 PASS/FAIL/INCONCLUSIVE） |

### 4.5 Observation（SPEC-305 逻辑端点原样落路由）

| Method | Path |
|---|---|
| GET | `/api/v1/sessions/{id}/observation/summary` |
| GET | `/api/v1/sessions/{id}/events` |
| GET | `/api/v1/sessions/{id}/timeline` |
| POST | `/api/v1/sessions/{id}/metrics/query` |
| GET | `/api/v1/sessions/{id}/alerts` |
| GET | `/api/v1/sessions/{id}/health` |
| GET | `/api/v1/sessions/{id}/exports/{export_id}` |
| POST | `/api/v1/sessions/{id}/exports` |

查询参数 = SPEC-305 §5 扁平标量基准（`start_ns/end_ns/step_ns + clock_domain`，ISO 仅 wall 域）；只读纪律与导出限流同 SPEC-305。

### 4.6 Artifact

| Method | Path | 语义 |
|---|---|---|
| GET | `/api/v1/artifacts/{id}` | 元数据（SPEC-003 §2.7，`relative_path` 不出绝对路径） |
| GET | `/api/v1/artifacts/{id}/content` | 下载（支持 Range） |
| POST | `/api/v1/artifacts/{id}/analyze` | 触发 TSDuck 分析（SPEC-308；幂等重分析，产新 report artifact） |

### 4.7 Scenario

| Method | Path | 语义 |
|---|---|---|
| GET | `/api/v1/scenarios` | 内置实验包列表（只读，SPEC-205） |
| GET | `/api/v1/scenarios/{id}` | 实验包详情（目标/提示/步骤/pass_criteria） |

## 5. DTO 纪律

- Pydantic DTO 权威定义于本规格实现（`app/api/dto/`）；Domain 层 dataclass 与 API DTO 分离（SPEC-108 §4 既有纪律：Pydantic 在 API/Application 层做 JSON validation）。
- JSON 字段 **snake_case**；`bytes` 类字段以 hex 编码（SPEC-108 §4）；枚举串与 domain 一致。
- `RunContext` 不可由客户端构造（服务端生成 run_id/时间戳）；请求 DTO 不含 journal_seq（生产者永不填，ADR-0006 第 2 条）。

## 6. 错误映射

统一错误信封（SPEC-305 §7 形状）+ HTTP 映射扩展：

| HTTP | 场景 |
|---|---|
| 400 | 请求体/信封非法 |
| 404 | 未知 session/run/topology/artifact/scenario |
| 409 | 生命周期非法迁移、cursor/过滤器冲突、并发 run 冲突 |
| 413 | 请求体过大 |
| 422 | 语义非法：生成配置校验失败、fault prepare 拒绝（`SIM_FAULT_*` 附 schema path）、时钟域/范围语义非法 |
| 500 | 未分类内部错误 |
| 503 | 存储不可用、Artifact Storage 不可用、TSDuck 不可用 |

错误码逐码登记随实现进 SPEC-300 §13 注册表；新增错误码过兼容性评审。

## 7. 测试规格

- 每端点契约测试（请求/响应 DTO round-trip + 错误路径）。
- 生命周期端点 × 迁移表穷举矩阵（合法/非法）。
- fault_plan prepare 拒绝码映射矩阵（SPEC-204 §11 逐码）。
- SPEC-108 §4 映射表逐字段互证（JSON ↔ GeneratorConfig）。
- 观测端点查询形状与 SPEC-305 §5 基准一致（混形状拒绝）。
- Range 下载与 artifact 元数据路径安全（SPEC-503 §6）。

## 8. 验收标准

- `REQ-API-500-001`：路由清单与 §4 一致，`/api/v1` 冻结、additive-only。
- `REQ-API-500-002`：Pydantic DTO 权威落地，与 SPEC-108 §4 映射表逐字段对齐。
- `REQ-API-500-003`：生命周期端点与 SPEC-200 迁移表穷举一致，非法迁移 409。
- `REQ-API-500-004`：runs 异步作业语义（202 + run_id）与 fault_plan prepare 校验映射正确。
- `REQ-API-500-005`：错误信封统一且 HTTP 映射与 §6 一致。
- `REQ-API-500-006`：SPEC-305 八条观测端点原样落路由、扁平查询基准一致。
- `REQ-API-500-007`：部署姿态符合 Q4（127.0.0.1、无认证、tenant_id=local）。

## 9. 非目标与风险

- 不做鉴权/多租户/限流策略（MVP 单机）；不做 API 网关聚合。
- 风险：DTO 与 domain dataclass 漂移——契约测试以 SPEC-108 §4 映射表为互证锚点。

## 10. 交付要求

建议文件：`app/api/`（`routes/` 按 §4 域分文件 + `dto/` + `errors.py` 归属沿用 ts-core 契约裁决）。OpenAPI schema 由 FastAPI 生成并纳入契约测试快照。

## 11. 参考

- SPEC-200 §4/§5/§6（snapshot 与生命周期）、SPEC-203 §5.2（TSRunResult/artifacts）、SPEC-204 §11（错误码）。
- SPEC-305 §4/§5/§7（逻辑端点、查询基准、错误信封）、SPEC-108 §4（JSON↔DTO 映射）。
- [ADR-0007](../../../../adr/0007-fault-injection-pipeline-contract.md) 第 2 条（prepare 绑定）、[ADR-0006](../../../../adr/0006-canonical-event-envelope.md) 第 2 条（journal_seq 不由客户端填）。
- chatgpt-v04 §9（端点底稿；faults 端点形态被 ADR-0007 修订）。
