"""SPEC-623 section 6 — Unicable pure functions (ticket #162).

Seam: ``simulation.state.unicable`` — the four pure-function families:

1. tuning-message construction (EN 50494 ``[0xE0, 0x10, 0x5A, d1, d2]`` /
   EN 50607 ``[0x70, d1, d2, d3]`` + PIN variants 0x5C / 0x71),
2. frequency formulas (I ``t = round((f_IF + f_UB + 2)/4) - 350`` /
   II ``t = f_IF - 100``),
3. ``ub_conflicts`` three-branch conflict detection,
4. prepare validation (bit width / t overflow / protocol mixing).

Vector-first discipline (SPEC-623 section 11.2): every expected byte and
field value below was hand-derived from the SPEC-623 section 6 bit-layout
table — annotated as "four-implementation source-level consensus
(tvheadend / VDR / MuMuDVB / minisatip cross-checked)" — before the
implementation was written.  The implementation must reproduce these
literals; a mismatch is an implementation bug, never a test bug.

Bit conventions pinned here (SPEC-623 gives the field slots but not the
per-bit value mapping — ticket-authorised DiSEqC-generic defaults):

- data1 field order is MSB-first as listed in the spec table:
  EN 50494 ``[UB:7-5 | position:4 | polarization:3 | band:2 | t:1-0]``;
- polarization bit 0 = vertical / 1 = horizontal; band bit 0 = low /
  1 = high; position bit 0 = A / 1 = B (EN 50494);
- band is derived from the tuning frequency with the universal-LNB
  boundary 11700000 kHz (SPEC-621 appendix A band plan: low ends at
  11.70 GHz);
- EN 50607 ``data3`` bits 1-0 are reserved and pinned to zero (the spec
  table defines only bit7-2 = position);
- formula rounding is round-half-up on the /4 (integer-exact
  ``(n + 2) // 4``), pinned by the quadruple in
  :class:`TestFrequencyFormulas`.

No clause numbers of EN 50494:2007 / EN 50607:2015 appear anywhere — the
standard bodies' texts are paywalled (issue #145 gap list); only the
sandbox spec (SPEC-623 §6) and the four-implementation consensus
annotation are cited.
"""

from __future__ import annotations

import pytest

from simulation.state.unicable import (
    MAX_T_BY_PROTOCOL,
    MAX_UB_SLOT_BY_PROTOCOL,
    UNICABLE_PROTOCOL_EN50494,
    UNICABLE_PROTOCOL_EN50607,
    UBPrepareError,
    UBProtocolMixedError,
    TuningMessage,
    build_tuning_message,
    en50494_t_value,
    en50607_t_value,
    prepare_violations,
    t_value,
    ub_conflicts,
)

pytestmark = pytest.mark.unit

EN50494 = UNICABLE_PROTOCOL_EN50494
EN50607 = UNICABLE_PROTOCOL_EN50607


def _assignment(
    ub_slot: int,
    ub_center_freq_mhz: int,
    position: str | int,
    pin: int | None = None,
    tuner_node: str = "tuner-a",
) -> dict:
    """A ``ub_assignments`` entry in the #160 config-dict wire shape."""
    return {
        "tuner_node": tuner_node,
        "ub_slot": ub_slot,
        "ub_center_freq_mhz": ub_center_freq_mhz,
        "position": position,
        "pin": pin,
        "ub_bandwidth_mhz": 46,
    }


def _tuning_request(frequency_khz: int, polarization: str) -> dict:
    """A ``tuning_request`` in the #160 config-dict wire shape."""
    return {"frequency_khz": frequency_khz, "polarization": polarization}


def _message(
    protocol: str,
    ub_assignment: dict,
    tuning_request: dict,
    if_frequency_mhz: int,
) -> TuningMessage:
    return build_tuning_message(
        protocol,
        ub_assignment,
        tuning_request,
        if_frequency_mhz=if_frequency_mhz,
    )


