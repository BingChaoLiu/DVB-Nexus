"""The state_eval golden vectors — the #172 转正 conformance gate
(SPEC-506 §6 via the SPEC-505 conformance layer).

Three Phase 3 state-domain vectors (kind ``state_eval``, the SPEC-506
0.7.0 minimal additive revision):

- ``lnb-band-selection-14-states`` — SPEC-621 appendix A truth table,
  cell by cell, driven against the production ``select_band`` pure
  function;
- ``unicable-tuning-message-bit-layout`` — SPEC-623 §6 bit-layout frames
  (EN 50494 + EN 50607 + PIN variants 0x5C/0x71 + field isolations +
  the EN 50607 polarization invariance), driven against the production
  ``build_tuning_message`` pure function;
- ``unicable-frequency-formula`` — SPEC-623 §6 formulas I/II numeric
  vectors (round-half-up quadruple + constant paths + boundaries),
  driven against ``en50494_t_value`` / ``en50607_t_value``.

Independent-verification discipline (SPEC-506 §5): the golden tables are
hand-transcribed spec-table derivations (no src involvement); the
production functions were vector-pinned to the SAME tables before they
existed (#161/#162 向量先钉纪律) — the conformance drive compares the
implementation against the spec transcription, never against its own
output. Each test also cross-checks the canonical table ↔ the
expectations face (the sha-pinned table is the identity; the
expectations.json entries are the machine-assertion face — they must
agree 1:1) and re-serializes the table canonically to pin the canonical
form (deterministic re-dump == the sha'd bytes).
"""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.conformance

from simulation.state.evaluators.lnb_evaluator import select_band
from simulation.state.unicable import (
    build_tuning_message,
    en50494_t_value,
    en50607_t_value,
)

from tests.conformance.golden_loader import GoldenLoader
from tests._support.paths import GOLDEN_ROOT

STATE_EVAL_IDS = (
    "lnb-band-selection-14-states",
    "unicable-tuning-message-bit-layout",
    "unicable-frequency-formula",
)


