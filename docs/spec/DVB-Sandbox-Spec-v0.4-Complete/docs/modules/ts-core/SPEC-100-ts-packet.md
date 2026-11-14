---
spec_id: SPEC-100
title: MPEG-2 Transport Stream Packet Core
version: 0.5.0
status: APPROVED
phase: MVP
owner: TS Core
priority: P0
depends_on: [SPEC-003, SPEC-004, SPEC-105]
requirements: [REQ-TS-100-001, REQ-TS-100-002, REQ-TS-100-003, REQ-TS-100-004, REQ-TS-100-005, REQ-TS-100-006]
---

# SPEC-100 — MPEG-2 TS Packet

## 1. 目标

实现 MPEG-2 Transport Stream 标准 188-byte Packet 的纯 Python 数据模型、解析、序列化、字段校验和用于生成端的 PID 独立 CC 分配器。Packet 是 TS Core 的最低层数据结构，所有更高层模块均通过该模型或其原始 bytes 表达数据。

## 2. 范围

### 2.1 In Scope

- 固定 188-byte Packet 的 `from_bytes()` / `to_bytes()`。
- 4-byte TS Header 的字段解析与编码。
- Adaptation Field 的长度、Flags、PCR/OPCR、Splice Countdown、Private Data、Extension 原始保留和 stuffing。
- Payload 的边界与字节保留。
- PID / CC / Scrambling Control / AFC 范围校验。
- 生成端 CCAllocator，按 PID 维护状态。
- 结构化 ParseIssue/ValidationIssue。

### 2.2 Out of Scope

- 204-byte RS204/FEC trailer。
- 对输入文件进行 188/192/204 自动同步和重同步扫描（归 SPEC-631/Analyzer）。
- 输入码流全局 CC 统计和根因诊断（统计归 SPEC-302，诊断归 SPEC-306/307）。
- T2MI、BISS、DVB-CA 或 RF 层解析。
- 自行纠正 TEI、错误 PID 或错误 CC。

## 3. 标准结构

一个 Packet 固定 188 bytes：4-byte Header + 184-byte 后续区域。Header 位定义：

| Byte/Bit | 字段 | 位宽 | 说明 |
|---|---|---:|---|
| 0 | `sync_byte` | 8 | 固定 `0x47` |
| 1[7] | `transport_error_indicator` | 1 | TEI |
| 1[6] | `payload_unit_start_indicator` | 1 | PUSI |
| 1[5] | `transport_priority` | 1 | 优先级 |
| 1[4:0] + 2 | `PID` | 13 | Packet Identifier |
| 3[7:6] | `transport_scrambling_control` | 2 | 00 Not scrambled；01/10/11 User-defined（DVB 惯例 10/11 = 偶/奇钥，ISO/IEC 13818-1 Table 2-4） |
| 3[5:4] | `adaptation_field_control` | 2 | 00 reserved/invalid；01 payload only；10 adaptation only；11 both |
| 3[3:0] | `continuity_counter` | 4 | 0..15 |

## 4. 数据模型

以下是接口形态约束，Agent 可补充私有辅助方法，但不得改变字段语义：

```python
from dataclasses import dataclass
from enum import IntEnum

TS_PACKET_SIZE = 188
TS_HEADER_SIZE = 4
TS_SYNC_BYTE = 0x47
PID_NULL = 0x1FFF

class AdaptationFieldControl(IntEnum):
    RESERVED = 0
    PAYLOAD_ONLY = 1
    ADAPTATION_ONLY = 2
    ADAPTATION_AND_PAYLOAD = 3

# PCR is the single authoritative value type defined by SPEC-105.
from app.ts.clock import PCR

@dataclass(frozen=True)
class AdaptationField:
    discontinuity_indicator: bool = False
    random_access_indicator: bool = False
    elementary_stream_priority_indicator: bool = False
    pcr: PCR | None = None
    opcr: PCR | None = None
    splice_countdown: int | None = None  # signed 8-bit
    transport_private_data: bytes | None = None
    extension_raw: bytes | None = None  # opaque extension body for round-trip
    stuffing: bytes = b""

@dataclass(frozen=True)
class TSPacket:
    pid: int
    continuity_counter: int
    payload: bytes | None
    adaptation_field: AdaptationField | None = None
    transport_error_indicator: bool = False
    payload_unit_start_indicator: bool = False
    transport_priority: bool = False
    transport_scrambling_control: int = 0
```

`adaptation_field_control` 由 `payload is not None` 与 `adaptation_field is not None` 推导；两者都不存在时非法。若实现需要保留原始 AFC，应使用独立 raw parser result，不允许对象处于不可序列化状态。

