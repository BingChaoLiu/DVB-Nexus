"""SPEC-003 section 2.7 TSArtifact.

Metadata for an asset file (generated/faulted TS, report, log, evidence).
Data only: retention/cleanup/access/verification policy is deferred (SPEC-003
section 6); path safety and content addressing live in storage (SPEC-503).

The model is deliberately filesystem-blind — ``relative_path`` is a plain
string that must stay relative to the application-managed artifact root;
absolute paths are never exposed to API clients (SPEC-003 section 2.7), and
the import-linter contract forbids domain from importing pathlib/os anyway.

Home package: artifacts are the evidence carriers of the observation chain
(CONTEXT.md 证据: observation -> PID + packet index + artifact).
"""

from enum import Enum
from typing import Literal, Optional

from domain._base import DomainModel
from domain.observation.ids import OpaqueEntityId


class ArtifactKind(str, Enum):
    """Asset kind (SPEC-003 section 2.7; SPEC-603 §5 kind increment).

    ``INNER_TS`` is the Phase 2 additive kind (SPEC-603 §14 additive-only):
    the reconstructed Inner TS stream of the three-level demux chain, landed
    content-addressed per SPEC-503.  The ts-side kind string mirror lives in
    ``ts.t2mi.inner_ts.INNER_TS_ARTIFACT_KIND`` (ts purity: one-way mirror).
    """

    INPUT_TS = "input_ts"
    GENERATED_TS = "generated_ts"
    FAULTED_TS = "faulted_ts"
    INNER_TS = "inner_ts"
    REPORT = "report"
    LOG = "log"
    EVIDENCE = "evidence"


class TSArtifact(DomainModel):
    """SPEC-003 section 2.7 ``TSArtifact``."""

    artifact_id: OpaqueEntityId
    run_id: OpaqueEntityId
    kind: ArtifactKind
    #: Relative to the managed artifact root; never an absolute path.
    relative_path: str
    #: MVP only produces 188-byte packets (ADR-0003 item 7; RS204/M2TS later).
    packet_size: Optional[Literal[188, 204]] = None
    packet_count: Optional[int] = None
    byte_size: int
    sha256: str
    generator_version: Optional[str] = None
    config_hash: Optional[str] = None
    fault_profile_ids: Optional[list[OpaqueEntityId]] = None
    created_at_utc_ms: int


__all__ = ["ArtifactKind", "TSArtifact"]
