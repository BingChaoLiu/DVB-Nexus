"""Unit-layer tests for TSDuck version-line extraction (pure functions).

The sample line is the **measured asset** from ``docs/research/tsduck-env.md``
(ticket #3 实测, SPEC-505 §6: TSDuck 输出样例以实测资产为基准，不凭记忆编造):
``tsp --version`` → ``TSDuck - The MPEG Transport Stream Toolkit - version 3.40-4165``
with extraction regex ``version (\\d+\\.\\d+-\\d+)``.
"""

from __future__ import annotations

from tests._support.tsduck_probe import extract_version

#: Measured output line (docs/research/tsduck-env.md, ticket #3).
MEASURED_VERSION_LINE = (
    "TSDuck - The MPEG Transport Stream Toolkit - version 3.40-4165"
)


def test_measured_asset_version_extracted():
    assert extract_version(MEASURED_VERSION_LINE) == "3.40-4165"


def test_version_with_newline_and_crlf():
    assert extract_version(MEASURED_VERSION_LINE + "\r\n") == "3.40-4165"


def test_no_version_word_yields_none():
    assert extract_version("Python 3.10.11\n") is None


def test_empty_output_yields_none():
    assert extract_version("") is None
    assert extract_version("\n\n") is None


def test_stderr_noise_line_without_version_token_yields_none():
    # 偶发在线版本检查提示走 stderr（tsduck-env.md:133）；若其文本混入
    # stdout，缺少数值版本 token 时同样不得误判。
    assert extract_version("* new TSDuck version check skipped\n") is None
