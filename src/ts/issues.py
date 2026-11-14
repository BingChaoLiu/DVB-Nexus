"""TS Core shared issue types (TS-CORE-INTEGRATION-CONTRACT §6).

Authoritative definition of the two cross-module issue dataclasses. SPEC-100
declares them by reference ("权威定义见集成契约 §6，本模块不重复定义"); every
ts-core module that reports parse or validation problems imports them from
here instead of redefining local variants (contract §6 "这是概念契约").

Owner: ticket #27 (SPEC-105 implementation wave W1); every other ts-core
ticket imports these classes read-only.

- :class:`ParseIssue` — 解析层问题（带 offset），strict 模式拒绝畸形数据时
  或非 strict 模式收集问题时使用。
- :class:`ValidationIssue` — 语义校验问题（不带 offset），SPEC-100
  ``validate()``、SPEC-108 ``validate_config()`` 的返回类型。

Both are frozen dataclasses: issue reports are immutable observations.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ParseIssue:
    """One problem found while parsing untrusted byte input (contract §6).

    ``offset`` is the byte offset inside the parsed input where the problem
    was detected (``None`` when not attributable). ``severity`` defaults to
    ``"error"``; per contract §7, strict public APIs reject the input
    instead of returning objects that merely carry a ParseIssue.
    """

    code: str
    message: str
    offset: int | None = None
    severity: str = "error"


@dataclass(frozen=True)
class ValidationIssue:
    """One semantic validation finding on an already-parsed object (§6).

    Validation is a semantic-layer judgement and carries no ``offset``;
    ``severity`` defaults to ``"warning"`` and ``field`` optionally names
    the offending object field.
    """

    code: str
    message: str
    severity: str = "warning"
    field: str | None = None
