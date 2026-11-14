"""Three-subpackage importability and acyclicity (ticket #21 acceptance).

Seam 3 (pre-agreed): module importability of the public API of all three
domain subpackages, plus fresh-interpreter imports in different orders to
prove the package graph is acyclic (diagnosis -> observation is the only
intra-domain edge; topology stands alone). The lint-clean consumer-perspective
evidence is the ``lint-imports`` run (9/9 contracts KEPT) recorded in the
ticket report; tests are outside the import-linter graph.

No red phase by nature: this slice pins behavior built by the previous
slices (importability), it introduces none.
"""

import subprocess
import sys

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


class TestAcyclicImports:
    def _import_in_fresh_interpreter(self, import_statement: str) -> None:
        result = subprocess.run(
            [sys.executable, "-c", import_statement],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stderr

    def test_import_order_diagnosis_first(self):
        self._import_in_fresh_interpreter(
            "import domain.diagnosis, domain.observation, domain.topology"
        )

    def test_import_order_topology_first(self):
        self._import_in_fresh_interpreter(
            "import domain.topology, domain.diagnosis, domain.observation"
        )

    def test_import_order_observation_first(self):
        self._import_in_fresh_interpreter(
            "import domain.observation, domain.topology, domain.diagnosis"
        )


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