# ---------------------------------------------------------------------------
# 1. EN 50494 frame vectors (AC-623-01, AC-623-06)
# ---------------------------------------------------------------------------


class TestEn50494FrameVectors:
    """Hand-derived EN 50494 frames (five bytes, PIN variant six bytes)."""

    def test_baseline_all_zero_bits(self) -> None:
        # t = round((1000 + 1210 + 2) / 4) - 350 = round(2212/4) - 350
        #   = 553 - 350 = 203 -> data1 t[9:8] = 0b00, data2 = 203 = 0xCB.
        # UB=0 / position A / vertical / low -> data1 = 0x00.
        message = _message(
            EN50494,
            _assignment(0, 1210, "A"),
            _tuning_request(10700000, "vertical"),
            if_frequency_mhz=1000,
        )
        assert message.frame_bytes == (0xE0, 0x10, 0x5A, 0x00, 0xCB)
        assert message.t == 203

    def test_all_bits_set(self) -> None:
        # t = round((1400 + 2040 + 2) / 4) - 350 = round(3442/4) - 350
        #   = round(860.5) - 350 = 861 - 350 = 511 (round-half-up pin).
        # UB=7 -> 0xE0; position B -> 0x10; horizontal -> 0x08; high -> 0x04;
        # t[9:8] = 0b01 -> 0x01.  data1 = 0xFD; data2 = 511 & 0xFF = 0xFF.
        message = _message(
            EN50494,
            _assignment(7, 2040, "B"),
            _tuning_request(11836000, "horizontal"),
            if_frequency_mhz=1400,
        )
        assert message.frame_bytes == (0xE0, 0x10, 0x5A, 0xFD, 0xFF)

    def test_pin_variant_command_byte_0x5c(self) -> None:
        # t = round((1200 + 1420 + 2) / 4) - 350 = round(655.5) - 350
        #   = 656 - 350 = 306 -> t[9:8] = 0b01, data2 = 50 = 0x32.
        # UB=3 -> 0x60; data1 = 0x61.  PIN 107 = 0x6B appended, cmd 0x5C.
        message = _message(
            EN50494,
            _assignment(3, 1420, "A", pin=107),
            _tuning_request(10700000, "vertical"),
            if_frequency_mhz=1200,
        )
        assert message.frame_bytes == (0xE0, 0x10, 0x5C, 0x61, 0x32, 0x6B)

    def test_pin_zero_is_a_six_byte_frame(self) -> None:
        # PIN 0 is a legal PIN (0..255) — the PIN variant is keyed on
        # presence, not on the value.
        message = _message(
            EN50494,
            _assignment(0, 1210, "A", pin=0),
            _tuning_request(10700000, "vertical"),
            if_frequency_mhz=1000,
        )
        assert message.frame_bytes == (0xE0, 0x10, 0x5C, 0x00, 0xCB, 0x00)

    def test_abs_max_t_is_encodable(self) -> None:
        # Boundary: t = 1023 (10-bit maximum).  round((f + 2040 + 2)/4)
        #   = 1373 -> f + 2042 in [5490, 5493] -> f = 3448.
        # UB=7 / B / horizontal / high + t[9:8] = 0b11 -> data1 = 0xFF.
        message = _message(
            EN50494,
            _assignment(7, 2040, "B"),
            _tuning_request(11836000, "horizontal"),
            if_frequency_mhz=3448,
        )
        assert message.t == 1023
        assert message.frame_bytes == (0xE0, 0x10, 0x5A, 0xFF, 0xFF)

    def test_field_isolation_ub_bits_7_to_5(self) -> None:
        # UB=5 -> 0b101 << 5 = 0xA0; every other field identical to baseline.
        message = _message(
            EN50494,
            _assignment(5, 1210, "A"),
            _tuning_request(10700000, "vertical"),
            if_frequency_mhz=1000,
        )
        assert message.frame_bytes == (0xE0, 0x10, 0x5A, 0xA0, 0xCB)

    def test_field_isolation_position_bit_4(self) -> None:
        message = _message(
            EN50494,
            _assignment(0, 1210, "B"),
            _tuning_request(10700000, "vertical"),
            if_frequency_mhz=1000,
        )
        assert message.frame_bytes == (0xE0, 0x10, 0x5A, 0x10, 0xCB)

    def test_field_isolation_polarization_bit_3(self) -> None:
        message = _message(
            EN50494,
            _assignment(0, 1210, "A"),
            _tuning_request(10700000, "horizontal"),
            if_frequency_mhz=1000,
        )
        assert message.frame_bytes == (0xE0, 0x10, 0x5A, 0x08, 0xCB)

    def test_field_isolation_band_bit_2_from_tuning_frequency(self) -> None:
        # Band comes from the tuning frequency against the universal-LNB
        # boundary 11700000 kHz (SPEC-621 appendix A band plan).
        message = _message(
            EN50494,
            _assignment(0, 1210, "A"),
            _tuning_request(11800000, "vertical"),
            if_frequency_mhz=1000,
        )
        assert message.frame_bytes == (0xE0, 0x10, 0x5A, 0x04, 0xCB)

    def test_field_isolation_t_low_byte_and_high_bits(self) -> None:
        # f_IF 1002 -> round((1002 + 1210 + 2)/4) = round(553.5) = 554
        #   -> t = 204: data2 0xCC (only the t field moved).
        low = _message(
            EN50494,
            _assignment(0, 1210, "A"),
            _tuning_request(10700000, "vertical"),
            if_frequency_mhz=1002,
        )
        assert low.frame_bytes == (0xE0, 0x10, 0x5A, 0x00, 0xCC)
        # t = 353 (f_IF 1600): t[9:8] = 0b01 lands in data1 bits 1-0.
        high = _message(
            EN50494,
            _assignment(0, 1210, "A"),
            _tuning_request(10700000, "vertical"),
            if_frequency_mhz=1600,
        )
        assert high.frame_bytes == (0xE0, 0x10, 0x5A, 0x01, 0x61)


