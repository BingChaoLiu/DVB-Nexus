---
spec_id: TS-CORE-IC-001
title: TS Core Cross-Module Integration Contract
version: 0.4.0
status: DRAFT
phase: MVP
owner: Architecture
applies_to: SPEC-100..SPEC-108
depends_on: [SPEC-001, SPEC-003, SPEC-004, SPEC-005]
---

# TS Core 跨模块集成契约

## 1. 目的与权威性

本文定义 SPEC-100～SPEC-108 之间必须一致的公共类型、依赖方向、时间语义、字节序、异常类别和集成顺序。它是 TS Core 子系统内部的横向契约；各模块 Spec 定义本模块的详细行为。

如果本文与单个模块 Spec 有冲突，标记冲突并提交 Spec Change Request；不得由 Agent 自行选择一份执行。经批准后同步更新所有关联文档。

## 2. 核心原则

1. **协议字节是权威结果。** 所有可观察的 PID、CC、PCR、PAT、PMT、PES 事实最终必须能从序列化 TS 字节重新解析出来。
2. **纯 Python 核心。** `app.ts` 不依赖 FastAPI、Pydantic、SQLite、TSDuck、UI 或业务服务。数据模型优先使用标准库 `dataclass`、`Enum`、`Protocol`。
3. **层次分离。** TS Packet、Section、PES、Packetizer、Mux、Generator 是不同抽象，不互相复制实现。
4. **精确整数运算。** PID/长度/时间戳/码率调度不使用浮点数参与协议编码；必要时使用整数和 `fractions.Fraction`。
5. **无隐式修复。** 解析器默认报告畸形数据，不得静默改写输入；修复属于明确的 Fault/Repair/Adapter 行为。
6. **确定性。** 相同规范化配置、生成器版本、seed、初始媒体时钟应产生字节一致的 TS 输出。
7. **MVP 固定 188-byte。** 一个输出 Artifact 内不得混合 188 与 204 byte 包。

## 3. 模块依赖

```text
SPEC-105 Media Clock ───────────────┐
                                     v
SPEC-100 TSPacket ───────┬──────> SPEC-102 PSI Section
                        │
SPEC-101 MPEG2 CRC32 ────┘
                                  │
                                  v
                            SPEC-103 PAT/PMT

SPEC-105 Media Clock ──────> SPEC-104 PES
         │                         │
         └─────────────────────────┴──> SPEC-106 Packetizer
SPEC-100 TSPacket ────────────────────> SPEC-106 Packetizer
SPEC-102 PSI Section ─────────────────> SPEC-106 Packetizer
                                          │
                                          v
                                    SPEC-107 TS Mux
                                          │
SPEC-103 PAT/PMT ────────────────────────┤
SPEC-104 PES ────────────────────────────┤
                                          v
                                    SPEC-108 Generator
```

`SPEC-101` 是纯 CRC 算法，不应反向依赖 Section。`SPEC-105` 是媒体时钟数学，不依赖 Runtime 的 wall-clock/Session Clock。`SPEC-108` 负责装配各组件，不复制 Packet/Section/PES 编解码逻辑。

## 4. 公共命名、单位和位宽

| 名称 | 类型 | 单位/范围 | 约定 |
|---|---|---|---|
| `PID` | `int` | 13 bit，0..8191 | 对外 API 使用十进制整数；日志可显示 `0xNNNN` |
| `CC` | `int` | 4 bit，0..15 | modulo-16 |
| `packet_index` | `int` | 从 0 开始 | 指向 TS Artifact 中的 188-byte Packet |
| `section_length` | `int` | 12 bit，0..4095 | 按 table profile 再施加更严格的上限 |
| `program_number` | `int` | 16 bit | PAT 中 0 有 NIT PID 特殊含义；PMT program_number 非 0 |
| `program_map_PID` | `PID` | 13 bit | PAT 中 PMT PID |
| `PCR_PID` | `PID` | 13 bit | PMT 中 PCR 所在 PID |
| `PTS/DTS` | `int` | 33 bit，90 kHz ticks | modulo `2^33` |
| `PCR.base` | `int` | 33 bit，90 kHz ticks | PCR 主计数 |
| `PCR.extension` | `int` | 9 bit | 合法值 0..299 |
| `PCR ticks` | `int` | 27 MHz ticks | `base * 300 + extension` |
| `bitrate_bps` | `int` | bit/s | TS 码率包含 TS Header、AF 和 Null Packet |
| `packet_size` | `int` | MVP 固定 188 | 204 不由 Generator 输出 |

禁止用 `float` 保存协议时间戳或序列化长度。

## 5. 字节序与 CRC

- TS Header 多字节字段按标准位布局逐字节打包；不要直接依赖本机 struct 对齐。
- Section/PES 内的多字节整数按网络字节序（big-endian）编码。
- MPEG-2 PSI CRC 使用 CRC-32/MPEG-2：poly `0x04C11DB7`、init `0xFFFFFFFF`、RefIn=false、RefOut=false、XorOut=`0x00000000`；Section CRC 以 4-byte big-endian 写入。
- `mpeg2_crc32(section_including_crc) == 0` 表示 CRC remainder 校验通过。
- 参考向量：ASCII `123456789` → `0x0376E6E7`。

## 6. 建议公共类型（逻辑契约）

