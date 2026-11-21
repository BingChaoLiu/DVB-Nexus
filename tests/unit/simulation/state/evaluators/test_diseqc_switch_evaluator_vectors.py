"""SPEC-622 §6 — DiSEqC switch register end-state vectors (#161).

Seam: ``simulation.state.evaluators.diseqc_switch_evaluator`` — the
register-reduction pure functions plus the :class:`DiseqcSwitchEvaluator`
shell.

Vector-first discipline (SPEC-622 §11.2): every register value below was
hand-computed from the §6 reduction semantics **before** the
implementation was written.

Bit semantics frozen by ticket #161 (REPORT-declared):

- Command mapping: 0x38 Write N0 = the ``committed`` register; 0x39
  Write N1 = the ``uncommitted`` register (SPEC-622 §2.1 command subset)
  — the structured intent carries the register name.
- Each write applies in declaration order: a ``high``-nibble write CLEARS
  the register's high nibble then places ``value`` there
  (``reg = (reg & 0x0F) | (value << 4)``); a ``low``-nibble write sets
  the low nibble (``reg = (reg & 0xF0) | value``) — 高 nibble 清 / 低
  nibble 置位逐条，终态 = 最后生效.
- Register state shape: one 8-bit JSON int per register (two 4-bit
  nibble groups; the SPEC-622 §5 "4 bit nibble 位组" gloss refers to the
  nibble-granular write semantics).  Reset state = 0 (no historical
  process artefacts, AC-622-02).
- ``port_selected = committed & 0x03`` — the 2-bit port select inside the
  4-bit committed register (classic 4-way committed switch), 0-based
  fan-out leg index; the declared port face is the coax_out port's
  ``max_connections`` (registry template budget 4).  A selection outside
  the declared face → error health (命令意图与端口面不符).
- No command intent → idle; register states stay at the reset value 0 and
  ``port_selected`` stays null.  The idle switch is signal-transparent:
  its output port health passes the feeder's health through (power-on
  state forwards the carrier), REPORT-frozen.
- Malformed writes (register/nibble outside the vocabulary, value outside
  0..15) are skipped no-ops at evaluation time — prepare rejection is the
  #163/#165 face, the walk's exception isolation stays reserved for
  evaluator-internal faults.
"""

from __future__ import annotations

import pytest

from simulation.state.evaluate import (
    EvalContext,
    Health,
    PortState,
)
from simulation.state.graph import NodeConfig, PortSpec
from simulation.state.evaluators import DiseqcSwitchEvaluator
from simulation.state.evaluators.diseqc_switch_evaluator import (
    derive_port_selected,
    port_face,
    reduce_registers,
)

pytestmark = pytest.mark.unit


def _write(register: str, nibble: str, value: int) -> dict:
    return {"register": register, "nibble": nibble, "value": value}


def _intent(*writes: dict, committed: bool = True, uncommitted: bool = False) -> dict:
    return {
        "target_register": {"committed": committed, "uncommitted": uncommitted},
        "nibble_writes": list(writes),
    }


class TestRegisterReduction:
    """AC-622-01 — bit semantics asserted bit-exactly; AC-622-02 — terminal
    states only, no historical process artefacts."""

    def test_committed_high_nibble_write_clears_then_sets(self) -> None:
        # 0x38 high-nibble write value 5: high nibble cleared then set
        # → 0b0101_0000 = 80; low nibble untouched (0).
        committed, uncommitted = reduce_registers([_write("committed", "high", 5)])
        assert committed == 0b0101_0000
        assert uncommitted == 0

    def test_committed_low_nibble_write_sets_low(self) -> None:
        committed, _uncommitted = reduce_registers([_write("committed", "low", 9)])
        assert committed == 0b0000_1001

    def test_uncommitted_write_leaves_committed_at_reset(self) -> None:
        # 0x39 write: the committed register keeps its reset state.
        committed, uncommitted = reduce_registers([_write("uncommitted", "high", 0xA)])
        assert committed == 0
        assert uncommitted == 0b1010_0000

    def test_sequence_high_then_low_last_wins(self) -> None:
        # Declaration order: high nibble first (0xF0), then the low nibble
        # set (|0x3) — the terminal state is 0xF3.
        committed, uncommitted = reduce_registers(
            [_write("committed", "high", 0xF), _write("committed", "low", 0x3)]
        )
        assert committed == 0b1111_0011
        assert uncommitted == 0

    def test_sequence_same_nibble_last_write_wins(self) -> None:
        committed, _uncommitted = reduce_registers(
            [_write("committed", "low", 5), _write("committed", "low", 9)]
        )
        assert committed == 9

    def test_sequence_across_registers_is_independent(self) -> None:
        committed, uncommitted = reduce_registers(
            [
                _write("committed", "low", 0x1),
                _write("uncommitted", "high", 0xC),
                _write("committed", "high", 0x2),
            ]
        )
        assert committed == 0b0010_0001
        assert uncommitted == 0b1100_0000

    def test_empty_write_list_keeps_reset_state(self) -> None:
        committed, uncommitted = reduce_registers([])
        assert (committed, uncommitted) == (0, 0)

    def test_malformed_writes_are_skipped_no_ops(self) -> None:
        # REPORT-frozen: out-of-subset register names (0x5A-style foreign
        # commands), unknown nibbles and out-of-range values never apply —
        # prepare rejection is the #163/#165 face.
        committed, uncommitted = reduce_registers(
            [
                _write("0x5A", "low", 3),
                _write("committed", "middle", 3),
                _write("committed", "low", 99),
                _write("committed", "low", "7"),
            ]
        )
        assert (committed, uncommitted) == (0, 0)

    def test_undeclared_register_write_is_skipped(self) -> None:
        # A write referencing a register target_register does not declare:
        # skipped (the DTO validator is the config-period face).
        intent = _intent(
            _write("uncommitted", "low", 4), committed=True, uncommitted=False
        )
        committed, uncommitted = reduce_registers(
            intent["nibble_writes"],
            target_register=intent["target_register"],
        )
        assert committed == 0
        assert uncommitted == 0


