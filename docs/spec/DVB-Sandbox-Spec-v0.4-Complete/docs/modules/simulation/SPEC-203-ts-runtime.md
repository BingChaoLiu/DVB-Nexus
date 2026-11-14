---
spec_id: SPEC-203
title: L1 TS Runtime Integration
version: 0.5.0
status: APPROVED
phase: MVP
owner: Simulation Engine
priority: P0
depends_on: [SPEC-003, SPEC-100, SPEC-101, SPEC-102, SPEC-103, SPEC-104, SPEC-105, SPEC-106, SPEC-107, SPEC-108, SPEC-201, SPEC-204]
requirements: [REQ-SIM-203-001, REQ-SIM-203-002, REQ-SIM-203-003, REQ-SIM-203-004, REQ-SIM-203-005, REQ-SIM-203-006, REQ-SIM-203-007]
---

# SPEC-203 — L1 TS Runtime 集成（SIM_TS 编排）

## 1. 目标

定义 SIM_TS 保真级（L1）的生成编排：把 TS Core 公共契约（SPEC-100~108）装配成受控的确定性生成 Run——生命周期、时钟策略、取消、资源限制、故障管线接入与 Artifact 生命周期归本模块；包/Section/PES/PCR/Mux 语义归 TS Core。**不得重复实现 TS 序列化或 CC 逻辑。**

## 2. 范围

### 2.1 In Scope

- `TSRuntimeAdapter` 接口：prepare / run / cancel（含 fault plan 绑定，ADR-0007）。
- `PreparedTSRun` 确定性指纹与 `TSRunResult.artifacts` 列表契约。
- tee 双写管线（ADR-0007 第 2 条）：baseline 流与 faulted 流的同 Run 产出。
- 取消语义、部分产物标注、事件循环隔离。
- Artifact 记录的最小元数据契约（存储本体归 SPEC-503）。

### 2.2 Out of Scope

- TS 序列化、CC 分配、Mux 调度、PCR 编码（SPEC-100~107）。
- 故障变换的实现与四类故障语义（SPEC-204；本模块只负责把过滤器接入管线）。
- Artifact 落盘路径安全与保留策略（SPEC-503）。
- TSDuck 传输级注入路由（TSDuck Adapter，SPEC-308，文本随 #13；MVP 不启用传输级注入）。
- 会话生命周期状态机（SPEC-200）。

## 3. 架构位置与依赖

ADR-0005 依赖链：Runtime（200）→ 本模块 → TS Core（100~108）。另依赖 SPEC-204 的 FaultDefinition/过滤器契约（prepare 签名引用，ADR-0007 第 2 条）与 SPEC-201 时钟（虚拟时长读取）。**只使用 TS Core 公共契约**（SPEC-108 Generator 入口、SPEC-107 Mux、包/Section 模型），禁止 import TS Core 内部实现。

## 4. 公开接口

```python
class TSRuntimeAdapter(Protocol):
    async def prepare(
        self,
        session: SessionContext,
        config: TSGeneratorConfig,
        fault_plan: tuple[FaultDefinition, ...] = (),
    ) -> PreparedTSRun: ...
    async def run(self, prepared: PreparedTSRun, sink: ArtifactSink) -> TSRunResult: ...
    async def cancel(self, run_id: str) -> None: ...
```

- **fault plan 在 prepare 绑定**（ADR-0007 第 2 条）：plan 在 prepare 阶段校验（对齐 AC-204-01"session 变异前拒绝"：未知 fault_type/参数键/越界 activation 在此拒绝），并把 plan 绑定进 `PreparedTSRun` 的确定性指纹；`run()` 签名不含 plan。plan 为空 = 仅出 baseline（八步闭环 Generate 步形态不变，ADR-0002）。
- `PreparedTSRun` 不可变；重复 `run(prepared)` 产生同指纹的新 Run（run_id 每次新建，uuid4）。
- `cancel(run_id)` 在有界批次边界生效（第 8 节）。

