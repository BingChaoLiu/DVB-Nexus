"""RunContext and shared ID type tests (SPEC-003 section 2.2, ADR-0006).

Seam: public construction/validation surface of ``domain.observation``
(RunContext, OpaqueEntityId) plus enum closed-set membership for ``mode`` and
``fidelity``. Expected literals come from SPEC-003 section 2.2 text.
"""

import pytest
from pydantic import ValidationError

from domain.observation import Fidelity, OpaqueEntityId, RunContext, RunMode


def _run_context(**overrides) -> RunContext:
    fields = {
        "run_id": "3b241101-e2bb-4255-8caf-4136c566a962",
        "session_id": "9f0c8b1e-6d4a-4f3e-9c2b-7a1d5e0f3a44",
        "topology_id": "topo-1",
        "topology_revision": 3,
        "sequence_number": 0,
        "mode": "sandbox",
        "fidelity": "SIM_TS",
        "started_at_utc_ms": 1_700_000_000_000,
    }
    fields.update(overrides)
    return RunContext(**fields)


class TestEnumClosedSets:
    def test_mode_has_exactly_sandbox_and_live(self):
        assert {member.value for member in RunMode} == {"sandbox", "live"}

    def test_fidelity_has_exactly_the_three_spec_tiers(self):
        assert {member.value for member in Fidelity} == {"SIM_STATE", "SIM_TS", "LIVE"}


class TestOpaqueEntityId:
    def test_uuid_string_accepted(self):
        ctx = _run_context()
        assert ctx.run_id == "3b241101-e2bb-4255-8caf-4136c566a962"

    def test_empty_id_rejected(self):
        with pytest.raises(ValidationError) as excinfo:
            _run_context(run_id="")
        assert excinfo.value.errors()[0]["loc"] == ("run_id",)


class TestRunContext:
    def test_valid_construction_with_required_fields_only(self):
        ctx = _run_context()
        assert ctx.mode is RunMode.SANDBOX
        assert ctx.fidelity is Fidelity.SIM_TS
        assert ctx.generator_version is None
        assert ctx.config_hash is None
        assert ctx.seed is None

    def test_valid_construction_with_all_optionals(self):
        ctx = _run_context(
            generator_version="ts-core-0.1.0",
            config_hash="a" * 64,
            seed=42,
        )
        assert ctx.generator_version == "ts-core-0.1.0"
        assert ctx.config_hash == "a" * 64
        assert ctx.seed == 42

    def test_round_trip(self):
        ctx = _run_context(generator_version="ts-core-0.1.0", seed=42)
        assert RunContext.model_validate(ctx.model_dump()) == ctx

    def test_invalid_mode_rejected_at_mode_field(self):
        with pytest.raises(ValidationError) as excinfo:
            _run_context(mode="replay")
        assert excinfo.value.errors()[0]["loc"] == ("mode",)

    def test_invalid_fidelity_rejected_at_fidelity_field(self):
        with pytest.raises(ValidationError) as excinfo:
            _run_context(fidelity="BEST_EFFORT")
        assert excinfo.value.errors()[0]["loc"] == ("fidelity",)

    def test_missing_required_field_reports_location(self):
        with pytest.raises(ValidationError) as excinfo:
            RunContext(
                session_id="9f0c8b1e-6d4a-4f3e-9c2b-7a1d5e0f3a44",
                topology_id="topo-1",
                topology_revision=3,
                sequence_number=0,
                mode="sandbox",
                fidelity="SIM_TS",
                started_at_utc_ms=1_700_000_000_000,
            )
        error_locs = {error["loc"] for error in excinfo.value.errors()}
        assert ("run_id",) in error_locs

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError) as excinfo:
            _run_context(journal_seq=7)
        assert excinfo.value.errors()[0]["loc"] == ("journal_seq",)

    def test_frozen_model_rejects_assignment(self):
        ctx = _run_context()
        with pytest.raises(ValidationError):
            ctx.sequence_number = 1
