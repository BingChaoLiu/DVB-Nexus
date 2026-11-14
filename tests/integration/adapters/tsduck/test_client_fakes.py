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
    TSDuckCancelledError,
    TSDuckJsonGateError,
    TSDuckSpawnFailedError,
    TSDuckTimeoutError,
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


class FailingRunner:
    """Runner seam for the §9 failure family: raises like the real runner.

    The real runner (process.py) raises TSDuckTimeoutError/TSDuckCancelled-
    Error with ``partial_result`` attached (the drained partial run) and
    TSDuckSpawnFailedError bare; this fake reproduces exactly that surface
    so the client's failure-path recording duty (review fix A1) is
    exercised without spawning anything.
    """

    def __init__(self, error: Exception) -> None:
        self.error = error

    async def run_async(self, argv, *, timeout=None, env=None, on_start=None):
        raise self.error


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
def fake_tsp(tmp_path: Path) -> Path:
    """The probed ``tsp`` inside a fake TSDuck bin dir, plus the tsanalyze
    sibling the client resolves.

    Both names are platform-shaped (``sys.platform`` branch, review fix B7):
    tests hand THIS file to the probe, so on Linux the probed executable is
    the existing ``tsp`` — not a nonexistent ``tsp.exe`` that only passes by
    accident because the probe is fake. The pass reason is direct.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    tsp = bin_dir / ("tsp.exe" if sys.platform == "win32" else "tsp")
    tsp.write_bytes(b"")
    tsanalyze_name = "tsanalyze.exe" if sys.platform == "win32" else "tsanalyze"
    (bin_dir / tsanalyze_name).write_bytes(b"")
    return tsp


@pytest.fixture
def make_client(fake_tsp: Path):
    """TSDuckClient factory over the fake install (review fix B7).

    One construction point instead of eight inline ``TSDuckClient(probe=…,
    runner=…)`` copies: default wiring is the available fake probe bound to
    the platform-shaped ``fake_tsp``; tests override the runner (canned
    results / failure seams), the synthetic version token, or the whole
    probe for the negative cases.
    """

    def _make(
        runner=None,
        *,
        version: str = FAKE_VERSION,
        probe=None,
    ) -> TSDuckClient:
        return TSDuckClient(
            probe=(
                probe if probe is not None else _available_probe(fake_tsp, version)
            ),
            runner=runner,
        )

    return _make


class TestAnalyzeOrchestration:
    def test_analyze_builds_whitelist_argv_and_records_nine_fields(
        self, tmp_path, make_client
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
        client = make_client(runner)

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

    def test_analyze_returns_normalized_report(self, tmp_path, make_client):
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
        client = make_client(runner)

        result = asyncio.run(client.analyze(ts_file))

        assert result.report.ts.bytes == 188_000
        assert result.report.ts.services_total == 1
        assert result.report.source_document  # raw JSON kept for the artifact

    def test_timeout_forwarded_to_runner(self, tmp_path, make_client):
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
        client = make_client(runner)

        asyncio.run(client.analyze(ts_file, timeout=7.5))

        assert runner.calls[0]["timeout"] == 7.5

    def test_gate_failure_carries_the_call_record(self, tmp_path, make_client):
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
        client = make_client(runner)

        with pytest.raises(TSDuckJsonGateError) as excinfo:
            asyncio.run(client.analyze(ts_file, run_id="run-9"))

        record = excinfo.value.call_record
        assert record is not None
        assert record.exit_code == 0
        assert record.input_artifact_sha256 == hashlib.sha256(bytes(16)).hexdigest()
        assert record.run_id == "run-9"


class TestFailurePathCallRecords:
    """§7 recording duty holds on the §9 failure family (SPEC-308 §7/§9,
    review fix A1, REQ-TSK-308-002): timeout/cancellation/spawn failure must
    still produce the nine-field call record — it travels on the raised
    error as ``call_record``; fields with no data are explicit ``None``,
    never fabricated."""

    def test_timeout_record_nine_fields_from_the_partial_run(
        self, tmp_path, make_client
    ):
        ts_file = tmp_path / "input.ts"
        ts_file.write_bytes(bytes(32))
        error = TSDuckTimeoutError("tree killed after timeout")
        # The real runner's partial shape: drained streams, kill exit code.
        error.partial_result = ProcessResult(
            argv=(),
            exit_code=1,
            stdout=b"",
            stderr=b"partial stderr bytes",
            duration_seconds=2.0,
            pid=99,
            timed_out=True,
        )
        client = make_client(FailingRunner(error))

        with pytest.raises(TSDuckTimeoutError) as excinfo:
            asyncio.run(client.analyze(ts_file, run_id="run-timeout"))

        record = excinfo.value.call_record
        assert record is not None
        assert excinfo.value.partial_result is error.partial_result
        assert record.version == FAKE_VERSION
        assert record.executable_path is not None
        assert Path(record.executable_path).is_file()
        assert record.argv == ("tsanalyze", "--json", str(ts_file))
        assert record.started_at <= record.finished_at
        assert record.exit_code == 1
        assert record.stdout_text == ""  # captured-but-empty is data
        assert record.stderr_text == "partial stderr bytes"  # display decode
        assert record.input_artifact_sha256 == hashlib.sha256(bytes(32)).hexdigest()
        assert record.run_id == "run-timeout"

    def test_cancelled_record_nine_fields_from_the_partial_run(
        self, tmp_path, make_client
    ):
        ts_file = tmp_path / "input.ts"
        ts_file.write_bytes(bytes(16))
        error = TSDuckCancelledError("tree killed on cancellation")
        error.partial_result = ProcessResult(
            argv=(),
            exit_code=1,
            stdout=b"partial stdout bytes",
            stderr=b"",
            duration_seconds=0.5,
            pid=7,
            cancelled=True,
        )
        client = make_client(FailingRunner(error))

        with pytest.raises(TSDuckCancelledError) as excinfo:
            asyncio.run(client.analyze(ts_file, run_id="run-cancel"))

        record = excinfo.value.call_record
        assert record is not None
        assert record.version == FAKE_VERSION
        assert record.argv == ("tsanalyze", "--json", str(ts_file))
        assert record.started_at <= record.finished_at
        assert record.exit_code == 1
        assert record.stdout_text == "partial stdout bytes"
        assert record.stderr_text == ""
        assert record.input_artifact_sha256 == hashlib.sha256(bytes(16)).hexdigest()
        assert record.run_id == "run-cancel"

    def test_spawn_failure_record_carries_explicit_none_for_no_data(
        self, tmp_path, make_client
    ):
        """Nothing was spawned and nothing was captured: exit code and the
        two stream fields are explicit ``None`` — 不虚构 (§7 duty still
        holds for the fields that DO have data)."""
        ts_file = tmp_path / "input.ts"
        ts_file.write_bytes(bytes(16))
        client = make_client(FailingRunner(TSDuckSpawnFailedError("spawn boom")))

        with pytest.raises(TSDuckSpawnFailedError) as excinfo:
            asyncio.run(client.analyze(ts_file, run_id="run-spawn"))

        record = excinfo.value.call_record
        assert record is not None
        assert record.version == FAKE_VERSION
        assert record.executable_path is not None
        assert Path(record.executable_path).is_file()
        assert record.argv == ("tsanalyze", "--json", str(ts_file))
        assert record.started_at <= record.finished_at
        assert record.exit_code is None
        assert record.stdout_text is None
        assert record.stderr_text is None
        # the pre-spawn hash (B9) is real data even when the spawn failed:
        assert record.input_artifact_sha256 == hashlib.sha256(bytes(16)).hexdigest()
        assert record.run_id == "run-spawn"


class TestClientErrorFamily:
    def test_unavailable_probe_raises_not_found(self):
        client = TSDuckClient(probe=_unavailable_probe())
        with pytest.raises(TSDuckNotFoundError):
            asyncio.run(client.get_version())

    def test_below_baseline_raises_unsupported(self, make_client):
        # 3.39 < MVP baseline 3.40 — synthetic fixture token, not an env claim.
        client = make_client(version="3.39-4165")
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
        self, tmp_path, make_client
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
        client = make_client(runner)

        with pytest.raises(TSDuckJsonGateError) as excinfo:
            asyncio.run(client.analyze(missing))

        assert excinfo.value.call_record.exit_code == 1
        assert excinfo.value.call_record.input_artifact_sha256 is None
        assert "exit_code=1" in str(excinfo.value)
