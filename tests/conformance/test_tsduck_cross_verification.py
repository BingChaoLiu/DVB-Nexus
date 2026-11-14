"""TSDuck cross-verification of the registered first-batch vectors.

Conformance layer, ``tsduck``-marked (SPEC-506 §6 / #14 Q6): these tests
run in CI **in full** (the Windows CI job installs ``TSDuck.TSDuck`` via
winget; an install failure fails the job — never a skip).  On a local
developer machine without TSDuck the ``tsduck`` fixture skips with an
explicit, summary-visible reason (SPEC-505 §5) — the conformance summary
then carries those vectors as **NOT RUN** in its own block, never as PASS
(#14: 兜底仅限本地, 不冒绿).

Assertions are shape-level vector facts (PIDs, program numbers, counts) —
never environment literals (tests/README.md §6: TSDuck stderr is GBK-
localized and only decoded with ``errors="replace"``, never parsed for
semantics; tool versions are recorded in the per-vector verification
notes, not asserted here).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tests._support.tsduck_cli import resolve_tool

pytestmark = [pytest.mark.conformance, pytest.mark.tsduck]

PCR_WRAP_TICKS = [
    ((1 << 33) - 3) * 300,
    ((1 << 33) - 2) * 300,
    ((1 << 33) - 1) * 300,
    0,  # the wrap step
    300,
    600,
]


def _run(argv: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, timeout=timeout)


def _run_tsp(tsduck, args: list[str], timeout: int = 120) -> str:
    """Run ``tsp -I file <vector> ... -O drop <plugin>``; return the report.

    TSDuck plugin reports (pcrextract CSV rows, continuity findings) are
    emitted on the message channel (stderr); stdout stays empty for
    ``-O drop``.  Decoding is ``errors="replace"`` on both streams (SPEC-308
    GBK discipline) — only the ASCII data-report lines are matched below,
    never localized diagnostics.
    """
    result = _run([tsduck.executable, "-I", "file", *args, "-O", "drop"], timeout)
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    return result.stdout.decode("utf-8", "replace") + result.stderr.decode(
        "utf-8", "replace"
    )


def _golden_path(vector_id: str) -> Path:
    from tests._support.paths import GOLDEN_ROOT

    return GOLDEN_ROOT / vector_id / f"{vector_id}.ts"


# --- PSI vectors: table reassembly ---------------------------------------------


@pytest.mark.parametrize(
    "vector_id",
    ["pat-minimal", "pat-pmt-multi", "section-fragmentation"],
)
def test_tsduck_reassembles_registered_psi_tables(golden_loader, tsduck, vector_id):
    vector = golden_loader.load(vector_id)
    assert vector.kind == "generated_ts"
    result = _run(
        [resolve_tool(tsduck.executable, "tstables"), str(_golden_path(vector_id))]
    )
    assert result.returncode == 0
    out = result.stdout.decode("utf-8", "replace")
    assert "* PAT" in out
    if vector_id == "pat-minimal":
        assert "TS id:       1" in out
        assert "Program:     1 (0x0001)  PID: 4096 (0x1000)" in out
        assert out.count("* PMT") == 1
    elif vector_id == "pat-pmt-multi":
        assert "Program:     1 (0x0001)  PID: 4096 (0x1000)" in out
        assert "Program:     2 (0x0002)  PID: 4352 (0x1100)" in out
        assert out.count("* PMT") == 2  # both PMTs found on their real PIDs
    else:  # section-fragmentation: the 3-packet section reassembles whole
        assert "total size: 412 bytes" in out
        assert out.count("Program:") == 100


# --- cc-wrap: continuity silence across the wrap --------------------------------


def test_tsduck_continuity_silent_on_cc_wrap(golden_loader, tsduck):
    golden_loader.load("cc-wrap")  # registered
    out = _run_tsp(
        tsduck,
        [str(_golden_path("cc-wrap")), "-P", "continuity"],
    )
    assert out.strip() == ""  # no continuity findings across the 15→0 wrap


# --- pcr-wrap: independent 27 MHz readback ---------------------------------------


def test_tsduck_pcrextract_reads_wrapped_pcr_values(golden_loader, tsduck):
    golden_loader.load("pcr-wrap")  # registered
    out = _run_tsp(
        tsduck,
        [str(_golden_path("pcr-wrap")), "-P", "pcrextract"],
    )
    rows = [line.split(",") for line in out.strip().splitlines()[1:]]
    values = [int(row[5]) for row in rows]
    assert values == PCR_WRAP_TICKS  # includes the wrap step ...300 → 0


# --- faulted pairs: symptoms observable by the independent tool ------------------


def test_tsduck_sees_pat_stopping_at_activation_window(golden_loader, tsduck):
    baseline = golden_loader.load("pat-missing-baseline")
    faulted = golden_loader.load("pat-missing")
    counts = {}
    for label, vector in (("baseline", baseline), ("faulted", faulted)):
        result = _run(
            [
                resolve_tool(tsduck.executable, "tsanalyze"),
                "--json",
                str(_golden_path(vector.vector_id)),
            ]
        )
        assert result.returncode == 0
        doc = json.loads(result.stdout.decode("utf-8", "replace"))
        pid0 = next(p for p in doc["pids"] if p["id"] == 0)
        counts[label] = pid0["packets"]["total"]
    assert counts["baseline"] == 3  # PAT slots 0/202/404
    assert counts["faulted"] == 1  # only slot 0 — PAT_MISSING window


def test_tsduck_rejects_crc_invalid_pmt(golden_loader, tsduck):
    golden_loader.load("pmt-invalid-crc-baseline")
    golden_loader.load("pmt-invalid-crc")
    services = {}
    for label, vector_id in (
        ("baseline", "pmt-invalid-crc-baseline"),
        ("faulted", "pmt-invalid-crc"),
    ):
        result = _run(
            [
                resolve_tool(tsduck.executable, "tsanalyze"),
                "--json",
                str(_golden_path(vector_id)),
            ]
        )
        assert result.returncode == 0
        doc = json.loads(result.stdout.decode("utf-8", "replace"))
        services[label] = doc["services"][0]
    # Baseline: PMT accepted (PCR PID bound, all three component PIDs seen).
    assert services["baseline"]["pcr-pid"] == 256
    assert services["baseline"]["components"]["total"] == 3
    # Faulted: CRC-invalid PMT dropped — no PCR PID bound, PMT PID only.
    assert "pcr-pid" not in services["faulted"]
    assert services["faulted"]["pids"] == [4096]


def test_tsduck_flags_cc_discontinuity_at_landing_slot(golden_loader, tsduck):
    golden_loader.load("cc-discontinuity")  # registered
    out = _run_tsp(
        tsduck,
        [str(_golden_path("cc-discontinuity")), "-P", "continuity"],
    )
    assert "PID: 0x0100 (256)" in out
    assert "packet index: 50" in out  # the frozen landing slot
    assert "missing 3 packets" in out  # the frozen delta


def test_tsduck_sees_repointed_pat_and_orphan_pmt(golden_loader, tsduck):
    golden_loader.load("pmt-pid-mismatch")  # registered
    result = _run(
        [resolve_tool(tsduck.executable, "tstables"), str(_golden_path("pmt-pid-mismatch"))]
    )
    assert result.returncode == 0
    out = result.stdout.decode("utf-8", "replace")
    # PAT repointed to the wrong PID…
    assert "Program:     1 (0x0001)  PID: 4100 (0x1004)" in out
    # …while the untouched PMT remains on the real PID (orphaned).
    assert "* PMT, TID 0x02 (2), PID 0x1000 (4096)" in out
