"""L2 TSDuck bidirectional cross-verification through the PRODUCTION adapter.

Ticket #38 / SPEC-506 §5 (three-layer acceptance, #14 Q1): L2 TSDuck 双向交叉
= 合格独立验证路径.  Ticket #36 already crosses the registered vectors with
the raw TSDuck CLI (``test_tsduck_cross_verification.py``); this module runs
the cross through the PRODUCTION analyze chain (``adapters.tsduck.client``
— ticket #37, imported, never re-implemented):

- **验证方向** (self-generate→tsduck-analyze): golden forward vectors →
  ``TSDuckClient.analyze`` (probe → whitelist argv → JSON content gate →
  normalized report) → every registered expectation (the L1 golden
  assertions, ADR-0007 第 5 条同构) must be observable in the normalized
  report;
- **生成方向** (tsduck-generate vs M1 generator): the SAME table config
  generated once by the TSDuck toolchain (tsxml → tstabcomp → tsp inject,
  the #3-tested chain) and once by the M1 Generator (SPEC-108, via the
  ``ts_e2e`` generation seam) → both streams analyzed by the production
  adapter → the same PSI observable set (SPEC-506 §7: 对同配置流断言同一
  expectations 可观测, **不做字节比对** — different muxers, different bytes);
- **faulted symptoms through the adapter**: the faulted vectors' symptoms
  are independently observable in the adapter's normalized report /
  registered findings / content-gate refusals — the adapter never accepts a
  broken stream as valid merely because the bytes parse.

Assertions are muxer-independent semantics (PIDs, table ids, service/PMT/
PCR/component associations, packet-count deltas on registered slots) —
never environment literals (tests/README.md §6: version tokens, drive
paths and executable casings differ between the reference machine and CI;
TSDuck stderr is GBK-localized and only ever decoded ``errors="replace"``).
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from tests._support.paths import GOLDEN_ROOT
from tests._support.tsduck_probe import TSDuckProbe
from tests._support.tsduck_cli import resolve_tool

from adapters.tsduck.client import TSDuckClient
from adapters.tsduck.process import TSDuckProcessRunner
from adapters.tsduck.report_parser import report_findings
from adapters.tsduck.version import TSDuckVersionProbe
from domain.observation import ConfidenceKind, ObservationSource

pytestmark = [pytest.mark.conformance, pytest.mark.tsduck]

#: Registered forward vectors whose expectations are service-bearing — the
#: JSON content gate (``ts.services.total >= 1``, ticket #3) requires a
#: PAT→PMT association, so only these can cross the production analyze chain.
#: The remaining forward vectors (cc-wrap / pcr-wrap / section-fragmentation)
#: keep their L2 cross via the raw CLI module (tstables / pcrextract /
#: continuity) — same red line, different observation surface.
SERVICE_BEARING_FORWARD_VECTORS = (
    "pat-minimal",
    "pat-pmt-multi",
    "pat-missing-baseline",
    "pmt-invalid-crc-baseline",
    "cc-discontinuity-baseline",
    "pmt-pid-mismatch-baseline",
)

#: The registered same-config semantic anchor for the generation direction:
#: the four faulted baselines share one SPEC-108 pull-safe geometry stream
#: (tsid 1 / program 1 / pmt 4096 / pcr 256 / ES 27@256 + 3@257).
GENERATION_ANCHOR_VECTOR = "pat-missing-baseline"


class _FixtureBoundProbe(TSDuckVersionProbe):
    """Production probe semantics, bound to the fixture's resolved executable.

    The ``tsduck`` fixture (SPEC-505 §4) owns availability/skip and the
    ``DVB_NEXUS_TSP_PATH`` override; binding the production probe to the
    fixture's executable keeps the client on production behavior (explicit
    override resolution) without re-implementing any probe logic.
    """

    def __init__(self, executable: str) -> None:
        super().__init__()
        self._executable = executable

    def probe(self, *, override=None):  # noqa: ANN001 - production signature
        return super().probe(override=self._executable)


@pytest.fixture
def client(tsduck: TSDuckProbe) -> TSDuckClient:
    return TSDuckClient(
        probe=_FixtureBoundProbe(tsduck.executable),
        runner=TSDuckProcessRunner(default_timeout=60.0),
    )


def _golden_ts(vector_id: str) -> Path:
    return GOLDEN_ROOT / vector_id / f"{vector_id}.ts"


def _analyze(client: TSDuckClient, path: Path):
    """Sync facade over the production async analyze chain (#37 facade shape)."""
    return asyncio.run(client.analyze(path, run_id="conformance-l2-cross"))


def _expected_component_set(detail: dict, pmt_pid: int) -> set[int]:
    """tsanalyze counts a service's components as its associated PIDs:
    the PMT pid itself, the PCR pid and the PMT-declared ES pids
    (measured 3.40-4165, docs/research/tsduck-env.md §4.2)."""
    components = {pmt_pid}
    pcr_pid = detail.get("pcr_pid")
    if pcr_pid is not None:
        components.add(pcr_pid)
    components.update(stream["pid"] for stream in detail.get("streams", ()))
    return components


def _assert_expectations_observable(report, expectations) -> None:
    """Cross-check registered golden expectations against the normalized report.

    Muxer-independent semantics only: packet_index slots are the shared
    baseline/faulted frame (ADR-0007 第 4 条) and are deliberately NOT
    asserted here — tsanalyze has no per-packet-index observation surface,
    and different muxers legitimately place packets differently (§7).
    """
    for expectation in expectations:
        event_type = expectation["event_type"]
        locator = expectation["locator"]
        detail = expectation.get("detail", {})
        pid = locator.get("pid")

        if event_type == "ts.psi_section_observed":
            table_id = detail.get("table_id")
            assert any(
                table.pid == pid and (table_id is None or table.table_id == table_id)
                for table in report.tables
            ), f"table {pid}/tid={table_id} not observable: {report.tables}"
            tsid = detail.get("transport_stream_id")
            if tsid is not None:
                assert report.ts.transport_stream_id == tsid
            for program in detail.get("programs", ()):
                service = next(
                    (
                        service
                        for service in report.services
                        if service.service_id == program["program_number"]
                    ),
                    None,
                )
                assert service is not None, f"program {program} not in services"
                assert service.pmt_pid == program["pmt_pid"]
            if "service_id" in detail:
                service = next(
                    (
                        service
                        for service in report.services
                        if service.service_id == detail["service_id"]
                    ),
                    None,
                )
                assert service is not None, f"service {detail['service_id']} missing"
                if "pcr_pid" in detail:
                    assert service.pcr_pid == detail["pcr_pid"]
                expected_components = _expected_component_set(detail, pid)
                assert service.components_total == len(expected_components)

        elif event_type == "ts.packet_batch_observed":
            pid_report = next(
                (row for row in report.pids if row.pid == pid), None
            )
            assert pid_report is not None, f"PID {pid} not observable in report"
            assert pid_report.packets_total >= 1
            if detail.get("pcr_present"):
                assert pid_report.pcr >= 1, f"no PCR carrier seen on PID {pid}"

        else:
            pytest.fail(f"expectation type not crossable via adapter: {event_type}")


# --- 验证方向: golden forward vectors through the production adapter ----------


class TestVerificationDirection:
    @pytest.mark.parametrize("vector_id", SERVICE_BEARING_FORWARD_VECTORS)
    def test_registered_expectations_observable_in_adapter_report(
        self, golden_loader, client, vector_id
    ):
        vector = golden_loader.load(vector_id)
        assert vector.verification is not None
        assert vector.verification.path == "tsduck-cross"

        result = _analyze(client, _golden_ts(vector_id))

        # byte-identity linkage: the adapter hashed the very bytes the
        # loader verified (sha256 即身份, SPEC-506 §6).
        assert result.call_record.input_artifact_sha256 == vector.sha256
        # the registered L1 golden assertions hold on the independent tool's
        # report, through the production analyze chain end to end.
        _assert_expectations_observable(result.report, vector.expectations)


# --- faulted symptoms independently observable through the adapter ------------


class TestFaultedSymptomsThroughAdapter:
    def test_pat_missing_window_shrinks_pid0_packet_count(
        self, golden_loader, client
    ):
        golden_loader.load("pat-missing")  # registered pair
        counts = {}
        for label in ("pat-missing-baseline", "pat-missing"):
            result = _analyze(client, _golden_ts(label))
            pid0 = next(row for row in result.report.pids if row.pid == 0)
            counts[label] = pid0.packets_total
        # the PAT_MISSING window (Null 顶替, SPEC-204 §6.1) is independently
        # visible as the PAT repetition count dropping 3 → 1 on PID 0.
        assert counts["pat-missing-baseline"] == 3
        assert counts["pat-missing"] == 1

    def test_cc_discontinuity_surfaces_as_registered_finding(
        self, golden_loader, client
    ):
        baseline = golden_loader.load("cc-discontinuity-baseline")
        faulted = golden_loader.load("cc-discontinuity")

        baseline_findings = report_findings(_analyze(client, _golden_ts(baseline.vector_id)).report)
        assert baseline_findings == ()  # continuous baseline: silent

        faulted_result = _analyze(client, _golden_ts(faulted.vector_id))
        findings = report_findings(faulted_result.report)
        entry = next(
            (f for f in findings if f.event_type == "ts.continuity_error" and f.pid == 256),
            None,
        )
        assert entry is not None, "CC_DISCONTINUITY symptom not surfaced"
        assert entry.value["count"] >= 1  # the persisted offset deltas
        # SPEC-308 §8 marking: parsed TSDuck observation, never "measured".
        assert entry.source == ObservationSource.TSDUCK
        assert entry.confidence == ConfidenceKind.PARSED

    def test_pmt_invalid_crc_independently_dropped(self, golden_loader, client):
        """PMT_INVALID_CRC (SPEC-204 §6.2): the independent demuxer refuses
        every PMT instance — the normalized service loses the PCR binding and
        collapses to the PAT-declared association PID only, while the
        baseline shows the bound PMT with all components (the expectations'
        pcr_pid / streams semantics, observed through the production chain)."""
        baseline_id = "pmt-invalid-crc-baseline"
        golden_loader.load(baseline_id)
        faulted = golden_loader.load("pmt-invalid-crc")
        services = {}
        for label, vector_id in (("baseline", baseline_id), ("faulted", faulted.vector_id)):
            result = _analyze(client, _golden_ts(vector_id))
            services[label] = next(
                service
                for service in result.report.services
                if service.service_id == 1
            )
        assert services["baseline"].pcr_pid == 256
        assert services["baseline"].components_total == 3
        assert services["faulted"].pmt_pid == 4096  # PAT-declared association survives
        assert services["faulted"].pcr_pid is None  # no accepted PMT → unbound
        assert services["faulted"].components_total == 1  # only the PMT PID

    def test_pmt_pid_mismatch_repoint_independently_observable(
        self, golden_loader, client
    ):
        """PMT_PID_MISMATCH (SPEC-204 §6.4): the independent tool sees the
        PAT's repointed (wrong) association PID — exactly the faulted vector's
        registered programs detail — and no PMT at that PID, so the PCR stays
        unbound."""
        faulted = golden_loader.load("pmt-pid-mismatch")
        programs_detail = next(
            expectation["detail"]["programs"]
            for expectation in faulted.expectations
            if expectation["locator"]["pid"] == 0
        )
        result = _analyze(client, _golden_ts(faulted.vector_id))
        service = next(
            service
            for service in result.report.services
            if service.service_id == 1
        )
        assert [program["pmt_pid"] for program in programs_detail] == [service.pmt_pid]
        assert service.pmt_pid == 4100  # the wrong PID, independently seen
        assert service.pcr_pid is None


# --- 生成方向: TSDuck toolchain vs M1 generator, same config ------------------


#: tsxml sources for the GENERATION_ANCHOR config (tools/tsduck-tsxml schema;
#: text assets, not TS bytes — tests/README §5 discipline).  Same tables as
#: the M1 generator's pull-safe geometry: tsid 1 / program 1 / pmt 4096 /
#: pcr 256 / ES 27@256 + 3@257.
PAT_TSXML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    "<tsduck>\n"
    '  <PAT version="0" current="true" transport_stream_id="0x0001">\n'
    '    <service service_id="0x0001" program_map_PID="0x1000"/>\n'
    "  </PAT>\n"
    "</tsduck>\n"
)
PMT_TSXML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    "<tsduck>\n"
    '  <PMT version="0" current="true" service_id="0x0001" PCR_PID="0x0100">\n'
    '    <component elementary_PID="0x0100" stream_type="0x1B"/>\n'
    '    <component elementary_PID="0x0101" stream_type="0x03"/>\n'
    "  </PMT>\n"
    "</tsduck>\n"
)


