"""Three-subpackage importability (ticket #21 acceptance).

Seam 3 (pre-agreed): module importability of the public API of all three
domain subpackages. The lint-clean consumer-perspective evidence is the
``lint-imports`` run (9/9 contracts KEPT) recorded in the ticket report;
tests are outside the import-linter graph. The fresh-interpreter
import-order acyclicity probes live in the integration layer
(``tests/integration/domain/test_import_order.py``) — real subprocesses
are integration I/O per SPEC-505 §3, and the unit-layer I/O gate
(SPEC-505 §8 分层互斥) enforces the split (moved in review-fix #6;
assertions unchanged).

No red phase by nature: this slice pins behavior built by the previous
slices (importability), it introduces none.
"""

from pydantic import BaseModel

import domain.diagnosis
import domain.observation
import domain.topology


class TestThreeSubpackagesImportable:
    def test_topology_public_api(self):
        for name in domain.topology.__all__:
            assert hasattr(domain.topology, name), name

    def test_observation_public_api(self):
        for name in domain.observation.__all__:
            assert hasattr(domain.observation, name), name

    def test_diagnosis_public_api(self):
        for name in domain.diagnosis.__all__:
            assert hasattr(domain.diagnosis, name), name


class TestDomainModelContract:
    """Every public SPEC-003 model is a frozen Pydantic model (ADR-0003 stack)."""

    EXPECTED_MODELS = {
        domain.topology: [
            "Topology",
            "TopologyNode",
            "TopologyPort",
            "TopologyConnection",
        ],
        domain.observation: [
            "RunContext",
            "Observation",
            "Metric",
            "TSArtifact",
        ],
        domain.diagnosis: [
            "Diagnosis",
        ],
    }

    def test_all_public_models_are_frozen_pydantic_models(self):
        for package, model_names in self.EXPECTED_MODELS.items():
            for name in model_names:
                model = getattr(package, name)
                assert issubclass(model, BaseModel), f"{package.__name__}.{name}"
                assert model.model_config.get("frozen") is True, (
                    f"{package.__name__}.{name}"
                )
                assert model.model_config.get("extra") == "forbid", (
                    f"{package.__name__}.{name}"
                )