## 5. 数据模型

### 5.1 PreparedTSRun 确定性指纹

指纹输入显式化，全部进入 `config_hash` 类指纹字段：

1. 生成器版本（SPEC-108 generator_version）与有效 `TSGeneratorConfig`；
2. seed 与初始虚拟时钟（SPEC-201 config + start_time_ns）；
3. **fault plan 指纹**：plan 非空时，按 fault_type + 参数 + activation 的规范化序列化（键排序）计算，显式入指纹——相同 plan 必得相同指纹，不同 plan 必得不同指纹。

指纹计算本身确定；墙钟、session_id、run_id、路径**不入指纹**。

### 5.2 TSRunResult 与 artifacts 列表

```python
@dataclass(frozen=True)
class ArtifactRef:
    artifact_id: str          # uuid4
    kind: Literal["generated_ts", "faulted_ts", "log"]
    sha256: str
    byte_size: int
    packet_count: int | None  # TS 类 artifact 必填
    partial: bool

@dataclass(frozen=True)
class TSRunResult:
    run_id: str
    status: Literal["completed", "cancelled", "failed"]
    packet_count: int
    byte_count: int
    virtual_duration_ns: int
    artifacts: tuple[ArtifactRef, ...]     # 列表化（ADR-0007）
    warnings: tuple[Warning, ...]
    generator_version: str
    config_hash: str          # 含 fault plan 指纹
```

- **artifacts 列表化**：单字段改为列表，`kind` 标注 `generated_ts` / `faulted_ts` / `log`。
- **tee 双写**（ADR-0007 第 2 条）：plan 非空的 Run 同时产出——过滤器**前**流 → baseline sink（kind=`generated_ts`）；过滤器**后**流 → faulted sink（kind=`faulted_ts`）+ mutation log artifact（kind=`log`，内容结构归 SPEC-204 §7 mutation log）。两条流共用同一包序 frame（packet index 同槽位，ADR-0007 第 4 条）。
- **baseline 去重**：重复 Run 的 baseline 按 SHA-256 内容寻址去重（同指纹同字节 → 复用既有 artifact 记录，不重复落盘）；faulted 流不做跨 Run 去重。
- **188 不变式**：完成态输出（generated/faulted 均适用）满足 `byte_count == packet_count * 188`；CBR 恒定在 faulted 流上维持（等位替换保证，SPEC-204 §6）。

## 6. 处理算法要求

1. **管线形态**：Generator（SPEC-108）→（plan 非空时）语义流式过滤器（`faults` 包，SPEC-204）→ sink。TS Core 正常生成链路**零故障分支**（TS-CORE-INTEGRATION-CONTRACT §9 维持）；SPEC-107 Mux 对故障零感知。
2. **事件循环隔离**：同步生成不得阻塞 FastAPI event loop——用有界 worker 执行（进程内线程/进程池，按实测负载选型，SPEC-507 复核）；提交/取回边界全部异步。
3. **取消**：run 内部按有界批次（如每 N 包或每 M ms 虚拟时间）检查取消标志；取消后已产字节停止增长。
4. **部分产物**：cancelled/failed Run 的已产 Artifact 必须标 `partial=true`，**永不**标 complete；partial artifact 不得被后续 Run 引用为 baseline。
5. **确定性**：相同 config_hash（含 plan 指纹）+ 引擎版本 → SHA-256 字节一致；墙钟与 session/run ID 不影响 TS 字节。
6. **事件发射**：`simulation.run_started/run_progress/run_completed/run_failed`（信封义务包级承载；run_progress 可合并限流）。

## 7. Artifact 记录契约

本模块定义 Run 维度的最小记录；持久化与路径安全归 SPEC-503：