# ---------------------------------------------------------------------------
# 2. EN 50607 frame vectors (AC-623-01, AC-623-06)
# ---------------------------------------------------------------------------


class TestEn50607FrameVectors:
    """Hand-derived EN 50607 frames (four bytes, PIN variant five bytes)."""

    def test_baseline_small_values(self) -> None:
        # t = 1000 - 100 = 900 -> t[10:8] = 0b011 = 3, data2 = 132 = 0x84.
        # UB=0 -> data1 = 0x03; position 0 -> data3 = 0x00 (bits 1-0 zero).
        message = _message(
            EN50607,
            _assignment(0, 1210, 0),
            _tuning_request(10700000, "vertical"),
            if_frequency_mhz=1000,
        )
        assert message.frame_bytes == (0x70, 0x03, 0x84, 0x00)
        assert message.t == 900

    def test_all_bits_set(self) -> None:
        # t = 1950 - 100 = 1850 -> t[10:8] = 0b111 = 7, data2 = 58 = 0x3A.
        # UB=31 -> 0xF8 | 7 = 0xFF; position 63 -> 63 << 2 = 0xFC.
        message = _message(
            EN50607,
            _assignment(31, 2040, 63),
            _tuning_request(11836000, "horizontal"),
            if_frequency_mhz=1950,
        )
        assert message.frame_bytes == (0x70, 0xFF, 0x3A, 0xFC)

    def test_abs_max_t_is_encodable(self) -> None:
        # Boundary: t = 2047 (11-bit maximum) -> f_IF = 2147.
        # UB=31 -> 0xF8 | 7 = 0xFF; data2 = 0xFF; position 63 -> 0xFC.
        message = _message(
            EN50607,
            _assignment(31, 2040, 63),
            _tuning_request(11836000, "horizontal"),
            if_frequency_mhz=2147,
        )
        assert message.t == 2047
        assert message.frame_bytes == (0x70, 0xFF, 0xFF, 0xFC)

    def test_t_zero_boundary(self) -> None:
        # t = 100 - 100 = 0 — the smallest encodable t.
        message = _message(
            EN50607,
            _assignment(0, 1210, 0),
            _tuning_request(10700000, "vertical"),
            if_frequency_mhz=100,
        )
        assert message.frame_bytes == (0x70, 0x00, 0x00, 0x00)

    def test_pin_variant_command_byte_0x71(self) -> None:
        # t = 1500 - 100 = 1400 -> t[10:8] = 5, data2 = 120 = 0x78.
        # UB=17 -> 17 << 3 = 136 | 5 = 0x8D; position 42 -> 168 = 0xA8.
        message = _message(
            EN50607,
            _assignment(17, 1420, 42, pin=255),
            _tuning_request(10700000, "vertical"),
            if_frequency_mhz=1500,
        )
        assert message.frame_bytes == (0x71, 0x8D, 0x78, 0xA8, 0xFF)

    def test_field_isolation_ub_bits_7_to_3(self) -> None:
        # UB=1 -> 1 << 3 = 0x08; data1 = 0x0B, everything else unchanged.
        message = _message(
            EN50607,
            _assignment(1, 1210, 0),
            _tuning_request(10700000, "vertical"),
            if_frequency_mhz=1000,
        )
        assert message.frame_bytes == (0x70, 0x0B, 0x84, 0x00)

    def test_field_isolation_position_bits_7_to_2(self) -> None:
        # Position 1 -> 1 << 2 = 0x04 in data3; data3 bits 1-0 stay zero.
        message = _message(
            EN50607,
            _assignment(0, 1210, 1),
            _tuning_request(10700000, "vertical"),
            if_frequency_mhz=1000,
        )
        assert message.frame_bytes == (0x70, 0x03, 0x84, 0x04)

    def test_field_isolation_t_low_byte(self) -> None:
        # f_IF 1100 -> t = 1000: t[10:8] still 0b011, data2 232 = 0xE8.
        message = _message(
            EN50607,
            _assignment(0, 1210, 0),
            _tuning_request(10700000, "vertical"),
            if_frequency_mhz=1100,
        )
        assert message.frame_bytes == (0x70, 0x03, 0xE8, 0x00)

    def test_frame_carries_no_polarization_or_band_bits(self) -> None:
        # The SPEC-623 section 6 EN 50607 table defines no polarization /
        # band slots — the frame must be identical for either intent
        # (pinned so the "independent UB space" framing stays honest).
        vertical = _message(
            EN50607,
            _assignment(0, 1210, 0),
            _tuning_request(10700000, "vertical"),
            if_frequency_mhz=1000,
        )
        horizontal = _message(
            EN50607,
            _assignment(0, 1210, 0),
            _tuning_request(11836000, "horizontal"),
            if_frequency_mhz=1000,
        )
        assert vertical.frame_bytes == horizontal.frame_bytes


