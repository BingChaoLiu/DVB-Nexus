"""Version-line extraction surface (SPEC-308 §3 ``version.py``, ticket #25).

Seam 3 of the delegator-approved seam list: version-line parsing at the
probe's public extraction surface ``scan_for_version`` — the one sanctioned
stderr-extraction per ADR-0005 decision 6 (adapter-worker stderr otherwise
stays display-only per SPEC-308 §7).

Synthetic line fixtures are anchored to the **measured** assets in
``docs/research/tsduck-env.md`` (ticket #3 实测; re-measured for #25 on
2026-11-14: ``tsp --version`` writes stdout=0 bytes and one stderr line
``tsp: TSDuck - The MPEG Transport Stream Toolkit - version 3.40-4165``).
These are ordinary test text, not TS byte streams (禁手拼字节 rule governs
TS byte payloads only). Expected values are literals here — an independent
source of truth that disagrees if the implementation regex drifts.
"""

from pathlib import Path

import pytest

from adapters.tsduck.version import (
    ResolutionSource,
    TSDuckProbeResult,
    TSDuckUnavailableReason,
    TSDuckVersion,
    VersionMatch,
    VersionStream,
    extract_version,
    scan_for_version,
)

# Measured anchor (docs/research/tsduck-env.md §2.1 / §6.2).
MEASURED_LINE = "TSDuck - The MPEG Transport Stream Toolkit - version 3.40-4165"
# Measured stderr carries a "tsp: " program prefix before the version line.
MEASURED_STDERR_LINE = f"tsp: {MEASURED_LINE}"


class TestScanForVersionMeasuredLine:
    def test_finds_measured_version_line_on_stderr(self):
        match = scan_for_version(
            stdout=b"",
            stderr=(MEASURED_STDERR_LINE + "\r\n").encode("utf-8"),
        )

        assert match is not None
        assert match.version == "3.40-4165"
        assert (match.major, match.minor, match.build) == (3, 40, 4165)
        assert match.stream is VersionStream.STDERR
        assert match.raw_version_line == MEASURED_STDERR_LINE

    def test_stdout_scanned_before_stderr(self):
        # Ordering discipline of the extraction surface: when both streams
        # carry a valid line, stdout wins (stdout is the spec's primary
        # JSON/report channel, SPEC-308 §7).
        match = scan_for_version(
            stdout=(MEASURED_LINE + "\r\n").encode("utf-8"),
            stderr=(MEASURED_STDERR_LINE + "\r\n").encode("utf-8"),
        )

        assert match is not None
        assert match.stream is VersionStream.STDOUT
        assert match.raw_version_line == MEASURED_LINE

    def test_version_check_noise_line_never_matches(self):
        # Measured runtime noise (tsduck-env.md §2.2): TSDuck periodically
        # prints `* new TSDuck version 3.45-4798 is available (yours is
        # 3.40-4165), ...` — a naive `version (\d+\.\d+-\d+)` search would
        # report the WRONG (upstream) version from that line. The measured
        # line shape must win; `*`-prefixed TSDuck log lines (the measured
        # noise/message prefix, §2.2/§4.4) are never a version report.
        noise = (
            "* new TSDuck version 3.45-4798 is available (yours is 3.40-4165), "
            "use 'tsversion --upgrade' or see https://tsduck.io/"
        )
        payload = (noise + "\r\ntsp: " + MEASURED_LINE + "\r\n").encode("utf-8")

        match = scan_for_version(stdout=b"", stderr=payload)

        assert match is not None
        assert match.version == "3.40-4165"
        assert match.raw_version_line == MEASURED_STDERR_LINE

    def test_noise_only_payload_yields_none(self):
        # An update-notification line alone is not a version report.
        noise = (
            "* new TSDuck version 3.45-4798 is available (yours is 3.40-4165), "
            "use 'tsversion --upgrade'"
        )
        assert scan_for_version(stdout=b"", stderr=noise.encode("utf-8")) is None

    def test_non_canonical_line_still_matches_via_loose_tier(self):
        # Future tolerance: a line without the measured "Toolkit -" prefix
        # but carrying the version token (and not a `*` log line) still
        # matches through the loose tier of the measured regex.
        payload = "TSDuck version 3.42-4380\r\n".encode("utf-8")

        match = scan_for_version(stdout=payload, stderr=b"")

        assert match is not None
        assert (match.major, match.minor, match.build) == (3, 42, 4380)

    def test_garbage_payload_yields_none(self):
        # The measured-regex gate: no "version <major>.<minor>-<build>"
        # token anywhere in either stream → no match (exit 0 never gates,
        # ticket #3 — garbage stdout payloads parse to nothing here).
        assert scan_for_version("hello garbage world".encode("utf-8"), b"") is None
        assert scan_for_version(b"", b"\r\n\r\n") is None

    def test_gbk_encoded_stderr_decodes_via_fallback(self):
        # Decode policy (test-pinned): UTF-8 first, GBK fallback. The
        # GBK-localized error text from tsduck-env.md §4.4 ("cannot open
        # file" system message) is invalid as UTF-8; the version line that
        # follows is ASCII and must still be found.
        gbk_error = "tsanalyze: cannot open data/no_such.ts: 系统找不到指定的文件。"
        payload = (gbk_error + "\r\n" + MEASURED_STDERR_LINE + "\r\n").encode("gbk")

        match = scan_for_version(stdout=b"", stderr=payload)

        assert match is not None
        assert match.version == "3.40-4165"
        assert match.stream is VersionStream.STDERR


class TestExtractVersionSurface:
    def test_measured_regex_extracts_token(self):
        assert extract_version(MEASURED_LINE) == "3.40-4165"
        assert extract_version(MEASURED_STDERR_LINE) == "3.40-4165"

    def test_non_version_lines_return_none(self):
        assert extract_version("tsp: some other tool output") is None
        assert extract_version("") is None
        # Incomplete tokens do not match the measured shape (d+.d+-d+).
        assert extract_version("version 3.40") is None
        assert extract_version("version 3.40-") is None


class TestProbeResultInvariants:
    """Frozen-result contract the M2 client consumes (SPEC-308 §4)."""

    def test_available_result_without_version_rejected(self):
        with pytest.raises(ValueError):
            TSDuckProbeResult(
                available=True,
                version=None,
                reason=None,
                detail="broken",
            )

    def test_unavailable_result_without_reason_rejected(self):
        with pytest.raises(ValueError):
            TSDuckProbeResult(
                available=False,
                version=None,
                reason=None,
                detail="broken",
            )

    def test_available_result_with_reason_rejected(self):
        version = TSDuckVersion(
            executable=Path("tsp.exe"),
            version="3.40-4165",
            major=3,
            minor=40,
            build=4165,
            raw_version_line=MEASURED_LINE,
            stream=VersionStream.STDERR,
            resolution=ResolutionSource.PATH,
        )
        with pytest.raises(ValueError):
            TSDuckProbeResult(
                available=True,
                version=version,
                reason=TSDuckUnavailableReason.NOT_EXECUTABLE,
                detail="broken",
            )

    def test_reason_enumeration_covers_ticket_25_contract(self):
        # The three structured unavailability reasons of the ticket body.
        assert TSDuckUnavailableReason.NOT_INSTALLED.value == "not_installed"
        assert TSDuckUnavailableReason.NOT_EXECUTABLE.value == "not_executable"
        assert TSDuckUnavailableReason.VERSION_UNPARSEABLE.value == "version_unparseable"
