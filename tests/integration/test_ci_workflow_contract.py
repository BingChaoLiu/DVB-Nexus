"""CI workflow ↔ pytest contract consistency (seam 2, ticket #22).

Integration layer: parses the real workflow YAML files and enforces the
SPEC-505 §5 / #13 / #14 CI gate design structurally:

- tests.yml: ubuntu 必绿组合 job + windows-first job (winget TSDuck +
  ``tsp --version`` gate + ``windows_only or tsduck`` selection);
- tests-nightly.yml: scheduled slow run;
- every marker used in any ``pytest -m "…"`` filter is registered in
  pyproject (the two surfaces cannot drift apart silently);
- workflow style mirrors the existing repo workflows (ubuntu-latest,
  Python 3.12, ``pip install -e ".[dev]"``).
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from tests._support.paths import REPO_ROOT

_WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

# `pytest -m "…" ` (quoted expression) or `pytest -m slow` (single bare token).
_PYTEST_M_QUOTED = re.compile(r'pytest[^\n"]*-m\s+"([^"]+)"')
_PYTEST_M_BARE = re.compile(r'pytest[^\n"]*-m\s+([a-z_0-9]+)(?=\s|$)')
_PYTHON_VERSION = re.compile(r"python-version:\s*\"?([0-9.]+)\"?")
_EXPECTED_MARKERS = {
    "unit",
    "integration",
    "conformance",
    "e2e",
    "slow",
    "tsduck",
    "windows_only",
}


def _load_workflow(name: str) -> dict:
    path = _WORKFLOWS_DIR / name
    assert path.is_file(), f"missing workflow file: {path}"
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    # YAML 1.1 parses the bare `on:` key as boolean True; normalize it.
    if "on" not in workflow and True in workflow:
        workflow["on"] = workflow[True]
    return workflow


def _job_steps(workflow: dict, job_id: str) -> list[dict]:
    return workflow["jobs"][job_id]["steps"]


def _step_runs(step: dict) -> str:
    return str(step.get("run", ""))


def _all_runs(workflow: dict, job_id: str) -> str:
    return "\n".join(_step_runs(step) for step in _job_steps(workflow, job_id))


def _marker_filters(workflow: dict, job_id: str) -> list[str]:
    runs = _all_runs(workflow, job_id)
    return _PYTEST_M_QUOTED.findall(runs) + _PYTEST_M_BARE.findall(runs)


class TestTestsWorkflow:
    def test_file_exists_with_required_jobs(self):
        workflow = _load_workflow("tests.yml")
        job_ids = set(workflow["jobs"])
        assert {"pytest-core", "pytest-windows-first"} <= job_ids

    def test_core_job_is_ubuntu_with_green_combo(self):
        workflow = _load_workflow("tests.yml")
        job = workflow["jobs"]["pytest-core"]
        assert job["runs-on"] == "ubuntu-latest"
        filters = _marker_filters(workflow, "pytest-core")
        assert filters == [
            "(unit or integration or conformance or e2e) and not (tsduck or slow)"
        ]

    def test_windows_job_installs_tsduck_and_runs_windows_only(self):
        workflow = _load_workflow("tests.yml")
        job = workflow["jobs"]["pytest-windows-first"]
        assert job["runs-on"] == "windows-latest"
        runs = _all_runs(workflow, "pytest-windows-first")
        # #14: winget install, install failure = CI failure, tsp --version
        # recorded before the test step.
        assert "TSDuck.TSDuck" in runs
        assert "tsp --version" in runs
        filters = _marker_filters(workflow, "pytest-windows-first")
        assert filters == ["windows_only or tsduck"]

    def test_windows_job_verifies_tsp_before_pytest(self):
        workflow = _load_workflow("tests.yml")
        runs = [
            _step_runs(step) for step in _job_steps(workflow, "pytest-windows-first")
        ]
        tsp_positions = [
            index for index, run in enumerate(runs) if "tsp --version" in run
        ]
        pytest_positions = [
            index for index, run in enumerate(runs) if "-m" in run and "pytest" in run
        ]
        assert tsp_positions and pytest_positions
        assert min(tsp_positions) < min(pytest_positions)

    def test_install_uses_editable_dev_extras(self):
        workflow = _load_workflow("tests.yml")
        for job_id in ("pytest-core", "pytest-windows-first"):
            assert 'pip install -e ".[dev]"' in _all_runs(workflow, job_id)


class TestNightlyWorkflow:
    def test_scheduled_slow_run(self):
        workflow = _load_workflow("tests-nightly.yml")
        assert "schedule" in workflow["on"]
        cron = workflow["on"]["schedule"][0]["cron"]
        assert re.match(r"^\S+\s+\S+\s+\S+\s+\S+\s+\S+$", cron)
        filters = _marker_filters(workflow, "pytest-slow")
        assert filters == ["slow"]

    def test_nightly_also_manual_dispatch_and_never_on_pr(self):
        workflow = _load_workflow("tests-nightly.yml")
        assert "workflow_dispatch" in workflow["on"]
        # SPEC-505 §5: slow 归夜间跑，不进 PR 门（夜间 = schedule + dispatch）。
        assert "pull_request" not in workflow["on"]


class TestCrossSurfaceConsistency:
    def test_every_marker_in_ci_filters_is_registered(self):
        for name in ("tests.yml", "tests-nightly.yml"):
            workflow = _load_workflow(name)
            for job_id in workflow["jobs"]:
                for expression in _marker_filters(workflow, job_id):
                    tokens = set(re.findall(r"[a-z_0-9]+", expression))
                    tokens -= {"and", "or", "not"}
                    unknown = tokens - _EXPECTED_MARKERS
                    assert not unknown, (
                        f"{name}:{job_id} uses unregistered markers {unknown} "
                        f"in -m {expression!r}"
                    )

    def test_python_version_pinned_312_everywhere(self):
        for name in ("tests.yml", "tests-nightly.yml"):
            raw = (Path(_WORKFLOWS_DIR) / name).read_text(encoding="utf-8")
            versions = _PYTHON_VERSION.findall(raw)
            assert versions, f"{name}: no python-version pinned"
            assert set(versions) == {"3.12"}

    def test_tests_workflow_triggers_on_pull_request_like_existing_workflows(self):
        workflow = _load_workflow("tests.yml")
        assert "pull_request" in workflow["on"]
        assert "push" in workflow["on"]
