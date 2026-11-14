---
spec_id: SPEC-103
title: PAT and PMT Tables
version: 0.5.0
status: APPROVED
phase: MVP
owner: TS Core
priority: P0
depends_on: [SPEC-100, SPEC-101, SPEC-102, SPEC-004]
requirements: [REQ-TS-103-001, REQ-TS-103-002, REQ-TS-103-003, REQ-TS-103-004, REQ-TS-103-005, REQ-TS-103-006]
---

# SPEC-103 — PAT / PMT

## 1. 目标

实现 MPEG-2 Program Association Table（PAT）和 Program Map Table（PMT）的数据模型、Section 编码/解码、字段验证和 Generator 构建接口。它们是 MVP Service/PID 关系可见性的基础。

## 2. 范围

**In Scope：** PAT `table_id=0x00`、PMT `table_id=0x02`；Long-form Section；CRC；program loop / ES loop；PID 关联；version/section 字段；单 Section 生成与多 Section 解析。  
**Out of Scope：** CAT、NIT、SDT、EIT、descriptor 详细语义、完整 DVB SI 表库、动态 PMT 版本切换调度策略（发送周期交 Mux 配置）。

## 3. PAT 结构要求

- PAT 固定出现在 PID `0x0000`。
- `table_id=0x00`，Long-form Section，CRC 必须存在。
- `table_id_extension` 对应 `transport_stream_id`。
- `version_number` 5 bits；`current_next_indicator` 1 bit。
- `section_number` / `last_section_number` 8 bits。
- 每个 `program_number` 项含 16-bit program_number 和 13-bit `program_map_PID`（高位 reserved bits 按标准编码）。
- `program_number=0` 项表示 network_PID（NIT PID）；它不是一个 PMT 项。
- 普通节目项的 `program_number` 非 0，映射到相应 PMT PID。
- PAT 的 `section_length` 按实际 program loop 计算；`section_length = 9 + 4 * program_entry_count`（其中每个 entry 为 4 bytes，network_PID 项也计 1 个 entry）。单 Section `section_length` 不得超过 1021 bytes；MVP 生成器超过上限应显式失败，不自动悄悄拆分。

## 4. PMT 结构要求

- PMT 固定使用 `table_id=0x02`，通常通过 PAT 项中的 `program_map_PID` 找到。
- `table_id_extension` 为 `program_number`。
- `PCR_PID` 指示承载该 Program PCR 的 PID；如使用独立 PCR PID，该 PID 也必须在生成的 TS 中得到正确处理。
- `program_info_length` 后是 Program-level descriptor loop。
- 每个 Elementary Stream 项包括 `stream_type`、`elementary_PID`、`ES_info_length` 和 descriptor loop。
- `program_info_length` / `ES_info_length` 为 12-bit length field，所有 loop 长度和边界必须验证。
- MVP 生成器可以只生成空 descriptor loop；Parser 必须保留 descriptor bytes，暂不要求解释每个 descriptor。
- PMT 的 `section_length` 需要根据固定字段、descriptor bytes 和 ES loop 精确计算：`13 + program_descriptors_length + Σ(5 + es_descriptors_length)`；单 Section `section_length` 不得超过 1021 bytes。不得手工常量加错。

## 5. 数据模型

```python
@dataclass(frozen=True)
class PATProgram:
    program_number: int
    program_map_pid: int  # program_number=0 时字段语义为 network_pid

@dataclass(frozen=True)
class PATSection:
    transport_stream_id: int
    version_number: int
    current_next_indicator: bool
    section_number: int
    last_section_number: int
    programs: tuple[PATProgram, ...]

@dataclass(frozen=True)
class ElementaryStream:
    stream_type: int
    elementary_pid: int
    descriptors: bytes = b""

@dataclass(frozen=True)
class PMTSection:
    program_number: int
    version_number: int
    current_next_indicator: bool
    section_number: int
    last_section_number: int
    pcr_pid: int
    program_descriptors: bytes
    streams: tuple[ElementaryStream, ...]
```

禁止对 `program_number=0` 创建 PMT；`PATProgram.program_map_pid` 对这个特殊项必须在 API 文档中说明是 network_PID。

## 6. 公共接口

```python
class PATBuilder:
    def build(self, table: PATSection) -> PSISection: ...

class PMTBuilder:
    def build(self, table: PMTSection) -> PSISection: ...


def parse_pat(section: PSISection) -> PATSection: ...
def parse_pmt(section: PSISection) -> PMTSection: ...

def parse_pat_sections(sections: list[PSISection]) -> "PATTable": ...
def parse_pmt_sections(sections: list[PSISection]) -> "PMTTable": ...
```

`PATTable` / `PMTTable` 可以是逻辑聚合对象，必须保留每个 section 的 section_number、version、current_next 信息，以便发现缺失 section 或版本混合。

## 7. 编码和校验规则