# ---------------------------------------------------------------------------
# 3. Frequency formulas (AC-623-02)
# ---------------------------------------------------------------------------


class TestFrequencyFormulas:
    """Formula I / II numeric vectors, including the constant paths."""

    def test_formula_i_rounding_quadruple(self) -> None:
        # (f_IF + f_UB + 2) mod 4 = 0 / 1 / 2 / 3 -> exact / down / UP / up.
        # The "= 2" case is the round-half-up pin: 553.5 rounds to 554.
        assert en50494_t_value(1000, 1210) == 203  # 2212/4 = 553 exact
        assert en50494_t_value(1001, 1210) == 203  # 2213/4 = 553.25
        assert en50494_t_value(1002, 1210) == 204  # 2214/4 = 553.5 -> 554
        assert en50494_t_value(1003, 1210) == 204  # 2215/4 = 553.75

    def test_formula_i_plus_2_constant_path(self) -> None:
        # The +2 constant is normative (receiver tunes (t+350)*4 - f_IF
        # ~= f_UB + 2 MHz; minisatip omits it — majority-annotated).
        # With +2: round((1002+1210+2)/4) = 554; without it the same
        # input would give round(2212/4) = 553 — one slot apart.
        assert en50494_t_value(1002, 1210) == 204

    def test_formula_i_minus_350_constant_path(self) -> None:
        # The -350 bias: round(2212/4) = 553 raw, published t = 203.
        assert en50494_t_value(1000, 1210) == 553 - 350

    def test_formula_i_rounding_is_integer_exact(self) -> None:
        # Large values stay exact through the integer half-up form
        # (no float rounding anywhere on the path).
        assert en50494_t_value(0, 0) == ((0 + 0 + 2) + 2) // 4 - 350
        assert en50494_t_value(3448, 2040) == 1023

    def test_formula_ii(self) -> None:
        # EN 50607: t = f_IF - 100 (1 MHz resolution, 11-bit field).
        assert en50607_t_value(1000) == 900
        assert en50607_t_value(1950) == 1850
        assert en50607_t_value(100) == 0  # smallest encodable
        # Below the 100 MHz offset the pure formula goes negative — range
        # enforcement is the prepare layer's job (declared seam split).
        assert en50607_t_value(99) == -1

    def test_t_value_dispatch(self) -> None:
        assert t_value(EN50494, 1000, 1210) == 203
        assert t_value(EN50607, 1000) == 900
        with pytest.raises(UBPrepareError):
            t_value("EN50495", 1000)

    def test_width_tables_are_self_consistent(self) -> None:
        # The t-range table derives from the bit widths; the UB width
        # table is #160's reused constant (imported, not redefined).
        assert MAX_T_BY_PROTOCOL == {EN50494: 1023, EN50607: 2047}
        assert MAX_UB_SLOT_BY_PROTOCOL == {EN50494: 7, EN50607: 31}
        assert (EN50494, EN50607) == ("EN50494", "EN50607")


