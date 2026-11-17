"""SPEC-601 §5/§6/§7/§8 — BBFrame parser/encapsulator (ticket #123).

``parse(frames)`` / ``build(up_stream, config)``: the BBHEADER-level
bidirectional face (EN 302 755 §5.1.7) between the T2-MI layer
(SPEC-600, #122) and Inner TS reconstruction (SPEC-603, #125).

BBHEADER wire layout (10 bytes)::

    [0..1]  MATYPE  — 16-bit big-endian: TS_GS (bits 15..14), ISI
                      (bits 13..11), NPD (bit 10), ISSYI (bit 9), reserved 0
    [2..3]  UPL     — user packet length **in bits** (NM TS: 188*8 = 1504;
                      0 = High Efficiency Mode)
    [4..5]  DFL     — data field length **in bits** (real UP payload;
                      excludes the tail stuffing of a padded frame)
    [6]     SYNC    — the sync byte copied from the user packets (0x47 TS NM)
    [7..8]  SYNCD   — **bit distance** from the start of the data field to
                      the first user packet — NOT a sync byte (SPEC-601 §3
                      teaching anchor, rendered verbatim by #132's view);
                      ``0xFFFF`` = no UP starts in this frame (continuation)
    [9]     CRC-8   — CRC-8 (poly 0xD5, init 0x00, MSB-first) over bytes
                      [0..8] **XOR MODE** (0x00 Normal Mode, 0x01 High
                      Efficiency Mode; any other residue = corrupted
                      BBHEADER).  Cross-checked against TSDuck master
                      ``tsT2MIDemux::demuxTS`` (``data[9] ^ BBHeaderCRC8``)
                      and the two independent research constructors
                      (#104 / ffmpeg-t2mi-demuxer) — three implementations
                      of the same EN 302 755 table.

Spec-note: SPEC-601 §2.1 lists "UPL(1)" — a typo; the 10-byte total and
EN 302 755 §5.1.7 both pin UPL at 16 bits (2 bytes), and the registered
``t2mi-minimal`` vector (#122) already encodes UPL at bytes [2..3].  The
wire layout here follows the standard (the authoritative face).

Beyond-TSDuck duty (SPEC-601 §12): TSDuck 3.45-4798 neither verifies the
BBHEADER CRC-8 nor survives a multi-UP (N_UPS > 1) tail frame (#104
measured silent propagation, #105 measured tail loss).  Both faces are
red lines here:

- CRC-8 is **mandatory** on the parse path: a failed check marks the
  frame ``crc8_valid=False`` / state ``crc8_invalid``, withholds the UP
  boundaries (the header is untrusted — its bytes are preserved verbatim
  in ``data_field``/header faces), and feeds the
  ``bbframe.recovery_failed`` count via :mod:`ts.t2mi.bbframe_summary`.
  Never a silent propagation.
- Multi-UP tails are **deterministic**: ``build`` batches ``n_ups`` UPs
  per frame; a tail frame with ``k < n_ups`` UPs carries the real UPs
  first, then ``0xFF`` baseband stuffing up to the full
  ``n_ups * upl`` data-field capacity, with ``DFL`` declaring the real
  payload bits only.  The registered ``bbframe-nups3`` vector pins the
  rule byte-exactly (SPEC-601 §7 尾包 golden 钉扎).

Error face (SPEC-601 §8): parse-side anomalies are explicit **states on
the frame object** (mirror of the #122 parser discipline: 显式标记继续
解析, never an exception mid-sequence); build-side input-shape violations
are prepare-time **exceptions** (非 188 倍数 UP 流 prepare 前拒绝).
Error codes are module-owned per the TS Core contract §7 归属约定 and
raise as :class:`ts.t2mi.errors.T2miError` (the reusable #122 family;
``errors.py`` unchanged).

Unit conventions (frozen, documented for #125/#128/#129): the
:class:`BBFrame` DTO face reports the **wire field values** (``upl`` /
``dfl`` / ``syncd`` in bits as received); :class:`BBFrameBuildConfig`
takes ``upl`` in **bytes** (188, matching the #122
``T2miBuildConfig.upl_bytes`` family convention).  The bytes themselves
never enter the wire DTO projection (:meth:`BBFrame.wire_detail` —
artifact addressing holds the bytes, SPEC-600 §5 discipline).

MVP progressive-registration boundary (SPEC-601 §2.2): HEM parse
support (UPL=0, 187-byte UPs) and the MATYPE ISSYI/NPD bit semantics are
in; NM **build** with ISSY present / NPD enabled is refused until a
golden pins the field construction (SPEC-601 §2.1 渐进钉扎); GFPS/GCS/
GSE/VCM/ACM surfaces as the explicit ``matype_unsupported`` state, never
a guess.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ts._bytesutil import _coerce_bytes
from ts.t2mi.errors import T2miError

__all__ = [
    "BBFRAME_BUILD_EMPTY",
    "BBFRAME_BUILD_NOT_UP_ALIGNED",
    "BBFRAME_CONFIG_ISSY_UNSUPPORTED",
    "BBFRAME_CONFIG_MATYPE_CONFLICT",
    "BBFRAME_CONFIG_MATYPE_UNSUPPORTED",
    "BBFRAME_CONFIG_NPD_UNSUPPORTED",
    "BBFRAME_CONFIG_N_UPS_INVALID",
    "BBFRAME_CONFIG_UPL_INVALID",
    "BBFRAME_CRC8_POLY",
    "BBFRAME_HEM_UP_BYTES",
    "BBFRAME_MATYPE_TS_NM",
    "BBFRAME_MODE_HEM",
    "BBFRAME_MODE_NM",
    "BBFRAME_MODE_UNKNOWN",
    "BBFRAME_STATE_CRC8_INVALID",
    "BBFRAME_STATE_DFL_MISMATCH",
    "BBFRAME_STATE_MALFORMED_SHORT",
    "BBFRAME_STATE_MATYPE_UNSUPPORTED",
    "BBFRAME_STATE_OK",
    "BBFRAME_STATE_SYNCD_MISALIGNED",
    "BBFRAME_STATE_SYNCD_OUT_OF_RANGE",
    "BBFRAME_STATE_UPL_INVALID",
    "BBFRAME_SYNC_TS_NM",
    "BBFRAME_SYNCD_CONTINUATION",
    "BBHEADER_FIELD_RANGES",
    "BBHEADER_SIZE",
    "BBFrame",
    "BBFrameBuildConfig",
    "crc8_dvb",
    "parse",
]

# --- EN 302 755 §5.1.7 wire constants ---------------------------------------------

#: BBHEADER size in bytes (MATYPE 2 + UPL 2 + DFL 2 + SYNC 1 + SYNCD 2 + CRC-8 1).
BBHEADER_SIZE = 10

#: CRC-8 polynomial for the BBHEADER check (EN 302 755 annex F).
BBFRAME_CRC8_POLY = 0xD5

#: MODE residue for Normal Mode (stored CRC-8 byte equals the plain CRC-8).
BBFRAME_MODE_NM = 0x00
#: MODE residue for High Efficiency Mode (stored byte = CRC-8 XOR 0x01).
BBFRAME_MODE_HEM = 0x01
#: MODE residue outside {NM, HEM} — the corrupted-BBHEADER face.
BBFRAME_MODE_UNKNOWN = "unknown"

#: The SYNC byte carried by TS Normal Mode BBHEADERs (the 0x47 identity
#: copied from the user packets; the transmitted UPs themselves replace
#: their sync byte with the per-UP CRC-8, EN 302 755 §5.1.8).
BBFRAME_SYNC_TS_NM = 0x47

#: SYNCD value meaning "no user packet starts in this data field" — the
#: current UP continues from the previous frame (SPEC-603 carry-over).
BBFRAME_SYNCD_CONTINUATION = 0xFFFF

#: High Efficiency Mode user packet size: 187 bytes (sync byte removed),
#: before the optional NPD byte (EN 302 755 §5.1.8).
BBFRAME_HEM_UP_BYTES = 187

#: MATYPE value for TS Normal Mode baseline (TS_GS=11, ISI=010 as in the
#: registered #122 vectors, NPD/ISSYI clear).
BBFRAME_MATYPE_TS_NM = 0xD000

#: BBHEADER field byte ranges — the BBHEADER_SYNC_FAULT (SPEC-204 §Phase2)
#: addressing table, shared with :mod:`faults.filters.bbheader_sync`.
BBHEADER_FIELD_RANGES: dict[str, tuple[int, int]] = {
    "MATYPE": (0, 2),
    "UPL": (2, 4),
    "DFL": (4, 6),
    "SYNC": (6, 7),
    "SYNCD": (7, 9),
    "CRC-8": (9, 10),
}

# --- SPEC-601 §8 explicit frame states ---------------------------------------------

BBFRAME_STATE_OK = "ok"
BBFRAME_STATE_MALFORMED_SHORT = "malformed_short"
BBFRAME_STATE_CRC8_INVALID = "crc8_invalid"
BBFRAME_STATE_MATYPE_UNSUPPORTED = "matype_unsupported"
BBFRAME_STATE_UPL_INVALID = "upl_invalid"
BBFRAME_STATE_DFL_MISMATCH = "dfl_mismatch"
BBFRAME_STATE_SYNCD_OUT_OF_RANGE = "syncd_out_of_range"
BBFRAME_STATE_SYNCD_MISALIGNED = "syncd_misaligned"

#: Deterministic precedence when a frame carries several anomalies: the
#: earlier state wins (a short blob cannot even hold a header; a failed
#: CRC-8 makes every later header field untrusted).
_STATE_PRECEDENCE: tuple[str, ...] = (
    BBFRAME_STATE_MALFORMED_SHORT,
    BBFRAME_STATE_CRC8_INVALID,
    BBFRAME_STATE_MATYPE_UNSUPPORTED,
    BBFRAME_STATE_UPL_INVALID,
    BBFRAME_STATE_DFL_MISMATCH,
    BBFRAME_STATE_SYNCD_OUT_OF_RANGE,
    BBFRAME_STATE_SYNCD_MISALIGNED,
)

# --- module-owned error codes (prepare-time exceptions) -----------------------------

BBFRAME_CONFIG_MATYPE_UNSUPPORTED = "BBFRAME_CONFIG_MATYPE_UNSUPPORTED"
BBFRAME_CONFIG_MATYPE_CONFLICT = "BBFRAME_CONFIG_MATYPE_CONFLICT"
BBFRAME_CONFIG_ISSY_UNSUPPORTED = "BBFRAME_CONFIG_ISSY_UNSUPPORTED"
BBFRAME_CONFIG_NPD_UNSUPPORTED = "BBFRAME_CONFIG_NPD_UNSUPPORTED"
BBFRAME_CONFIG_UPL_INVALID = "BBFRAME_CONFIG_UPL_INVALID"
BBFRAME_CONFIG_N_UPS_INVALID = "BBFRAME_CONFIG_N_UPS_INVALID"
BBFRAME_BUILD_EMPTY = "BBFRAME_BUILD_EMPTY"
BBFRAME_BUILD_NOT_UP_ALIGNED = "BBFRAME_BUILD_NOT_UP_ALIGNED"

_MASK8 = 0xFF
_MASK16 = 0xFFFF
#: MATYPE bit positions (16-bit big-endian value).
_MATYPE_TS_GS_SHIFT = 14
_MATYPE_NPD_BIT = 0x0400
_MATYPE_ISSYI_BIT = 0x0200
#: The only registered build-side ISSY mode until a golden pins the field.
_ISSY_MODE_ABSENT = "absent"
_STUFFING_BYTE = 0xFF


def crc8_dvb(data: bytes) -> int:
    """CRC-8 over ``data`` with poly 0xD5, init 0x00, MSB-first (no final xor).

    The EN 302 755 BBHEADER check (annex F).  Implemented here rather than
    in :mod:`ts.crc` so this module stays the single owner of the BBHEADER
    wire face; independent implementations exist in the registered vector
    constructors (``tools/make_golden_t2mi_vectors.py``, research scripts)
    and TSDuck ``T2MIDemux::BBHeaderCRC8`` — all agree.
    """
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ BBFRAME_CRC8_POLY) & _MASK8
            else:
                crc = (crc << 1) & _MASK8
    return crc


@dataclass(frozen=True)
class BBFrameBuildConfig:
    """Encapsulator configuration (SPEC-601 §5 ``BBFrameBuildConfigDTO`` face).

    Attributes:
        matype_value: the full 16-bit MATYPE stamped into every BBHEADER
            (default :data:`BBFRAME_MATYPE_TS_NM`).  ``TS_GS`` must be
            ``0b11`` (TS transport) — GFPS/GCS/GSE raise
            ``BBFRAME_CONFIG_MATYPE_UNSUPPORTED`` (VCM/ACM progressive,
            SPEC-601 §8).
        upl: user packet length in **bytes** (188 for TS Normal Mode,
            matching the ``T2miBuildConfig.upl_bytes`` family convention;
            the BBHEADER carries ``upl * 8`` bits).
        n_ups: multi-UP batch size — UPs per frame (SPEC-601 §7; the tail
            frame is padded deterministically up to this capacity).
        issy_mode: only ``"absent"`` is registered until an ISSY golden
            pins the field construction (SPEC-601 §2.1 渐进钉扎); the
            MATYPE ISSYI bit must agree.
        npd_enabled: must stay ``False`` — the builder performs no null
            packet deletion, so stamping the NPD bit would claim semantics
            it does not implement (``BBFRAME_CONFIG_NPD_UNSUPPORTED``).
            The parse side accepts NPD-marked frames (slicing includes the
            DNP byte inside ``upl`` per EN 302 755 §5.1.8).

    All violations raise :class:`ts.t2mi.errors.T2miError` at construction
    time (prepare 前拒绝纪律).
    """

    matype_value: int = BBFRAME_MATYPE_TS_NM
    upl: int = 188
    n_ups: int = 1
    issy_mode: str = _ISSY_MODE_ABSENT
    npd_enabled: bool = False

    def __post_init__(self) -> None:
        if (
            isinstance(self.matype_value, bool)
            or not isinstance(self.matype_value, int)
            or not 0 <= self.matype_value <= _MASK16
        ):
            raise T2miError(
                f"{BBFRAME_CONFIG_MATYPE_UNSUPPORTED}: matype_value must be a "
                f"16-bit int, got {self.matype_value!r}"
            )
        ts_gs = (self.matype_value >> _MATYPE_TS_GS_SHIFT) & 0x03
        if ts_gs != 0x03:
            raise T2miError(
                f"{BBFRAME_CONFIG_MATYPE_UNSUPPORTED}: matype_value "
                f"{self.matype_value:#06x} declares TS_GS={ts_gs:#04b} — only "
                "TS transport (0b11) is registered for build; GFPS/GCS/GSE/"
                "VCM/ACM are explicit progressive states (SPEC-601 §8)"
            )
        if (
            isinstance(self.upl, bool)
            or not isinstance(self.upl, int)
            or self.upl < 1
        ):
            raise T2miError(
                f"{BBFRAME_CONFIG_UPL_INVALID}: upl must be a positive int "
                f"(user packet length in bytes), got {self.upl!r}"
            )
        if (
            isinstance(self.n_ups, bool)
            or not isinstance(self.n_ups, int)
            or self.n_ups < 1
        ):
            raise T2miError(
                f"{BBFRAME_CONFIG_N_UPS_INVALID}: n_ups must be a positive "
                f"int (UPs per frame), got {self.n_ups!r}"
            )
        if self.issy_mode != _ISSY_MODE_ABSENT:
            raise T2miError(
                f"{BBFRAME_CONFIG_ISSY_UNSUPPORTED}: issy_mode "
                f"{self.issy_mode!r} is not registered — NM ISSY field "
                "construction waits for its golden (SPEC-601 §2.1 渐进钉扎)"
            )
        if bool(self.matype_value & _MATYPE_ISSYI_BIT):
            raise T2miError(
                f"{BBFRAME_CONFIG_MATYPE_CONFLICT}: matype_value "
                f"{self.matype_value:#06x} sets the ISSYI bit while "
                f"issy_mode={self.issy_mode!r} — the MATYPE bits and the "
                "config flags must agree (SPEC-601 §5 MATYPE semantics)"
            )
        if self.npd_enabled:
            raise T2miError(
                f"{BBFRAME_CONFIG_NPD_UNSUPPORTED}: npd_enabled=True is not "
                "registered for build — the encapsulator performs no null "
                "packet deletion, so the NPD bit would be a false claim "
                "(SPEC-601 §2.2); the parse side accepts NPD-marked frames"
            )
        if bool(self.matype_value & _MATYPE_NPD_BIT):
            raise T2miError(
                f"{BBFRAME_CONFIG_MATYPE_CONFLICT}: matype_value "
                f"{self.matype_value:#06x} sets the NPD bit while "
                f"npd_enabled={self.npd_enabled} — the MATYPE bits and the "
                "config flags must agree"
            )


@dataclass(frozen=True)
class BBFrame:
    """One parsed BBFRAME — the SPEC-601 §5 ``BBFrameDTO``-shaped face.

    Wire keys (frozen, SPEC-601 §5): ``matype / upl / dfl / sync / syncd /
    crc8_valid / up_count / up_indices`` — :meth:`wire_detail` projects
    them plus the explicit ``state`` (SPEC-601 §8).  ``upl`` / ``dfl`` /
    ``syncd`` carry the **wire field values in bits**; ``up_indices`` are
    the byte offsets of each complete user packet's start inside the data
    field.  ``data_field`` is the implementation-side face (bytes are
    artifact-addressed, never wire-projected).

    ``state`` (SPEC-601 §8, deterministic precedence):

    - ``malformed_short`` — fewer bytes than a BBHEADER;
    - ``crc8_invalid`` — the CRC-8/MODE check failed (header untrusted:
      the UP boundaries are withheld, bytes preserved verbatim);
    - ``matype_unsupported`` — TS_GS outside the registered TS subset
      (VCM/ACM/GFPS/GCS/GSE explicit face);
    - ``upl_invalid`` — NM UPL not a whole byte multiple (no UP boundary
      is derivable);
    - ``dfl_mismatch`` — DFL declares more data than the frame holds
      (畸形帧态; the mirror case, DFL below the field length, is the
      legal tail-stuffing shape and surfaces as ``stuffing_bytes``);
    - ``syncd_out_of_range`` — SYNCD exceeds the declared data field
      (SPEC-601 §8 B2 symptom entry);
    - ``syncd_misaligned`` — SYNCD is not a whole byte multiple (UP 边界
      错位 — the B2 *shift* fault symptom, distinct from corruption);
    - ``ok`` — includes the ``SYNCD=0xFFFF`` continuation face
      (``up_count == 0``; the cross-frame carry-over belongs to
      SPEC-603, #125).
    """

    matype: int
    upl: int
    dfl: int
    sync: int
    syncd: int
    crc8_valid: bool
    up_count: int
    up_indices: tuple[int, ...]
    state: str
    mode: str
    npd_enabled: bool
    issy_present: bool
    crc8_stored: int
    data_field: bytes

    @property
    def dfl_bytes(self) -> int:
        """Declared data field length in bytes (ceil of ``dfl`` bits)."""
        return (self.dfl + 7) // 8

    @property
    def stuffing_bytes(self) -> int:
        """Tail stuffing between the declared payload and the data field.

        The deterministic build-side padding rule reserves the full
        ``n_ups * upl`` capacity; ``DFL`` counts the real payload only,
        so a padded tail frame reports its stuffing here (the
        ``bbframe.stage_summary`` stuffing-ratio face).
        """
        return max(0, len(self.data_field) - self.dfl_bytes)

    @property
    def carryover_bytes(self) -> int:
        """Bytes of a partial UP continuing into the next frame (SPEC-603).

        ``0xFFFF`` SYNCD frames carry the whole declared field as
        carry-over; otherwise the trailing bytes after the last complete
        UP.  Consumed by the SPEC-603 UP reassembly (#125).
        """
        if self.syncd == BBFRAME_SYNCD_CONTINUATION:
            return self.dfl_bytes
        if self.syncd % 8 != 0 or self.up_count == 0:
            return 0
        up_size = self._up_size()
        if up_size == 0:
            return 0
        first = self.syncd // 8
        return self.dfl_bytes - first - self.up_count * up_size

    def _up_size(self) -> int:
        """Transmitted UP size in bytes for the frame's mode (0 = unknown)."""
        if self.mode == "hem":
            return BBFRAME_HEM_UP_BYTES + (1 if self.npd_enabled else 0)
        if self.mode == "nm":
            return self.upl // 8 if self.upl % 8 == 0 and self.upl >= 8 else 0
        return 0

    def wire_detail(self) -> dict:
        """The frozen wire-key projection (SPEC-601 §5 + §8 ``state``).

        Identity/artifact faces (``data_field`` bytes, stored CRC value)
        stay out of the projection — the #129 Pydantic DTO mirrors these
        keys.
        """
        return {
            "matype": self.matype,
            "upl": self.upl,
            "dfl": self.dfl,
            "sync": self.sync,
            "syncd": self.syncd,
            "crc8_valid": self.crc8_valid,
            "up_count": self.up_count,
            "up_indices": list(self.up_indices),
            "state": self.state,
        }


def _resolve_state(states: set[str]) -> str:
    """The highest-precedence state among the collected anomalies."""
    for state in _STATE_PRECEDENCE:
        if state in states:
            return state
    return BBFRAME_STATE_OK


def parse(frames: Sequence[bytes]) -> tuple[BBFrame, ...]:
    """Parse BBFRAMEs (SPEC-601 §6): CRC-8 mandatory, explicit states.

    Args:
        frames: one BBFRAME per element — ``BBHEADER (10 bytes) + data
            field`` (the byte blobs as received from the T2-MI layer's
            ``T2miPacket.bbframe`` face or the layered runtime's frame
            hand-off).

    Returns:
        A tuple of :class:`BBFrame`, one per input frame, in order.
        Anomalies are explicit states (SPEC-601 §8) — nothing is dropped
        or repaired silently; a short blob still yields a frame object
        (``malformed_short``) so downstream faces stay index-aligned.
    """
    parsed: list[BBFrame] = []
    for index, blob in enumerate(frames):
        frame = _coerce_bytes(blob, param=f"frames[{index}]")
        parsed.append(_parse_one(frame))
    return tuple(parsed)


def _parse_one(frame: bytes) -> BBFrame:
    """Deterministic single-frame parse (states, never exceptions)."""
    if len(frame) < BBHEADER_SIZE:
        return BBFrame(
            matype=0,
            upl=0,
            dfl=0,
            sync=0,
            syncd=0,
            crc8_valid=False,
            up_count=0,
            up_indices=(),
            state=BBFRAME_STATE_MALFORMED_SHORT,
            mode=BBFRAME_MODE_UNKNOWN,
            npd_enabled=False,
            issy_present=False,
            crc8_stored=0,
            data_field=frame,
        )

    matype = int.from_bytes(frame[0:2], "big")
    upl = int.from_bytes(frame[2:4], "big")
    dfl = int.from_bytes(frame[4:6], "big")
    sync = frame[6]
    syncd = int.from_bytes(frame[7:9], "big")
    crc8_stored = frame[9]
    data_field = frame[BBHEADER_SIZE:]

    # --- CRC-8 / MODE (mandatory; the beyond-TSDuck red line) -----------
    computed = crc8_dvb(frame[0:9])
    mode_residue = crc8_stored ^ computed
    if mode_residue == BBFRAME_MODE_NM:
        mode: str = "nm"
        crc8_valid = True
    elif mode_residue == BBFRAME_MODE_HEM:
        mode = "hem"
        crc8_valid = True
    else:
        mode = BBFRAME_MODE_UNKNOWN
        crc8_valid = False

    npd_enabled = bool(matype & _MATYPE_NPD_BIT)
    issy_present = bool(matype & _MATYPE_ISSYI_BIT)
    ts_gs = (matype >> _MATYPE_TS_GS_SHIFT) & 0x03

    states: set[str] = set()
    if not crc8_valid:
        states.add(BBFRAME_STATE_CRC8_INVALID)
    if ts_gs != 0x03:
        states.add(BBFRAME_STATE_MATYPE_UNSUPPORTED)

    # --- UP boundary derivation (only from a trusted header) ------------
    up_count = 0
    up_indices: tuple[int, ...] = ()
    if crc8_valid and ts_gs == 0x03:
        up_size = (
            BBFRAME_HEM_UP_BYTES + (1 if npd_enabled else 0)
            if mode == "hem"
            else (upl // 8 if upl % 8 == 0 and upl >= 8 else 0)
        )
        if up_size == 0:
            states.add(BBFRAME_STATE_UPL_INVALID)
        else:
            dfl_bytes = (dfl + 7) // 8
            if dfl_bytes > len(data_field):
                # DFL declaring more than the frame holds: 畸形帧态.
                states.add(BBFRAME_STATE_DFL_MISMATCH)
            elif syncd == BBFRAME_SYNCD_CONTINUATION:
                pass  # continuation face: no UP starts here (state stays ok)
            elif syncd > dfl:
                # SYNCD beyond the declared data field: B2 symptom entry.
                states.add(BBFRAME_STATE_SYNCD_OUT_OF_RANGE)
            elif syncd % 8 != 0:
                # Bit-distance not on a byte boundary: UP 边界错位.
                states.add(BBFRAME_STATE_SYNCD_MISALIGNED)
            else:
                first = syncd // 8
                available = dfl_bytes - first
                if available >= 0:
                    count = available // up_size
                    up_indices = tuple(
                        first + offset * up_size for offset in range(count)
                    )
                    up_count = count

    return BBFrame(
        matype=matype,
        upl=upl,
        dfl=dfl,
        sync=sync,
        syncd=syncd,
        crc8_valid=crc8_valid,
        up_count=up_count,
        up_indices=up_indices,
        state=_resolve_state(states),
        mode=mode,
        npd_enabled=npd_enabled,
        issy_present=issy_present,
        crc8_stored=crc8_stored,
        data_field=data_field,
    )


def build(up_stream: bytes, config: BBFrameBuildConfig) -> tuple[bytes, ...]:
    """Build BBFRAMEs from a user-packet stream (SPEC-601 §6): deterministic.

    Args:
        up_stream: concatenated user packets (each ``config.upl`` bytes;
            the whole stream must be a whole multiple of ``upl`` — the
            非 188 倍数 prepare-time rejection, SPEC-601 §8).
        config: :class:`BBFrameBuildConfig` (validated at construction).

    Returns:
        A tuple of complete BBFRAME byte strings (``BBHEADER + data
        field``), each data field exactly ``config.n_ups * config.upl``
        bytes: full frames carry ``n_ups`` UPs; the tail frame carries
        the remaining UPs followed by ``0xFF`` stuffing up to capacity
        with ``DFL`` declaring the real payload bits only (SPEC-601 §7
        deterministic tail rule).  Same input + same config → same bytes
        (SPEC-601 §7 determinism duty).
    """
    stream = _coerce_bytes(up_stream, param="up_stream")
    if not stream:
        raise T2miError(
            f"{BBFRAME_BUILD_EMPTY}: up_stream is empty — the encapsulator "
            "produces at least one frame or refuses"
        )
    if len(stream) % config.upl != 0:
        raise T2miError(
            f"{BBFRAME_BUILD_NOT_UP_ALIGNED}: up_stream is {len(stream)} "
            f"byte(s), not a whole multiple of upl={config.upl} (非 188 倍数 "
            "UP 流 prepare 前拒绝, SPEC-601 §8)"
        )

    matype = config.matype_value.to_bytes(2, "big")
    upl_bits = (config.upl * 8).to_bytes(2, "big")
    capacity = config.n_ups * config.upl

    frames: list[bytes] = []
    for offset in range(0, len(stream), capacity):
        batch = stream[offset : offset + capacity]
        dfl_bits = len(batch) * 8
        data_field = batch.ljust(capacity, b"\xff")
        header_prefix = matype + upl_bits + dfl_bits.to_bytes(2, "big")
        header_prefix += bytes([BBFRAME_SYNC_TS_NM])
        header_prefix += b"\x00\x00"  # SYNCD: first UP at data-field start
        crc8 = crc8_dvb(header_prefix) ^ BBFRAME_MODE_NM
        frames.append(header_prefix + bytes([crc8]) + data_field)
    return tuple(frames)
