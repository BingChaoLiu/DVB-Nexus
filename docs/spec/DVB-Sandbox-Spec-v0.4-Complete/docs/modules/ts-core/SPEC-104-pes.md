---
spec_id: SPEC-104
title: MPEG-2 PES Packet Core
version: 0.5.1
status: APPROVED
phase: MVP
owner: TS Core
priority: P0
depends_on: [SPEC-100, SPEC-105, SPEC-004]
requirements: [REQ-TS-104-001, REQ-TS-104-002, REQ-TS-104-003, REQ-TS-104-004, REQ-TS-104-005, REQ-TS-104-006]
---

# SPEC-104 — PES

## 1. 目标

实现常见 MPEG-2 PES Packet 的头部解析、序列化、PTS/DTS 字段处理、PES length 校验和按 TS Payload 重组。它为 TS Generator 提供可供 Analyzer 识别的 PES 封装；不负责生成合法音视频 Elementary Stream。

## 2. 范围

**In Scope：** 常见带标准 `10` 前缀 PES optional header 的音视频/私有数据 PES；start code prefix、stream_id、PES_packet_length、flags、header_data_length、PTS/DTS、payload。TS 分片重组由 `PESAssembler` 完成。  
**Out of Scope：** Program Stream pack/system headers；所有特殊 stream_id 的专属短格式；H.264/H.265/AAC 编码；字幕语义；解码和播放；PES scrambling/CA。

## 3. PES 结构与约束

- Start code prefix 固定为 `00 00 01`。
- 随后为 8-bit `stream_id` 和 16-bit `PES_packet_length`（big-endian）。
- 本 Spec 支持的标准 optional-header 路径在 length 后包括 3 bytes 固定控制字段：`'10'` marker、PES flags、`PES_header_data_length`。
- MVP 支持 PES scrambling control 原值保留（Generator 默认 clear），并支持 PES priority、data alignment、copyright、original/copy 位。
- MVP 只解释 PTS/DTS 时间戳；ESCR、ES_rate、DSM trick mode、additional copy info、PES CRC、PES extension 等其它 optional feature flags 若置位，Parser 必须返回 `PES_OPTIONAL_FIELD_UNSUPPORTED`，不可把其 bytes 错当成 PTS 或 Payload。
- `PES_header_data_length` 必须覆盖本次出现的所有可选 Header 字节；PTS only 占 5 bytes，PTS+DTS 占 10 bytes。MVP 不允许在 PTS/DTS 之外携带未定义的 raw optional bytes。
- `PTS_DTS_flags=00`：无 PTS/DTS；`10`：有 PTS；`11`：有 PTS+DTS；`01` 保留/非法。
- PTS/DTS 各 33 bits，90 kHz 时基，采用 marker-bit 分段编码。
- `PES_packet_length` 统计紧随该 16-bit 字段之后的 bytes（固定 optional-header 控制字节、header data 和 PES payload）。
- `PES_packet_length=0` 在标准允许的特定视频 PES 场景中可表示未指定长度；不得对所有 stream_id 无条件允许。生成配置必须显式指定 `packet_length_mode`。
- 对非零长度的标准 PES，解析器必须确保 declared length 与实际组装字节数一致。
- 由于特殊 `stream_id` 有不同 Header 语法，本模块默认使用 `StandardPES` profile；不支持的 special stream_id 应显式返回 `PES_STREAM_ID_PROFILE_UNSUPPORTED`，不得误解析成普通 Header。

## 4. 数据模型

```python
@dataclass(frozen=True)
class PESHeader:
    stream_id: int
    pes_packet_length: int  # 0..65535
    pts: int | None = None  # 33-bit, 90 kHz
    dts: int | None = None  # 33-bit, 90 kHz
    pes_scrambling_control: int = 0
    pes_priority: bool = False
    data_alignment_indicator: bool = False
    copyright: bool = False
    original_or_copy: bool = False

@dataclass(frozen=True)
class PESPacket:
    header: PESHeader
    payload: bytes
```

MVP 不提供 raw optional header 字段：遇到本模块未解释的 optional feature flags 一律报 `PES_OPTIONAL_FIELD_UNSUPPORTED`（见 §3），PTS/DTS 只存在于 typed 字段，不存在 raw/typed 重复编码问题。

## 5. 公共接口

```python
def parse_pes(data: bytes, *, profile: str = "standard") -> PESPacket: ...
def serialize_pes(packet: PESPacket, *, packet_length_mode: str = "auto") -> bytes: ...

class PESAssembler:
    def __init__(self, pid: int, *, max_buffer_bytes: int) -> None: ...
    def push(self, packet: TSPacket) -> list[PESPacket]: ...
    def reset(self, reason: str) -> None: ...
    def flush(self) -> list[ParseIssue]: ...
```

`PESAssembler` 依据 TS `payload_unit_start_indicator=1` 判断新的 PES 起始，不解析 TS Packet 之外的任意偏移。它必须检查 Packet PID 与构造参数一致。

## 6. PTS/DTS 处理

