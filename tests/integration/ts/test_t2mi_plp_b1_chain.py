"""SPEC-602 §7 — B1 symptom chain, in-process integration (ticket #124).

AC-602-02's 本票范围: the B1 injection semantics verified as the
parse → build(plp_ids) → filter chain plus the ``t2mi.plp_mismatch``
candidate on the mock/in-process emitter face (ruling §10-7).  The
cross-ticket end-to-end (layered runtime emission, WS visibility,
diagnosis candidates, package-inspector evidence) lands with #128 /
#129 / #131.

B1 story (roadmap §4): the outer lock stays green — the faulted T2-MI
stream parses cleanly (CRC valid, counters continuous, zero truncation)
— while the demux, still filtering on the scenario-declared
``expected_plp``, receives the explicit empty result and the honest
"缺失 ≠ 零" candidate: the business is gone from the selected PLP, and
``plps_seen`` shows where it actually went.
"""

from __future__ import annotations

import pytest

from ts.t2mi.parser import parse
from ts.t2mi.plp import (
    PLP_MISMATCH_PAYLOAD_KEYS,
    PlpAssignment,
    PlpAssignmentEntry,
    PlpFilterConfig,
    T2MI_PLP_MISMATCH_EVENT_TYPE,
    assign,
    collect_plp_mismatch,
    filter,
    plps_seen,
)

from faults.definition import FaultActivation, FaultDefinition
from faults.filters.t2mi_plp_mismatch import T2miPlpMismatchTransform

pytestmark = pytest.mark.integration

EXPECTED_PLP = 3
ACTUAL_PLP = 7
UPL_BYTES = 188
BBHEADER_SIZE = 10


def _frame(up_count: int, seed: int) -> bytes:
    header = bytes(((i + seed) * 13) & 0xFF for i in range(BBHEADER_SIZE))
    ups = b"".join(
        bytes(((i + j) * 17 + seed * 11) & 0xFF for j in range(UPL_BYTES))
        for i in range(up_count)
    )
    return header + ups


def _assignment() -> PlpAssignment:
    return PlpAssignment(
        entries=(PlpAssignmentEntry(plp_id=EXPECTED_PLP, source_tag="business"),)
    )


def _demux_config() -> PlpFilterConfig:
    return PlpFilterConfig(mode="expected", expected_plp=EXPECTED_PLP)


def _encapsulated() -> tuple:
    """The encapsulator face: sources → assignment table → tagged stream."""
    return assign(
        {"business": [_frame(1, i) for i in range(4)]},
        _assignment(),
    )


def _fault(
    *,
    parameters: dict | None = None,
    activation: FaultActivation | None = None,
    fault_id: str = "f-b1-plp-001",
) -> T2miPlpMismatchTransform:
    return T2miPlpMismatchTransform(
        FaultDefinition(
            fault_id=fault_id,
            fault_type="T2MI_PLP_MISMATCH",
            target_id="t2mi-enc-0",
            parameters=(
                parameters
                if parameters is not None
                else {"expected_plp": EXPECTED_PLP, "actual_plp": ACTUAL_PLP}
            ),
            activation=activation or FaultActivation(kind="session_start"),
            expected_observations=("t2mi.plp_mismatch",),
            layer="T2MI",
        )
    )


def _faulted_stream(fault: T2miPlpMismatchTransform) -> tuple:
    """The runtime's per-layer chain face: 生成 → 本层过滤器 → (封装已完成)."""
    return tuple(fault.apply(index, packet) for index, packet in enumerate(_encapsulated()))


class TestB1BaselineRun:
    """Unfaulted run: assignment and demux agree — business flows."""

    def test_baseline_stream_carries_the_expected_plp(self) -> None:
        packets = _encapsulated()
        assert [packet.plp_id for packet in packets] == [EXPECTED_PLP] * 4
        assert plps_seen(packets) == {"plps_seen": [EXPECTED_PLP]}

    def test_baseline_demux_receives_the_full_business(self) -> None:
        selected = filter(_encapsulated(), _demux_config())
        assert len(selected) == 4
        assert collect_plp_mismatch(_encapsulated(), _demux_config()) is None


