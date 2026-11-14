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
from pathlib import Path

import pytest

from tests._support.artifact_paths import ArtifactStoreHandle
from tests._support.markers import check_layer_markers, layer_for_path
from tests._support.sqlite_support import JournalHandle, default_migrations_dir
from tests._support.tsduck_probe import TSP_ENV_OVERRIDE, probe_tsp


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


# ---------------------------------------------------------------------------
# Core fixture 六件 (SPEC-505 §4). Fixtures are function-scoped: no implicit
# shared mutable state between fixtures/tests; every test builds its own tmp
# resources. Immutable probe results may be cached (see tsduck fixture).
# ---------------------------------------------------------------------------


@pytest.fixture
def journal_migrations_dir() -> Path | None:
    """Where ``journal`` looks for ``NNN_*.sql`` migrations.

    Default: SPEC-502 §11 suggested home ``src/adapters/storage/migrations``
    when it exists (M0 skeleton: absent → no migrations applied, database
    starts at ``user_version=0``). Override this fixture in a test module
    to point at a tmp migrations tree.
    """
    return default_migrations_dir()


@pytest.fixture
def journal(tmp_path: Path, journal_migrations_dir: Path | None) -> JournalHandle:
    """SPEC-505 §4 `journal`: tmp SQLite + 迁移后库 (SPEC-502).

    Chosen variant: tmp **file** database (WAL + migration semantics are
    only observable on files; SPEC-505 §4 "二选一实现期定"). Applies pending
    numbered ``.sql`` migrations at setup — missing migrations dir is not an
    initialization failure (M0 skeleton state), but a failing migration IS a
    test failure (SPEC-505 §7 不降级跳过).
    """
    db_path = tmp_path / "journal.sqlite3"
    handle = JournalHandle(db_path=db_path, migrations_dir=journal_migrations_dir)
    try:
        handle.migrate()
    except BaseException:
        handle.close_all()
        raise
    yield handle
    handle.close_all()


@pytest.fixture
def artifact_store(tmp_path: Path) -> ArtifactStoreHandle:
    """SPEC-505 §4 `artifact_store`: tmp root + 索引库 (SPEC-503).

    Provides the content-addressed root skeleton (``artifacts/`` + ``tmp/``)
    and the tmp→atomic-rename staging protocol. The index-DB half is the
    SPEC-502/503 implementation seam (recorded in ticket #22 report); the
    fixture never fabricates index rows.
    """
    return ArtifactStoreHandle(root=tmp_path / "artifact_store")


@pytest.fixture
def tsduck() -> "TSDuckProbe":
    """SPEC-505 §4 `tsduck`: availability probe (SPEC-308).

    Missing/broken CLI → explicit ``pytest.skip`` with a summary-visible
    reason (SPEC-505 §5 禁静默跳过; #14: 兜底 skip 仅限本地 — the Windows CI
    job installs ``TSDuck.TSDuck`` via winget and an install failure fails
    that job). Available → frozen probe result (executable, measured-format
    version, raw line). Probe results are immutable and cached per
    executable path, so sharing them crosses no mutable state.
    """
    from tests._support.tsduck_probe import TSDuckProbe

    probe = probe_tsp()
    if not probe.available:
        pytest.skip(
            f"tsduck: TSDuck CLI unavailable — {probe.detail} "
            "(explicit skip per SPEC-505 §5; 兜底仅限本地 per #14)"
        )
    assert isinstance(probe, TSDuckProbe)
    return probe