```python
from dataclasses import dataclass
from enum import IntEnum

class TransportScramblingControl(IntEnum):
    NOT_SCRAMBLED = 0b00
    RESERVED = 0b01
    SCRAMBLED_EVEN = 0b10
    SCRAMBLED_ODD = 0b11

@dataclass(frozen=True)
class PacketLocation:
    packet_index: int
    pid: int

@dataclass(frozen=True)
class ParseIssue:
    code: str
    message: str
    offset: int | None = None
    severity: str = "error"
```

具体字段以各模块 Spec 为准；这是概念契约，不要求复制同名类到每个包。

## 7. 异常类型注册

建议在 `app.ts.errors` 集中定义稳定异常类别：

- `TSCoreError`：所有 TS Core 可预期错误的基类。
- `InvalidPacketError`：Packet 长度、Sync Byte、AFC 或字段边界错误。
- `InvalidSectionError`：Section 长度、语法或 CRC 错误。
- `InvalidPESPacketError`：PES 起始码、Header 长度、PTS/DTS 编码错误。
- `InvalidTimestampError`：时间戳超范围或 PCR extension 非法。
- `InvalidMuxConfigError`：Mux 码率、PID、周期或容量配置非法。
- `GenerationError`：生成配置无法表达或内部生成失败。

解析不可信数据的公共 API 应允许调用方选择 strict 模式或取得 `ParseIssue`；默认 strict，不得以全零对象伪装成功。

## 8. 模块接口总览

| Spec | 核心公开对象/函数 | 输入 | 输出 |
|---|---|---|---|
| 100 | `TSPacket`, `AdaptationField`, `CCAllocator` | 188 bytes / 字段 | Packet 对象 / 188 bytes |
| 101 | `mpeg2_crc32`, `verify_mpeg2_crc32`, `append_mpeg2_crc32` | bytes | CRC 整数 / bool / bytes |
| 102 | `PSISection`, `SectionAssembler` | Section bytes / TS packet | Section 对象 / Section 列表 |
| 103 | `PATSection`, `PMTSection`, `PATBuilder`, `PMTBuilder` | 表对象/二进制 Section | PAT/PMT 对象/bytes |
| 104 | `PESPacket`, `PESHeader`, `PESAssembler` | PES bytes / TS payload | PES 对象/bytes |
| 105 | `MediaClock`, `PCR`, `encode_pts`, `decode_pts` | 整数时钟 ticks | PCR/PTS/DTS bytes/value |
| 106 | `SectionPacketizer`, `PESPacketizer` | Section/PES、PID、CC allocator | `TSPacket` 迭代器 |
| 107 | `TSMux`, `MuxConfig`, `ScheduledPacket` | 多 PID packet source | 有序 TS packet 迭代器 |
| 108 | `TSGenerator`, `GeneratorConfig`, `GenerationSummary` | 规范化配置 | 有序 TS packet 迭代器与摘要 |

## 9. 连续性计数器职责边界

- `SPEC-100` 定义 Packet 的 CC 字段语义及用于生成的 `CCAllocator`；其 PCR 字段使用 SPEC-105 唯一的 `PCR` 数据类型，PCR 6-byte 编码算法仍只存在于 SPEC-105。
- `SPEC-106` 在封装单 PID Packet 时调用 allocator，不自行维护第二套计数规则。
- `SPEC-107` 不修改已封装 Packet 的 CC；如需要插入 PCR-only Packet，由 Packetizer/专用 PCR Packet Builder 调用同一个 allocator，并遵循 adaptation-only 使用最近 CC 的规则。
- 输入流 CC 质量统计/告警属于 Observation/Metrics/Analyzer 范畴，不由 `CCAllocator` 完成。
- 测试故障导致的 CC 篡改应放在 Fault Injector（SPEC-204），TS Core 正常生成链路不应内置故障分支。

## 10. 时间语义边界

- `MediaClock` 仅表示 MPEG 媒体时基和 27 MHz/90 kHz 换算。
- `SimulationClock`（SPEC-201）负责实验虚拟时间推进/暂停/倍速。
- `observedAtUtcMs` 来自系统时钟，仅用于运行事件排序和审计。
- Generator 必须把媒体时间由显式配置/时钟推进生成，不得读取 `datetime.now()` 产生 PCR/PTS。

## 11. 配置与依赖约束

- TS Core 公开配置使用 typed dataclass / Enum；API 层可用 Pydantic DTO 做 JSON 校验，但 DTO 不得反向成为 TS Core 的强制运行时依赖。
- 所有公共方法提供类型注解和 docstring。
- 核心逻辑只依赖 Python 标准库；如提议第三方二进制/协议依赖，提交 ADR/变更申请。
- TSDuck 只能在集成测试/交叉验证层调用，不得从 `app.ts.*` 导入或启动。

## 12. 集成完成条件

- 每份模块 Spec 的公开接口在代码中只有一个权威实现。
- 跨模块测试确认 PAT/PMT Section → Packetizer → Mux → Generator 的端到端链路。
- TS 输出经独立自研 parser 和 TSDuck 分析，比较字段有明确映射。
- 所有不一致输出 `ANALYZER_DISAGREEMENT`，不自动偏袒任何一方。
- 生成文件 SHA-256 可复现，并能通过 Artifact 层关联到 `run_id` / `config_hash`。

## 13. 标准参考

规范性依据为适用版本的 ITU-T H.222.0 / ISO/IEC 13818-1；当前参考版本为 H.222.0 (04/2025)。辅助工程参考见包 README 的标准列表。
