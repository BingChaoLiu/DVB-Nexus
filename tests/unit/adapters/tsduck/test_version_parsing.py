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

import pytest

from adapters.tsduck.version import (
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