## 5. 字段与编码规则

### 5.1 PID 与保留值

- PID 必须为 0..0x1FFF。
- `0x1FFF` 是 Null Packet PID；本模块只提供常量和字段表示，不强制其 payload 内容。
- PAT/CAT 等特殊 PID 的用途检查属于更高层 table/profile 校验，不在通用 Packet 构造器中硬编码。

### 5.2 Adaptation Field

- `adaptation_field_length` 是紧随长度字节之后的 AF 字节数，范围 0..183（AFC=11 时上限 182）。
- AF length 为 0 时，不存在 flags byte；为正数时，第一个 AF 内容字节为 8 个 Flags。
- Flags 后的可选字段必须按 flags 顺序编码：PCR、OPCR、splice countdown、transport private data、adaptation extension。
- PCR / OPCR 各占 6 bytes；具体位编码由 SPEC-105 定义，并由本模块调用。
- `transport_private_data_length` 为 8-bit；其后必须恰好提供对应字节数。
- adaptation extension 若暂不解释内部字段，必须按长度完整保留原始 bytes，禁止 parse→serialize 时静默丢弃。
- AF stuffing 使用 `0xFF`。构造器自动填充时必须精确满足 188 bytes。
- adaptation-only（AFC=10）包没有 Payload，AF length 必须使 AF 占满 Header 后 184 bytes（length byte + AF body = 184）。
- adaptation+payload（AFC=11）必须至少有 1 byte Payload；AF length 不得越界。

### 5.3 Scrambling Control

2-bit 原值必须可无损解析和序列化。`01` 保留值应产生可查询的语义 ValidationIssue，但不能在无损 round-trip 路径中自动改写为 `00`。

### 5.4 CC

- 生成端 CC 以 PID 为独立状态。
- Packet 的 CC 值按“最近一个带 Payload 的 Packet”递增；仅 Adaptation Field Packet 使用该 PID 最近一个 Packet 的 CC，不推进计数。
- 对每个 PID 保存 `last_emitted_cc` 与 `last_payload_cc`，不能简单地在每次 `allocate()` 调用时无条件自增。
- 第一个 Packet（无论是否带 Payload）使用配置的 `initial_cc`；若此前没有带 Payload 的 Packet，则第一个带 Payload 的 Packet 也使用 `initial_cc`。
- 例：payload → adaptation-only → payload，CC 应为 `0, 0, 1`；连续两个 payload → CC 为 `0, 1`；首包 adaptation-only → 后续首个 payload，CC 可为 `0, 0`。
- 明确声明 discontinuity 的行为由调用者提供策略；本 Spec 的 CCAllocator 提供显式 `reset(pid, next_value)`，不根据墙钟或猜测自动重置。
- 输入 CC 连续性诊断、重复 Packet 判别和异常统计不属于 CCAllocator。

## 6. 公共接口

```python
class TSPacket:
    @classmethod
    def from_bytes(cls, data: bytes, *, strict: bool = True) -> "TSPacket": ...
    def to_bytes(self) -> bytes: ...
    def validate(self) -> list["ValidationIssue"]: ...

class CCAllocator:
    def __init__(self, initial_cc: int = 0) -> None: ...
    def allocate(self, pid: int, *, has_payload: bool) -> int: ...
    def reset(self, pid: int, next_value: int) -> None: ...
    def clear(self) -> None: ...
```

`ValidationIssue` 的权威定义见 `TS-CORE-INTEGRATION-CONTRACT.md` §6（code/message/severity/field）；本模块不重复定义。

`allocate()` 的状态规则必须等价于：

```python
if pid_has_no_previous_packet:
    cc = initial_cc
elif has_payload:
    cc = initial_cc if last_payload_cc is None else (last_payload_cc + 1) & 0x0F
else:
    cc = last_emitted_cc

last_emitted_cc = cc
if has_payload:
    last_payload_cc = cc
return cc
```

这里 `initial_cc` 是该 PID 当前 generation 的初始计数值；`reset(pid, next_value)` 清除该 PID 的历史并设定新的初始值。

约束：`from_bytes` 必须要求输入长度恰好 188；不承担自动找到 Sync Byte 的职责。`strict=True` 遇到 `sync_byte != 0x47`、AFC=00、AF 长度越界等结构错误应抛出 `InvalidPacketError`。`strict=False` 仅用于诊断工具，必须通过 parse result/issue 明确暴露错误，不能返回无错误的“有效 Packet”。

## 7. 处理算法要求

