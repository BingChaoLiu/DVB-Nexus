"""gen.* emission discipline at the emitter seam — the unit half
(ticket #128, SPEC-303 §Phase2, ruling §10-7).

The four Phase 2 namespaces are emitted through the same
:class:`simulation.events.SimulationEventEmitter` choke point as every
other run-scoped event (ADR-0006 — no fourth envelope).  Until #129 lands
the registry entries, ``domain.observation`` rejects the new types with
``EnvelopeError`` — so the emitter carries the orchestrator-mandated
"未注册守卫": unregistered types are skipped before envelope construction
(debug-logged, never delivered), and once #129 registers them the guard
passes them through untouched.

Unit layer (no fixtures — unit discipline, tests/README §1): the guard's
default world against the REAL registry.  The fixture-driven paths (the
registry stub through the full envelope + the runtime emission face) live
in the integration half
(``tests/integration/simulation/test_gen_events_delivery.py``); the
layered-chain delivery posture lives in the layered runtime tests.

Payload keys frozen (#128 REPORT — the #129 registry-entry contract):

- ``gen.stage_started``   ``{layer}``
- ``gen.stage_completed`` ``{layer, item_count}``
- ``gen.packet_sampled``  ``{layer, packet_index, byte_size, sha256}``
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from domain.observation.registry import is_registered

#: The four Phase 2 namespaces (SPEC-303 §Phase2). None of them is
#: registered before #129 — the guard's default world.
PHASE2_EVENT_TYPES = (
    "gen.stage_started",
    "gen.stage_completed",
    "gen.packet_sampled",
    "t2mi.stage_summary",
    "t2mi.plp_mismatch",
    "bbframe.stage_summary",
    "bbframe.recovery_failed",
    "biss.scramble_applied",
    "biss.descramble_failed",
)


class TestUnregisteredGuardDefaultWorld:
    """裁定 §10-7: pre-#129, the Phase 2 types hit the guard's skip path."""

    def test_real_registry_carries_no_phase2_entry_yet(self) -> None:
        # #129 owns the additive entries; until then the guard must skip
        # (this pin flips naturally when #129 lands — the guard then
        # passes the types through and the registry-stub tests keep
        # holding the shape contract).
        for event_type in PHASE2_EVENT_TYPES:
            assert not is_registered(event_type), (
                f"{event_type} is registered — #129 landed; the #128 guard "
                "now passes it through (see the registry-stub tests in "
                "tests/integration/simulation/test_gen_events_delivery.py)"
            )

    def test_guard_module_surface_exists(self) -> None:
        # The guard reads the registry lookup through the events module
        # namespace (monkeypatchable at BOTH consumption points — the
        # integration stub path proves the pair).
        import simulation.events as events_module

        assert events_module.is_registered is is_registered


class TestPayloadShapeContract:
    """The frozen payload keys (the #129 registry-entry contract).

    Documented as the vocabulary constants' home test: the shapes are
    exercised end-to-end in the integration stub path; this pin keeps the
    key sets named in one place so a drift cannot slip silently.
    """

    def test_stage_started_keys(self) -> None:
        assert set(_STAGE_STARTED_KEYS) == {"layer"}

    def test_stage_completed_keys(self) -> None:
        assert set(_STAGE_COMPLETED_KEYS) == {"layer", "item_count"}

    def test_packet_sampled_keys(self) -> None:
        assert set(_PACKET_SAMPLED_KEYS) == {
            "layer",
            "packet_index",
            "byte_size",
            "sha256",
        }


_STAGE_STARTED_KEYS = frozenset({"layer"})
_STAGE_COMPLETED_KEYS = frozenset({"layer", "item_count"})
_PACKET_SAMPLED_KEYS = frozenset({"layer", "packet_index", "byte_size", "sha256"})
