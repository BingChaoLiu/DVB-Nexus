---
spec_id: SPEC-200
title: Simulation Runtime and Session Lifecycle
version: 0.5.0
status: APPROVED
phase: MVP
owner: Simulation Engine
priority: P0
depends_on: [SPEC-003, SPEC-201, SPEC-202, SPEC-203]
requirements: [REQ-SIM-200-001, REQ-SIM-200-002, REQ-SIM-200-003, REQ-SIM-200-004, REQ-SIM-200-005, REQ-SIM-200-006, REQ-SIM-200-007]
---

# SPEC-200 — Simulation Runtime 与会话生命周期

## 1. 目标

定义本地沙盘会话（Session）生命周期的唯一权威归属：会话的创建、验证、启动、暂停、恢复、停止与销毁，任务与子进程资源的所有权，L0（SPEC-202）与 L1（SPEC-203）两个 Runtime 的编排，以及快照（Snapshot）发布。本模块不编码 TS 包、不实现协议解析、不执行拓扑求值与故障变换本身。

## 2. 范围

### 2.1 In Scope

- 会话生命周期状态机（第 5 节穷举迁移表）。
- `SimulationRuntime` 公开接口与会话契约（SessionSpec / SessionView / Snapshot）。
- pause/resume 与 SimulationClock（SPEC-201）的联动条款。
- 会话级并发纪律：命令串行化、会话隔离、停止幂等、销毁回收。
- 生命周期事件的发射义务（`simulation.session_*` / `simulation.run_*`，经 ADR-0006 信封）。
- Snapshot 作为拉取 API 的语义（含 `journal_seq` cursor，ADR-0006 第 5 条）。
- 机器实体 ID 策略（ADR-0006 第 3 条）。

### 2.2 Out of Scope

- 虚拟时钟的实现与调度算法（SPEC-201）。
- L0 拓扑求值语义（SPEC-202）。
- TS 生成编排、故障过滤器管线与 Artifact 落盘细节（SPEC-203/204，包级 tee 双写条款见 SPEC-203）。
- 场景文档格式与实验流程（SPEC-205）。
- 通关判定（SPEC-206）。
- 事件信封结构本身（SPEC-301 为权威；本模块只承担发射义务）。
- 实况模式（Live Mode）与多用户/分布式会话（`docs/roadmap.md`）。

## 3. 架构位置与依赖

ADR-0005 依赖链：API/UI → Runtime（本模块）→ Clock（201）/ L0（202）/ L1 adapter（203）→ TS Core（100~108）。本模块是会话内所有命令的入口与仲裁者：

- 持有每个会话的 SimulationClock、L0 State Engine、TSRuntimeAdapter 实例引用并编排其调用顺序。
- 事件信封义务由包级 `SIMULATION-INTEGRATION-CONTRACT.md` 统一承载；本模块不重复定义信封字段。
- TS Core 不感知本模块（不得 import 会话/生命周期概念）。

## 4. 数据模型

```python
@dataclass(frozen=True)
class SimulationSessionSpec:
    session_id: str            # uuid4，服务端生成，opaque（ADR-0006）
    topology: Topology         # SPEC-003 §2.1 配置模型；nodeId 为拓扑内语义 slug
    seed: int                  # uint64
    deterministic: bool
    clock_config: SimulationClockConfig   # SPEC-201
    resource_limits: ResourceLimits       # 码率/内存/时长上限，取值口径随 #16 定档复核

@dataclass(frozen=True)
class SessionView:
    session_id: str
    revision: int              # 会话内单调递增
    lifecycle: LifecycleState
    virtual_time_ns: int
    topology_revision: int
    node_states: Mapping[str, NodeState]  # key = node_id 语义 slug
    active_faults: tuple[FaultView, ...]
    latest_artifact_refs: tuple[ArtifactRef, ...]
```

- **ID 策略**：`session_id` / `run_id` / `fault_id` / `scenario_id` / `artifact_id` / `event_id` 一律 uuid4 opaque，消费方不得解析语义；`node_id` 例外为拓扑内稳定语义 slug（ADR-0006 第 3 条）。
- **Snapshot 是全量替换视图**：包含 session ID、单调 revision、虚拟时间、生命周期态、拓扑 revision、节点/连线状态、活跃故障与最新 Artifact 引用。它是重连恢复与大幅变更后的拉取状态 API，带 `journal_seq` cursor 参数；**全状态大对象不进事件流**（ADR-0006 第 5 条，`snapshot.updated` 已撤出事件注册表）。
- Snapshot 只读：它镜像 Simulation/TS Core 的权威状态，自身不是权威（数据所有权表见 SPEC-300 §5）。

