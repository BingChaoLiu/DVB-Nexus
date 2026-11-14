---
spec_id: SPEC-201
title: Simulation Clock and Deterministic Scheduler
version: 0.5.0
status: APPROVED
phase: MVP
owner: Simulation Engine
priority: P0
depends_on: [SPEC-003, SPEC-105]
requirements: [REQ-SIM-201-001, REQ-SIM-201-002, REQ-SIM-201-003, REQ-SIM-201-004, REQ-SIM-201-005, REQ-SIM-201-006]
---

# SPEC-201 — Simulation Clock 与确定性调度器

## 1. 目标

定义沙盘唯一可控时钟：单调整数纳秒虚拟时间、有理数倍速、确定性调度器及其与 TS Core 媒体时钟（SPEC-105）的换算边界。相同配置 + 种子 + 引擎版本必须产生相同的事件顺序与 TS 字节（CONTEXT.md 确定性复现）。

## 2. 范围

### 2.1 In Scope

- `virtual_time_ns` 时间域模型与会话纪元（epoch）。
- `SimulationClockConfig`：deterministic/realtime 双模式、有理数倍速、tick 量子。
- 确定性调度器：排序键、work budget、回调纪律。
- pause/resume 对虚拟时间的冻结语义（编排方见 SPEC-200 §5.1）。
- 虚拟时间 ↔ PCR/PTS/DTS 域的显式换算函数（调 SPEC-105）。

### 2.2 Out of Scope

- 墙钟本身的管理（operational metadata，可观测不参与仿真序）。
- PCR/PTS/DTS 的编解码与回绕语义（SPEC-105/104 权威）。
- Runtime 生命周期状态机（SPEC-200）。
- 事件信封（SPEC-301；`simulation.clock_advanced` 事件的发射属包级契约义务）。

## 3. 时间域模型

- `virtual_time_ns`：自会话纪元起算的单调 **int64 整数纳秒**；只前进，不接受倒退。
- 墙钟（wall clock）只是 operational metadata：可记日志、可入 `time.observed`（ADR-0006 信封），**永不参与仿真事件定序，永不进入确定性 TS 字节**。
- PCR/PTS/DTS 是 TS Core 的媒体时钟域（90 kHz / 27 MHz，含回绕），与 `virtual_time_ns` 是不同域；换算必须经第 6 节显式函数，禁止隐式算术混用（SPEC-300 §6 时钟模型同理）。

## 4. 数据模型

```python
@dataclass(frozen=True)
class SimulationClockConfig:
    mode: Literal["deterministic", "realtime"]
    start_time_ns: int = 0
    speed_num: int = 1        # realtime 倍速分子，> 0
    speed_den: int = 1        # realtime 倍速分母，> 0；倍速 = speed_num / speed_den
    tick_quantum_ns: int = 1_000_000   # 调度器最小推进量子，> 0
```

- 全部数值字段范围校验：`start_time_ns >= 0`，`tick_quantum_ns > 0`，`speed_num/speed_den > 0`。
- 倍速用**有理整数**表达，禁止 float 参与时间推进（避免累计漂移）；倍速作用于 realtime 模式的墙钟换算。

## 5. 公开接口

```python
class SimulationClock(Protocol):
    def now_ns(self) -> int: ...
    async def advance_to(self, target_ns: int) -> int: ...   # 返回实际到达的 ns
    async def advance_by(self, delta_ns: int) -> int: ...
    async def pause(self) -> None: ...    # 内部编排接口，见 SPEC-200 §5.1
    async def resume(self) -> None: ...
    def is_paused(self) -> bool: ...
```

- **deterministic 模式**：虚拟时间只经调度器 commit 或显式 `advance_to/advance_by` 前进；无墙钟参与。
- **realtime 模式**：虚拟时间 = 已冻结累计值 + (当前墙钟 − 恢复点墙钟) × speed_num/speed_den；倍速换算全部整数化。pause 冻结累计值，resume 重设恢复点。
- `advance_to(target)` 若 target ≤ 当前值，拒绝（`SIM_CLOCK_TIME_BACKWARDS`）。

## 6. 与 SPEC-105 的换算边界