# ---------------------------------------------------------------------------
# 4. ub_conflicts three branches (AC-623-03)
# ---------------------------------------------------------------------------

_SCR_TABLE_EN50494 = [
    _assignment(0, 1210, "A", tuner_node="tuner-a"),
    _assignment(1, 1420, "B", tuner_node="tuner-b"),
]


class TestUBConflicts:
    """Branch 1 conflict pairs / branch 2 empty / branch 3 protocol reject."""

    def test_no_conflict_baseline(self) -> None:
        # Baseline claims mirror the SCR table one-to-one (rule 1) — no
        # stacking, empty result.
        claims = [
            {"node_id": "tuner-a", "ub_slot": 0},
            {"node_id": "tuner-b", "ub_slot": 1},
        ]
        assert ub_conflicts(_SCR_TABLE_EN50494, claims) == ()

    def test_empty_inputs_no_conflict(self) -> None:
        assert ub_conflicts([], []) == ()

    def test_fault_override_creates_conflict_pair(self) -> None:
        # SC-10 shape: the UB_SLOT_CONFLICT fault rewrote tuner-b's
        # effective ub_slot onto tuner-a's occupied slot 0.
        faulted = [
            {"node_id": "tuner-a", "ub_slot": 0},
            {"node_id": "tuner-b", "ub_slot": 0},
        ]
        assert ub_conflicts(_SCR_TABLE_EN50494, faulted) == (
            ("tuner-a", "tuner-b", 0),
        )

    def test_effective_claim_overrides_table_row(self) -> None:
        # tuner-b appears in the table (slot 1) but its effective claim is
        # slot 0 — the effective state wins over the stale table row.
        faulted = [{"node_id": "tuner-b", "ub_slot": 0}]
        assert ub_conflicts(_SCR_TABLE_EN50494, faulted) == (
            ("tuner-a", "tuner-b", 0),
        )

    def test_triple_collision_yields_three_pairs(self) -> None:
        # Three tuners stacked on one slot -> all unordered pairs,
        # claimants lexicographic inside the slot.
        stacked = [
            {"node_id": "tuner-c", "ub_slot": 2},
            {"node_id": "tuner-a", "ub_slot": 2},
            {"node_id": "tuner-b", "ub_slot": 2},
        ]
        assert ub_conflicts([], stacked) == (
            ("tuner-a", "tuner-b", 2),
            ("tuner-a", "tuner-c", 2),
            ("tuner-b", "tuner-c", 2),
        )

    def test_multi_slot_pairs_ordered_by_slot(self) -> None:
        claims = [
            {"node_id": "tuner-d", "ub_slot": 1},
            {"node_id": "tuner-c", "ub_slot": 1},
            {"node_id": "tuner-b", "ub_slot": 0},
            {"node_id": "tuner-a", "ub_slot": 0},
        ]
        assert ub_conflicts([], claims) == (
            ("tuner-a", "tuner-b", 0),
            ("tuner-c", "tuner-d", 1),
        )

    def test_null_and_malformed_slots_do_not_participate(self) -> None:
        # ub_slot None (no UB participation) / bool-typed / non-int values
        # never form claims.
        claims = [
            {"node_id": "tuner-a", "ub_slot": None},
            {"node_id": "tuner-b", "ub_slot": True},
            {"node_id": "tuner-c", "ub_slot": "0"},
            {"node_id": "tuner-d", "ub_slot": 0},
        ]
        assert ub_conflicts([], claims) == ()

    def test_cross_protocol_context_rejected(self) -> None:
        # Branch 3: the mixed-protocol prepare reject — the EN 50494 and
        # EN 50607 UB spaces are independent (SPEC-623 section 7).
        mixed_table = [
            dict(_assignment(0, 1210, "A", tuner_node="tuner-a"), protocol=EN50494),
        ]
        mixed_claims = [
            {"node_id": "tuner-b", "ub_slot": 0, "protocol": EN50607},
        ]
        with pytest.raises(UBProtocolMixedError):
            ub_conflicts(mixed_table, mixed_claims)

    def test_cross_protocol_within_table_rejected(self) -> None:
        table = [
            dict(_assignment(0, 1210, "A", tuner_node="tuner-a"), protocol=EN50494),
            dict(_assignment(1, 1420, "B", tuner_node="tuner-b"), protocol=EN50607),
        ]
        with pytest.raises(UBProtocolMixedError):
            ub_conflicts(table, [])

    def test_single_protocol_context_passes_the_guard(self) -> None:
        table = [
            dict(_assignment(0, 1210, "A", tuner_node="tuner-a"), protocol=EN50494),
        ]
        claims = [{"node_id": "tuner-a", "ub_slot": 0, "protocol": EN50494}]
        assert ub_conflicts(table, claims) == ()

    def test_deterministic_double_run(self) -> None:
        # AC-623-06 spirit: structural facts repeat byte-identically.
        faulted = [{"node_id": "tuner-b", "ub_slot": 0}]
        first = ub_conflicts(_SCR_TABLE_EN50494, faulted)
        second = ub_conflicts(_SCR_TABLE_EN50494, faulted)
        assert first == second == (("tuner-a", "tuner-b", 0),)


