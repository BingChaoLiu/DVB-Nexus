"""SPEC-506 §7 #7-#10 — independent faulted-vector transform script.

Produces the faulted half of the four first-batch golden pairs by
transforming the registered **baseline** bytes directly at the byte level
(SPEC-204 §6 frozen semantics + §7 slot-preserving substitution invariant):

- ``pat-missing``       §6.1: from the frozen activation index to stream
                        end, every PID-0 (PAT) packet slot is replaced by a
                        canonical Null packet (PID 0x1FFF, AFC 01, CC 0,
                        0xFF body — SPEC-107 §5.1 shape).  Window runs to
                        stream end, so no PID-0 packet follows and the §6.1
                        CC 重盖 clause has no instance to apply to.
- ``pmt-invalid-crc``   §6.2: mode ``persistent`` (default), corruption
                        ``invert`` (default) — the 4 CRC bytes of every
                        PMT section instance from the activation index on
                        are inverted in place (section length unchanged).
- ``cc-discontinuity``  §6.3: relative-offset semantics — landing packet =
                        first payload packet of the target PID after the
                        activation index (adaptation-only packets never
                        land, SPEC-100 §5.4 reuse rule); its CC becomes
                        ``(expected_next + delta) mod 16``; the offset
                        persists (subsequent payload packets continue +1
                        from the rewritten value).
- ``pmt-pid-mismatch``  §6.4: PAT ``program_map_PID`` rewritten to
                        ``wrong_pmt_pid`` (13-bit, reserved bits preserved)
                        and the PAT CRC **recomputed** — the PAT stays
                        valid, the symptom is "points wrong", not "CRC bad".

**Independence discipline** (SPEC-506 §7 / #14): this script imports
nothing from ``src/ts`` and runs neither the Generator nor the fault
filter — it transforms frozen bytes with its own wire-level parsers and
its own CRC-32/MPEG-2 (verified against the published check value
``0x0376E6E7``).  The faulted bytes are the byte-level oracle for the
future ADR-0007 filter (integration ticket: filter output SHA == faulted
golden SHA), and TSDuck 复核 provides the independent verification
evidence.

Every transform preserves the slot frame (ADR-0007 第 4 条): the faulted
stream has exactly the baseline's packet count and every packet_index
points at the same slot in both streams.

Usage::

    python tools/golden_fault_transform.py <fault_id> \\
        --baseline <baseline .ts file> --output-dir <golden root>
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

TS_PACKET_SIZE = 188
PID_NULL = 0x1FFF

# --- frozen fault parameters (SPEC-204 §6, schema v1) ------------------------

FAULT_PARAMS: dict[str, dict] = {
    "pat-missing": {
        "fault_type": "PAT_MISSING",
        "activation": {"packet_index": 202},  # 2nd PAT repetition slot
        "parameters": {},  # schema v1: {}
    },
    "pmt-invalid-crc": {
        "fault_type": "PMT_INVALID_CRC",
        "activation": {"packet_index": 1},  # first PMT instance slot
        "parameters": {"mode": "persistent", "corruption": "invert"},
    },
    "cc-discontinuity": {
        "fault_type": "CC_DISCONTINUITY",
        "activation": {"packet_index": 30},
        "parameters": {"delta": 3, "target_pid": 256},
    },
    "pmt-pid-mismatch": {
        "fault_type": "PMT_PID_MISMATCH",
        "activation": {"packet_index": 0},
        "parameters": {"wrong_pmt_pid": 4100},
    },
}


# --- independent wire helpers (no src/ts imports) -----------------------------


def _split_packets(data: bytes) -> list[bytes]:
    if len(data) % TS_PACKET_SIZE:
        raise ValueError(f"baseline is not 188-aligned: {len(data)} bytes")
    return [data[i : i + TS_PACKET_SIZE] for i in range(0, len(data), 188)]


def _pid(packet: bytes) -> int:
    return ((packet[1] & 0x1F) << 8) | packet[2]


def _pusi(packet: bytes) -> bool:
    return bool(packet[1] & 0x40)


def _afc(packet: bytes) -> int:
    return (packet[3] >> 4) & 0x03


def _cc(packet: bytes) -> int:
    return packet[3] & 0x0F


def _has_payload(packet: bytes) -> bool:
    return _afc(packet) & 0b01


def _payload_offset(packet: bytes) -> int:
    """Byte offset of the payload region (SPEC-100 §5.2): after the header,
    and after the adaptation field when AFC carries one (AFC=10/11)."""
    if _afc(packet) & 0b10:
        return 5 + packet[4]  # AF length byte + AF body
    return 4


def _section_span(packet: bytes) -> tuple[int, int]:
    """(start, length) of the first PSI section inside a PUSI packet,
    honouring the pointer_field and any adaptation field."""
    if not _pusi(packet):
        raise ValueError("section scan on non-PUSI packet")
    payload = _payload_offset(packet)
    pointer = packet[payload]
    start = payload + 1 + pointer
    length = ((packet[start + 1] & 0x0F) << 8) | packet[start + 2]
    return start, 3 + length


def _section_bytes(packet: bytes) -> bytes:
    """First PSI section carried by a PUSI packet."""
    start, length = _section_span(packet)
    return packet[start : start + length]


def _crc32_mpeg2(data: bytes) -> int:
    """CRC-32/MPEG-2 over the full PSI section minus the CRC field
    (H.222.0 Annex A).  Check value: ``123456789`` → ``0x0376E6E7``
    (CRC32-MPEG2.md)."""
    crc = 0xFFFFFFFF
    for byte in data:
        crc ^= byte << 24
        for _ in range(8):
            if crc & 0x80000000:
                crc = ((crc << 1) ^ 0x04C11DB7) & 0xFFFFFFFF
            else:
                crc = (crc << 1) & 0xFFFFFFFF
    return crc


def _crc_ok(section: bytes) -> bool:
    return _crc32_mpeg2(section[:-4]) == int.from_bytes(section[-4:], "big")


def _null_packet() -> bytes:
    """Canonical Null packet (SPEC-107 §5.1): PID 0x1FFF, AFC 01, CC 0,
    0xFF body — the same shape the SPEC-107 mux emits."""
    return bytes([0x47, 0x1F, 0xFF, 0x10]) + b"\xff" * 184


# --- transforms (each returns the full faulted packet list) -------------------


def transform_pat_missing(baseline: list[bytes]) -> list[bytes]:
    """SPEC-204 §6.1: window = activation → stream end; every PID-0 slot
    becomes a Null packet (等位替换)."""
    activation = FAULT_PARAMS["pat-missing"]["activation"]["packet_index"]
    out = []
    for index, packet in enumerate(baseline):
        if index >= activation and _pid(packet) == 0x0000:
            out.append(_null_packet())
        else:
            out.append(packet)
    return out


def transform_pmt_invalid_crc(baseline: list[bytes]) -> list[bytes]:
    """SPEC-204 §6.2 persistent + invert: invert the 4 CRC bytes of every
    PMT instance from the activation index on."""
    activation = FAULT_PARAMS["pmt-invalid-crc"]["activation"]["packet_index"]
    out = []
    for index, packet in enumerate(baseline):
        if index >= activation and _pid(packet) == 4096 and _pusi(packet):
            start, length = _section_span(packet)
            crc_offset = start + length - 4
            mutated = bytearray(packet)
            for offset in range(crc_offset, crc_offset + 4):
                mutated[offset] ^= 0xFF
            out.append(bytes(mutated))
        else:
            out.append(packet)
    return out


def transform_cc_discontinuity(baseline: list[bytes]) -> list[bytes]:
    """SPEC-204 §6.3: relative offset, persistent, landing on the first
    payload packet of the target PID after the activation index."""
    params = FAULT_PARAMS["cc-discontinuity"]["parameters"]
    activation = FAULT_PARAMS["cc-discontinuity"]["activation"]["packet_index"]
    delta = params["delta"] & 0x0F
    target = params["target_pid"]
    out = [bytes(packet) for packet in baseline]

    landing = None
    for index in range(activation + 1, len(baseline)):
        packet = baseline[index]
        if _pid(packet) == target and _has_payload(packet):
            landing = index
            break
    if landing is None:
        raise ValueError("no payload packet of the target PID after activation")

    last_cc = _cc(baseline[landing])
    for index in range(landing, len(baseline)):
        packet = baseline[index]
        if _pid(packet) != target:
            continue
        mutated = bytearray(packet)
        if _has_payload(packet):
            # expected_next is the baseline's own contiguous value; the
            # faulted value carries the permanent relative offset.
            mutated[3] = (mutated[3] & 0xF0) | ((_cc(packet) + delta) & 0x0F)
            last_cc = mutated[3] & 0x0F
        else:
            # Adaptation-only packets keep the reuse rule (SPEC-100 §5.4)
            # against the faulted stream's own last CC.
            mutated[3] = (mutated[3] & 0xF0) | last_cc
        out[index] = bytes(mutated)
    return out


def transform_pmt_pid_mismatch(baseline: list[bytes]) -> list[bytes]:
    """SPEC-204 §6.4: rewrite PAT program_map_PID (reserved bits kept) and
    recompute the PAT CRC — PAT stays valid."""
    params = FAULT_PARAMS["pmt-pid-mismatch"]["parameters"]
    wrong_pid = params["wrong_pmt_pid"]
    activation = FAULT_PARAMS["pmt-pid-mismatch"]["activation"]["packet_index"]
    if not (0x0001 <= wrong_pid <= 0x1FFE) or wrong_pid in (0x0000, 0x1FFF):
        raise ValueError("wrong_pmt_pid outside the §6.4 parameter range")
    out = []
    for index, packet in enumerate(baseline):
        if index >= activation and _pid(packet) == 0x0000 and _pusi(packet):
            start, length = _section_span(packet)
            section = bytearray(_section_bytes(packet))
            # PAT program loop: 8-byte fixed part, then 4-byte entries.
            entry = section[8:12]
            program_number = int.from_bytes(entry[0:2], "big")
            if program_number != 0:  # rewrite real program entries only
                section[10] = (entry[2] & 0xE0) | (wrong_pid >> 8)
                section[11] = wrong_pid & 0xFF
                recomputed = _crc32_mpeg2(bytes(section[:-4]))
                section[-4:] = recomputed.to_bytes(4, "big")
            mutated = bytearray(packet)
            mutated[start : start + length] = section
            out.append(bytes(mutated))
        else:
            out.append(packet)
    return out


TRANSFORMS = {
    "pat-missing": transform_pat_missing,
    "pmt-invalid-crc": transform_pmt_invalid_crc,
    "cc-discontinuity": transform_cc_discontinuity,
    "pmt-pid-mismatch": transform_pmt_pid_mismatch,
}

#: The fault symptom each faulted vector declares (SPEC-301 §4 event types,
#: SPEC-204 §6 观测 column).
FAULT_EXPECTATIONS: dict[str, dict] = {
    "pat-missing": {
        "expectations": [
            {
                "event_type": "ts.packet_batch_observed",
                "locator": {"pid": PID_NULL, "packet_index": 202},
                "detail": {
                    "substitutes_pid": 0,
                    "note": "PAT_MISSING: Null packet replaces the PAT slot "
                            "(SPEC-204 §6.1, 等位替换)",
                },
            },
            {
                "event_type": "ts.packet_batch_observed",
                "locator": {"pid": PID_NULL, "packet_index": 404},
                "detail": {
                    "substitutes_pid": 0,
                    "note": "PAT_MISSING: Null packet replaces the PAT slot",
                },
            },
        ]
    },
    "pmt-invalid-crc": {
        "expectations": [
            {
                "event_type": "ts.psi_section_observed",
                "locator": {"pid": 4096},
                "detail": {
                    "crc_valid": False,
                    "corruption": "invert",
                    "mode": "persistent",
                    "packet_index": [1, 206, 412],
                    "note": "PMT_INVALID_CRC: every PMT instance fails CRC "
                            "(SPEC-204 §6.2)",
                },
            }
        ]
    },
    "cc-discontinuity": {
        "expectations": [
            {
                "event_type": "ts.continuity_error",
                "locator": {"pid": 256, "packet_index": 50},
                "detail": {
                    "expected_cc": 1,
                    "actual_cc": 4,
                    "delta": 3,
                    "persists": True,
                    "note": "CC_DISCONTINUITY: relative offset 3 lands on the "
                            "first payload packet after activation and "
                            "persists (SPEC-204 §6.3)",
                },
            }
        ]
    },
    "pmt-pid-mismatch": {
        "expectations": [
            {
                "event_type": "ts.psi_section_observed",
                "locator": {"pid": 0},
                "detail": {
                    "table_id": 0,
                    "crc_valid": True,
                    "programs": [{"program_number": 1, "pmt_pid": 4100}],
                    "note": "PMT_PID_MISMATCH: valid PAT repointed to the "
                            "wrong PMT PID (SPEC-204 §6.4)",
                },
            },
            {
                "event_type": "ts.psi_section_observed",
                "locator": {"pid": 4096},
                "detail": {
                    "orphan_pmt": True,
                    "note": "PMT remains on the real PID — orphaned by the "
                            "repointed PAT",
                },
            },
        ]
    },
}


def build_manifest(vector_id: str, sha256: str, baseline_id: str) -> dict:
    frozen = FAULT_PARAMS[vector_id]
    return {
        "vector_id": vector_id,
        "kind": "faulted_ts",
        "related_specs": ["SPEC-204", "SPEC-108"],
        "generator_version": (
            "tools/golden_fault_transform.py v1 (independent byte-level "
            "transform; no src/ts involvement)"
        ),
        "config_hash": None,
        "sha256": f"sha256:{sha256}",
        "packet_count": None,
        "fault_plan_ref": baseline_id,
        "fault_parameters": {
            "schema_version": 1,
            "fault_type": frozen["fault_type"],
            "activation": frozen["activation"],
            "parameters": frozen["parameters"],
        },
        "verification": {
            "path": "tsduck-cross",
            "direction": "independent-transform→tsduck-analyze",
            "evidence_ref": (
                f"docs/test-vectors/golden/{vector_id}/{vector_id}.verification.md"
            ),
        },
    }


def write_trio(output_dir: Path, fault_id: str, baseline_ts: Path) -> Path:
    baseline = _split_packets(baseline_ts.read_bytes())
    faulted = TRANSFORMS[fault_id](baseline)
    if len(faulted) != len(baseline):
        raise AssertionError("slot-preserving invariant broken: packet count changed")
    ts_bytes = b"".join(faulted)
    sha256 = hashlib.sha256(ts_bytes).hexdigest()
    vector_id = fault_id
    base = output_dir / vector_id
    base.mkdir(parents=True, exist_ok=True)
    (base / f"{vector_id}.ts").write_bytes(ts_bytes)
    (base / "manifest.json").write_text(
        json.dumps(
            build_manifest(vector_id, sha256, f"{fault_id}-baseline"),
            indent=2,
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )
    (base / "expectations.json").write_text(
        json.dumps(FAULT_EXPECTATIONS[fault_id], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return base


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("fault_id", choices=sorted(TRANSFORMS))
    parser.add_argument(
        "--baseline", required=True, type=Path, help="baseline .ts file"
    )
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    base = write_trio(Path(args.output_dir), args.fault_id, args.baseline)
    ts_bytes = b"".join(
        TRANSFORMS[args.fault_id](_split_packets(args.baseline.read_bytes()))
    )
    print(f"{args.fault_id}: {len(ts_bytes)} bytes, "
          f"sha256={hashlib.sha256(ts_bytes).hexdigest()}")
    print(f"trio written under {base}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
