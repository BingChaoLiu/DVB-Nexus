"""Fault target addressing (ADR-0006 item 3 dual form + the SPEC-204
§Phase3 node-attribute form, SPEC-204 §3).

Three target forms:

- stream-level (SIM_TS, pid 0..0x1FFF): ``{node_id}:pid:0x{hex}``, e.g.
  ``demux-0:pid:0x0100``;
- node-level (state plane): the bare ``{node_id}`` slug, e.g. ``lnb-0``;
- node-attribute (state plane, #163 / ruling A4): ``{node_id}:{attr_name}``,
  e.g. ``tuner-b:ub_slot`` — the attr segment is a snake_case identifier
  that never carries a colon and never collides with the ``pid`` form.

Parsing is pure — ``SIM_FAULT_TARGET_INVALID`` details are produced by the
registry validator on top of :class:`ValueError`.
"""

from __future__ import annotations

import pytest

from faults.targets import FaultTarget, parse_target_id

pytestmark = pytest.mark.unit


class TestStreamLevelTargets:
    def test_hex_slug_parsed_with_node_and_pid(self) -> None:
        target = parse_target_id("demux-0:pid:0x0100")
        assert target == FaultTarget(node_id="demux-0", pid=0x0100)

    def test_pid_zero_and_null_pid_ranges_parse(self) -> None:
        assert parse_target_id("demux-0:pid:0x0000").pid == 0x0000
        assert parse_target_id("demux-0:pid:0x1FFF").pid == 0x1FFF

    def test_short_hex_and_lowercase_accepted(self) -> None:
        assert parse_target_id("mux:pid:0x1a").pid == 0x1A
        assert parse_target_id("demux-0:pid:0x1000").pid == 0x1000


class TestNodeLevelTargets:
    def test_bare_node_id_is_node_level(self) -> None:
        assert parse_target_id("demux-0") == FaultTarget(
            node_id="demux-0", pid=None
        )

    def test_node_slug_charset(self) -> None:
        assert parse_target_id("Node_01-a").node_id == "Node_01-a"


class TestNodeAttrTargets:
    """The third form (#163, ruling A4): ``{node_id}:{attr_name}``."""

    def test_attr_form_parsed_with_node_and_attr(self) -> None:
        # The SC-10 wire face: target_id "tuner-b:ub_slot" verbatim.
        target = parse_target_id("tuner-b:ub_slot")
        assert target == FaultTarget(
            node_id="tuner-b", pid=None, attr="ub_slot"
        )

    def test_two_form_construction_stays_backward_compatible(self) -> None:
        # The frozen two-argument constructor keeps producing the same
        # shapes the existing tests (and callers) compare against.
        assert parse_target_id("demux-0") == FaultTarget(
            node_id="demux-0", pid=None
        )
        assert parse_target_id("demux-0:pid:0x0100") == FaultTarget(
            node_id="demux-0", pid=0x0100
        )

    def test_snake_case_attr_charset_accepted(self) -> None:
        assert parse_target_id("n:ub_slot").attr == "ub_slot"
        assert parse_target_id("n:attr1").attr == "attr1"
        assert parse_target_id("n:UB_SLOT").attr == "UB_SLOT"

    @pytest.mark.parametrize(
        "bad",
        [
            "tuner-b:ub-slot",  # hyphen: not a snake_case identifier
            "tuner-b:",  # empty attr segment
            "tuner-b:ub:slot",  # second colon
            "demux-0:pid",  # "pid" segment reserved for the stream form
            ":ub_slot",  # empty node segment
        ],
    )
    def test_value_error_on_malformed_attr_slug(self, bad: str) -> None:
        with pytest.raises(ValueError):
            parse_target_id(bad)

    def test_stream_form_still_takes_precedence_over_attr_reading(self) -> None:
        # "pid:0x{hex}" is always the stream form, never an attr reading.
        target = parse_target_id("demux-0:pid:0x0000")
        assert target.attr is None
        assert target.pid == 0x0000


class TestUnparseableTargets:
    @pytest.mark.parametrize(
        "bad",
        [
            "",
            ":pid:0x0100",
            "demux-0:pid:",
            "demux-0:pid:0x",
            "demux-0:pid:0xZZZZ",
            "demux-0:pid:100",
            "demux-0:pid:0x20000",
            "demux-0:pid:-1",
            "demux-0:pid:0x0100:extra",
            "demux-0:pid:0x0100 ",
            "demux-0:",
        ],
    )
    def test_value_error_on_malformed_slug(self, bad: str) -> None:
        with pytest.raises(ValueError):
            parse_target_id(bad)
