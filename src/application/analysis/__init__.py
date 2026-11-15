"""Application analysis package — the minimal semantic-layer analysis
bridge (ticket #58, 裁定 A).

Turns produced TS artifacts into ``ts.*`` observation events over the
real ``ts`` semantic layer: :mod:`application.analysis.parser` is the
pure facts half; :mod:`application.analysis.service` normalizes the
facts into SPEC-301 envelopes and publishes them through the SPEC-300
§12 producer face. The MVP scope is the four fault-signal families of
the fault lab (PAT presence / PMT CRC / PAT↔PMT mapping / CC sequence)
— not a SPEC-308 full analyzer. The REST-facing analyze route stays
frozen (SPEC-500 §4.6, 501) — the 裁定 B in-process anchor means callers
drive this service directly (the composition root exposes it on the
production stack).
"""

from application.analysis.parser import (
    BatchFact,
    ContinuityErrorFact,
    PatMissingFact,
    PatSectionFact,
    PmtSectionFact,
    analyze_transport_stream,
)
from application.analysis.service import (
    CONFIDENCE,
    PRODUCER_ID,
    PRODUCER_VERSION,
    SOURCE,
    AnalysisReport,
    AnalysisService,
)

__all__ = [
    "CONFIDENCE",
    "PRODUCER_ID",
    "PRODUCER_VERSION",
    "SOURCE",
    "AnalysisReport",
    "AnalysisService",
    "BatchFact",
    "ContinuityErrorFact",
    "PatMissingFact",
    "PatSectionFact",
    "PmtSectionFact",
    "analyze_transport_stream",
]
