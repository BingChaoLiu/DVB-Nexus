---
spec_id: SPEC-001
title: System Architecture
version: 0.4.0
status: DRAFT
phase: BASELINE
owner: Architecture
depends_on:
  - SPEC-000
---

# SPEC-001 — 系统总体架构

## 1. 架构目标

- 用一套领域模型和观测/诊断链路统一 Sandbox 与后续 Live 模式。
- 让 Python 承担控制面、编排和主要业务逻辑。
- TS Core 自主生成二进制 MPEG-TS；TSDuck 负责独立分析/处理和交叉验证。
- 以模块化单体控制复杂度，长任务通过独立 Worker/子进程隔离。
- 允许未来增加 T2MI、BISS、RF/SEC 和 DVB Frontend，而不重写通用运行时。

## 2. 架构形态

建议采用 **Modular Monolith + Worker Process**：

- 一个主要 Python Backend 进程提供 API、应用服务和短时领域操作。
- 长时间 TS 生成、TSDuck 分析等任务在独立任务执行器或子进程中运行。
- 第一版不拆分成微服务，不引入 Kafka/Redis/Celery 等分布式基础设施，除非性能或部署要求提供明确依据。

## 3. 逻辑分层

```text
Presentation: React/TypeScript UI (proposed)
       | REST / WebSocket
Application/API: API routers, Session Manager, use-case orchestration
       |
Domain: Topology, Observation, Diagnosis, Fault Scenario, Artifact metadata
       |
Runtime: SIM_STATE Runtime / SIM_TS Runtime / future LIVE Runtime
       |
Adapters: TS Core, TSDuck Worker, SQLite repository, file Artifact store
```

### 3.1 Presentation Layer

负责拓扑编辑、节点状态、TS 分析、日志、Packet Inspector 和训练界面。前端不得自行作为拓扑求值或诊断的权威实现。

### 3.2 API / Application Layer

负责请求校验、Session 生命周期、任务编排、权限/资源边界（单机用户场景仍需路径和进程安全）、事件订阅及 Snapshot 聚合。API 层不得包含 TS 二进制编码细节。

### 3.3 Domain Layer

负责纯领域模型和规则：Topology Validator/Evaluator、Observation、Metrics 定义、Diagnosis 规则契约、Fault/Scenario 定义和 Artifact 元数据。

领域模型不得直接调用 FastAPI、SQLite、文件系统或 TSDuck CLI。

### 3.4 Runtime Layer

- `SIM_STATE`：参数传播、节点状态、约束检查和因果链计算；不声称生成真实协议数据。
- `SIM_TS`：调用 TS Generator 生成真实二进制 TS，并将生成、注入、分析和事件关联到 Run。
- Future `LIVE`：真实 TS 文件、网络流或 DVB Frontend 输入；不属于 MVP。

SIM_STATE 与 SIM_TS 实现统一 Runtime 接口，但可以拥有不同内部处理模型。

### 3.5 Adapter / Infrastructure Layer

TS Core、TSDuck 子进程、SQLite、文件系统和未来硬件适配器均通过明确接口接入。外部依赖不能反向污染 Domain 层。

## 4. 核心模块边界

| 模块 | 负责 | 不负责 |
|---|---|---|
| `api` | HTTP/WS 协议、请求响应、连接管理 | 协议解析和诊断规则 |
| `application` | 用例编排、Session 生命周期、事务边界 | TS 字节编码 |
| `topology` | 节点/端口/连线校验、无状态求值 | 码流生成、硬件 IO |
| `simulation` | Runtime、虚拟时钟、任务生命周期 | 持久化实现细节 |
| `ts` | TS Packet/PSI/PES/PCR/Mux/Generator | FastAPI、UI、数据库 |
| `faults` | 故障定义、触发、变换和记录 | 直接设置 UI health |
| `observation` | 事实/指标/证据统一模型和事件发布契约 | 推导最终根因 |
| `diagnosis` | 将 Observation 映射为根因候选和建议 | 直接解析原始 TS 或启动进程 |
| `tsduck` | 进程管理、命令执行、报告解析 | 取代自研 TS Core |
| `storage` | Repository、Artifact 文件和元数据保存 | 领域决策 |
| `knowledge` | 解释内容、标准引用和教学提示 | 修改运行状态 |

## 5. 关键数据流

### 5.1 SIM_TS 正常数据流

```text
Topology + TS Config
       -> TS Generator
       -> TS Artifact
       -> Fault Pipeline (empty or configured)
       -> Final TS Artifact
       -> Internal Parser + TSDuck Worker
       -> Observation Events
       -> Diagnosis Engine
       -> Snapshot / API / WebSocket
```

### 5.2 SIM_STATE 数据流

