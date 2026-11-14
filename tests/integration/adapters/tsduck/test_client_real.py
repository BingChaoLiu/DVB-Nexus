"""Real-TSDuck analyze chain acceptance (SPEC-308 §10/§11, ticket #37).

The ticket's headline acceptance: the analyze chain runs against the M1
registered golden vectors and passes the JSON content gate; whitelist-外
argv is refused; the #3 garbage-input discipline (exit 0 ≠ valid) holds on
the real CLI; error/timeout behavior matches the §9 family.

Real-environment discipline (tests/README §6, #69): assertions are SHAPE
assertions — version token ``^\\d+\\.\\d+-\\d+$`` with self-consistent
components, existing executable, gate-passing content. No literal version
pins (the CI winget install differs from the reference machine).

Markers: ``tsduck`` (explicit skip with a visible reason when the CLI is
absent — 兜底仅限本地, #14; the Windows CI job installs TSDuck) and
``windows_only`` (the client's sibling resolution and the runner's tree
kill are Windows-shaped).
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from pathlib import Path

import pytest

from tests._support.paths import GOLDEN_ROOT

from adapters.tsduck.client import TSDuckClient
from adapters.tsduck.command_builder import build_analyze_argv
from adapters.tsduck.errors import TSDuckJsonGateError, TSDuckNotEnabledError
from adapters.tsduck.process import TSDuckProcessRunner

pytestmark = [pytest.mark.tsduck, pytest.mark.windows_only]

#: A parsed version token must be the measured shape ``X.Y-Z``.
VERSION_SHAPE = re.compile(r"^\d+\.\d+-\d+$")

#: First-batch registered golden vector (SPEC-506, ticket #36) — the M1
#: product the analyze chain must consume.
GOLDEN_VECTOR = "pat-minimal"


@pytest.fixture
def golden_ts() -> Path:
    path = GOLDEN_ROOT / GOLDEN_VECTOR / f"{GOLDEN_VECTOR}.ts"
    assert path.is_file(), f"registered golden vector missing: {path}"
    return path


@pytest.fixture
def client() -> TSDuckClient:
    # The ``tsduck`` fixture (requested per-test) owns the explicit skip;
    # here it doubles as the availability gate.
    return TSDuckClient(runner=TSDuckProcessRunner(default_timeout=60.0))


class TestRealAnalyzeGolden:
    def test_analyze_chain_runs_golden_vector_through_the_gate(
        self, tsduck, client, golden_ts
    ):
        result = asyncio.run(client.analyze(golden_ts, run_id="run-acceptance-1"))

        # JSON content gate passed (the report exists at all).
        report = result.report
        assert report.ts.bytes > 0
        assert report.ts.services_total >= 1
        assert report.ts.packets_total > 0

    def test_call_record_nine_fields_on_real_run(self, tsduck, client, golden_ts):
        result = asyncio.run(client.analyze(golden_ts, run_id="run-acceptance-2"))
        record = result.call_record

        assert record.version is not None
        assert VERSION_SHAPE.match(record.version)
        major, minor, build = (int(p) for p in record.version.replace("-", ".").split("."))
        assert (record.version.count("."), record.version.count("-")) == (1, 1)
        assert minor >= 0 and build >= 0 and major >= 0
        # Baseline enforcement ran silently (3.40 floor) — an available
        # result here means the parsed components cleared it.
        assert (major, minor) >= (3, 40)

        assert record.executable_path is not None
        assert Path(record.executable_path).is_file()
        assert record.argv == tuple(build_analyze_argv(golden_ts))
        assert record.argv[:2] == ("tsanalyze", "--json")
        assert record.started_at <= record.finished_at
        assert record.exit_code == 0
        assert record.stdout_text  # the JSON report itself
        # stderr is display-only; success on a clean install is typically
        # empty, but noise tolerance (GBK, version banner) is the policy —
        # the record keeps it verbatim either way. Never parsed here.
        assert isinstance(record.stderr_text, str)
        assert record.input_artifact_sha256 == hashlib.sha256(
            golden_ts.read_bytes()
        ).hexdigest()
        assert record.run_id == "run-acceptance-2"

    def test_golden_report_normalized_shape(self, tsduck, client, golden_ts):
        result = asyncio.run(client.analyze(golden_ts))
        report = result.report
        # pat-minimal: PAT on PID 0 with service 1 (registered expectations
        # anchor the vector; the report's normalized rows must agree).
        assert report.pids, "PID rows normalized"
        pat_rows = [p for p in report.pids if p.pid == 0]
        assert pat_rows and pat_rows[0].description == "PAT"
        assert report.services, "service rows normalized"
        assert report.services[0].service_id == 1


class TestRealGateDiscipline:
    def test_garbage_input_exits_zero_and_gate_refuses(self, tsduck, client, tmp_path):
        """The #3 measured discipline, real CLI: garbage input still exits 0
        with well-formed JSON — the content gate is what refuses it."""
        garbage = tmp_path / "garbage.ts"
        garbage.write_bytes(bytes(64))

        with pytest.raises(TSDuckJsonGateError) as excinfo:
            asyncio.run(client.analyze(garbage))

        assert "exit_code=0" in str(excinfo.value)  # exit 0 did NOT fool it
        record = excinfo.value.call_record
        assert record is not None
        assert record.exit_code == 0
        assert record.input_artifact_sha256 == hashlib.sha256(bytes(64)).hexdigest()

    def test_missing_input_exits_nonzero_and_gate_refuses(self, tsduck, client, tmp_path):
        """#3 §4.4: nonexistent input → CLI exit 1 → gate refuses (no raw
        FileNotFoundError leak; the §9 family stays coherent)."""
        with pytest.raises(TSDuckJsonGateError) as excinfo:
            asyncio.run(client.analyze(tmp_path / "no_such.ts"))

        assert "exit_code=1" in str(excinfo.value)
        assert excinfo.value.call_record.input_artifact_sha256 is None


class TestRealReservedOperations:
    def test_inject_and_generate_refused_without_touching_the_cli(self, tsduck, client):
        from adapters.tsduck.client import GenerateSpec, InjectSpec

        with pytest.raises(TSDuckNotEnabledError):
            asyncio.run(client.inject(InjectSpec()))
        with pytest.raises(TSDuckNotEnabledError):
            asyncio.run(client.generate(GenerateSpec()))


class TestRealWhitelist:
    def test_whitelist_rejection_needs_no_cli_and_is_argument_shaped(
        self, tsduck, client, golden_ts
    ):
        """Acceptance: 白名单外 argv 构造被拒绝 — a user-named plugin outside
        the §5 whitelist cannot enter any argv construction."""
        from adapters.tsduck.command_builder import require_allowed_plugin
        from adapters.tsduck.errors import TSDuckPluginNotAllowedError

        with pytest.raises(TSDuckPluginNotAllowedError):
            require_allowed_plugin("dektec")
