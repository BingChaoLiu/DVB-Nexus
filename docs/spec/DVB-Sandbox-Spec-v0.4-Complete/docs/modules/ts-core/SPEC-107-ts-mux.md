---
spec_id: SPEC-107
title: MPEG-TS Multiplexer and CBR Scheduler
version: 0.4.0
status: DRAFT
phase: MVP
owner: TS Core
priority: P0
depends_on: [SPEC-100, SPEC-105, SPEC-106, SPEC-004]
requirements: [REQ-TS-107-001, REQ-TS-107-002, REQ-TS-107-003, REQ-TS-107-004, REQ-TS-107-005, REQ-TS-107-006, REQ-TS-107-007]
---

# SPEC-107 — TS Mux

## 1. 目标

实现基于 packet slot 的确定性 MPEG-TS Multiplexer，负责把多 PID Packet Source 合并为单一输出序列，并支持目标 CBR、表重复调度、PCR 周期调度和 Null Packet 填充。Mux 不重新封装 PSI/PES，也不应擅自修改已经完成的 TS Packet。

## 2. 范围

**In Scope：** MVP 单 Program；多 PID packet source；固定目标 transport bitrate；packet-slot scheduler；PAT/PMT 周期插入；PCR 调度；Null PID 0x1FFF；可重复/确定性输出；资源上限。  
**Out of Scope：** 多层级 DVB SI 更新策略、多个独立 PCR domain、统计复用的实时复杂算法、硬件/网络实时输出、variable-rate 输出、DVB 调制器 FEC。

## 3. 核心调度模型

### 3.1 Packet Slot

一个 TS Packet 固定 188 bytes，即 1504 bits。目标 TS bitrate 为 `B` bit/s 时，理想 Packet Slot 周期为 `1504 / B` 秒。调度内部使用整数/rational accumulator，不使用 float 累积 slot 时间。

对于 slot index `n`，媒体时钟时间应由精确整数公式得到，例如：

`slot_time_27mhz(n) = floor(n * 1504 * 27_000_000 / B)`

必须明确 rounding 规则，并保证长时间累计误差有界；不得每个包都将浮点 packet duration 累加。

### 3.2 CBR

- 输出每个 slot 恰好一个 188-byte Packet。
- 所有 Packet（包括 PAT/PMT、PES、PCR-only、Null Packet）均占用目标 TS bitrate。
- 当某 slot 没有其它已到期 Packet 时，插入 Null Packet PID 0x1FFF。
- `packet_count` 固定的输出，其字节数必须等于 `packet_count * 188`。
- CBR 是媒体时间调度定义，不要求 Generator 在真实墙钟上实时发送。

### 3.3 Scheduled Packet

建议内部调度项：

```python
@dataclass(frozen=True)
class ScheduledPacket:
    packet: TSPacket
    release_tick_27mhz: int
    deadline_tick_27mhz: int | None
    priority: int
    source_id: str
    source_sequence: int
```

同一 slot 有多个候选 Packet 时，使用确定性排序：最早 deadline、较高优先级（项目需冻结数值方向）、source_id、source_sequence。相同配置的 tie-break 必须稳定。

## 4. Mux 配置

```python
@dataclass(frozen=True)
class PIDRateConfig:
    pid: int
    bitrate_bps: int
    source_id: str

@dataclass(frozen=True)
class TableRepetitionConfig:
    pat_period_ms: int
    pmt_period_ms: int

@dataclass(frozen=True)
class PCRScheduleConfig:
    pcr_pid: int
    target_interval_ms: int
    insertion_policy: str  # payload_packet_first | adaptation_only_fallback

@dataclass(frozen=True)
class MuxConfig:
    target_bitrate_bps: int
    output_packet_count: int
    pid_rates: tuple[PIDRateConfig, ...]
    tables: TableRepetitionConfig
    pcr: PCRScheduleConfig
    initial_media_clock_27mhz: int = 0
```

MVP 必须校验 `target_bitrate_bps > 0`、packet_count 为正数、PID 唯一策略、各 ES bitrate 总和不会长期超过可用 TS capacity（允许协议 overhead 另外计算）。

## 5. 调度算法要求

1. 为每个 PID Source 维护独立的整数码率相位/令牌累加器，避免因 float 累加造成漂移。
2. PAT/PMT 根据配置的周期生成待发送 Section，再由 SPEC-106 Packetizer 输出 Packet；表的发送周期由 Mux 配置控制。
3. PCR 以目标周期进入调度。当 PCR_PID 的待发送 Payload Packet 可容纳 PCR 时，优先将 PCR 放入带 AF 的 Packet；若不能在允许窗口内找到可用 Payload Packet，则按配置产生 adaptation-only PCR Packet。
4. adaptation-only PCR Packet 必须遵守 SPEC-100 CC 语义，不推进该 PID 的 CC。
5. 选取已到期 Packet；无候选时输出 Null Packet。
6. 如果候选 Packet 过期，按配置记录 deadline miss；MVP 默认生成错误并终止，不静默丢弃 Packet。
7. `output_packet_count` 到达后停止；不能额外输出延迟 Packet。
8. 输出顺序、优先级和相位计算必须可复现。

