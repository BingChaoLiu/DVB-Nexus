---
spec_id: SPEC-102
title: PSI Section Framing and Assembly
version: 0.4.0
status: DRAFT
phase: MVP
owner: TS Core
priority: P0
depends_on: [SPEC-100, SPEC-101, SPEC-004]
requirements: [REQ-TS-102-001, REQ-TS-102-002, REQ-TS-102-003, REQ-TS-102-004, REQ-TS-102-005, REQ-TS-102-006]
---

# SPEC-102 — PSI Section

## 1. 目标

实现 MPEG-2 PSI Section 的通用 framing、解析、序列化、长度校验、CRC 策略和 TS Packet 到 Section 的分片重组。PAT/PMT 的表专属语义由 SPEC-103 实现。

## 2. 范围

### In Scope

- 3-byte Section Header 解析。
- `table_id`、`section_syntax_indicator`、`private_indicator`、reserved bits、`section_length`。
- Long-form Section 公共头字段解析：`table_id_extension`、`version_number`、`current_next_indicator`、`section_number`、`last_section_number`。
- 可配置的 CRC policy。
- 完整 Section 的序列化和最大长度策略。
- SectionAssembler：从指定 PID 的 TS Packet Payload 重组一个或多个 Section，处理 PUSI 与 pointer_field。
- 部分输入、截断输入、超长输入和 discontinuity 的显式处理。

### Out of Scope

- PAT/PMT 具体循环字段。
- DVB SI 特有表语义和 descriptor 解码。
- 表版本集合的跨 Section 缓存/完整表重建（可以作为后续 TableRepository）。
- Section 传输的 CC 统计报告（由 Observation/Metrics 管理）。

## 3. Section 基础格式

- Section 前 3 bytes：`table_id`（8 bits）、`section_syntax_indicator`/`private_indicator`/reserved bits/`section_length`。
- `section_length` 表示紧随这 3-byte Header 之后的总字节数，不包含最前面的 3 bytes。
- wire 字段是 12 bits；通用 parser 必须通过 `SectionPolicy.max_section_length` 限制实际允许值，不能将 wire 可表达最大值误当成所有 table 的合法最大值。
- Long-form（`section_syntax_indicator=1`）在后续公共字段中包含 extension、version/current、section number、last section number；是否含 CRC 由 table policy 决定，但 PAT/PMT 必须含 CRC。
- Short-form 不应仅凭 `section_syntax_indicator=0` 就推断“没有 CRC”；DVB TOT 等有 table-specific 例外。因此 `crc_policy` 必须由 table profile 决定，不能只看 SSI 位。

## 4. 数据模型

```python
from dataclasses import dataclass
from enum import Enum

class CrcPolicy(str, Enum):
    REQUIRED = "required"
    ABSENT = "absent"
    OPTIONAL = "optional"

@dataclass(frozen=True)
class SectionPolicy:
    max_section_length: int
    crc_policy: CrcPolicy
    require_long_syntax: bool | None = None
    expected_table_id: int | None = None

@dataclass(frozen=True)
class PSISection:
    table_id: int
    section_syntax_indicator: bool
    private_indicator: bool
    section_length: int
    raw_bytes: bytes
    table_id_extension: int | None = None
    version_number: int | None = None
    current_next_indicator: bool | None = None
    section_number: int | None = None
    last_section_number: int | None = None
    crc_value: int | None = None
```

`raw_bytes` 保留完整 Section（包含 CRC 字段时也包含 CRC）。解析后的派生字段不得与原始 bytes 不一致；序列化应从字段构建，或对 immutable raw section 原样输出。

## 5. 公共接口

```python
def parse_section(data: bytes, policy: SectionPolicy) -> PSISection: ...

def serialize_section(section: PSISection, policy: SectionPolicy) -> bytes: ...

def section_total_size(first_three_bytes: bytes, *, max_section_length: int) -> int: ...

class SectionAssembler:
    def __init__(self, pid: int, policy_resolver) -> None: ...
    def push(self, packet: TSPacket) -> list[PSISection]: ...
    def reset(self, reason: str) -> None: ...
    def flush(self) -> list[ParseIssue]: ...
```

`policy_resolver(table_id)` 返回 SectionPolicy。Assembler 只处理配置的一个 PID；一个 PID 对应多个 table_id 时按 table_id 选择 policy。

## 6. Parsing 与 Assembly 逻辑

### 6.1 单个 Section

1. 输入不足 3 bytes 时 `TRUNCATED_SECTION_HEADER`。
2. 解析 12-bit section_length，校验不超过 policy.max_section_length。
3. 总长度为 `3 + section_length`；输入必须至少达到总长度。
4. 如传入 buffer 含额外 bytes，单 Section parser 只解析首个 Section，并返回 consumed length 的扩展 API，或拒绝 trailing bytes；行为必须在实现中固定并测试。
5. 对 Long-form Section 验证公共头最小长度和字段完整性。
6. 按 CRC policy 调用 SPEC-101；REQUIRED 缺 CRC/CRC 错误必须拒绝，OPTIONAL 依据表 profile 明确处理。
7. 对 reserved bits 可记录 ValidationIssue；strict profile 可拒绝。

