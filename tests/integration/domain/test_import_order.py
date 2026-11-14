"""Fresh-interpreter import-order acyclicity (ticket #21 acceptance; moved).

Integration layer per SPEC-505 §3 (真实子进程 is the integration I/O
class): each test spawns a real ``python -c`` interpreter to import the
domain subpackages in different orders and prove the package graph is
acyclic at runtime (diagnosis -> observation is the only intra-domain
edge; topology stands alone). Moved from
``tests/unit/domain/test_importability.py`` in review-fix #6, when the
unit-layer I/O gate (SPEC-505 §8 分层互斥) landed — fresh-interpreter
spawns are real subprocesses, a unit-layer structural violation; the
assertions are unchanged.

The static layering authority remains lint-imports (9/9 contracts KEPT);
tests are outside the import-linter graph, so these spawns are the
runtime belt-and-braces.
"""

from __future__ import annotations

import subprocess
import sys


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
