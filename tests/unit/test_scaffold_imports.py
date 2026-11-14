"""Vertical-slice sanity: the src skeleton packages import cleanly.

Scaffold validation for ticket #22 (SPEC-505 gate runs against a real
importable tree) — not business-logic coverage. The 11 canonical packages
follow ADR-0005 decision 4 (directory-merged layout); the two container
packages (adapters, domain) are included so namespace packages resolve too.
"""

from __future__ import annotations

import importlib

import pytest

#: 11 canonical packages per ADR-0005 decision 4.
CANONICAL_PACKAGES: tuple[str, ...] = (
    "ts",
    "faults",
    "simulation",
    "knowledge",
    "adapters.storage",
    "adapters.tsduck",
    "api",
    "application",
    "domain.observation",
    "domain.diagnosis",
    "domain.topology",
)

#: Namespace containers that must stay importable as namespaces.
CONTAINER_PACKAGES: tuple[str, ...] = ("adapters", "domain")


@pytest.mark.parametrize("package", CANONICAL_PACKAGES)
def test_canonical_src_package_imports(package: str):
    module = importlib.import_module(package)
    assert module.__name__ == package


@pytest.mark.parametrize("package", CONTAINER_PACKAGES)
def test_container_src_package_imports(package: str):
    module = importlib.import_module(package)
    assert module.__name__ == package
