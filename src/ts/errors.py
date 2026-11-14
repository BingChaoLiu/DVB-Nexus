"""TS Core shared exception registry (TS-CORE-INTEGRATION-CONTRACT §7).

Owner: ticket #27 (SPEC-105 implementation wave W1); every other ts-core
ticket imports these classes read-only. This module carries ONLY the
exception classes and the shared base class defined by contract §7 —
business error-code string constants are NOT defined here; each module spec
owns its own error codes (contract §7 归属约定), and each concrete error
code family maps onto one of the classes below via the §7 mapping table.

Authoritative text: TS-CORE-INTEGRATION-CONTRACT.md §7 "异常类型注册"
(APPROVED 0.5.0, ruling #11). The class set and semantics below are a
verbatim transcription of that section; docstrings carry the §7 description
plus the error-code-family mapping for each class.
"""

from __future__ import annotations


class TSCoreError(Exception):
    """所有 TS Core 可预期错误的基类（契约 §7）。

    Base class of every expected TS Core error. Callers that want to handle
    any ts-core failure catch this; unexpected (non-TSCore) exceptions must
    never be masked by it.
    """


class InvalidPacketError(TSCoreError):
    """Packet 长度、Sync Byte、AFC 或字段边界错误（契约 §7）。

    Error-code family (contract §7 mapping): ``TS_*`` (SPEC-100).
    """


class InvalidSectionError(TSCoreError):
    """Section 长度、语法或 CRC 错误（契约 §7）。

    Error-code families (contract §7 mapping): ``SECTION_*`` (SPEC-102);
    ``PAT_*`` / ``PMT_*`` / ``TABLE_*`` (SPEC-103).
    """


class InvalidPESPacketError(TSCoreError):
    """PES 起始码、Header 长度、PTS/DTS 编码错误（契约 §7）。

    Error-code family (contract §7 mapping): ``PES_*`` (SPEC-104).
    """


class InvalidTimestampError(TSCoreError):
    """时间戳超范围或 PCR extension 非法（契约 §7）。

    Error-code families (contract §7 mapping): ``PCR_*`` / ``PTS_*`` /
    ``CLOCK_*`` (SPEC-105).
    """


class InvalidMuxConfigError(TSCoreError):
    """Mux 码率、PID、周期或容量配置非法（契约 §7）。

    Error codes (contract §7 mapping): ``MUX_INVALID_BITRATE`` /
    ``MUX_INVALID_PACKET_COUNT`` / ``MUX_PID_DUPLICATE_SOURCE`` /
    ``MUX_PID_RATE_OVERCOMMITTED`` / ``MUX_TABLE_PERIOD_INVALID`` /
    ``MUX_PCR_INTERVAL_INVALID``.
    """


class PacketizationError(TSCoreError):
    """SPEC-106 封装过程失败（契约 §7）。

    Error-code family (contract §7 mapping): ``PACKETIZER_*`` (SPEC-106).
    """


class MuxSchedulingError(TSCoreError):
    """Mux 运行期调度失败（契约 §7）。

    Error codes (contract §7 mapping): ``MUX_PACKET_DEADLINE_MISSED`` /
    ``MUX_SLOT_COUNT_MISMATCH`` / ``MUX_SOURCE_EXHAUSTED``.
    """


class GenerationError(TSCoreError):
    """生成配置无法表达或内部生成失败（契约 §7）。

    Error-code family (contract §7 mapping): ``GENERATOR_*`` (SPEC-108).
    """
