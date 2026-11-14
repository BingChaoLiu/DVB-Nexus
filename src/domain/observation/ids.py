"""Shared identifier types (ADR-0006 decision 3 ID strategy).

Two deliberately distinct concepts that must never collapse into one type:

- ``OpaqueEntityId``: machine-entity IDs (session/run/fault/scenario/artifact/
  event per ADR-0006) are opaque uuid4 values produced by their owners;
  consumers must not parse semantics out of them. The domain model carries
  them as non-empty strings and does **not** enforce uuid4 format — SPEC-301's
  authoritative envelope schema also treats them as plain strings; uuid4 is a
  producer-side policy (recorded as an assumption in the ticket #21 report).
- ``NodeId`` (the exception, defined in ``domain.topology``): topology-stable
  semantic slug such as ``demux-0``.
"""

from typing import Annotated

from pydantic import StringConstraints

#: Opaque machine-entity identifier (uuid4 by producer policy, ADR-0006
#: decision 3). Non-empty is the only model-level invariant of "identifier".
OpaqueEntityId = Annotated[str, StringConstraints(min_length=1)]

#: Neutral identifier for entities whose ID strategy SPEC-003/ADR-0006 do not
#: pin (topology_id, observation_id, metric_id, rule_id, ...). Non-empty; no
#: opaque/semantic claim.
Identifier = Annotated[str, StringConstraints(min_length=1)]

__all__ = ["Identifier", "OpaqueEntityId"]
