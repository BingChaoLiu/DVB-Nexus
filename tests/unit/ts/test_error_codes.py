"""TS-CORE-INTEGRATION-CONTRACT §7 — structured ``.code`` on the error base.

Every ts-core error message carries its error code as the ``CODE: message``
head (the raise sites' convention, e.g. ``f"{GENERATOR_X}: ..."``). The
base class extracts that head once at construction into a structured
``.code`` attribute so consumers never parse ``str(exc)`` (M3 review-fix:
the SIM runtime's string-split recovery is deleted in favor of ``.code``).
Construction behavior is unchanged — ``str(exc)``, args and subclassing
all behave exactly as before; ``.code`` is purely additive and ``None``
when the message carries no code head.
"""

import pytest

from ts.errors import (
    GenerationError,
    InvalidPacketError,
    InvalidSectionError,
    TSCoreError,
)


def test_code_head_is_extracted():
    error = TSCoreError("TS_SYNC_BYTE_INVALID: expected 0x47, got 0x12")
    assert error.code == "TS_SYNC_BYTE_INVALID"


def test_plain_message_has_no_code():
    assert TSCoreError("something went wrong").code is None


def test_multi_word_head_is_not_a_code():
    """A head containing spaces is prose, not a code — the None guard."""
    assert TSCoreError("packet malformed: sync byte missing").code is None


def test_headless_message_with_colon_still_none():
    assert TSCoreError(": leading colon is not a code").code is None


def test_no_args_and_non_string_arg_are_none():
    assert TSCoreError().code is None
    assert TSCoreError(123).code is None


def test_subclasses_inherit_the_extraction():
    assert GenerationError("GENERATOR_CONFIG_INVALID: bad config").code == (
        "GENERATOR_CONFIG_INVALID"
    )
    assert InvalidPacketError("TS_AF_FIELD_OUT_OF_RANGE: splice").code == (
        "TS_AF_FIELD_OUT_OF_RANGE"
    )
    assert InvalidSectionError("no code here").code is None


def test_str_and_args_behavior_unchanged():
    """Additive attribute: rendering and exception semantics untouched."""
    error = InvalidSectionError("SECTION_CRC_INVALID: crc mismatch")
    assert str(error) == "SECTION_CRC_INVALID: crc mismatch"
    assert error.args == ("SECTION_CRC_INVALID: crc mismatch",)
    with pytest.raises(TSCoreError):
        raise error