class TestB1FaultedRun:
    """Faulted run: outer green light, Inner TS business absent."""

    def test_outer_lock_stays_green(self) -> None:
        result = parse(
            b"".join(packet.to_bytes() for packet in _faulted_stream(_fault()))
        )
        assert not result.truncated
        assert all(packet.crc32_valid for packet in result)
        counters = [packet.packet_counter for packet in result]
        assert counters == [0, 1, 2, 3]

    def test_demux_sees_the_business_on_the_wrong_plp(self) -> None:
        assert plps_seen(_faulted_stream(_fault())) == {"plps_seen": [ACTUAL_PLP]}

    def test_demux_filter_gives_the_explicit_empty_result(self) -> None:
        selected = filter(_faulted_stream(_fault()), _demux_config())
        assert selected == ()

    def test_candidate_carries_the_drift_pair_and_evidence(self) -> None:
        stream = _faulted_stream(_fault())
        payload = collect_plp_mismatch(stream, _demux_config())
        assert payload is not None
        assert set(payload) == PLP_MISMATCH_PAYLOAD_KEYS
        assert payload["expected_plp"] == EXPECTED_PLP
        assert payload["actual_plp"] == ACTUAL_PLP
        evidence = payload["business_absent_evidence"]
        assert evidence["plps_seen"] == [ACTUAL_PLP]
        assert evidence["filtered_packet_count"] == 0
        assert evidence["bbframe_packet_count"] == 4

    def test_candidate_reaches_the_injected_emitter_exactly_once(self) -> None:
        captured: list[tuple[str, dict]] = []
        filter(
            _faulted_stream(_fault()),
            _demux_config(),
            emitter=lambda event_type, payload: captured.append(
                (event_type, dict(payload))
            ),
        )
        assert len(captured) == 1
        event_type, payload = captured[0]
        assert event_type == T2MI_PLP_MISMATCH_EVENT_TYPE
        assert set(payload) == PLP_MISMATCH_PAYLOAD_KEYS

    def test_mutation_records_locate_every_drifted_slot(self) -> None:
        fault = _fault()
        _faulted_stream(fault)
        assert fault.applied_packet_indexes == (0, 1, 2, 3)
        assert fault.restamp_summary() == {
            "restamped_packet_count": 4,
            "expected_plp": EXPECTED_PLP,
            "actual_plp": ACTUAL_PLP,
            "plp_version_switch": False,
            "first_restatement_index": 0,
        }

    def test_recovery_run_restores_the_business_byte_identically(self) -> None:
        baseline = _encapsulated()
        recovered = _encapsulated()
        assert recovered == baseline  # same sources + same assignment → same bytes
        assert filter(recovered, _demux_config()) != ()


class TestB1MidStreamSwitchVariant:
    """plp_version_switch: the PLP switches at the activation index."""

    def _switched_stream(self) -> tuple:
        return _faulted_stream(
            _fault(
                parameters={
                    "expected_plp": EXPECTED_PLP,
                    "actual_plp": ACTUAL_PLP,
                    "plp_version_switch": True,
                },
                activation=FaultActivation(kind="packet_index", packet_index=2),
            )
        )

    def test_switch_point_splits_the_business(self) -> None:
        stream = self._switched_stream()
        assert [packet.plp_id for packet in stream] == [
            EXPECTED_PLP,
            EXPECTED_PLP,
            ACTUAL_PLP,
            ACTUAL_PLP,
        ]
        assert plps_seen(stream) == {"plps_seen": [EXPECTED_PLP, ACTUAL_PLP]}

    def test_demux_keeps_only_the_pre_switch_segment(self) -> None:
        selected = filter(self._switched_stream(), _demux_config())
        assert [packet.frame_index for packet in selected] == [0, 1]

    def test_no_candidate_while_the_expected_plp_still_flows(self) -> None:
        assert collect_plp_mismatch(self._switched_stream(), _demux_config()) is None

    def test_post_switch_total_drift_fires_the_candidate(self) -> None:
        stream = _faulted_stream(
            _fault(
                fault_id="f-b1-plp-002",
                parameters={
                    "expected_plp": EXPECTED_PLP,
                    "actual_plp": ACTUAL_PLP,
                    "plp_version_switch": True,
                },
                activation=FaultActivation(kind="packet_index", packet_index=0),
            )
        )
        payload = collect_plp_mismatch(stream, _demux_config())
        assert payload is not None
        assert payload["actual_plp"] == ACTUAL_PLP
