"""SPEC-622 §6 — the DiSEqC switch register reduction + evaluator (#161).

Seam: ``simulation.state.evaluators.diseqc_switch_evaluator`` — registered
under the ``"diseqc_switch"`` node-type wire string via
:func:`evaluate_topology`'s injection mapping
(:data:`simulation.state.evaluators.DEFAULT_EVALUATORS`).

Pure-function core (each independently unit-tested):

- :func:`reduce_registers` — the §6 terminal-state reduction: writes apply
  in declaration order, a ``high``-nibble write clears the register's high
  nibble then places the value (``reg = (reg & 0x0F) | (value << 4)``), a
  ``low``-nibble write sets the low nibble — 高 nibble 清 / 低 nibble
  置位逐条，终态 = 最后生效.  Registers are 8-bit JSON ints (two 4-bit
  nibble groups; the §5 "4 bit nibble 位组" gloss refers to the
  nibble-granular write semantics, REPORT-frozen); the reset state is 0
  and no historical process artefact survives (AC-622-02).  Malformed
  writes (register/nibble outside the {0x38→committed, 0x39→uncommitted}
  subset, value outside 0..15) are skipped no-ops — prepare rejection is
  the #163/#165 face.  When ``target_register`` is supplied, writes to
  registers it does not declare are skipped too.
- :func:`derive_port_selected` — ``committed & 0x03``: the 2-bit port
  select inside the 4-bit committed register (classic 4-way committed
  switch), 0-based fan-out leg index.
- :func:`port_face` — the declared port face: the first output port's
  ``max_connections`` (registry template budget 4, aligned with the 4-bit
  register space); ``None`` = unbounded.

Shell semantics (REPORT-frozen):

- Command intent source: the switch's own config ``diseqc_commands`` key
  (SPEC-622 §5 structured shape verbatim) with the feeding port's A2
  ``PortState.metrics`` as the fallback channel — the spec places the
  intent on the *tuner* config, but the frozen walk evaluates the switch
  upstream of the tuners, so the composition root (#165) bridges the
  tuner-side intent into the switch config (or the signal-chain
  fallback); the seam decision is flagged to the orchestrator.
- No command intent → idle health; register states stay at the reset
  value 0 and ``port_selected`` stays null.  The idle switch is signal-
  transparent: its output port health forwards the feeder's health (the
  power-on state passes the carrier); an error/warn node health
  (command intent vs port face mismatch) propagates to the output port.
- ``power_pass`` is config passthrough only — the power-domain evaluation
  belongs to SPEC-621 (a missing key stays ``None`` in the metrics rather
  than being invented).
- Output ports merge the feeder's signal facts with the switch's own
  metrics on the A2 channel — SCR tuners behind the switch see the lnb's
  ``ub_assignments`` table through the chain.
- The §7 timing constants (PWK 500 µs / ≥6 ms silence / >15 ms gaps /
  ≥100 ms cascade spacing / 2.x reply ≤150 ms, Eutelsat BFS v4.2) are a
  reference table and never enter the evaluation products.
"""

from __future__ import annotations

from simulation.state.evaluate import (
    EvalContext,
    Health,
    NodeEvalResult,
    PortState,
    severity_rank,
)
from simulation.state.evaluators._vocab import (
    COMMITTED_CONFIG_KEY,
    DISEQC_COMMANDS_CONFIG_KEY,
    NIBBLES,
    NIBBLE_CONFIG_KEY,
    PORT_SELECT_MASK,
    POWER_PASS_CONFIG_KEY,
    REGISTERS,
    REGISTER_CONFIG_KEY,
    REGISTER_NIBBLE_SHIFT,
    SWITCH_METRIC_KEYS,
    UNCOMMITTED_CONFIG_KEY,
    VALUE_CONFIG_KEY,
)
from simulation.state.graph import NodeConfig

__all__ = [
    "DiseqcSwitchEvaluator",
    "derive_port_selected",
    "port_face",
    "reduce_registers",
]


def _is_int(value: object) -> bool:
    """int but not bool (booleans sneak in through JSON wire dicts)."""
    return isinstance(value, int) and not isinstance(value, bool)


