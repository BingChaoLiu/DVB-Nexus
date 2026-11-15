"""Fault target addressing (ADR-0006 item 3 dual form, SPEC-204 §3).

Stream-level targets are ``{node_id}:pid:0x{hex}`` slugs (SIM_TS pid
0..0x1FFF); node-level targets are the bare ``{node_id}`` slug.  Parsing is
pure — ``SIM_FAULT_TARGET_INVALID`` details are produced by the registry
validator on top of :class:`ValueError`.
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
