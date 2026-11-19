"""``faults.factory`` pluggable transform registration (ticket #121).

Orchestrator ruling §10-4: ``register_transform(fault_type, builder)`` is
the Phase 2 pluggable filter-builder API.  Downstream tickets (#123 /
#124 / #126 / #127) self-register their real builders from their OWN
filter modules (import side effect) and never edit ``factory.py`` again.

Registration semantics (pinned here — the API is frozen once published in
the #121 report):

- same ``(fault_type, builder)`` pair again → idempotent no-op;
- same ``fault_type`` with a *different* builder → ``ValueError`` unless
  ``allow_replace=True`` (the sanctioned way for a downstream ticket to
  replace #121's skeleton wiring);
- unknown ``fault_type`` (not in ``KNOWN_FAULT_TYPES``) → ``ValueError``
  (typo'd registrations must fail loudly, not silently rot).

Resolution: ``transform_builder_for`` consults the override table first,
then the MVP built-in table in :mod:`faults.registry`.  The semantic
filter resolves through the same path, so self-registered builders are
visible to prepared runs without touching ``factory.py``.

``factory.py`` also carries #121's own skeleton wiring: the four Phase 2
primitives resolve to ``NotImplementedError`` skeletons until their
owning tickets (#124 / #123 / #126 / runtime #128) register the real
builders.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from faults.definition import FaultActivation, FaultDefinition
from faults.factory import (
    register_transform,
    transform_builder_for,
)
from faults.filters import phase2_skeletons
from faults.filters.base import FaultTransform
from faults.registry import (
    FAULT_TYPE_BBHEADER_SYNC_FAULT,
    FAULT_TYPE_BISS_KEY_MISMATCH,
    FAULT_TYPE_PAT_MISSING,
    FAULT_TYPE_PMT_PID_DRIFT,
    FAULT_TYPE_T2MI_PLP_MISMATCH,
    KNOWN_FAULT_TYPES,
    validate_fault_definition,
)
from faults.filters.semantic import SemanticFaultFilter

pytestmark = pytest.mark.unit


@contextmanager
def _clean_override_table():
    """Isolate the process-global downstream registration table per test.

    The #121 skeleton tier (``_SKELETON_BUILDERS``) is module state that
    never mutates, so a fresh empty ``_EXTRA_BUILDERS`` is the pristine
    downstream-registration baseline.  A plain context manager (not a
    fixture) keeps the unit layer free of fixture requests (SPEC-505 §8
    io_rules).
    """
    import faults.factory as factory_module

    original = factory_module._EXTRA_BUILDERS
    factory_module._EXTRA_BUILDERS = {}
    try:
        yield
    finally:
        factory_module._EXTRA_BUILDERS = original


def _definition(
    fault_type: str,
    target_id: str,
    layer: str,
    parameters: dict | None = None,
    activation: FaultActivation | None = None,
) -> FaultDefinition:
    return FaultDefinition(
        fault_id="f-1",
        fault_type=fault_type,
        target_id=target_id,
        parameters=parameters or {},
        activation=activation
        or FaultActivation(kind="session_start", packet_index=None),
        expected_observations=("placeholder.observation",),
        layer=layer,
    )


class TestSkeletonWiring:
    """factory.py's #121 wiring: the four primitives resolve to skeletons."""

    @pytest.mark.parametrize(
        ("fault_type", "skeleton_class", "target_id", "layer"),
        [
            (
                FAULT_TYPE_BBHEADER_SYNC_FAULT,
                phase2_skeletons.BBHeaderSyncFaultSkeletonTransform,
                "t2mi-enc-0",
                "BBFRAME",
            ),
            (
                FAULT_TYPE_PMT_PID_DRIFT,
                phase2_skeletons.PmtPidDriftSkeletonTransform,
                "demux-0:pid:0x1000",
                "TS",
            ),
        ],
    )
    def test_phase2_types_resolve_to_skeletons(
        self, fault_type, skeleton_class, target_id, layer
    ) -> None:
        # The skeleton tier is immutable module state: resolve against a
        # pristine downstream table.  Downstream tickets self-register
        # their real builders at import time (ruling §10-4) — BISS_KEY_
        # MISMATCH (#126), T2MI_PLP_MISMATCH (#124), BBHEADER_SYNC_FAULT
        # (#123) all have live registrations in-process; see
        # test_biss_resolves_to_real_transform /
        # test_t2mi_plp_resolves_to_real_transform.  The skeleton-tier
        # pinning stays order-independent through the file's own
        # isolation helper.
        with _clean_override_table():
            assert transform_builder_for(fault_type) is skeleton_class

    def test_biss_resolves_to_real_transform(self) -> None:
        """#126 replaced the BISS_KEY_MISMATCH skeleton: importing the
        owning filter module self-registers the real builder (ruling
        §10-4) — the resolution order puts it ahead of the skeleton tier.
        #127 (SPEC-611) replaced the registration with the dispatching
        builder: Mode 1 definitions still resolve to #126's transform
        (the identity pin becomes a behavior pin — the resolution
        produces #126's transform for a Mode 1 definition)."""
        import faults.filters.biss_mode_e  # noqa: F401 — dispatch registration
        from faults.definition import FaultActivation, FaultDefinition
        from faults.filters.scrambler import BissKeyMismatchTransform

        builder = transform_builder_for(FAULT_TYPE_BISS_KEY_MISMATCH)
        definition = FaultDefinition(
            fault_id="f-biss-mismatch",
            fault_type=FAULT_TYPE_BISS_KEY_MISMATCH,
            target_id="mux-0",
            parameters={
                "wrong_session_word": "0123456789AB",
                "pid_scope": [0x0100],
            },
            activation=FaultActivation(kind="session_start", packet_index=None),
            layer="BISS",
        )
        assert isinstance(builder(definition), BissKeyMismatchTransform)

    def test_t2mi_plp_resolves_to_real_transform(self) -> None:
        """#124 replaced the T2MI_PLP_MISMATCH skeleton: importing the
        owning filter module self-registers the real builder (ruling
        §10-4) — the resolution order puts it ahead of the skeleton tier."""
        import faults.filters.t2mi_plp_mismatch  # noqa: F401 — self-registration
        from faults.filters.t2mi_plp_mismatch import T2miPlpMismatchTransform

        assert (
            transform_builder_for(FAULT_TYPE_T2MI_PLP_MISMATCH)
            is T2miPlpMismatchTransform
        )

    @pytest.mark.parametrize(
        ("fault_type", "target_id", "layer", "parameters", "activation"),
        [
            (
                FAULT_TYPE_T2MI_PLP_MISMATCH,
                "t2mi-demux-0",
                "T2MI",
                {"expected_plp": 0, "actual_plp": 1},
                FaultActivation(kind="session_start", packet_index=None),
            ),
            (
                FAULT_TYPE_BBHEADER_SYNC_FAULT,
                "t2mi-enc-0",
                "BBFRAME",
                {"field": "SYNCD", "mode": "corrupt"},
                FaultActivation(kind="packet_index", packet_index=1),
            ),
            (
                FAULT_TYPE_BISS_KEY_MISMATCH,
                "biss-scrambler-0",
                "BISS",
                {"wrong_session_word": "A13DBC42908F", "pid_scope": [0x100]},
                FaultActivation(kind="session_start", packet_index=None),
            ),
            (
                FAULT_TYPE_PMT_PID_DRIFT,
                "demux-0:pid:0x1000",
                "TS",
                {"new_pid_map": {1: 0x0900}, "pmt_version_bump": True},
                FaultActivation(kind="packet_index", packet_index=2),
            ),
        ],
    )
    def test_semantic_filter_accepts_skeleton_wired_plan(
        self, fault_type, target_id, layer, parameters, activation
    ) -> None:
        with _clean_override_table():
            definition = _definition(
                fault_type, target_id, layer, parameters, activation
            )
            assert validate_fault_definition(definition) == ()
            filter_instance = SemanticFaultFilter((definition,))
            assert filter_instance is not None

    def test_skeleton_transform_is_explicitly_not_implemented(self) -> None:
        # The skeleton placeholder discipline is structural: the #121
        # skeleton classes themselves still refuse to fake a transform
        # (all four Phase 2 primitives have real builders since #139 —
        # the skeletons remain as the honest-refusal tier they were
        # created for).
        from faults.filters.pat_missing import null_packet
        from faults.filters.phase2_skeletons import PmtPidDriftSkeletonTransform

        transform = PmtPidDriftSkeletonTransform(
            _definition(
                FAULT_TYPE_PMT_PID_DRIFT, "demux-0:pid:0x1000", "TS"
            )
        )
        assert isinstance(transform, FaultTransform)
        packet = null_packet()
        with pytest.raises(NotImplementedError):
            transform.apply(0, packet)

    def test_pmt_pid_drift_resolves_the_real_ts_builder(self) -> None:
        # The TS-layer drift went real in #139 (the #136 收口 patch
        # ticket D-2): the SC-09 injection chain builder resolves to the
        # real transform, never the skeleton.
        from faults.filters.pmt_pid_drift import PmtPidDriftTransform

        assert transform_builder_for(FAULT_TYPE_PMT_PID_DRIFT) is (
            PmtPidDriftTransform
        )


