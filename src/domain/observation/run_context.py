"""SPEC-003 section 2.2 RunContext.

Describes the run a record belongs to. Kept verbatim per the #12 ruling:
``RunContext`` survives the RuntimeEvent envelope abolition untouched — its
``sequence_number`` is the run's own sequence, NOT the platform event total
order (that is ``journal_seq``, gateway-stamped per session, ADR-0006
decision 2), and ``started_at_utc_ms`` is operational wall-clock metadata only.
``LIVE`` is a future mode; MVP does not implement it.

Home package: ``domain.observation`` is the unified exchange interface
(ADR-0005 decision 4) and every run-scoped record (Observation, Metric,
TSArtifact, Diagnosis) carries ``run_id`` referencing this context — so the
context travels with the exchange vocabulary, reachable by diagnosis too.
"""

from enum import Enum
from typing import Optional

from domain._base import DomainModel
from domain.observation.ids import Identifier, OpaqueEntityId


class RunMode(str, Enum):
    """Execution mode (SPEC-003 section 2.2). ``LIVE`` stays out — MVP has no live mode."""

    SANDBOX = "sandbox"
    LIVE = "live"


class Fidelity(str, Enum):
    """Data-production fidelity tiers (SPEC-003 section 2.2, CONTEXT.md 保真级).

    ``SIM_STATE`` (state-level) and ``SIM_TS`` (real TS bytes) are two runtimes
    of one system; ``LIVE`` is the future live mode.
    """

    SIM_STATE = "SIM_STATE"
    SIM_TS = "SIM_TS"
    LIVE = "LIVE"


class RunContext(DomainModel):
    """SPEC-003 section 2.2 ``RunContext``."""

    run_id: OpaqueEntityId
    session_id: OpaqueEntityId
    topology_id: Identifier
    topology_revision: int
    #: Run-internal monotonic sequence; never the platform event order
    #: (SPEC-003 section 2.3 pointer, ADR-0006 decision 2).
    sequence_number: int
    mode: RunMode
    fidelity: Fidelity
    #: UTC Unix epoch milliseconds (wall clock, operational metadata only).
    started_at_utc_ms: int
    generator_version: Optional[str] = None
    config_hash: Optional[str] = None
    seed: Optional[int] = None


__all__ = ["Fidelity", "RunContext", "RunMode"]