### 5.1 Null Packet

- PID 固定 `0x1FFF`。
- AFC=payload-only，Payload 填充 0xFF。
- CC 对 Null PID 不作为业务连续性指标；MVP 固定为 0，避免引入伪语义。
- Null Packet 仅用于补齐 CBR slot。

### 5.2 表周期

- PAT/PMT period 是仿真配置，不在本 Spec 声称为所有标准 profile 的统一固定值。
- Generator 默认值应由已批准的 MVP profile 冻结；建议 PAT/PMT 均 100 ms 作为初始默认，但必须在配置/报告中可见。
- 未来 DVB profile 应按相应规范更新 table repetition 约束，不能将 MPEG 默认配置直接宣称为 DVB 所有网络的合规值。

### 5.3 PCR 周期

- `target_interval_ms` 是 Generator/Mux 配置。
- DVB TR 101 290 的 PCR repetition / accuracy 检测规则由 Analyzer/Conformance Spec 实现；Mux 不将一个诊断阈值当作 PCR 编码规则。
- MVP 建议初始 PCR 目标周期 40 ms，预留测量裕量；这是项目配置建议，不是本模块宣称的标准强制常数。

## 6. 公共接口

```python
class TSMux:
    def __init__(self, config: MuxConfig, sources: list[PacketSource]) -> None: ...
    def iter_packets(self) -> Iterator[TSPacket]: ...
    def summary(self) -> MuxSummary: ...
```

`PacketSource` 是内部 Protocol，负责以稳定次序提供 ScheduledPacket 或 packet batches。Mux 不能依赖文件系统、TSDuck 或 FastAPI。

## 7. 错误处理

- `MUX_INVALID_BITRATE`
- `MUX_INVALID_PACKET_COUNT`
- `MUX_PID_DUPLICATE_SOURCE`
- `MUX_PID_RATE_OVERCOMMITTED`
- `MUX_TABLE_PERIOD_INVALID`
- `MUX_PCR_INTERVAL_INVALID`
- `MUX_PACKET_DEADLINE_MISSED`
- `MUX_SOURCE_EXHAUSTED`（按 source 定义；不应误判为全局错误）
- `MUX_SLOT_COUNT_MISMATCH`

所有终止错误需包含 run-independent 的可复现上下文：slot index、source_id、PID、target bitrate；禁止包含不可控临时路径。

## 8. 测试规格

- 空业务 Source：输出全部 Null Packet，长度和 CBR slot 数准确。
- 单 PID 固定 bitrate：包分布稳定、无 drift。
- 多 PID：每 PID 目标速率和总速率。
- PAT/PMT period 触发次数和 packet index。
- PCR 插入到 Payload Packet 与 adaptation-only fallback 两条路径。
- PCR packet adaptation field 不损坏 payload，CC 不错误递增。
- bitrate 不是 1504 整数倍的场景，长序列误差有界。
- 候选 Packet 同时到期时 deterministic tie-break。
- 超售时配置拒绝或产生明确 deadline miss。
- 重复运行字节级一致。
- `packet_count * 188` 与实际输出一致。

## 9. 验收标准

- `REQ-TS-107-001`：输出 Packet Slot 数准确，所有 Packet 为 188 bytes。
- `REQ-TS-107-002`：目标 bitrate 通过整数时基稳定调度，无累计浮点漂移。
- `REQ-TS-107-003`：PAT/PMT 周期插入受配置控制。
- `REQ-TS-107-004`：PCR 依照目标周期插入，payload 不被破坏。
- `REQ-TS-107-005`：空 slot 以 Null Packet 补齐，输出 CBR 结构完整。
- `REQ-TS-107-006`：过载/期限问题显式报告，不静默丢包。
- `REQ-TS-107-007`：相同输入配置产生确定性调度输出。

## 10. MVP 限制

- 仅单 Program 配置，但允许多个 ES PID。
- 仅固定 CBR 输出。
- 不支持多 PCR domain 和复杂实时统计复用。
- 不在此处做 Fault Injection；故障处理由 SPEC-204 在正常 TS 输出后完成。

## 11. 交付要求

建议文件：`mux/config.py`、`mux/scheduler.py`、`mux/sources.py`、`mux/null_packet.py`。提供 packet slot 数、总 bitrate、PCR packet positions 和 Null packet count 的 MuxSummary。