# ---------------------------------------------------------------------------
# 5. Prepare validation (AC-623-03 width / SPEC-623 section 8 t overflow)
# ---------------------------------------------------------------------------


class TestPrepareValidation:
    """Bit-width, t-overflow, vocabulary and protocol guards."""

    def test_legal_en50494_inputs_pass(self) -> None:
        violations = prepare_violations(
            EN50494,
            _assignment(7, 2040, "B", pin=200),
            3448,
            tuning_request=_tuning_request(11836000, "horizontal"),
        )
        assert violations == ()

    def test_legal_en50607_inputs_pass_without_ub_center_freq(self) -> None:
        # EN 50607's t formula does not consume ub_center_freq_mhz — a
        # slot/position/pin-only assignment still validates.
        assignment = {"tuner_node": "tuner-a", "ub_slot": 31, "position": 63}
        violations = prepare_violations(
            EN50607,
            assignment,
            2147,
            tuning_request=_tuning_request(11836000, "horizontal"),
        )
        assert violations == ()

    def test_ub_slot_width_rejections(self) -> None:
        assert any(
            code.startswith("ub_slot:")
            for code in prepare_violations(EN50494, _assignment(8, 1210, "A"), 1000)
        )
        assert any(
            code.startswith("ub_slot:")
            for code in prepare_violations(EN50607, _assignment(32, 1210, 0), 1000)
        )
        # Boundary slots stay legal (bit width 3 / 5 bits).
        assert not any(
            code.startswith("ub_slot:")
            for code in prepare_violations(EN50494, _assignment(7, 1210, "A"), 1000)
        )
        assert not any(
            code.startswith("ub_slot:")
            for code in prepare_violations(EN50607, _assignment(31, 1210, 0), 1000)
        )

    def test_t_overflow_rejections(self) -> None:
        # EN 50494: f_IF 3454 + f_UB 2040 -> round(5496/4) - 350 = 1024 > 1023.
        assert any(
            code.startswith("t:")
            for code in prepare_violations(EN50494, _assignment(0, 2040, "A"), 3454)
        )
        # EN 50607: t = 2148 - 100 = 2048 > 2047.
        assert any(
            code.startswith("t:")
            for code in prepare_violations(EN50607, _assignment(0, 1210, 0), 2148)
        )

    def test_negative_t_rejections(self) -> None:
        # EN 50494: round((100+1210+2)/4) - 350 = 328 - 350 = -22.
        assert any(
            code.startswith("t:")
            for code in prepare_violations(EN50494, _assignment(0, 1210, "A"), 100)
        )
        # EN 50607: 99 - 100 = -1 (declared addition: unencodable sign).
        assert any(
            code.startswith("t:")
            for code in prepare_violations(EN50607, _assignment(0, 1210, 0), 99)
        )

    def test_unknown_protocol_rejected(self) -> None:
        violations = prepare_violations("EN50495", _assignment(0, 1210, "A"), 1000)
        assert len(violations) == 1
        assert violations[0].startswith("protocol:")

    def test_position_vocabulary_rejections(self) -> None:
        # EN 50494 positions are the strings A/B (domain DTO mirror).
        assert any(
            code.startswith("position:")
            for code in prepare_violations(EN50494, _assignment(0, 1210, 0), 1000)
        )
        # EN 50607 positions are ints 0..63.
        assert any(
            code.startswith("position:")
            for code in prepare_violations(EN50607, _assignment(0, 1210, "A"), 1000)
        )
        assert any(
            code.startswith("position:")
            for code in prepare_violations(EN50607, _assignment(0, 1210, 64), 1000)
        )

    def test_pin_range_rejections(self) -> None:
        assert any(
            code.startswith("pin:")
            for code in prepare_violations(
                EN50494, _assignment(0, 1210, "A", pin=256), 1000
            )
        )
        assert any(
            code.startswith("pin:")
            for code in prepare_violations(
                EN50494, _assignment(0, 1210, "A", pin=-1), 1000
            )
        )

    def test_if_frequency_sanity_rejections(self) -> None:
        assert any(
            code.startswith("if_frequency:")
            for code in prepare_violations(EN50494, _assignment(0, 1210, "A"), -1)
        )
        assert any(
            code.startswith("if_frequency:")
            for code in prepare_violations(EN50607, _assignment(0, 1210, 0), True)
        )

    def test_missing_ub_center_freq_rejected_for_en50494(self) -> None:
        # Formula I needs f_UB — no ub_center_freq_mhz, no t.
        assignment = {"tuner_node": "tuner-a", "ub_slot": 0, "position": "A"}
        assert any(
            code.startswith("ub_center_freq_mhz:")
            for code in prepare_violations(EN50494, assignment, 1000)
        )

    def test_tuning_request_vocabulary_rejections(self) -> None:
        bad_polarization = prepare_violations(
            EN50494,
            _assignment(0, 1210, "A"),
            1000,
            tuning_request={"frequency_khz": 10700000, "polarization": "circular"},
        )
        assert any(code.startswith("polarization:") for code in bad_polarization)
        bad_frequency = prepare_violations(
            EN50494,
            _assignment(0, 1210, "A"),
            1000,
            tuning_request={"frequency_khz": "10700", "polarization": "vertical"},
        )
        assert any(code.startswith("frequency_khz:") for code in bad_frequency)

    def test_violations_deterministic_order(self) -> None:
        # Multiple failures in one call: frozen field order
        # (ub_slot > position > pin > polarization > frequency_khz >
        # if_frequency); the t check is skipped when its inputs already
        # failed their own guards (no garbage-derived t details).
        violations = prepare_violations(
            EN50494,
            _assignment(8, 1210, "C", pin=256),
            -1,
            tuning_request={"frequency_khz": 0, "polarization": "circular"},
        )
        prefixes = [code.split(":", 1)[0] for code in violations]
        assert prefixes == [
            "ub_slot",
            "position",
            "pin",
            "polarization",
            "frequency_khz",
            "if_frequency",
        ]