def _canonical(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


@pytest.fixture(scope="module")
def loader() -> GoldenLoader:
    return GoldenLoader(GOLDEN_ROOT)


class TestStateEvalRegistration:
    """The three vectors register cleanly under the state_eval kind."""

    def test_three_state_eval_vectors_are_registered(self, loader: GoldenLoader):
        for vector_id in STATE_EVAL_IDS:
            vector = loader.load(vector_id)
            assert vector.kind == "state_eval", vector_id
            assert vector.sha256
            assert vector.verification is not None
            assert vector.verification.path == "bit-level-review"
            assert vector.expectations, vector_id

    def test_tables_are_canonical_serializations(self, loader: GoldenLoader):
        """The data file IS the canonical JSON form — re-serializing the
        parsed table reproduces the sha'd bytes byte for byte."""
        for vector_id in STATE_EVAL_IDS:
            vector = loader.load(vector_id)
            table = json.loads(vector.ts_bytes.decode("utf-8"))
            assert _canonical(table).encode("utf-8") == vector.ts_bytes


class TestLnbBandSelection14States:
    """SPEC-621 appendix A — the 14-state truth table, golden-driven."""

    def test_production_select_band_matches_the_golden_table(self, loader: GoldenLoader):
        vector = loader.load("lnb-band-selection-14-states")
        table = json.loads(vector.ts_bytes.decode("utf-8"))
        rows = table["rows"]
        assert table["lnb_kind"] == "universal"
        assert len(rows) == 14
        for row in rows:
            delivery = select_band(
                table["lnb_kind"],
                row["voltage"],
                row["tone_actual"],
                row["tone_composite"],
            )
            assert delivery.band_selected == row["band_selected"], row["row"]
            assert delivery.lo_frequency_khz == row["lo_frequency_khz"], row["row"]
            assert (
                delivery.polarization_delivered == row["polarization_delivered"]
            ), row["row"]

    def test_expectations_face_agrees_with_the_table(self, loader: GoldenLoader):
        vector = loader.load("lnb-band-selection-14-states")
        table = json.loads(vector.ts_bytes.decode("utf-8"))
        entries = vector.expectations
        assert len(entries) == len(table["rows"]) == 14
        for entry, row in zip(entries, table["rows"]):
            assert entry["event_type"] == "sec.state_observed"
            assert entry["locator"] == {"node_type": "lnb", "row": row["row"]}
            assert entry["detail"] == {
                "voltage": row["voltage"],
                "tone_actual": row["tone_actual"],
                "tone_composite": row["tone_composite"],
                "band_selected": row["band_selected"],
                "lo_frequency_khz": row["lo_frequency_khz"],
                "polarization_delivered": row["polarization_delivered"],
            }


class TestUnicableTuningMessageBitLayout:
    """SPEC-623 §6 — the bit-layout frames, golden-driven byte for byte."""

    def test_production_build_tuning_message_matches_the_golden_frames(
        self, loader: GoldenLoader
    ):
        vector = loader.load("unicable-tuning-message-bit-layout")
        table = json.loads(vector.ts_bytes.decode("utf-8"))
        cases = table["cases"]
        assert len(cases) == 21
        for case in cases:
            message = build_tuning_message(
                case["protocol"],
                case["ub_assignment"],
                case["tuning_request"],
                if_frequency_mhz=case["if_frequency_mhz"],
            )
            expected = case["expected"]
            assert list(message.frame_bytes) == expected["frame_bytes"], case["case"]
            assert message.t == expected["t"], case["case"]

    def test_en50607_frames_are_polarization_invariant(self, loader: GoldenLoader):
        """The EN 50607 frame carries no polarization/band slots — the
        vertical/horizontal intent pair must produce the SAME frame."""
        vector = loader.load("unicable-tuning-message-bit-layout")
        table = json.loads(vector.ts_bytes.decode("utf-8"))
        by_case = {case["case"]: case for case in table["cases"]}
        vertical = by_case["en50607-polarization-invariant-vertical"]["expected"]
        horizontal = by_case["en50607-polarization-invariant-horizontal"]["expected"]
        assert vertical["frame_bytes"] == horizontal["frame_bytes"]
        assert vertical["t"] == horizontal["t"]

    def test_expectations_face_agrees_with_the_table(self, loader: GoldenLoader):
        vector = loader.load("unicable-tuning-message-bit-layout")
        table = json.loads(vector.ts_bytes.decode("utf-8"))
        entries = vector.expectations
        assert len(entries) == len(table["cases"]) == 21
        for entry, case in zip(entries, table["cases"]):
            assert entry["event_type"] == "sec.state_observed"
            assert entry["locator"] == {
                "node_type": "lnb",
                "case": case["case"],
            }
            assert entry["detail"] == {
                "protocol": case["protocol"],
                "frame_bytes": case["expected"]["frame_bytes"],
                "t": case["expected"]["t"],
            }


class TestUnicableFrequencyFormula:
    """SPEC-623 §6 — formulas I/II numeric vectors, golden-driven."""

    def test_production_t_values_match_the_golden_numbers(self, loader: GoldenLoader):
        vector = loader.load("unicable-frequency-formula")
        table = json.loads(vector.ts_bytes.decode("utf-8"))
        formula_i = table["formula_i"]
        assert formula_i["protocol"] == "EN50494"
        for case in formula_i["cases"]:
            assert en50494_t_value(case["f_if_mhz"], case["f_ub_mhz"]) == case["t"], case
        formula_ii = table["formula_ii"]
        assert formula_ii["protocol"] == "EN50607"
        for case in formula_ii["cases"]:
            assert en50607_t_value(case["f_if_mhz"]) == case["t"], case

    def test_expectations_face_agrees_with_the_table(self, loader: GoldenLoader):
        vector = loader.load("unicable-frequency-formula")
        table = json.loads(vector.ts_bytes.decode("utf-8"))
        entries = vector.expectations
        i_cases = table["formula_i"]["cases"]
        ii_cases = table["formula_ii"]["cases"]
        assert len(entries) == len(i_cases) + len(ii_cases) == 13
        for entry, case in zip(entries, i_cases):
            assert entry["event_type"] == "sec.state_observed"
            assert entry["locator"] == {
                "node_type": "lnb",
                "formula": "I",
                "f_if_mhz": case["f_if_mhz"],
                "f_ub_mhz": case["f_ub_mhz"],
            }
            assert entry["detail"]["t"] == case["t"]
        for entry, case in zip(entries[len(i_cases):], ii_cases):
            assert entry["event_type"] == "sec.state_observed"
            assert entry["locator"] == {
                "node_type": "lnb",
                "formula": "II",
                "f_if_mhz": case["f_if_mhz"],
            }
            assert entry["detail"]["t"] == case["t"]