```text
Topology + Node Config
       -> Topology Validator/Evaluator
       -> State Runtime
       -> Simulated Observations
       -> Diagnosis Engine
       -> Snapshot / API / WebSocket
```

### 5.3 统一性要求

两种 Runtime 使用相同的 `RunContext`、事件 envelope、Observation 语义和诊断入口。数据来源必须明确标为 `simulated`、`parsed`、`measured` 或 `inferred`，不得仅凭模式字段推断数据可信度。

## 6. Runtime 接口原则

建议定义 Python Protocol，最终签名由 SPEC-200/203 冻结：

```python
class SimulationRuntime(Protocol):
    async def start(self, config) -> None: ...
    async def stop(self) -> None: ...
    async def apply_config(self, config) -> None: ...
    async def events(self) -> AsyncIterator[RuntimeEvent]: ...
```

要求：

- `start` / `stop` 幂等性和状态转换在模块 Spec 定义。
- 长任务必须可取消、可超时、可清理。
- 配置变更必须带 `topology_revision` 或等价版本号。
- 运行事件需包含单调递增 `sequence_number`。
- 不能在 API Event Loop 中执行大文件同步生成或长时间 subprocess wait。

## 7. TSDuck 集成边界

MVP 推荐以独立进程集成：

- 使用参数数组启动进程，不拼接 shell 命令，不使用 `shell=True`。
- 记录 TSDuck 版本、可执行路径、argv、开始/结束时间、退出码、stdout/stderr 和输入 Artifact SHA-256。
- 必须处理 timeout、cancel、stdout/stderr 持续读取、进程组清理和最大输出量。
- 用户配置不得直接成为任意 CLI 插件或 shell 参数；由白名单命令构建器生成 argv。
- TSDuck 报告解析与进程控制分开。
- 不把 TSDuck 当成所有协议的绝对真值；分歧必须保留双方结果。

## 8. 前端建议

建议 React + TypeScript；拓扑画布可评估 React Flow。最终库版本、状态管理、组件系统在 SPEC-400 批准前不冻结。前端只消费后端 Snapshot/Events；需要原始 Packet 时通过按需 API 获取，不经 WebSocket 广播整条 TS。

## 9. API 与事件通信

建议 REST 用于配置、启动/停止、查询 Artifact/报告；WebSocket 用于运行状态变化、聚合指标和诊断事件。

不允许通过 WebSocket 推送每个 188-byte Packet。应采用聚合、节流、状态合并和有界队列。慢客户端可以丢弃中间 metrics/snapshot，但不可静默丢失重要诊断/故障事件；重连后通过完整 Snapshot 恢复。

具体路径和 schema 由 SPEC-500/501 定义。

## 10. 持久化建议

MVP 建议 SQLite 保存拓扑、实验、Run 元数据、诊断摘要和 Artifact 元数据；文件系统保存 TS、日志、报告和证据文件。实际数据库、迁移工具、目录布局和保留策略由 SPEC-502/503 定义并批准。

## 11. 安全与资源边界

- 所有 Artifact 路径必须限制在应用管理的根目录内，防止路径穿越。
- 不允许把用户输入直接拼接到 shell 命令。
- 子进程必须设置超时、资源限制策略和终止清理。
- 文件上传/读取限制大小和类型；校验文件路径和符号链接行为。
- 日志不得记录未来 BISS/CA 等敏感密钥明文；相关模块尚未进入 MVP。
- WebSocket 事件队列和任务队列必须有界。
- 错误日志不得无限写入或包含不必要的原始码流大块数据。

## 12. 质量属性

| 属性 | 架构要求 |
|---|---|
| 可测试性 | TS Core 可脱离 API/DB 单测；Runtime 可用 Fake Adapter 测试 |
| 可复现性 | 固定配置、版本、种子、虚拟时钟时尽可能字节级确定 |
| 可追踪性 | Run → Artifact → Analysis → Observation → Diagnosis 关联完整 |
| 可扩展性 | 新数据源通过 Adapter/Runtime 接入，不破坏通用模型 |
| 可恢复性 | 子进程失败、WebSocket 断连和任务取消均有明确状态 |
| 可维护性 | 首版模块化单体，不为未经证实的扩展提前引入分布式系统 |

## 13. 架构验收

- SIM_STATE 和 SIM_TS 可以通过统一 Session API 启停。
- 两种模式都能产生统一 envelope 的事件，并保留来源类型。
- TS 生成和 TSDuck 分析不会阻塞 API Event Loop。
- TSDuck 崩溃不会导致主 API 进程退出。
- 任一诊断结果可以关联到 Run 和输入/输出 Artifact。
- WebSocket 不承载完整 TS Packet 流。
- 至少一个架构集成测试覆盖 Generate → Analyze → Diagnose。
