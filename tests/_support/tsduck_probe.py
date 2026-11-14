"""TSDuck CLI availability probe for the ``tsduck`` fixture (SPEC-505 §4 → SPEC-308).

Consolidation note (review-fix #3): the fixture probe is a thin delegate to
the PRODUCTION probe (:mod:`adapters.tsduck.version`, ticket #25) — one
implementation, one policy: PATH-first discovery with fallback roots, the
two-tier version-line scan (canonical line first, loose regex on non-log
lines), UTF-8→GBK decode, and both-streams search. The scaffold copy's
divergent loose-regex/first-line behavior was deleted with its logic; the
production validity gate (the version pattern, never the exit code —
ticket #3) now governs the fixture too.

What remains here is the fixture seam only:

- the ``DVB_NEXUS_TSP_PATH`` environment override (SPEC-505 §4/#14: tests
  and non-PATH installs), forwarded to the production probe as the explicit
  override (unresolvable override → structured unavailability, no PATH
  fall-through — the caller configured a location explicitly);
- the frozen fixture-shaped result (:class:`TSDuckProbe`) — frozen
  dataclasses make per-executable caching immutable sharing, not mutable
  fixture state (SPEC-505 §4 隔离纪律).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from adapters.tsduck.version import TSDuckProbeResult, TSDuckVersionProbe

#: Env var for an explicit tsp executable override (tests / non-PATH installs).
TSP_ENV_OVERRIDE = "DVB_NEXUS_TSP_PATH"

#: Dedicated fixture probe instance (production implementation). Successful
#: probes are cached per resolved executable; failures are never cached —
#: the production cache discipline (ADR-0005 decision 6), so a transient
#: failure cannot poison the fixture for later tests.
_FIXTURE_PROBE = TSDuckVersionProbe()


@dataclass(frozen=True)
class TSDuckProbe:
    """Immutable probe result yielded by the ``tsduck`` fixture."""

    available: bool
    executable: str | None
    version: str | None
    raw_version_line: str | None
    detail: str


def _to_fixture_shape(result: TSDuckProbeResult) -> TSDuckProbe:
    """Project the production result onto the fixture's flat shape.

    ``version``/``executable``/``raw_version_line`` come from the found
    payload only; unavailable results carry ``None`` and the production
    ``detail`` (display-only diagnostics, GBK content never parsed).
    """
    version = result.version
    return TSDuckProbe(
        available=result.available,
        executable=str(version.executable) if version is not None else None,
        version=version.version if version is not None else None,
        raw_version_line=version.raw_version_line if version is not None else None,
        detail=result.detail,
    )


def probe_tsp(override: str | None = None) -> TSDuckProbe:
    """Probe TSDuck CLI availability through the production probe.

    ``override`` defaults to the ``DVB_NEXUS_TSP_PATH`` environment value.
    Production semantics apply unchanged: an explicit override that does not
    resolve fails immediately with ``not_installed`` (no silent PATH
    fall-through); a resolvable-but-unusable override falls through to
    PATH/fallback candidates with most-informative-wins failure aggregation.
    """
    explicit = override if override is not None else os.environ.get(TSP_ENV_OVERRIDE)
    return _to_fixture_shape(_FIXTURE_PROBE.probe(override=explicit or None))