- artifact_id（uuid4 opaque）、kind、status（complete/partial/failed）、SHA-256、byte_size、packet_count、producing run_id、config_hash、generator_version。
- 绝不接受客户端文件系统路径；URI 相对 Artifact 根目录（SPEC-003 §2.7 TSArtifact 对齐）。
- mutation log artifact 的 evidence locator 满足 AC-204-04（SPEC-204 §7）。

## 8. 错误与诊断码

| Code | 条件 | 处理 |
|---|---|---|
| `SIM_TS_PLAN_INVALID` | fault plan 校验失败（prepare 阶段） | 拒绝，附 SPEC-204 校验错误明细 |
| `SIM_TS_CONFIG_INVALID` | TSGeneratorConfig 非法 | prepare 拒绝 |
| `SIM_TS_WORKER_UNAVAILABLE` | worker 池耗尽/崩溃 | retryable 语义，可重新 run |
| `SIM_TS_CANCELLED` | run 被 cancel | 返回 partial artifacts |
| `SIM_TS_GENERATION_FAILED` | TS Core 抛出错误（含 MUX_PACKET_DEADLINE_MISSED 等） | 透传根因错误码，Run failed |
| `SIM_TS_SINK_IO_ERROR` | ArtifactSink 写失败 | Run failed；已落盘 artifact 标 partial |

## 9. 测试规格

- 只用 TS Core 公共 API 的静态断言（import 白名单）。
- `byte_count == packet_count * 188`：baseline 与 plan 非空两条流都断言。
- tee 双写：同 Run 产 generated/faulted/log 三 artifact，index 对齐抽验（任取 k 个 index，两流该槽位包可互查）。
- baseline 去重：相同指纹二次 run，baseline artifact SHA 复用。
- plan 指纹：plan 参数变化 → 指纹变化；plan 相同 → 指纹相同；空 plan 与"空列表 plan"指纹相等。
- 确定性：同指纹跨进程重复生成，SHA-256 一致。
- 取消：中途 cancel 后 partial 标注、无 complete 误标；event loop 响应性（取消请求后 ≤ 一个批次边界生效）。
- 事件循环隔离：生成期间 event loop 心跳测试。

## 10. 验收标准

- `REQ-SIM-203-001`：只用 TS Core 公共契约，故障零分支进生成链路。
- `REQ-SIM-203-002`：prepare 绑定 plan 并入指纹；plan 在 session 变异前被校验拒绝。
- `REQ-SIM-203-003`：artifacts 列表化 + tee 双写（baseline/faulted/log），188 不变式与共用包序 frame 维持。
- `REQ-SIM-203-004`：baseline 按 SHA-256 内容寻址去重。
- `REQ-SIM-203-005`：取消有界、partial 标注正确。
- `REQ-SIM-203-006`：确定性 SHA-256（含 plan 的 Run 亦然）。
- `REQ-SIM-203-007`：event loop 全程响应，生成走有界 worker。

## 11. 非目标与风险

- 不在 MVP 实现 virtual-time activation 的故障（ADR-0007 第 3 条推迟项）；引入前必须重审本 spec 的指纹与管线假设。
- 不承诺 worker 池的具体实现（线程 vs 进程按 SPEC-507 基准定）。
- 风险：tee 双写使单 Run IO 翻倍——以 baseline 去重与 sink 缓冲缓解，性能口径随 OPEN-006（#16）定档复核。

## 12. 交付要求

建议文件：`app/simulation/ts_runtime.py`、`app/simulation/artifacts.py`；测试置于 `tests/unit/simulation/` 与 `tests/integration/simulation/`。故障管线集成测试与 SPEC-204 共用 fixture。

## 13. 参考

- ADR-0007 故障注入管线联合契约（注入架构、prepare 绑定、tee 双写、等位替换）。
- SPEC-108 TS Generator、SPEC-107 TS Mux、TS-CORE-INTEGRATION-CONTRACT §9（Generator 只出干净基线流；Artifact 通道保留给 TSDuck 传输级路由）。
- SPEC-503 Artifact Storage、SPEC-301 事件信封。