- PAT/PMT 必须使用 SPEC-102 Section framing 和 SPEC-101 CRC。
- PAT `section_length` 按实际编码长度累加：transport_stream_id(2) + version/current(1) + section_number(1) + last_section_number(1) + program loop（每项 4 bytes）+ CRC(4)，即 `9 + 4 * program_entry_count`（与 §3 公式一致）；不允许在代码中依赖未说明的魔法数。
- PMT 长度由 program_number(2)、version/current、section_number、last_section_number、PCR_PID(2)、program_info_length(2)、program descriptor bytes、ES entries（5-byte fixed prefix + descriptors）、CRC(4) 组成。
- 所有 reserved bits 编码为标准规定的常量值；Parser 可保留原始值并报告不符合标准的 issue。
- version_number 范围 0..31；section_number 与 last_section_number 范围 0..255，且 section_number ≤ last_section_number。
- PID 范围 0..0x1FFF；table-specific profile 需进一步拒绝不允许的 PID 用途（例如 PMT PID 不得使用 PAT 固定 PID 或 Null PID）。
- `current_next_indicator=0` 表示 next table，不应误当作当前生效表。
- 解析多 Section 时必须以 program/table extension、version、current_next 和 last_section_number 识别同一版本集合；不能将不同版本的 sections 拼为一张表。
- MVP Builder 支持单 Section；若超出表上限，抛 `TABLE_SECTION_TOO_LARGE`。多 Section 构建可作为 P1，但 Parser 需支持合法多 Section 输入。

## 8. PID 关联校验

提供独立 validator 检查：

1. PAT 位于 PID 0x0000。
2. PAT 每个非 0 program_number 映射至有效 PMT PID。
3. PMT 的 `program_number` 与 PAT 项匹配。
4. PMT 解析出的 Elementary PID 和 PCR PID 不应违反本项目的 PID 使用策略。
5. 同一 Program 的 ES PID 不应重复（除非后续标准 profile 明确许可）。
6. PCR_PID 不等于 Null PID（项目收紧规则：H.222.0 §2.4.4.8 明确允许无 PCR 关联的私有流 program 将 PCR_PID 置 0x1FFF；MVP 生成器校验按项目规则执行，validator 文案不得将其表述为标准断言）；如果 PCR PID 是某个 ES PID，则该 PID Packet 必须能够容纳/承载所需 PCR。
7. 不存在的 PMT 或不匹配 program_number 应产生诊断 issue，而不是用默认 PMT 补齐。

## 9. 错误码

- `PAT_TABLE_ID_INVALID`
- `PAT_PID_INVALID`
- `PAT_PROGRAM_ENTRY_TRUNCATED`
- `PAT_PROGRAM_NUMBER_INVALID`
- `PAT_PMTPID_INVALID`
- `PMT_TABLE_ID_INVALID`
- `PMT_FIXED_HEADER_TRUNCATED`
- `PMT_PROGRAM_INFO_LENGTH_INVALID`
- `PMT_ES_LOOP_TRUNCATED`
- `PMT_ES_INFO_LENGTH_INVALID`
- `PMT_PID_INVALID`
- `TABLE_VERSION_MISMATCH`
- `TABLE_SECTION_MISSING`
- `TABLE_SECTION_TOO_LARGE`
- `PAT_PMT_PROGRAM_MISMATCH`

## 10. 测试规格

- 构造最小 PAT：单节目；含/不含 program_number=0 NIT entry。
- 解析真实 PAT/PMT golden fixture；验证 CRC 和全部字段。
- PAT/PMT 编码→解析 round-trip。
- version_number 0、31；current_next 0/1；section number 边界。
- program_number=0 特殊项，不生成 PMT。
- PAT program loop 截断和 PMT descriptor/ES loop 长度越界。
- PAT 映射 PMT PID、PMT program_number 对照。
- 同一 program 的多 ES PID 和 PCR_PID 映射。
- CRC 损坏、table_id 错误、Section 长度溢出。
- 多 Section 缺号、乱序、版本混合和 last_section_number 不一致。
- 超过单 Section 上限时 Builder 明确拒绝。

## 11. 验收标准

- `REQ-TS-103-001`：PAT 编码/解析字段符合 H.222.0。
- `REQ-TS-103-002`：PMT 编码/解析字段符合 H.222.0。
- `REQ-TS-103-003`：PAT/PMT CRC、version、section number 正确。
- `REQ-TS-103-004`：program_number=0 和 PAT→PMT→ES PID 关联正确。
- `REQ-TS-103-005`：畸形 length/loop/descriptor 不发生越界。
- `REQ-TS-103-006`：多 Section 聚合不会混合不同 table version。

## 12. MVP 限制

- MVP 生成器默认一个 Program、一张 PAT Section、一张 PMT Section。
- 空 descriptor loop 是默认；不表示平台已支持完整 DVB descriptor 生态。
- 暂不实现 CAT/ECM/EMM、NIT/SDT/EIT、LCN/FastScan。

## 13. 交付要求

建议文件：`ts/tables/pat.py`、`ts/tables/pmt.py`、`ts/tables/table_validation.py`；测试：`tests/unit/ts/test_pat.py`、`test_pmt.py`。提交至少一份由本项目 Builder 生成、可被 TSDuck 识别的 `.ts` fixture 的表解码结果。

## 14. 参考

- ITU-T H.222.0 (04/2025), PAT/PMT syntax。
- TSDuck User Guide `tsanalyze` 和 PSI/SI 分析：<https://tsduck.io/docs/tsduck.html>。
