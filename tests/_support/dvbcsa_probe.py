"""libdvbcsa DLL availability probe — thin test-support delegate (SPEC-610
§8 / ADR-0011 §5, #126).

The probe implementation is the PRODUCTION module
(:mod:`adapters.dvbcsa._binding`, mirroring the tsduck-probe pattern:
production implementation, tests consume it).  DLL absence → the
``dvbcsa_dll`` conftest fixture skips with a visible reason (tests/README
§6: 缺失不冒绿; ruling §10-2 — CI 上 DLL 测试诚实 NOT RUN).
"""

from __future__ import annotations

from adapters.dvbcsa._binding import (
    ENV_DVBCSA_DLL,
    DvbcsaDllProbe,
    probe_dvbcsa_dll,
)

__all__ = ["DvbcsaDllProbe", "ENV_DVBCSA_DLL", "probe_dvbcsa_dll"]