def reduce_registers(
    nibble_writes: object,
    target_register: object = None,
) -> tuple[int, int]:
    """The §6 register end-state reduction (declaration order, last wins).

    ``target_register`` mirrors the intent's ``{committed, uncommitted}``
    declaration: writes referencing an undeclared register are skipped
    (the DTO validator is the config-period face; evaluation-time the
    write is a no-op).  Returns ``(committed, uncommitted)`` as 8-bit ints.
    """
    declared: dict[str, bool] | None = None
    if isinstance(target_register, dict):
        declared = {
            COMMITTED_CONFIG_KEY: target_register.get(COMMITTED_CONFIG_KEY) is True,
            UNCOMMITTED_CONFIG_KEY: target_register.get(UNCOMMITTED_CONFIG_KEY) is True,
        }

    committed = 0
    uncommitted = 0
    if not isinstance(nibble_writes, list):
        return committed, uncommitted

    for write in nibble_writes:
        if not isinstance(write, dict):
            continue
        register = write.get(REGISTER_CONFIG_KEY)
        nibble = write.get(NIBBLE_CONFIG_KEY)
        value = write.get(VALUE_CONFIG_KEY)
        if register not in REGISTERS or nibble not in NIBBLES:
            continue  # out-of-subset command (0x5A-style): no-op
        if not _is_int(value) or not 0 <= value <= 15:
            continue
        if declared is not None and not declared.get(register, False):
            continue  # write to an undeclared register: no-op
        if register == COMMITTED_CONFIG_KEY:
            committed = _apply_nibble(committed, nibble, value)
        else:
            uncommitted = _apply_nibble(uncommitted, nibble, value)
    return committed, uncommitted


def _apply_nibble(register: int, nibble: str, value: int) -> int:
    """高 nibble 清 / 低 nibble 置位，逐条应用."""
    if nibble == "high":
        return (register & 0x0F) | (value << REGISTER_NIBBLE_SHIFT)
    return (register & 0xF0) | value


def derive_port_selected(committed_switch_state: int) -> int:
    """The port select bits inside the committed register (0-based leg)."""
    return committed_switch_state & PORT_SELECT_MASK


def port_face(node: NodeConfig) -> int | None:
    """The declared fan-out face: the first output port's max_connections."""
    for port in node.ports:
        if port.direction.value == "output":
            return port.max_connections
    return None


def _severity_merge(left: Health, right: Health) -> Health:
    return left if severity_rank(left) >= severity_rank(right) else right


class DiseqcSwitchEvaluator:
    """The ``diseqc_switch`` node evaluator shell (SPEC-202 §6.1 shape)."""

    def evaluate(
        self,
        node: NodeConfig,
        inputs: dict,
        context: EvalContext,
    ) -> NodeEvalResult:
        config = node.config if isinstance(node.config, dict) else {}

        power_pass = config.get(POWER_PASS_CONFIG_KEY)

        feeder: PortState | None = None
        for state in inputs.values():
            feeder = state
            break  # the walk's deterministic first feeder
        feeder_metrics = (
            feeder.metrics
            if feeder is not None and isinstance(feeder.metrics, dict)
            else {}
        )

        intent = config.get(DISEQC_COMMANDS_CONFIG_KEY)
        if not isinstance(intent, dict):
            intent = feeder_metrics.get(DISEQC_COMMANDS_CONFIG_KEY)

        if not isinstance(intent, dict):
            # No command intent → idle; registers at reset, no selection.
            own_metrics = {
                "committed_switch_state": 0,
                "uncommitted_switch_state": 0,
                "port_selected": None,
                "power_pass": power_pass,
            }
            health = Health.IDLE
        else:
            committed, uncommitted = reduce_registers(
                intent.get("nibble_writes"),
                target_register=intent.get("target_register"),
            )
            port_selected = derive_port_selected(committed)
            face = port_face(node)
            if face is not None and port_selected >= face:
                health = Health.ERROR  # 命令意图与端口面不符
            else:
                health = Health.OK
            own_metrics = {
                "committed_switch_state": committed,
                "uncommitted_switch_state": uncommitted,
                "port_selected": port_selected,
                "power_pass": power_pass,
            }

        # Output-port health: an idle (no-intent) switch is signal-
        # transparent (the feeder's health passes through); an
        # error/warn/ok node health merges by severity with the feeder's.
        if health is Health.IDLE and feeder is not None:
            output_health = feeder.health
        elif feeder is not None:
            output_health = _severity_merge(feeder.health, health)
        else:
            output_health = health

        output_metrics = {**feeder_metrics, **own_metrics}
        port_states = tuple(
            PortState(
                port_id=port.port_id,
                health=output_health if port.direction.value == "output" else health,
                metrics=output_metrics if port.direction.value == "output" else {},
            )
            for port in node.ports
        )
        metrics = {
            key: own_metrics[key]
            for key in SWITCH_METRIC_KEYS
        }
        return NodeEvalResult(
            node_id=node.node_id,
            health=health,
            port_states=port_states,
            metrics=metrics,
            causes=(),
        )
