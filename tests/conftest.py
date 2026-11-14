"""Root conftest for the four-layer test tree (SPEC-505, ticket #22).

Responsibilities:

1. Layer-marker discipline (SPEC-505 §8 分层互斥): the directory under
   ``tests/`` is the layer source of truth. Missing layer markers are
   injected at collection; an explicit layer marker contradicting the
   directory is a structural violation and hard-fails collection.
2. ``windows_only`` platform guard (SPEC-505 §5 + ADR-0004): on non-Windows
   platforms these tests skip with an explicit, visible reason — never
   silently degraded.
3. The six core fixtures of SPEC-505 §4 (journal / artifact_store / tsduck /
   session_run / golden_loader / api_client) are added by their own commits
   of ticket #22; see tests/README.md for the full contract.
"""

from __future__ import annotations

import sys

import pytest

from tests._support.markers import check_layer_markers, layer_for_path


def pytest_collection_modifyitems(config, items):
    """Enforce layer-marker discipline at collection time (SPEC-505 §8)."""
    failures: list[str] = []
    for item in items:
        derived = layer_for_path(item.path)
        explicit = {marker.name for marker in item.iter_markers()}
        action, detail = check_layer_markers(derived, explicit)
        if action == "fail":
            failures.append(f"{item.nodeid}: {detail}")
        elif action == "inject":
            item.add_marker(getattr(pytest.mark, detail))
    if failures:
        pytest.fail(
            "layer marker contradictions (structural violations, SPEC-505 §8):\n"
            + "\n".join(sorted(failures)),
            pytrace=False,
        )


@pytest.fixture(autouse=True)
def _windows_only_platform_guard(request):
    """Explicitly skip ``windows_only`` tests off-Windows (SPEC-505 §5).

    Windows-first assertions (path separators, GBK stderr, process-tree
    cleanup — ADR-0004) must not silently degrade on other platforms; the
    skip reason surfaces via ``-ra`` in the summary.
    """
    if request.node.get_closest_marker("windows_only") is None:
        return
    if sys.platform != "win32":
        pytest.skip(
            "windows_only: requires Windows (ADR-0004); "
            f"running on sys.platform={sys.platform!r} — explicit skip, not silent",
            allow_module_level=False,
        )
