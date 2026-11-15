"""The four fault-lab scenario fixtures — load-time acceptance (ticket #58,
SPEC-205 §3/§4 via the production scenario engine).

The scenario documents are CONTENT, not code: this test drives the real
``simulation.scenario`` schema face over each fixture so the e2e loops
can rely on the loaded documents (uuid4 identity, version pinning,
single-fault plan with mandatory ``expected_observations``, six-kind
pass criteria, executable-content-clean hints).
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from simulation.scenario.schema import (
    SCENARIO_CRITERION_KINDS,
    scenario_content_hash,
    parse_scenario_document,
)

from tests._support.paths import REPO_ROOT

pytestmark = pytest.mark.e2e

SCENARIO_DIR = REPO_ROOT / "tests" / "fixtures" / "scenarios"

#: scenario_id ↔ fixture file (the fixed uuid4 identities of the lab).
SCENARIOS = {
    "pat-missing": "5a1e0000-0000-4000-8000-00000000e201",
    "pmt-invalid-crc": "5a1e0000-0000-4000-8000-00000000e202",
    "cc-discontinuity": "5a1e0000-0000-4000-8000-00000000e203",
    "pmt-pid-mismatch": "5a1e0000-0000-4000-8000-00000000e204",
}

#: fault_type ↔ the pairing rule's expected evidence (SPEC-307 §6).
EXPECTED_OBSERVATIONS = {
    "PAT_MISSING": ("ts.psi_section_observed",),
    "PMT_INVALID_CRC": ("ts.psi_section_observed",),
    "CC_DISCONTINUITY": ("ts.continuity_error",),
    "PMT_PID_MISMATCH": ("ts.psi_section_observed",),
}


def _load(name: str) -> dict:
    path = SCENARIO_DIR / f"fault-lab-{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_scenario_document_loads_through_the_production_schema(name):
    document = parse_scenario_document(_load(name))
    assert document.scenario_id == SCENARIOS[name]
    uuid.UUID(document.scenario_id)  # uuid4 opaque identity (ADR-0006 item 3)
    assert document.version == "1.0.0"
    assert document.topology is not None
    assert document.pass_criteria, "the lab verifies through pass criteria"


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_fault_plan_is_a_single_fault_with_expected_observations(name):
    document = parse_scenario_document(_load(name))
    assert len(document.fault_plan) == 1
    fault = document.fault_plan[0]
    assert fault.fault_id  # uuid4, referenced by the fault_inactive criterion
    assert fault.expected_observations == EXPECTED_OBSERVATIONS[fault.fault_type]


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_pass_criteria_reference_the_closed_kind_set(name):
    document = parse_scenario_document(_load(name))
    for criterion in document.pass_criteria:
        assert criterion.kind in SCENARIO_CRITERION_KINDS
        assert isinstance(criterion.mandatory, bool)
    kinds = {criterion.kind for criterion in document.pass_criteria}
    assert "fault_inactive" in kinds


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_version_pinning_is_content_hash_stable(name):
    raw = _load(name)
    document = parse_scenario_document(raw)
    # Same content ⇒ same pinning hash; any content change moves it
    # (SPEC-205 §5 加载即钉扎).
    assert document.content_hash == scenario_content_hash(
        {**raw, "schema_version": "1"}
    )
    mutated = {**raw, "title": raw["title"] + " (mutated)"}
    assert parse_scenario_document(mutated).content_hash != document.content_hash


def test_all_six_criterion_kinds_appear_across_the_lab():
    kinds: set[str] = set()
    for name in SCENARIOS:
        document = parse_scenario_document(_load(name))
        kinds.update(c.kind for c in document.pass_criteria)
    assert kinds == set(SCENARIO_CRITERION_KINDS)