1. 先验证输入长度，再读取任何 Header 字段。
2. 解析 Header 后检查 AFC；按 AFC 决定 AF/Payload 起始偏移。
3. 解析 AF 时，先验证 `adaptation_field_length` 与 Packet 边界，再读取 Flags/可选字段。
4. 各可选字段消费字节数不能超过 AF 内容边界；截断必须报错。
5. 未识别 AF extension 内容需以 `extension_raw` 保留。
6. 序列化时重新计算 AFC、AF length 和 stuffing，或验证调用方显式提供的 raw 字段一致；不能产生非 188-byte 输出。
7. `CCAllocator.allocate()` 必须实现“仅 payload packet 推进计数，adaptation-only packet 重用最近 CC”的状态规则；参见第 5.4 节伪代码。

## 8. 错误与诊断码

| Code | 条件 | 处理 |
|---|---|---|
| `TS_PACKET_SIZE_INVALID` | 输入长度不等于 188 | strict 抛错 |
| `TS_SYNC_BYTE_INVALID` | Byte 0 不是 0x47 | strict 抛错 |
| `TS_AFC_RESERVED` | AFC=00 | strict 抛错 |
| `TS_PID_OUT_OF_RANGE` | PID 超出 13-bit | 构造/序列化拒绝 |
| `TS_CC_OUT_OF_RANGE` | CC 不在 0..15 | 拒绝 |
| `TS_AF_LENGTH_INVALID` | AF 长度与 AFC/Packet 边界不兼容 | 拒绝 |
| `TS_AF_FIELD_TRUNCATED` | Optional AF 字段超出 AF 边界 | 拒绝 |
| `TS_AF_EXTENSION_OPAQUE` | extension 存在但不解析 | 信息项，不是错误 |
| `TS_SCRAMBLING_RESERVED` | scrambling_control=01 | 保留原值并报告 issue |

## 9. 测试规格

- Header 所有位域的 pack/unpack round-trip。
- PID 边界：0、1、0x1FFE、0x1FFF；拒绝 -1、0x2000。
- CC 边界：0、15；拒绝 -1、16。
- AFC 四种值：00 拒绝，01/10/11 正确解析。
- AF length：0、1、183（183 仅在 AFC=10 时合法）；超边界截断拒绝。
- 同时包含 PCR、OPCR、private data、splice countdown 的 AF 边界组合。
- AF extension opaque bytes round-trip。
- payload 0、1、183、184 bytes 与合法 AFC 组合。
- 任何有效对象 `len(to_bytes()) == 188`。
- CCAllocator：同 PID payload 递增、不同 PID 独立、adaptation-only 重用最近 CC、15→0 回绕、reset 行为；至少验证 `payload → adaptation-only → payload = 0,0,1`。
- fuzz/property test：任意 188-byte 输入不崩溃；只允许返回 Packet 或稳定 ParseError。

## 10. 验收标准

- `REQ-TS-100-001`：有效 188-byte Packet 可解析并原样 round-trip。
- `REQ-TS-100-002`：Header/PID/AFC/CC 字段编码与 H.222.0 位布局一致。
- `REQ-TS-100-003`：Adaptation Field 已实现字段可解析和编码，未知 extension 可无损保留。
- `REQ-TS-100-004`：对所有长度/偏移进行边界校验，无越界读取。
- `REQ-TS-100-005`：CCAllocator 正确处理 PID 独立状态、Payload 行为和 modulo-16 回绕。
- `REQ-TS-100-006`：单元测试、属性测试通过，所有负向输入有稳定错误结果。

## 11. 非目标与风险

- 不保证任意厂商私有 AF Extension 的语义理解；只要求能安全保留。
- 不提供 204-byte RS204 编码/校验。
- 不负责 TS 输入重同步与自动识别。
- 不将 Parser 的“结构可读”宣称为整个 Transport Stream 合规。

## 12. 交付要求

建议文件：`ts/packet.py`、`ts/adaptation_field.py`（可按实现合并）、`ts/cc.py`、`ts/errors.py`（异常类权威清单见集成契约 §7）；测试置于 `tests/unit/ts/`。提交 `IMPLEMENTATION_REPORT.md`，列出对应 REQ、所有边界测试和 188-byte round-trip 证据。

## 13. 参考

- ITU-T H.222.0 (04/2025), TS packet syntax / adaptation field。
- TSDuck `ts::TSPacket` Developer/API reference：<https://tsduck.io/docs/tsduck-dev.html>、<https://tsduck.io/doxy/df/dc6/classts_1_1TSPacket.html>。