class TestRegisterTransformSemantics:
    def test_register_and_resolve_custom_builder(self) -> None:
        class Custom(FaultTransform):
            def transform(self, index, packet):  # pragma: no cover
                return packet

        with _clean_override_table():
            register_transform(FAULT_TYPE_PAT_MISSING, Custom)
            assert transform_builder_for(FAULT_TYPE_PAT_MISSING) is Custom

    def test_same_builder_reregistration_is_idempotent(self) -> None:
        class Custom(FaultTransform):
            def transform(self, index, packet):  # pragma: no cover
                return packet

        with _clean_override_table():
            register_transform(FAULT_TYPE_PAT_MISSING, Custom)
            # Same (type, builder) pair again: no error, no state change.
            register_transform(FAULT_TYPE_PAT_MISSING, Custom)
            assert transform_builder_for(FAULT_TYPE_PAT_MISSING) is Custom

    def test_different_builder_for_registered_type_raises(self) -> None:
        class First(FaultTransform):
            def transform(self, index, packet):  # pragma: no cover
                return packet

        class Second(FaultTransform):
            def transform(self, index, packet):  # pragma: no cover
                return packet

        with _clean_override_table():
            register_transform(FAULT_TYPE_PAT_MISSING, First)
            with pytest.raises(ValueError):
                register_transform(FAULT_TYPE_PAT_MISSING, Second)
            # The sanctioned replacement path.
            register_transform(
                FAULT_TYPE_PAT_MISSING, Second, allow_replace=True
            )
            assert transform_builder_for(FAULT_TYPE_PAT_MISSING) is Second

    def test_downstream_can_replace_a_skeleton(self) -> None:
        class RealBuilder(FaultTransform):
            def transform(self, index, packet):  # pragma: no cover
                return packet

        # The skeleton tier remains the shadowed fallback (all four Phase 2
        # primitives have real builders since #139 — the tier persists for
        # exactly this replacement semantics)...
        with _clean_override_table():
            assert transform_builder_for(FAULT_TYPE_PMT_PID_DRIFT) is (
                phase2_skeletons.PmtPidDriftSkeletonTransform
            )
            # ...and a downstream registration shadows it without touching
            # factory.py.
            register_transform(FAULT_TYPE_PMT_PID_DRIFT, RealBuilder)
            assert transform_builder_for(FAULT_TYPE_PMT_PID_DRIFT) is RealBuilder

    @pytest.mark.parametrize("unknown_type", ["TYPO_TYPE", "PAT_MISSING_2"])
    def test_unknown_fault_type_registration_raises(self, unknown_type) -> None:
        class Custom(FaultTransform):
            def transform(self, index, packet):  # pragma: no cover
                return packet

        with _clean_override_table():
            with pytest.raises(ValueError):
                register_transform(unknown_type, Custom)
        assert unknown_type not in KNOWN_FAULT_TYPES

    def test_semantic_filter_uses_pluggable_resolution(self) -> None:
        recorded: list[FaultDefinition] = []

        class Probe(FaultTransform):
            def __init__(self, definition: FaultDefinition) -> None:
                recorded.append(definition)

            def transform(self, index, packet):  # pragma: no cover
                return packet

        definition = FaultDefinition(
            fault_id="f-probe",
            fault_type=FAULT_TYPE_PAT_MISSING,
            target_id="demux-0:pid:0x0000",
            expected_observations=("ts.psi_section_observed",),
        )
        with _clean_override_table():
            register_transform(FAULT_TYPE_PAT_MISSING, Probe)
            SemanticFaultFilter((definition,))
        assert recorded == [definition]
