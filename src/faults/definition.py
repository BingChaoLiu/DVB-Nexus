"""SPEC-204 §3 — canonical fault definition data models (ticket #44).

The canonical home of ``FaultDefinition`` / ``FaultActivation`` is the
``faults`` package (ADR-0005 decision 4: ``faults → ts``; the simulation
package consumes these — ``simulation → faults`` is a declared edge).
SIM-D (#43) had declared a structural seam in ``simulation.fault_plan``
carrying field-identical dataclasses; #44 performed the canonicalization,
so the seam now re-exports these classes and #43 consumers keep working
unchanged.

Shapes are frozen exactly per SPEC-204 §3:

- ``FaultDefinition`` — ``fault_id`` (uuid4 opaque identity, ADR-0006
  item 3: excluded from validation and from the plan fingerprint),
  ``fault_type`` (registry enum, :mod:`faults.registry`), ``target_id``
  (topology semantic slug, :mod:`faults.targets`), versioned ``parameters``
  (§4 schema, validated by the registry), ``activation`` (MVP narrow:
  packet_index + session_start, ADR-0007 item 3) and the mandatory
  ``expected_observations`` (ADR-0007 item 5 — the SPEC-206 anchor).
- ``FaultActivation`` — ``kind`` ∈ {``packet_index``, ``session_start``};
  ``packet_index`` is 0-based on the shared packet frame (SPEC-204 §7 item
  2) and required for ``kind="packet_index"``.  Virtual time / manual
  trigger are deferred; a wall-clock sleep may never schedule a fault.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

__all__ = [
    "FaultActivation",
    "FaultDefinition",
]


@dataclass(frozen=True)
class FaultActivation:
    """SPEC-204 §3 ``FaultActivation`` (MVP: packet_index + session_start)."""

    kind: str  # "packet_index" | "session_start"
    packet_index: int | None = None


@dataclass(frozen=True)
class FaultDefinition:
    """SPEC-204 §3 ``FaultDefinition`` (canonical home: the faults package).

    ``fault_id`` is uuid4-opaque identity (ADR-0006 item 3): it takes part
    in neither validation nor the plan fingerprint (identity is not
    semantics; the same plan re-issued with regenerated ids keeps the
    fingerprint stable).

    ``layer`` is the pipeline attribute (SPEC-204 §Phase2 / ADR-0010 §3,
    expanded by §Phase3 / ticket #163): ∈ {``TS``, ``BBFRAME``, ``T2MI``,
    ``BISS``, ``RF``, ``SEC``}, default ``"TS"`` so every MVP plan
    constructs and fingerprints exactly as before (additive; the default
    also matches the MVP rule that the four MVP fault types are TS-layer
    faults).  The runtime routes the fault by this value: package layers
    (TS/BBFRAME/T2MI/BISS) go to the matching pipeline layer's filter
    instance; the state layers (RF/SEC) go to the pre-evaluation pure
    config transform (``simulation.state.fault_transforms``, ADR-0012
    decision 3).  ``faults.registry`` validates the value against the
    fault type's declared layer.
    """

    fault_id: str
    fault_type: str
    target_id: str
    parameters: Mapping[str, Any] = field(default_factory=dict)
    activation: FaultActivation = field(
        default_factory=lambda: FaultActivation(
            kind="session_start", packet_index=None
        )
    )
    expected_observations: tuple[str, ...] = ()
    layer: str = "TS"