class TestPortSelected:
    """port_selected 派生：f(committed nibbles)，值域 = 声明端口面."""

    def test_derivation_masks_the_two_port_select_bits(self) -> None:
        assert derive_port_selected(0b0000_0000) == 0
        assert derive_port_selected(0b0000_0001) == 1
        assert derive_port_selected(0b0000_0010) == 2
        assert derive_port_selected(0b0000_0011) == 3
        assert derive_port_selected(0b0101_0100) == 0
        assert derive_port_selected(0b1111_1111) == 3

    def test_port_face_reads_the_output_port_budget(self) -> None:
        node = NodeConfig(
            node_id="sw-0",
            node_type="diseqc_switch",
            config={},
            ports=[
                PortSpec(port_id="coax_in", direction="input", plane="SEC_CONTROL", max_connections=1),
                PortSpec(port_id="coax_out", direction="output", plane="SEC_CONTROL", max_connections=4),
            ],
        )
        assert port_face(node) == 4

    def test_port_face_none_when_undeclared(self) -> None:
        node = NodeConfig(
            node_id="sw-0",
            node_type="diseqc_switch",
            config={},
            ports=[
                PortSpec(port_id="coax_in", direction="input", plane="SEC_CONTROL"),
                PortSpec(port_id="coax_out", direction="output", plane="SEC_CONTROL"),
            ],
        )
        assert port_face(node) is None


# -- evaluator shell helpers -----------------------------------------------------


def _switch_node(config: dict, max_connections: int | None = 4) -> NodeConfig:
    return NodeConfig(
        node_id="sw-0",
        node_type="diseqc_switch",
        config=config,
        ports=[
            PortSpec(port_id="coax_in", direction="input", plane="SEC_CONTROL", max_connections=1),
            PortSpec(
                port_id="coax_out",
                direction="output",
                plane="SEC_CONTROL",
                max_connections=max_connections,
            ),
        ],
    )


def _evaluate(
    config: dict,
    feeder: PortState | None = None,
    node: NodeConfig | None = None,
):
    evaluator = DiseqcSwitchEvaluator()
    node = node or _switch_node(config)
    inputs = {"coax_in": feeder} if feeder is not None else {}
    return evaluator.evaluate(node, inputs, EvalContext(topology_revision=1))


def _config(power_pass: str = "on", diseqc_commands: dict | None = None) -> dict:
    return {"power_pass": power_pass, "diseqc_commands": diseqc_commands}


def _lnb_facts(**overrides: object) -> dict:
    facts = {
        "lo_frequency_khz": 9_750_000,
        "band_selected": "low",
        "polarization_delivered": "vertical",
        "ub_assignments": [],
    }
    facts.update(overrides)
    return facts


