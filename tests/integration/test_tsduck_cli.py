"""TSDuck CLI presence test — ``tsduck`` marker (SPEC-505 §4/§5, SPEC-308).

Runs only where the TSDuck CLI is available. Skip path: the ``tsduck``
fixture skips with an explicit, summary-visible reason (兜底仅限本地 per
#14; the Windows CI job installs ``TSDuck.TSDuck`` via winget and any
install failure fails the job, so this test never silently vanishes).
"""

from __future__ import annotations

import pytest


@pytest.mark.tsduck
def test_tsduck_cli_probe_reports_version(tsduck):
    assert tsduck.available is True
    assert tsduck.executable
    assert tsduck.version  # measured regex `version (\d+\.\d+-\d+)`
    assert tsduck.raw_version_line  # full measured-format line kept verbatim