## 5. 生命周期状态机

状态集合：`CREATED, VALIDATING, READY, RUNNING, PAUSED, STOPPING, STOPPED, FAILED, DISPOSED`。

迁移表（穷举；未列出的迁移一律非法，非法迁移抛 `InvalidLifecycleTransition`）：

```text
CREATED    -> VALIDATING
VALIDATING -> READY | FAILED | STOPPING      # 验证失败直达 FAILED；验证期可取消
READY      -> RUNNING | FAILED | STOPPING    # start 失败可直达 FAILED
RUNNING    -> PAUSED | FAILED | STOPPING
PAUSED     -> RUNNING | FAILED | STOPPING
FAILED     -> STOPPING | DISPOSED            # FAILED 可直达 DISPOSED，资源随 dispose 回收
STOPPING   -> STOPPED
STOPPED    -> DISPOSED
```

- 终态：`STOPPED`、`DISPOSED`；**不可重启**，需要新会话就新建 session。
- `FAILED` 不是终态：会话可能仍持有任务/子进程，须经 `STOPPING` 清理或直接 `DISPOSED` 回收。
- 状态迁移是原子操作；每次迁移产生一条会话内单调的 `revision` 并按第 6 节规则发射事件。

### 5.1 pause/resume 与时钟联动

- `pause()` 在**同一临界区**内完成两件事：状态迁移 `RUNNING -> PAUSED` 与 `SimulationClock.pause()`（SPEC-201）。realtime 模式下冻结墙钟累计（暂停期间流逝的墙钟不计入虚拟时间）；deterministic 模式下禁止一切 advance 调度。
- `resume()` 对称：`PAUSED -> RUNNING` + `SimulationClock.resume()`。
- `SimulationClock` 的 `pause/resume` 是 Runtime 内部编排接口，**不直接暴露给 UI/API 层**；外部只能通过 `SimulationRuntime` 触达时钟。
- pause 期间到达的命令按第 6 节并发纪律排队；`get_snapshot` 在 PAUSED 下仍然可用（只读）。

## 6. 公开接口

```python
class LifecycleState(StrEnum):
    CREATED = "created"
    VALIDATING = "validating"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"
    DISPOSED = "disposed"

class SimulationRuntime(Protocol):
    async def create_session(self, spec: SimulationSessionSpec) -> SessionView: ...
    async def validate_session(self, session_id: str) -> ValidationReport: ...
    async def start(self, session_id: str) -> SessionView: ...
    async def pause(self, session_id: str) -> SessionView: ...
    async def resume(self, session_id: str) -> SessionView: ...
    async def stop(self, session_id: str, reason: str = "user") -> SessionView: ...
    async def dispose(self, session_id: str) -> None: ...
    async def get_snapshot(self, session_id: str, *, journal_seq_cursor: int | None = None) -> SimulationSnapshot: ...
```

- `ValidationReport` 复用 SPEC-202 的 path-addressed 结构化错误；验证不通过时会话停留在 `VALIDATING` 或迁移至 `FAILED`，不产生部分初始化的中间态。
- `stop(reason)` 幂等：对已 `STOPPING/STOPPED` 的会话重复调用直接返回当前视图，不重复清理。
- `dispose()` join/cancel 本会话拥有的全部任务与子进程（含 TSDuck 子进程），释放后迁移 `DISPOSED`。

## 7. 处理算法要求

1. **命令串行化**：每会话一个 async lock，全部变更命令（create/validate/start/pause/resume/stop/dispose 与经 Runtime 转发的 Run 命令）在该锁下串行执行；只读命令不持锁但必须读到一致视图。
2. **会话隔离**：会话之间不共享可变状态；一个会话的失败不得污染其他会话。
3. **revision 单调**：任何被 Snapshot 覆盖的状态变化都使 `revision` 严格递增；相同 revision 必然相同视图内容（同一会话内）。
4. **事件发射**：生命周期迁移按 ADR-0006 信封发射 `simulation.session_created/started/paused/resumed/stopped`，Run 维度发射 `simulation.run_started/run_progress/run_completed/run_failed`；`run_progress` 允许合并限流，其余禁静默丢弃（SPEC-301 §5）。`sequenceNumber`（per Run）、`sequence`（per session）等生产者自造全序字段废除，全序由 gateway 的 `journal_seq` 盖章。
5. **资源回收有界**：stop 受 shutdown timeout 约束；超时后升级为强制 cancel 并在事件 payload 标注。
6. **密钥脱敏**：任何错误消息、事件 payload、日志不得包含密钥/口令；错误类别见第 8 节。