# ---------------------------------------------------------------------------
# 6. Message construction guard + determinism (AC-623-06)
# ---------------------------------------------------------------------------


class TestMessageConstructionGuards:
    """The builder runs the prepare gate and fails with structured errors."""

    def test_builder_rejects_width_overflow(self) -> None:
        with pytest.raises(UBPrepareError) as excinfo:
            _message(
                EN50494,
                _assignment(8, 1210, "A"),
                _tuning_request(10700000, "vertical"),
                if_frequency_mhz=1000,
            )
        assert any(
            code.startswith("ub_slot:") for code in excinfo.value.violations
        )

    def test_builder_rejects_t_overflow(self) -> None:
        with pytest.raises(UBPrepareError) as excinfo:
            _message(
                EN50607,
                _assignment(0, 1210, 0),
                _tuning_request(10700000, "vertical"),
                if_frequency_mhz=2148,
            )
        assert any(code.startswith("t:") for code in excinfo.value.violations)

    def test_builder_rejects_unknown_protocol(self) -> None:
        with pytest.raises(UBPrepareError):
            _message(
                "EN50495",
                _assignment(0, 1210, "A"),
                _tuning_request(10700000, "vertical"),
                if_frequency_mhz=1000,
            )

    def test_prepare_error_carries_violations_tuple(self) -> None:
        error = UBPrepareError(["t: out of range", "ub_slot: width"])
        assert error.violations == ("t: out of range", "ub_slot: width")


class TestMessageDeterminism:
    """Same inputs -> same frame_bytes (SPEC-623 section 7, AC-623-06)."""

    _ASSIGNMENT = _assignment(3, 1420, "A", pin=107)
    _REQUEST = _tuning_request(10700000, "vertical")

    def test_double_run_byte_identical(self) -> None:
        first = _message(EN50494, self._ASSIGNMENT, self._REQUEST, 1200)
        second = _message(EN50494, self._ASSIGNMENT, self._REQUEST, 1200)
        assert first == second
        assert first.frame_bytes == second.frame_bytes

    def test_message_payload_keys_for_observation_bridge(self) -> None:
        # The #164 snapshot payload shape: {protocol, frame_bytes, t}
        # (SPEC-623 section 5 metrics keys), JSON-safe by construction.
        message = _message(EN50607, _assignment(17, 1420, 42), self._REQUEST, 1500)
        payload = message.payload()
        assert payload == {
            "protocol": EN50607,
            "frame_bytes": list(message.frame_bytes),
            "t": 1400,
        }
        assert set(payload) == {"protocol", "frame_bytes", "t"}
