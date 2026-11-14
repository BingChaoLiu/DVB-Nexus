"""Shared base for SPEC-003 domain value objects.

One place declaring the domain-wide model contract: every SPEC-003 model is a
frozen value object with a closed field set. Immutability keeps models safely
shareable across the ts/simulation/observation consumers; ``extra="forbid"``
makes the construction surface a strict contract — wire-level tolerance is the
SPEC-301 envelope's job ("loose envelope, tight payload", ADR-0006 decision 4),
not the domain model's.

No business logic may live here or in subclasses (ticket #21).
"""

from pydantic import BaseModel, ConfigDict


class DomainModel(BaseModel):
    """Base class for all SPEC-003 domain models."""

    model_config = ConfigDict(frozen=True, extra="forbid")