- 提供**显式、经测试**的纯函数：`virtual_time_ns ↔ PCR base/ext 值`、`virtual_time_ns ↔ PTS/DTS ticks`；实现直接调用 SPEC-105 的换算原语，不重复实现 27 MHz/90 kHz 算术与回绕。
- 换算是无状态纯函数；回绕判定窗口遵循 SPEC-105 冻结的 `modular_delta` 半周期窗口（[ts-core 修订批准](https://github.com/BingChaoLiu/DVB-Nexus/issues/11) 裁决）。

## 7. 处理算法要求（确定性调度器）

1. **排序键**：`(deadline_ns, priority, insertion_sequence)`。deadline 越早越先；deadline 相同按 priority 数值**越小越高**；再同按 insertion_sequence（入队先后）定序。
2. **work budget**：单次调度循环设工作量预算，防止零时长回调（deadline 相同的自续回调）饿死时间推进；超预算的回调顺延到下一循环。
3. **回调纪律**：回调不得阻塞（禁止同步 IO/长计算）；长工作必须转交 worker（SPEC-203 的 bounded worker 语义）。
4. **取消**：回调可在执行前被取消；已开始执行的回调不可中断，由实现自行协作式退出。
5. **deterministic 序稳定**：相同 config/seed/拓扑/fault plan 下，调度器产生的事件顺序逐次一致；禁止以墙钟、随机数、路径、session ID 参与排序键。
6. `simulation.clock_advanced` 事件按包级契约发射（允许合并限流，SPEC-301 §5）。

## 8. 错误与诊断码

| Code | 条件 | 处理 |
|---|---|---|
| `SIM_CLOCK_TIME_BACKWARDS` | advance 目标 ≤ 当前虚拟时间 | 拒绝 |
| `SIM_CLOCK_CONFIG_INVALID` | 配置越界（负 start、非正量子/倍速） | 构造时拒绝 |
| `SIM_CLOCK_PAUSED` | 冻结期间请求 advance | 拒绝或排队（编排方决定），不得静默丢弃 |
| `SIM_SCHEDULER_OVERLOAD` | work budget 持续超限（配置阈值） | 报告诊断事件，不中断会话 |

## 9. 测试规格

- 单调性：任意操作序列后 `now_ns` 不减；倒退请求拒绝。
- 排序稳定性：同 deadline 不同 priority/insertion_sequence 的回调执行序固定。
- 有理倍速：speed 7/3、1/1、1/1000 下 realtime 换算无浮点漂移（整数断言）。
- pause 冻结：PAUSED 期间墙钟流逝不改变 `now_ns`；resume 后从冻结值继续。
- work budget：构造零时长自续回调风暴，验证时间仍能推进。
- 回调取消：取消后不执行；执行中回调不被强杀。
- 换算函数：与 SPEC-105 测试向量交叉验证（PCR-PTS 测试向量，`docs/test-vectors/PCR-PTS.md`）。

## 10. 验收标准

- `REQ-SIM-201-001`：虚拟时间单调，倒退拒绝。
- `REQ-SIM-201-002`：调度排序键冻结，tie 顺序稳定可复现。
- `REQ-SIM-201-003`：pause 冻结虚拟时间，resume 对称恢复。
- `REQ-SIM-201-004`：有理数倍速全程整数运算，无 float 漂移。
- `REQ-SIM-201-005`：work budget 与取消机制防饿死。
- `REQ-SIM-201-006`：与 PCR/PTS 的换算只经 SPEC-105 显式函数，并有测试向量背书。

## 11. 非目标与风险

- 不提供分布式时钟同步（单机沙盘）。
- 不承诺 realtime 模式的硬实时精度；realtime 只是倍速墙钟驱动，抖动由诊断事件暴露而非承诺消除。
- 风险：virtual time activation 的故障触发（ADR-0007 推迟项）未来引入时，必须保持"CBR 下 virtual time ↔ packet index 可确定性换算"前提，否则破坏等位替换不变式——届时须重新评审 SPEC-204。

## 12. 交付要求

建议文件：`app/simulation/clock.py`、`app/simulation/scheduler.py`；换算函数放 `app/simulation/clock_convert.py` 或 SPEC-105 侧（实现自选，但必须单处权威）。测试置于 `tests/unit/simulation/`。

## 13. 参考

- SPEC-105 PCR/Clock（媒体时钟域、modular_delta 窗口）。
- ADR-0006 第 2 条（journal_seq 全序；生产者时间戳不定序）。
- CONTEXT.md「确定性复现」词条。