def _generate_via_tsduck_toolchain(tsduck: TSDuckProbe, tmp_path: Path) -> Path:
    """tsxml → tstabcomp → tsp inject (the #3-tested chain; argv shape per
    tools/make_golden_tsduck_vectors.py).  TSDuck failures fail loudly —
    no silent degradation (#3: exit codes are diagnostics, here a nonzero
    toolchain exit is a broken chain, not a data verdict)."""
    tstabcomp = resolve_tool(tsduck.executable, "tstabcomp")
    xml_dir = tmp_path / "tsxml"
    xml_dir.mkdir()
    binaries = []
    for name, text in (("pat", PAT_TSXML), ("pmt", PMT_TSXML)):
        xml = xml_dir / f"{name}.xml"
        xml.write_text(text, encoding="utf-8")
        binary = tmp_path / f"{name}.bin"
        result = subprocess.run(
            [tstabcomp, "--output", str(binary), str(xml)],
            capture_output=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
        binaries.append(binary)

    output = tmp_path / "tsduck-chain.ts"
    inject_args: list[str] = []
    for pid, binary in (("0x0", binaries[0]), ("0x1000", binaries[1])):
        inject_args += [
            "-P", "inject", "-p", pid, "--inter-packet", "100",
            "--stuffing", str(binary),
        ]
    result = subprocess.run(
        [tsduck.executable, "-I", "null", "600", *inject_args, "-O", "file", str(output)],
        capture_output=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    size = output.stat().st_size
    assert size > 0 and size % 188 == 0  # a real packetized stream came out
    return output


def _generate_via_m1_generator(tmp_path: Path) -> Path:
    """The same config through the M1 Generator (SPEC-108) — via the
    ``ts_e2e`` generation seam (the #34-proven pull-safe geometry; zero
    parallel generator copies)."""
    from tests._support.ts_e2e import generate_chunks, integration_config

    chunks, _summary = generate_chunks(integration_config())
    output = tmp_path / "m1-generator.ts"
    output.write_bytes(b"".join(chunks))
    return output


def _psi_observables(report) -> tuple:
    """Muxer-independent PSI observable set of a normalized report:
    transport_stream_id + per-service (id, pmt_pid, pcr_pid, components)
    + the observed PSI table rows (pid, table_id).  Repetition counts and
    packet placement are muxer decisions and deliberately excluded (§7)."""
    return (
        report.ts.transport_stream_id,
        tuple(
            sorted(
                (service.service_id, service.pmt_pid, service.pcr_pid,
                 service.components_total)
                for service in report.services
            )
        ),
        tuple(
            sorted((table.pid, table.table_id) for table in report.tables)
        ),
    )


class TestGenerationDirection:
    def test_tsduck_toolchain_and_m1_generator_exhibit_same_expectations(
        self, golden_loader, client, tsduck, tmp_path
    ):
        anchor = golden_loader.load(GENERATION_ANCHOR_VECTOR)
        psi_expectations = tuple(
            expectation
            for expectation in anchor.expectations
            if expectation["event_type"] == "ts.psi_section_observed"
        )
        assert len(psi_expectations) == 2  # PAT + PMT of the shared geometry

        tsduck_ts = _generate_via_tsduck_toolchain(tsduck, tmp_path)
        generator_ts = _generate_via_m1_generator(tmp_path)

        observables = []
        for label, path in (("tsduck-chain", tsduck_ts), ("m1-generator", generator_ts)):
            result = _analyze(client, path)
            # each stream independently exhibits the anchor's registered
            # PSI expectations (SPEC-506 §7: 同一 expectations 可观测).
            _assert_expectations_observable(result.report, psi_expectations)
            observables.append((label, _psi_observables(result.report)))

        # same config ⇒ same observable set, regardless of the muxer that
        # produced the bytes — and NOT byte equality (different muxers).
        assert observables[0][1] == observables[1][1]
        assert tsduck_ts.read_bytes() != generator_ts.read_bytes()