## 8. 错误与诊断码

| Code | 条件 | 处理 |
|---|---|---|
| `SIM_SESSION_NOT_FOUND` | session_id 不存在 | 404 语义，调用方处理 |
| `SIM_INVALID_LIFECYCLE_TRANSITION` | 违反第 5 节迁移表 | 拒绝，返回当前合法迁移集 |
| `SIM_VALIDATION_FAILED` | 会话验证不通过 | 附 ValidationReport |
| `SIM_RESOURCE_LIMIT` | 超出 resource_limits | 拒绝并指明超限维度 |
| `SIM_ENGINE_ERROR` | L0/L1/TS Core 内部错误 | 附根因错误码，迁移 FAILED |
| `SIM_IO_ERROR` | Artifact/存储 IO 失败 | 区分 retryable |
| `SIM_CANCELLED` | 命令被取消/超时 | 幂等可重试 |
| `SIM_INTERNAL` | 未分类内部错误 | 记录诊断，不外泄堆栈细节 |

错误统一携带 `error_code` / `message` / `retryable` / `details`（与 SPEC-300 §13 错误模型一致）。

## 9. 测试规格

- 第 5 节迁移表的全部合法边与全部非法边（穷举状态对矩阵测试）。
- 并发：同一会话并发 start/stop/pause 命令的串行化与最终状态唯一性。
- `stop` 幂等与 shutdown timeout 超时升级路径。
- `dispose` 后无遗留任务/子进程（进程树断言）。
- 会话隔离：会话 A 失败不影响会话 B 的状态与事件流。
- snapshot revision 单调性；相同 revision 视图一致性。
- pause/resume 与时钟联动：PAUSED 期间 `clock.now_ns()` 冻结（realtime 模式以墙钟推进验证冻结）。
- 事件义务：每次迁移产生对应 `session_*` 事件，事件通过 SPEC-301 信封 schema 校验。

## 10. 验收标准

- `REQ-SIM-200-001`：生命周期迁移表穷举实现，非法迁移全部拒绝且错误稳定。
- `REQ-SIM-200-002`：重复 start 不会派生重复 worker；stop 幂等且有界。
- `REQ-SIM-200-003`：dispose 后会话拥有的任务与子进程为零。
- `REQ-SIM-200-004`：会话相互隔离，单会话故障不外溢。
- `REQ-SIM-200-005`：snapshot revision 单调递增，snapshot 为拉取 API 且接受 `journal_seq` cursor。
- `REQ-SIM-200-006`：pause/resume 与 SimulationClock 联动正确，PAUSED 期间虚拟时间冻结。
- `REQ-SIM-200-007`：生命周期与 Run 事件按 ADR-0006 信封发射并通过 schema 校验。

## 11. 非目标与风险

- 不承诺会话跨进程持久恢复（`SPEC-504` Session Persistence 为 P1）。
- 不处理分布式/多用户会话（roadmap）。
- 风险：L0 与 L1 的编排顺序错误会造成快照与事件流不一致——以"命令串行 + revision 单调"约束兜底，实现时必须以事件序与快照内容的一致性测试覆盖。
- 风险：resource_limits 的具体取值依赖 OPEN-006 定档（#16）；本 spec 只冻结结构与校验义务，不冻结数值。

## 12. 交付要求

建议文件：`app/simulation/runtime.py`、`app/simulation/lifecycle.py`、`app/simulation/snapshot.py`（可按实现合并）；测试置于 `tests/unit/simulation/` 与 `tests/integration/simulation/`。事件发射义务的验收以 `SIMULATION-INTEGRATION-CONTRACT.md` 的契约测试为准。

## 13. 参考

- ADR-0005 架构基线（依赖链、端口级连线、Runtime 统一接口）。
- ADR-0006 事件信封统一裁决（ID 策略、journal_seq、snapshot 撤出事件流）。
- SPEC-003 §2.2 RunContext、§3 状态模型、§4 时间模型。