class TestSwitchEvaluatorShell:
    """Config intent in → terminal register facts out (AC-622-04 shape)."""

    def test_metrics_key_set_is_frozen(self) -> None:
        result = _evaluate(_config(power_pass="on"))
        assert set(result.metrics) == {
            "committed_switch_state",
            "uncommitted_switch_state",
            "port_selected",
            "power_pass",
        }

    def test_no_intent_is_idle_with_reset_registers(self) -> None:
        result = _evaluate(_config(power_pass="on"))
        assert result.health is Health.IDLE
        assert result.metrics["committed_switch_state"] == 0
        assert result.metrics["uncommitted_switch_state"] == 0
        assert result.metrics["port_selected"] is None
        assert result.metrics["power_pass"] == "on"

    def test_single_committed_write_terminal_state(self) -> None:
        result = _evaluate(_config(diseqc_commands=_intent(_write("committed", "high", 5))))
        assert result.health is Health.OK
        assert result.metrics["committed_switch_state"] == 80
        assert result.metrics["uncommitted_switch_state"] == 0
        assert result.metrics["port_selected"] == 0

    def test_low_nibble_write_selects_port_one(self) -> None:
        result = _evaluate(_config(diseqc_commands=_intent(_write("committed", "low", 9))))
        assert result.metrics["committed_switch_state"] == 9
        assert result.metrics["port_selected"] == 1
        assert result.health is Health.OK

    def test_multi_write_sequence_last_effect_wins(self) -> None:
        result = _evaluate(
            _config(
                diseqc_commands=_intent(
                    _write("committed", "high", 0xF), _write("committed", "low", 0x3)
                )
            )
        )
        assert result.metrics["committed_switch_state"] == 243
        assert result.metrics["port_selected"] == 3

    def test_intent_on_fallback_channel_via_feeder_metrics(self) -> None:
        # The composition bridge channel: the tuner-side command intent may
        # arrive through the feeding port's A2 metrics (REPORT-frozen
        # fallback; primary source = the switch's own config).
        feeder = PortState(
            port_id="coax_in",
            health=Health.OK,
            metrics={"diseqc_commands": _intent(_write("committed", "low", 2))},
        )
        result = _evaluate(_config(power_pass="on"), feeder=feeder)
        assert result.metrics["committed_switch_state"] == 2
        assert result.metrics["port_selected"] == 2

    def test_face_mismatch_is_error(self) -> None:
        # 命令意图与端口面不符 → error: port 3 outside a 2-leg face.
        node = _switch_node(_config(diseqc_commands=_intent(_write("committed", "low", 3))), max_connections=2)
        result = _evaluate({}, feeder=None, node=node)
        assert result.metrics["port_selected"] == 3
        assert result.health is Health.ERROR

    def test_face_none_accepts_any_selection(self) -> None:
        node = _switch_node(_config(diseqc_commands=_intent(_write("committed", "low", 3))), max_connections=None)
        result = _evaluate({}, feeder=None, node=node)
        assert result.metrics["port_selected"] == 3
        assert result.health is Health.OK

    def test_power_pass_passthrough(self) -> None:
        # config 透传 — the power-domain evaluation belongs to SPEC-621.
        result = _evaluate(_config(power_pass="off"))
        assert result.metrics["power_pass"] == "off"
        assert result.health is Health.IDLE

    def test_output_port_merges_upstream_signal_facts(self) -> None:
        # The A2 channel: coax_out carries the feeder's signal facts merged
        # with the switch's own metrics — SCR tuners behind the switch see
        # the lnb's ub_assignments table through the chain.
        table = [{"tuner_node": "tuner-a", "ub_slot": 0}]
        feeder = PortState(port_id="coax_in", health=Health.OK, metrics=_lnb_facts(ub_assignments=table))
        result = _evaluate(_config(diseqc_commands=_intent(_write("committed", "low", 1))), feeder=feeder)
        (coax_out,) = [state for state in result.port_states if state.port_id == "coax_out"]
        assert coax_out.metrics["committed_switch_state"] == 1
        assert coax_out.metrics["port_selected"] == 1
        assert coax_out.metrics["lo_frequency_khz"] == 9_750_000
        assert coax_out.metrics["ub_assignments"] == table

    def test_idle_node_is_signal_transparent(self) -> None:
        # REPORT-frozen: an idle (no-intent) switch forwards the feeder's
        # signal health on its output port — the power-on state passes the
        # carrier; the node-level idle marks the command domain only.
        feeder = PortState(port_id="coax_in", health=Health.OK, metrics=_lnb_facts())
        result = _evaluate(_config(power_pass="on"), feeder=feeder)
        assert result.health is Health.IDLE
        (coax_out,) = [state for state in result.port_states if state.port_id == "coax_out"]
        assert coax_out.health is Health.OK

    def test_error_node_propagates_to_output_port(self) -> None:
        feeder = PortState(port_id="coax_in", health=Health.OK, metrics=_lnb_facts())
        node = _switch_node(_config(diseqc_commands=_intent(_write("committed", "low", 3))), max_connections=2)
        result = _evaluate({}, feeder=feeder, node=node)
        assert result.health is Health.ERROR
        (coax_out,) = [state for state in result.port_states if state.port_id == "coax_out"]
        assert coax_out.health is Health.ERROR

    def test_no_feeder_output_health_is_node_health(self) -> None:
        result = _evaluate(_config(diseqc_commands=_intent(_write("committed", "low", 1))))
        (coax_out,) = [state for state in result.port_states if state.port_id == "coax_out"]
        assert coax_out.health is Health.OK

    def test_all_ports_reported(self) -> None:
        result = _evaluate(_config(power_pass="on"))
        assert [state.port_id for state in result.port_states] == ["coax_in", "coax_out"]

    def test_metrics_values_json_safe(self) -> None:
        result = _evaluate(_config(diseqc_commands=_intent(_write("committed", "high", 5))))
        for value in result.metrics.values():
            assert value is None or isinstance(value, (bool, int, str, list))

    def test_determinism_same_input_same_output(self) -> None:
        # AC-622-06: double run, field-identical.
        config = _config(diseqc_commands=_intent(_write("committed", "high", 0xF)))
        first = _evaluate(config)
        second = _evaluate(config)
        assert first == second