- 编码/解码委托 SPEC-105 的时间戳原语，或通过该模块明确公开的 `encode_pts/decode_pts`；不能出现两份算法。
- PTS only 使用正确的 4-bit prefix；PTS+DTS 时 PTS 与 DTS 各自使用不同 prefix。
- 所有 marker bit 必须为 1；Parser 检查 marker bit。
- `PTS_DTS_flags=01` 必须报错。
- PTS/DTS 值在 0..(2^33-1)；超范围拒绝，不静默 mask。
- 时间比较必须考虑 33-bit wraparound；不得简单用普通整数大小比较判断跨回绕的先后关系。

## 7. PESAssembler 行为

1. PUSI=1 时表示此 TS Payload 从一个 PES Packet 开始；如之前有 incomplete PES，按其 declared length/zero-length profile 决定完成或报 truncated，再开始新 PES。
2. PUSI=0 时只允许追加到当前 PES continuation；没有活动 PES 时丢弃并产生 issue，不得把中间字节猜成 PES start。
3. `pes_packet_length != 0` 时，Assembler 累积到准确总长度（6 + pes_packet_length）后输出 PES；后续同 Packet/TS payload bytes 的处理需按当前 Packetized PES profile 明确，不允许丢失。
4. `pes_packet_length=0` 时，在下一个 PUSI 或 EOF 作为边界；必须设置 `max_buffer_bytes` 防止无限增长。
5. TS Packet 的 adaptation field 不属于 PES payload；Assembler 只能消费 TSPacket.payload。
6. 收到 TEI=1、PID mismatch 或明确 discontinuity 时，应按配置中断/丢弃当前 PES，并给出 evidence issue。
7. Payload stuffing 不能被误认作 PES 内容；Packetizer 应通过 Adaptation Field 做尾部填充，PESAssembler 对收到的字节不自行去掉任意 `0xFF`。

## 8. 生成端要求

- MVP `analysis_only` Profile 可使用确定性测试 payload，不承诺解码。
- 如果 PMT 宣告 H.264/H.265/AAC stream_type，而 payload 不是对应合法码流，必须在 Generator 配置和 UI 中标识为 synthetic/test payload；不能宣称 playback-ready。
- PES packet length 自动计算时必须包含 optional-header bytes，不包含 6-byte start-code/stream-id/length 前缀。
- 超过 65535 bytes 时按配置拒绝或采用标准允许的 zero-length video PES profile；不得自动截断。

## 9. 错误码

- `PES_START_CODE_INVALID`
- `PES_HEADER_TRUNCATED`
- `PES_STREAM_ID_PROFILE_UNSUPPORTED`
- `PES_FLAGS_RESERVED`
- `PES_HEADER_DATA_LENGTH_INVALID`
- `PES_OPTIONAL_FIELD_UNSUPPORTED`
- `PES_PTS_DTS_FLAGS_INVALID`
- `PES_TIMESTAMP_MARKER_INVALID`
- `PES_PACKET_LENGTH_MISMATCH`
- `PES_LENGTH_ZERO_NOT_ALLOWED`
- `PES_BUFFER_LIMIT_EXCEEDED`
- `PES_CONTINUATION_WITHOUT_START`
- `PES_TRUNCATED_AT_NEW_START`
- `PES_TRUNCATED_AT_EOF`

## 10. 测试规格

- 最小 standard PES，无 PTS/DTS。
- PTS only；PTS+DTS；时间戳 marker bit 全部验证。
- PTS/DTS 值 0、1、2^33-1，拒绝负数和 2^33。
- packet_length 自动计算和 declared length parse。
- packet_length=0 的允许/拒绝 profile。
- special stream_id 明确拒绝或有独立 profile，不误解析。
- PES Header 在一个 TS Packet、跨两个/多个 Packet。
- 一个 TS payload 含 PES 完成后额外字节的策略测试。
- 新 PUSI 到来时前一 PES 的 incomplete 处理。
- EOF、TEI、discontinuity、buffer cap 和 PID mismatch。
- serialize→parse round-trip。

## 11. 验收标准

- `REQ-TS-104-001`：支持的 PES Header 字段解析/编码准确。
- `REQ-TS-104-002`：PTS/DTS 编码符合 33-bit 90 kHz 格式，marker 检查正确。
- `REQ-TS-104-003`：PES_packet_length 语义和边界正确。
- `REQ-TS-104-004`：PESAssembler 正确处理 PUSI、跨包和边界。
- `REQ-TS-104-005`：异常输入不会越界或导致无界内存增长。
- `REQ-TS-104-006`：测试 payload 明确标记为 analysis_only，不虚构可播放能力。

## 12. 交付要求

建议文件：`ts/pes.py`、`ts/pes_assembler.py`；时间戳编码从 SPEC-105 复用。测试覆盖 header、timestamps、packet length、PES spanning packets。

## 13. 参考

- ITU-T H.222.0 (04/2025), PES packet syntax。
- 时间戳格式必须以 H.222.0 正式文本为最终依据。
