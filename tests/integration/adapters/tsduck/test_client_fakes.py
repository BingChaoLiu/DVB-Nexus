"""TSDuckClient orchestration with injected fake probe/runner (SPEC-308 §4).

The client's collaborators are seam-injected (probe → version.py's real
result types; runner → process.py's real ProcessResult), so the orchestration
contract — argv plumbing, gate, call record, error family — is exercised
without the real CLI and runs in the ubuntu PR gate. File I/O (the sha256
over a real tmp file) keeps this at the integration layer; no TSDuck, no
spawn, no Windows-only mechanics.

Literal version tokens here ("3.40-4165", "3.39-4165") are synthetic fixture
inputs (tests/README §6: 钉扎只属于单测/fake), never environment assumptions.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path

import pytest

from adapters.tsduck.client import TSDuckClient
from adapters.tsduck.errors import (
    TSDuckNotFoundError,
    TSDuckJsonGateError,
    TSDuckVersionUnsupportedError,
)
from adapters.tsduck.process import ProcessResult
from adapters.tsduck.version import (
    ResolutionSource,
    TSDuckProbeResult,
    TSDuckUnavailableReason,
    TSDuckVersion,
    VersionStream,
)

#: Synthetic locked-baseline token for fake fixtures only.
FAKE_VERSION = "3.40-4165"


def _write_valid_report_stdout() -> str:
    """A minimal gate-passing tsanalyze-shaped document (§4.2 anchors)."""
    document = {
        "pids": [],
        "services": [{"id": 1, "pmt-pid": 4096, "pcr-pid": 256}],
        "tables": [],
        "ts": {
            "bytes": 188_000,
            "packets": {"total": 1_000},
            "pids": {"total": 5},
            "services": {"total": 1},
        },
    }
    return json.dumps(document)


class FakeProbe:
    """Probe seam: returns prebuilt real TSDuckProbeResult values."""

    def __init__(self, result: TSDuckProbeResult) -> None:
        self.result = result
        self.calls = 0

    def probe(self, *, override=None) -> TSDuckProbeResult:
        self.calls += 1
        return self.result


class FakeRunner:
    """Runner seam: records argv/timeout, returns canned ProcessResults."""

    def __init__(self, results: list[ProcessResult]) -> None:
        self.results = list(results)
        self.calls: list[dict] = []

    async def run_async(self, argv, *, timeout=None, env=None, on_start=None):
        self.calls.append({"argv": list(argv), "timeout": timeout, "env": env})
        return self.results.pop(0)


def _fake_version(tsp_path: Path, version: str = FAKE_VERSION) -> TSDuckVersion:
    major, minor, build = (int(p) for p in version.replace("-", ".").split("."))
    return TSDuckVersion(
        executable=tsp_path,
        version=version,
        major=major,
        minor=minor,
        build=build,
        raw_version_line=f"TSDuck - The MPEG Transport Stream Toolkit - version {version}",
        stream=VersionStream.STDERR,
        resolution=ResolutionSource.PATH,
    )


def _available_probe(tsp_path: Path, version: str = FAKE_VERSION) -> FakeProbe:
    return FakeProbe(
        TSDuckProbeResult(
            available=True,
            version=_fake_version(tsp_path, version),
            reason=None,
            detail="fake available probe",
        )
    )


def _unavailable_probe() -> FakeProbe:
    return FakeProbe(
        TSDuckProbeResult(
            available=False,
            version=None,
            reason=TSDuckUnavailableReason.NOT_INSTALLED,
            detail="fake unavailable probe",
        )
    )


@pytest.fixture
def fake_install(tmp_path: Path) -> Path:
    """A fake TSDuck bin dir: probed tsp + the tsanalyze sibling the client
    resolves (name is platform-shaped, as the client's resolution is)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    tsp = bin_dir / ("tsp.exe" if sys.platform == "win32" else "tsp")
    tsp.write_bytes(b"")
    tsanalyze_name = "tsanalyze.exe" if sys.platform == "win32" else "tsanalyze"
    (bin_dir / tsanalyze_name).write_bytes(b"")
    return bin_dir


class TestAnalyzeOrchestration:
    def test_analyze_builds_whitelist_argv_and_records_nine_fields(
        self, tmp_path, fake_install
    ):
        ts_file = tmp_path / "input.ts"
        ts_file.write_bytes(bytes(range(64)))
        runner = FakeRunner(
            [
                ProcessResult(
                    argv=(),
                    exit_code=0,
                    stdout=_write_valid_report_stdout().encode("utf-8"),
                    stderr=b"",
                    duration_seconds=0.01,
                    pid=4242,
                )
            ]
        )
        client = TSDuckClient(probe=_available_probe(fake_install / "tsp.exe"), runner=runner)

        result = asyncio.run(client.analyze(ts_file, run_id="run-42"))

        # argv = the builder's output, verbatim into the runner.
        assert runner.calls[0]["argv"] == ["tsanalyze", "--json", str(ts_file)]
        # Nine-field record, complete and run-associated.
        record = result.call_record
        assert record.version == FAKE_VERSION
        assert record.executable_path is not None
        assert Path(record.executable_path).is_file()
        assert record.argv == ("tsanalyze", "--json", str(ts_file))
        assert record.started_at <= record.finished_at
        assert record.exit_code == 0
        assert record.stdout_text
        assert record.stderr_text == ""
        assert record.input_artifact_sha256 == hashlib.sha256(ts_file.read_bytes()).hexdigest()
        assert record.run_id == "run-42"

    def test_analyze_returns_normalized_report(self, tmp_path, fake_install):
        ts_file = tmp_path / "input.ts"
        ts_file.write_bytes(bytes(64))
        runner = FakeRunner(
            [
                ProcessResult(
                    argv=(),
                    exit_code=0,
                    stdout=_write_valid_report_stdout().encode("utf-8"),
                    stderr=b"",
                    duration_seconds=0.01,
                )
            ]
        )
        client = TSDuckClient(probe=_available_probe(fake_install / "tsp.exe"), runner=runner)

        result = asyncio.run(client.analyze(ts_file))

        assert result.report.ts.bytes == 188_000
        assert result.report.ts.services_total == 1
        assert result.report.source_document  # raw JSON kept for the artifact

    def test_timeout_forwarded_to_runner(self, tmp_path, fake_install):
        ts_file = tmp_path / "input.ts"
        ts_file.write_bytes(bytes(16))
        runner = FakeRunner(
            [
                ProcessResult(
                    argv=(),
                    exit_code=0,
                    stdout=_write_valid_report_stdout().encode("utf-8"),
                    stderr=b"",
                    duration_seconds=0.01,
                )
            ]
        )
        client = TSDuckClient(probe=_available_probe(fake_install / "tsp.exe"), runner=runner)

        asyncio.run(client.analyze(ts_file, timeout=7.5))

        assert runner.calls[0]["timeout"] == 7.5

    def test_gate_failure_carries_the_call_record(self, tmp_path, fake_install):
        """§7 recording duty holds on failures: the failed invocation's
        record travels on the raised gate error."""
        ts_file = tmp_path / "garbage.ts"
        ts_file.write_bytes(bytes(16))
        runner = FakeRunner(
            [
                ProcessResult(
                    argv=(),
                    exit_code=0,
                    stdout=b"{}",
                    stderr=b"",
                    duration_seconds=0.01,
                )
            ]
        )
        client = TSDuckClient(probe=_available_probe(fake_install / "tsp.exe"), runner=runner)

        with pytest.raises(TSDuckJsonGateError) as excinfo:
            asyncio.run(client.analyze(ts_file, run_id="run-9"))

        record = excinfo.value.call_record
        assert record is not None
        assert record.exit_code == 0
        assert record.input_artifact_sha256 == hashlib.sha256(bytes(16)).hexdigest()
        assert record.run_id == "run-9"


class TestClientErrorFamily:
    def test_unavailable_probe_raises_not_found(self):
        client = TSDuckClient(probe=_unavailable_probe())
        with pytest.raises(TSDuckNotFoundError):
            asyncio.run(client.get_version())

    def test_below_baseline_raises_unsupported(self, fake_install):
        # 3.39 < MVP baseline 3.40 — synthetic fixture token, not an env claim.
        client = TSDuckClient(probe=_available_probe(fake_install / "tsp.exe", "3.39-4165"))
        with pytest.raises(TSDuckVersionUnsupportedError) as excinfo:
            asyncio.run(client.get_version())
        assert "3.39-4165" in str(excinfo.value)

    def test_missing_tsanalyze_sibling_raises_not_found(self, tmp_path):
        lone_tsp = tmp_path / "tsp.exe"
        lone_tsp.write_bytes(b"")  # no tsanalyze next to it
        client = TSDuckClient(probe=_available_probe(lone_tsp))
        # The version probe itself succeeds; the missing ANALYZE tool only
        # surfaces when analyze resolves its sibling executable.
        with pytest.raises(TSDuckNotFoundError) as excinfo:
            asyncio.run(client.analyze(tmp_path / "input.ts"))
        assert "tsanalyze" in str(excinfo.value)

    def test_unreadable_input_hashes_to_none_and_gate_still_governs(
        self, tmp_path, fake_install
    ):
        """Missing input file: tsanalyze exits 1 (#3 §4.4), sha256 cannot be
        computed — the record carries None and the gate (exit 1, no JSON)
        raises, never a raw FileNotFoundError leak."""
        missing = tmp_path / "no_such.ts"
        runner = FakeRunner(
            [
                ProcessResult(
                    argv=(),
                    exit_code=1,
                    stdout=b"",
                    # Ordinary test text via str.encode (禁手拼字节 constructor
                    # discipline; anchored to #3 §4.4's measured message shape).
                    stderr="tsanalyze: cannot open data/no_such.ts".encode("utf-8"),
                    duration_seconds=0.01,
                )
            ]
        )
        client = TSDuckClient(probe=_available_probe(fake_install / "tsp.exe"), runner=runner)

        with pytest.raises(TSDuckJsonGateError) as excinfo:
            asyncio.run(client.analyze(missing))

        assert excinfo.value.call_record.exit_code == 1
        assert excinfo.value.call_record.input_artifact_sha256 is None
        assert "exit_code=1" in str(excinfo.value)