### 6.2 TS 到 Section 的重组

- Packet 必须携带 Payload；没有 Payload 时不向 assembler 提供数据。
- 对 PSI payload，PUSI=1 时 Payload 第一个 byte 是 `pointer_field`；Section 起始位置是 pointer byte 后 `pointer_field` 个 byte 的位置。
- `pointer_field` 前的 bytes 可用于完成上一 Packet 中尚未完成的 Section；若当前不存在 partial Section，则这些 bytes 按 stuffing/未使用前缀处理，不得误认为新 Section。
- pointer 指向的位置开始一个新的 Section；若剩余 payload 足够，可继续解析同一 Packet 中后续完整 Section。
- PUSI=0 表示 payload 从已有 Section continuation 开始；若没有 partial Section，则不能把该 payload 任意位置当成 Section 起点。
- Section 结束后 `0xFF` stuffing 必须被识别为 stuffing，不再尝试解析成 table_id。
- 发现 Packet 的 `discontinuity_indicator=1` 时必须丢弃当前 partial Section 并重置；CC gap 的处理由调用者的传输连续性检查器通知 assembler reset，不得在未检测 CC 时悄悄拼接。
- 如果同一 payload 包含多个 Section，Assembler 按顺序逐个输出；未完成部分保留到下一 Packet。
- `flush()` 在输入结束时对未完成 Section 报告 truncated，不得自动补 0/0xFF 伪造完整表。

## 7. 长度与 CRC 策略

- Section header 的 12-bit 字段范围为 0..4095。
- 具体 table 的最大 section_length 由 profile 决定。PAT/PMT 使用其标准 table 上限，不得依赖通用 parser 的宽松上限。
- CRC 是 Section 级校验，不等同于 TS Packet 的任何字段校验。
- CRC 字段在 Section 末尾，32-bit big-endian。
- Parser 必须能区分 `CRC_NOT_PRESENT`、`CRC_INVALID`、`SECTION_LENGTH_INVALID` 等不同问题。

## 8. 错误码

| Code | 说明 |
|---|---|
| `SECTION_HEADER_TRUNCATED` | 不足 3 bytes |
| `SECTION_LENGTH_EXCEEDS_POLICY` | section_length 超过指定表策略 |
| `SECTION_BODY_TRUNCATED` | bytes 不足以达到 section_total_size |
| `SECTION_LONG_HEADER_TRUNCATED` | Long-form 公共头不完整 |
| `SECTION_CRC_MISSING` | 必须有 CRC 但缺失 |
| `SECTION_CRC_INVALID` | CRC remainder 非 0 |
| `SECTION_TABLE_ID_UNEXPECTED` | table_id 与 policy 不匹配 |
| `SECTION_POINTER_FIELD_INVALID` | pointer_field 超过 payload 剩余长度 |
| `SECTION_CONTINUATION_WITHOUT_START` | PUSI=0 但没有活动 Section |
| `SECTION_DISCARDED_ON_DISCONTINUITY` | discontinuity 导致 partial Section 丢弃 |
| `SECTION_TRUNCATED_AT_EOF` | flush 时仍有未完成 Section |

## 9. 测试规格

- Short/Long Section Header 基本解析。
- `section_length` 0、最小合法、profile 最大值、超过 profile 和超过 wire 范围。
- Long-form 公共头字段解析和 round-trip。
- CRC required/absent/optional 三类 policy。
- PAT/PMT 样例完整 Section 解析。
- 一个 Section 恰好在一个 Packet 内、跨 2 个/多个 Packet、边界在 payload 最后一个 byte。
- PUSI=1 pointer_field=0。
- PUSI=1 pointer_field>0 且先完成上一 Section。
- 一个 Packet 中两个完整 Section。
- PUSI=0 continuation。
- 无 partial 时的 PUSI=0、pointer_field 越界、stuffing、EOF partial。
- discontinuity 后 partial 必须清空。
- 任意畸形长度不得造成越界或无限循环。

## 10. 验收标准

- `REQ-TS-102-001`：Section Header 和长度解释正确。
- `REQ-TS-102-002`：Long-form 公共字段正确解析/序列化。
- `REQ-TS-102-003`：CRC policy 与 SPEC-101 集成正确。
- `REQ-TS-102-004`：SectionAssembler 正确处理 PUSI/pointer_field/跨包/多 Section。
- `REQ-TS-102-005`：不完整和 discontinuity 的恢复行为可预测且有事件。
- `REQ-TS-102-006`：非法长度和畸形 payload 具有边界安全性。

## 11. 非目标

不在本模块中实现 PAT/PMT 业务语义、DVB descriptor 树、EIT/NIT/SDT 具体解析或实时 SI 表缓存。

## 12. 交付要求

建议文件：`section.py`、`section_assembler.py`、`section_errors.py`；测试覆盖 parser、assembler、CRC 集成。必须附带一个跨 Packet 的 Section fixture 和对应 packet index 说明。

## 13. 参考

- ITU-T H.222.0 (04/2025), PSI section syntax。
- ETSI EN 300 468（DVB SI table syntax；本模块仅提供通用 Section framing）。
- PUSI/pointer_field 的辅助解释：<https://www.rfc-editor.org/rfc/rfc4259>。
