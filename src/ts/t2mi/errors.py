"""T2-MI error family (SPEC-600 §8, ticket #122).

``T2miError`` extends the TS Core shared base (:class:`ts.errors.TSCoreError`)
so existing ``except TSCoreError`` handlers keep working, while the new
``T2MI_*`` error-code family gets its own class instead of overloading a
TS-100-era class whose contract §7 mapping is scoped to ``TS_*`` codes.

Error-code string constants are module-owned per the TS Core integration
contract §7 归属约定 (packet codes in :mod:`ts.t2mi.packet`, builder codes
in :mod:`ts.t2mi.builder`); this module carries only the exception class.
Every raise site follows the ``"CODE: message"`` head convention so
``TSCoreError.code`` extraction works.
"""

from __future__ import annotations

from ts.errors import TSCoreError

__all__ = [
    "T2miError",
]


class T2miError(TSCoreError):
    """所有 T2-MI 可预期错误的基类（SPEC-600 §8）。

    Carries every ``T2MI_*`` error code family:

    - packet field guards (``T2MI_PACKET_*``, :mod:`ts.t2mi.packet`);
    - encapsulator config/build guards (``T2MI_CONFIG_*`` /
      ``T2MI_BUILD_*``, :mod:`ts.t2mi.builder`).

    Parse-side degradation faces (CRC-32 failure → marked bad packet,
    unknown packet_type → explicit unknown state, truncated tail →
    explicit truncation state) are *states on the parse result*, not
    exceptions (SPEC-600 §8: 显式标记继续解析, 静默丢弃为零).
    """
