"""SPEC-623 sections 6/7/8 — Unicable (EN 50494 / EN 50607) pure functions.

Ticket #162 pure-function module (ruling A7): four deterministic, I/O-free
families consumed by the #161 evaluators, the #163 fault transforms and the
#164 observation bridge:

1. **tuning-message construction** — :func:`build_tuning_message` packs the
   terminal (protocol, ub_assignment, tuning_request) fact into the wire
   frame.  EN 50494 (ODU_channel_change) ``[0xE0, 0x10, 0x5A, data1, data2]``
   with the multihome PIN variant = 6 bytes / command byte ``0x5C``; EN 50607
   (dCSS) ``[0x70, data1, data2, data3]`` with the PIN variant = 5 bytes /
   command byte ``0x71``.  EN 50494 framing/address bytes reuse the SPEC-622
   §2.1 DiSEqC framework vocabulary (``0xE0`` framing, ``0x10`` address);
   the EN 50607 frame bytes are not DiSEqC framework members (sandbox:
   construction only, no send path).

2. **frequency formulas** — :func:`en50494_t_value` /
   :func:`en50607_t_value`, the SPEC-623 §6 normative forms
   ``t = round((f_IF + f_UB + 2)/4) - 350`` and ``t = f_IF - 100``.

3. **UB conflict detection** — :func:`ub_conflicts`, the three-branch
   structural judgement (conflict pairs / no conflict / cross-protocol
   reject) shared by the SPEC-620 lock evaluation and UB static validation.

4. **prepare validation** — :func:`prepare_violations`, the bit-width /
   t-overflow / vocabulary guards (SPEC-623 §8 prepare-reject rows).

Bit conventions (pinned by test vectors; see
``tests/unit/simulation/state/test_unicable.py``):

- data1 field order is MSB-first as listed in the SPEC-623 §6 table:
  EN 50494 ``[UB:7-5 | position:4 | polarization:3 | band:2 | t:1-0]`` with
  ``data2 = t[7:0]``; EN 50607 ``data1 = [UB:7-3 | t:2-0]``,
  ``data2 = t[7:0]``, ``data3 = [position:7-2 | reserved-zero:1-0]``.
- value mappings follow the DiSEqC-generic defaults authorised by the
  ticket: polarization 0 = vertical / 1 = horizontal, band 0 = low /
  1 = high, position 0 = A / 1 = B (EN 50494).
- band derives from the tuning frequency against the universal-LNB
  boundary 11700000 kHz (SPEC-621 appendix A band plan: the low band ends
  at 11.70 GHz).
- the formula's ``round`` is round-half-up on the /4, implemented
  integer-exact as ``(n + 2) // 4`` — no float arithmetic anywhere.

Clause-number discipline: the EN 50494:2007 / EN 50607:2015 standard texts
are paywalled (issue #145 gap list, all "pending original-text check") —
the bit layout and formulas are annotated **"four-implementation
source-level consensus (tvheadend ``linuxdvb_en50494.c`` / VDR ``diseqc.c``
/ MuMuDVB ``tune.c`` / minisatip ``dvb.cpp`` cross-checked)"** and no
clause number of either standard is ever written.  The majority-side
frequency semantics is taken per the SPEC-623 §6 divergence record
(minisatip omits the ``+2``; majority keeps it).

Protocol/width vocabulary is **reused, not redefined**: the constants come
from :mod:`simulation.state.validate` (ticket #160's validator-side
vocabulary; importlinter contract 8 forbids ``domain.topology`` imports,
ruling A1 — the #161 DTO drift lock covers the mirrored field names).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from simulation.state.validate import (
    MAX_UB_SLOT_BY_PROTOCOL,
    PROTOCOL_CONFIG_KEY,
    TUNER_NODE_CONFIG_KEY,
    UB_SLOT_CONFIG_KEY,
    UNICABLE_PROTOCOL_EN50494,
    UNICABLE_PROTOCOL_EN50607,
    UNICABLE_PROTOCOLS,
)

__all__ = [
    "BAND_BIT_HIGH",
    "BAND_BIT_LOW",
    "EN50494_ADDRESS_BYTE",
    "EN50494_COMMAND_BYTE",
    "EN50494_FRAMING_BYTE",
    "EN50494_PIN_COMMAND_BYTE",
    "EN50494_POSITIONS",
    "EN50494_T_BIAS",
    "EN50494_T_DIVISOR",
    "EN50494_T_NUMERATOR_OFFSET_MHZ",
    "EN50607_COMMAND_BYTE",
    "EN50607_PIN_COMMAND_BYTE",
    "EN50607_POSITION_MAX",
    "EN50607_T_BIAS",
    "MAX_UB_SLOT_BY_PROTOCOL",
    "MAX_T_BY_PROTOCOL",
    "PIN_MAX",
    "PIN_MIN",
    "POLARIZATION_BIT_HORIZONTAL",
    "POLARIZATION_BIT_VERTICAL",
    "POLARIZATIONS",
    "POSITION_BIT_A",
    "POSITION_BIT_B",
    "T_BIT_WIDTH_BY_PROTOCOL",
    "TUNER_CONFIG_NODE_KEY",
    "UNIVERSAL_BAND_BOUNDARY_KHZ",
    "UBPrepareError",
    "UBProtocolMixedError",
    "TuningMessage",
    "build_tuning_message",
    "en50494_t_value",
    "en50607_t_value",
    "prepare_violations",
    "t_value",
    "ub_conflicts",
]


# -- frame / field constants (SPEC-623 §6; four-implementation consensus) -----

#: EN 50494 framing byte — master command, no reply, first transmission
#: (SPEC-622 §2.1 normative framing subset member).
EN50494_FRAMING_BYTE = 0xE0
#: EN 50494 address byte — "any LNB, switcher or SMATV" (SPEC-622 §2.1).
EN50494_ADDRESS_BYTE = 0x10
#: EN 50494 ODU_channel_change command byte.
EN50494_COMMAND_BYTE = 0x5A
#: EN 50494 multihome (PIN) variant command byte — 6-byte frame, PIN appended.
EN50494_PIN_COMMAND_BYTE = 0x5C

#: EN 50607 dCSS ODU_channel_change command byte (not a DiSEqC framework
#: member — construction-only in the sandbox).
EN50607_COMMAND_BYTE = 0x70
#: EN 50607 PIN variant command byte — 5-byte frame, PIN appended.
EN50607_PIN_COMMAND_BYTE = 0x71

#: EN 50494 position vocabulary (domain ``UbAssignmentDTO`` mirror:
#: str ``"A"``/``"B"``); EN 50607 positions are ints 0..63.
EN50494_POSITIONS: tuple[str, ...] = ("A", "B")
EN50607_POSITION_MAX = 63

#: Bit-level value mappings (DiSEqC-generic defaults, ticket-authorised;
#: the SPEC-623 §6 table fixes the slots but not the value mapping).
POSITION_BIT_A = 0
POSITION_BIT_B = 1
POLARIZATION_BIT_VERTICAL = 0
POLARIZATION_BIT_HORIZONTAL = 1
BAND_BIT_LOW = 0
BAND_BIT_HIGH = 1

#: Universal-LNB band boundary: tuning frequencies at/above this are high
#: band (SPEC-621 appendix A band plan: low band ends at 11.70 GHz).
UNIVERSAL_BAND_BOUNDARY_KHZ = 11_700_000

#: Polarization vocabulary (domain ``TuningRequestDTO`` mirror).
POLARIZATIONS: tuple[str, ...] = ("vertical", "horizontal")

#: PIN byte domain (domain ``UbAssignmentDTO`` mirror: ``pin`` 0..255).
PIN_MIN = 0
PIN_MAX = 255

#: Identity key inside ``tuner_configs`` entries handed to
#: :func:`ub_conflicts` (the graph-side ``node_id``; assignment entries use
#: the #160 ``tuner_node`` key instead).
TUNER_CONFIG_NODE_KEY = "node_id"

#: Config-dict key names mirrored from the domain config DTOs that #160
#: did not export (``validate.py`` owns scr/protocol/ub_slot/tuner_node).
UB_CENTER_FREQ_CONFIG_KEY = "ub_center_freq_mhz"
POSITION_CONFIG_KEY = "position"
PIN_CONFIG_KEY = "pin"
FREQUENCY_KHZ_CONFIG_KEY = "frequency_khz"
POLARIZATION_CONFIG_KEY = "polarization"


# -- formula constants (SPEC-623 §6 normative forms) ---------------------------

#: Formula I numerator constant: ``t = round((f_IF + f_UB + 2)/4) - 350``
#: (majority-side semantics per the §6 divergence record; minisatip omits it).
EN50494_T_NUMERATOR_OFFSET_MHZ = 2
#: Formula I divisor (MHz-domain quartic grid).
EN50494_T_DIVISOR = 4
#: Formula I bias: the ``- 350`` constant path.
EN50494_T_BIAS = 350
#: Formula II bias: EN 50607 ``t = f_IF - 100``.
EN50607_T_BIAS = 100


# -- width tables (SPEC-623 §2.1/§8; UB widths reused from #160) --------------

#: ``t`` field bit width per protocol (EN 50494: 10 bits, EN 50607: 11 bits
#: at 1 MHz resolution).
T_BIT_WIDTH_BY_PROTOCOL: dict[str, int] = {
    UNICABLE_PROTOCOL_EN50494: 10,
    UNICABLE_PROTOCOL_EN50607: 11,
}

#: Highest encodable ``t`` per protocol (SPEC-623 §8 overflow row:
#: EN 50494 > 1023 / EN 50607 > 2047 reject).
MAX_T_BY_PROTOCOL: dict[str, int] = {
    UNICABLE_PROTOCOL_EN50494: 1023,
    UNICABLE_PROTOCOL_EN50607: 2047,
}


# -- exceptions (module-owned; REPORT-frozen rejection semantics) --------------


class UBProtocolMixedError(ValueError):
    """Cross-protocol UB context (SPEC-623 §7: the EN 50494 and EN 50607
    UB spaces are independent — mixing is a prepare rejection).

    Raised by :func:`ub_conflicts` when the assignment/claim context
    carries more than one distinct protocol token.
    """


class UBPrepareError(ValueError):
    """One or more message-construction rejections (SPEC-623 §8).

    ``violations`` carries the frozen, deterministically ordered detail
    strings (same shape :func:`prepare_violations` returns) so callers can
    project them into their own error surface without re-parsing text.
    """

    def __init__(self, violations: Iterable[str]) -> None:
        self.violations: tuple[str, ...] = tuple(violations)
        super().__init__("; ".join(self.violations))


# -- frequency formulas (SPEC-623 §6, AC-623-02) -------------------------------


def en50494_t_value(f_if_mhz: int, f_ub_mhz: int) -> int:
    """Formula I — EN 50494 ``t = round((f_IF + f_UB + 2)/4) - 350`` (MHz).

    The receiver front end tunes ``(t + 350) * 4 - f_IF ≈ f_UB + 2`` MHz.
    Rounding is round-half-up on the /4, integer-exact as
    ``(n + 2) // 4`` (pinned by the rounding quadruple in the test
    vectors).  Pure arithmetic — range enforcement lives in
    :func:`prepare_violations`.
    """
    numerator = f_if_mhz + f_ub_mhz + EN50494_T_NUMERATOR_OFFSET_MHZ
    return (
        numerator + EN50494_T_DIVISOR // 2
    ) // EN50494_T_DIVISOR - EN50494_T_BIAS


def en50607_t_value(f_if_mhz: int) -> int:
    """Formula II — EN 50607 ``t = f_IF - 100`` (MHz, 1 MHz resolution).

    Below the 100 MHz offset the pure formula goes negative; encoding
    rejection is the prepare layer's job (declared seam split).
    """
    return f_if_mhz - EN50607_T_BIAS


def t_value(protocol: str, f_if_mhz: int, f_ub_mhz: int | None = None) -> int:
    """Protocol-dispatched ``t`` computation.

    EN 50494 requires ``f_ub_mhz`` (formula I's ``f_UB``); EN 50607 ignores
    it.  Unknown protocols raise :class:`UBPrepareError`.
    """
    if protocol == UNICABLE_PROTOCOL_EN50494:
        if f_ub_mhz is None:
            raise UBPrepareError(
                (f"ub_center_freq_mhz: required to compute t for {protocol}",)
            )
        return en50494_t_value(f_if_mhz, f_ub_mhz)
    if protocol == UNICABLE_PROTOCOL_EN50607:
        return en50607_t_value(f_if_mhz)
    raise UBPrepareError(
        (f"protocol: {protocol!r} outside the supported set {UNICABLE_PROTOCOLS}",)
    )


# -- prepare validation (SPEC-623 §8 rows, AC-623-03 width / t overflow) -------


def _is_int(value: object) -> bool:
    """int but not bool (booleans sneak in through JSON wire dicts)."""
    return isinstance(value, int) and not isinstance(value, bool)


def _violation(prefix: str, detail: str) -> str:
    return f"{prefix}: {detail}"


def prepare_violations(
    protocol: str,
    ub_assignment: dict,
    if_frequency_mhz: int,
    tuning_request: dict | None = None,
) -> tuple[str, ...]:
    """Message-input prepare gate (SPEC-623 §8; REPORT-frozen order).

    Validates exactly the inputs provided and returns deterministically
    ordered violation detail strings (empty tuple = valid):

    ``protocol`` → ``ub_slot`` → ``position`` → ``pin`` →
    ``polarization`` → ``frequency_khz`` → ``if_frequency`` → ``t``.

    Omitting ``tuning_request`` keeps the slot/width/t-only mode for
    callers that re-check a single field set (e.g. #163 fault transforms).
    The ``t`` check is skipped when its own inputs (``if_frequency`` /
    ``ub_center_freq_mhz``) already failed their guards — no garbage-
    derived t details.
    """
    violations: list[str] = []

    if protocol not in UNICABLE_PROTOCOLS:
        return (
            _violation(
                "protocol", f"{protocol!r} outside the supported set {UNICABLE_PROTOCOLS}"
            ),
        )

    slot = ub_assignment.get(UB_SLOT_CONFIG_KEY)
    if not _is_int(slot) or not 0 <= slot <= MAX_UB_SLOT_BY_PROTOCOL[protocol]:
        violations.append(
            _violation(
                "ub_slot",
                f"{slot!r} outside the {protocol} width "
                f"0..{MAX_UB_SLOT_BY_PROTOCOL[protocol]}",
            )
        )

    position = ub_assignment.get(POSITION_CONFIG_KEY)
    if protocol == UNICABLE_PROTOCOL_EN50494:
        if not isinstance(position, str) or position not in EN50494_POSITIONS:
            violations.append(
                _violation(
                    "position",
                    f"{position!r} outside the {protocol} vocabulary "
                    f"{EN50494_POSITIONS}",
                )
            )
    elif not _is_int(position) or not 0 <= position <= EN50607_POSITION_MAX:
        violations.append(
            _violation(
                "position",
                f"{position!r} outside the {protocol} domain 0..{EN50607_POSITION_MAX}",
            )
        )

    pin = ub_assignment.get(PIN_CONFIG_KEY)
    if pin is not None and (not _is_int(pin) or not PIN_MIN <= pin <= PIN_MAX):
        violations.append(
            _violation("pin", f"{pin!r} outside the PIN domain {PIN_MIN}..{PIN_MAX}")
        )

    if tuning_request is not None:
        polarization = tuning_request.get(POLARIZATION_CONFIG_KEY)
        if polarization not in POLARIZATIONS:
            violations.append(
                _violation(
                    "polarization",
                    f"{polarization!r} outside the vocabulary {POLARIZATIONS}",
                )
            )
        frequency_khz = tuning_request.get(FREQUENCY_KHZ_CONFIG_KEY)
        if not _is_int(frequency_khz) or frequency_khz < 1:
            violations.append(
                _violation("frequency_khz", f"{frequency_khz!r} must be an int >= 1")
            )

    if not _is_int(if_frequency_mhz) or if_frequency_mhz < 0:
        violations.append(
            _violation(
                "if_frequency", f"{if_frequency_mhz!r} must be an int >= 0 (MHz)"
            )
        )
        return tuple(violations)

    # t range — computed from the guarded inputs only.
    f_ub_mhz = ub_assignment.get(UB_CENTER_FREQ_CONFIG_KEY)
    if protocol == UNICABLE_PROTOCOL_EN50494:
        if not _is_int(f_ub_mhz) or f_ub_mhz < 1:
            violations.append(
                _violation(
                    "ub_center_freq_mhz",
                    f"{f_ub_mhz!r} must be an int >= 1 (MHz) to compute t",
                )
            )
            return tuple(violations)
    t = t_value(protocol, if_frequency_mhz, f_ub_mhz)
    if not 0 <= t <= MAX_T_BY_PROTOCOL[protocol]:
        violations.append(
            _violation(
                "t",
                f"{t} outside the encodable range 0..{MAX_T_BY_PROTOCOL[protocol]} "
                f"({T_BIT_WIDTH_BY_PROTOCOL[protocol]} bits)",
            )
        )
    return tuple(violations)


# -- tuning-message construction (SPEC-623 §6, AC-623-01/06) -------------------


@dataclass(frozen=True)
class TuningMessage:
    """Terminal tuning-message fact (SPEC-623 §5 ``tuning_message`` keys).

    ``frame_bytes`` is an immutable int tuple (one element per wire byte);
    :meth:`payload` projects the JSON-safe dict for the #164 snapshot
    events (keys ``protocol`` / ``frame_bytes`` / ``t``).
    """

    protocol: str
    frame_bytes: tuple[int, ...]
    t: int

    def payload(self) -> dict:
        """JSON-safe projection (SPEC-623 §5 metrics-key shape)."""
        return {
            "protocol": self.protocol,
            "frame_bytes": list(self.frame_bytes),
            "t": self.t,
        }


def build_tuning_message(
    protocol: str,
    ub_assignment: dict,
    tuning_request: dict,
    *,
    if_frequency_mhz: int,
) -> TuningMessage:
    """Construct the terminal Unicable tuning message (deterministic).

    Inputs are the #160 config-dict shapes (``ub_assignment`` mirrors
    ``UbAssignmentDTO``: ``ub_slot`` / ``ub_center_freq_mhz`` / ``position``
    / ``pin``; ``tuning_request`` mirrors ``TuningRequestDTO``:
    ``frequency_khz`` / ``polarization``).  ``if_frequency_mhz`` is the
    tuner's post-LO intermediate frequency in MHz (SPEC-620's
    ``if_frequency_khz`` / 1000) — the ticket-authorised constructor input
    carrying the t-source decision; ``t`` is always the frequency-formula
    output, never an independent input.

    Raises :class:`UBPrepareError` (with the :func:`prepare_violations`
    detail strings) on any SPEC-623 §8 rejection; identical inputs always
    produce identical frames (SPEC-623 §7 determinism obligation).
    """
    violations = prepare_violations(
        protocol, ub_assignment, if_frequency_mhz, tuning_request=tuning_request
    )
    if violations:
        raise UBPrepareError(violations)

    slot = ub_assignment[UB_SLOT_CONFIG_KEY]
    pin = ub_assignment.get(PIN_CONFIG_KEY)
    f_ub_mhz = ub_assignment.get(UB_CENTER_FREQ_CONFIG_KEY)
    t = t_value(protocol, if_frequency_mhz, f_ub_mhz)

    if protocol == UNICABLE_PROTOCOL_EN50494:
        # data1 = [UB:7-5 | position:4 | polarization:3 | band:2 | t:1-0]
        # (MSB-first as listed in the SPEC-623 §6 table; four-implementation
        # source-level consensus).  PIN variant: command 0x5C, PIN appended.
        position_bit = (
            POSITION_BIT_A if ub_assignment[POSITION_CONFIG_KEY] == "A" else POSITION_BIT_B
        )
        polarization_bit = (
            POLARIZATION_BIT_HORIZONTAL
            if tuning_request[POLARIZATION_CONFIG_KEY] == "horizontal"
            else POLARIZATION_BIT_VERTICAL
        )
        band_bit = (
            BAND_BIT_HIGH
            if tuning_request[FREQUENCY_KHZ_CONFIG_KEY] >= UNIVERSAL_BAND_BOUNDARY_KHZ
            else BAND_BIT_LOW
        )
        data1 = (
            (slot << 5)
            | (position_bit << 4)
            | (polarization_bit << 3)
            | (band_bit << 2)
            | ((t >> 8) & 0x03)
        )
        frame: list[int] = [EN50494_FRAMING_BYTE, EN50494_ADDRESS_BYTE]
        if pin is None:
            frame.append(EN50494_COMMAND_BYTE)
        else:
            frame.append(EN50494_PIN_COMMAND_BYTE)
        frame.extend((data1, t & 0xFF))
        if pin is not None:
            frame.append(pin)
        return TuningMessage(protocol=protocol, frame_bytes=tuple(frame), t=t)

    # EN 50607: data1 = [UB:7-3 | t:2-0], data2 = t[7:0],
    # data3 = [position:7-2 | reserved-zero:1-0]; PIN variant 0x71, 5 bytes.
    data1 = ((slot & 0x1F) << 3) | ((t >> 8) & 0x07)
    data3 = (ub_assignment[POSITION_CONFIG_KEY] & 0x3F) << 2
    frame = [EN50607_COMMAND_BYTE, data1, t & 0xFF, data3]
    if pin is not None:
        frame[0] = EN50607_PIN_COMMAND_BYTE
        frame.append(pin)
    return TuningMessage(protocol=protocol, frame_bytes=tuple(frame), t=t)


# -- UB conflict detection (SPEC-623 §6, AC-623-03) -----------------------------


def ub_conflicts(
    ub_assignments: Iterable[dict],
    tuner_configs: Iterable[dict],
) -> tuple[tuple[str, str, int], ...]:
    """Three-branch UB conflict judgement over one SCR context.

    Branch semantics (REPORT-frozen):

    - **conflict pairs** — every unordered pair of distinct tuners whose
      *effective* ``ub_slot`` claims collide, returned as
      ``(tuner_a, tuner_b, ub_slot)`` triples ordered by (slot ascending,
      claimant lexicographic);
    - **no conflict** — empty tuple;
    - **cross-protocol reject** — :class:`UBProtocolMixedError` when the
      context carries more than one distinct ``protocol`` token (entries
      may optionally carry the owning SCR's protocol under the #160
      ``protocol`` key; entries without it contribute no constraint).

    Inputs (config-dict shapes): ``ub_assignments`` are one SCR's
    ``ub_assignments`` entries (``tuner_node`` / ``ub_slot`` keys);
    ``tuner_configs`` are the *effective* tuner claims
    (``node_id`` / ``ub_slot`` keys).  A tuner's effective claim overrides
    its stale table row (runtime fault rewrites: the UB_SLOT_CONFLICT
    transform lands in ``tuner_configs``), and non-int / bool / None slots
    never form claims.  Structural facts only — zero numeric simulation.
    """
    protocols: set[str] = set()
    for entry in tuple(ub_assignments) + tuple(tuner_configs):
        if isinstance(entry, dict):
            token = entry.get(PROTOCOL_CONFIG_KEY)
            if isinstance(token, str):
                protocols.add(token)
    if len(protocols) > 1:
        raise UBProtocolMixedError(
            "mixed Unicable protocols in one SCR context "
            f"{sorted(protocols)} — the EN 50494 and EN 50607 UB spaces "
            "are independent (SPEC-623 §7 prepare rejection)"
        )

    claims: dict[str, int] = {}
    for entry in ub_assignments:
        if not isinstance(entry, dict):
            continue
        node = entry.get(TUNER_NODE_CONFIG_KEY)
        slot = entry.get(UB_SLOT_CONFIG_KEY)
        if isinstance(node, str) and _is_int(slot):
            claims[node] = slot
    for config in tuner_configs:
        if not isinstance(config, dict):
            continue
        node = config.get(TUNER_CONFIG_NODE_KEY)
        slot = config.get(UB_SLOT_CONFIG_KEY)
        if isinstance(node, str) and _is_int(slot):
            claims[node] = slot  # effective claim overrides the table row

    by_slot: dict[int, list[str]] = {}
    for node in sorted(claims):
        by_slot.setdefault(claims[node], []).append(node)

    conflicts: list[tuple[str, str, int]] = []
    for slot in sorted(by_slot):
        claimants = by_slot[slot]
        for index, tuner_a in enumerate(claimants):
            for tuner_b in claimants[index + 1 :]:
                conflicts.append((tuner_a, tuner_b, slot))
    return tuple(conflicts)
