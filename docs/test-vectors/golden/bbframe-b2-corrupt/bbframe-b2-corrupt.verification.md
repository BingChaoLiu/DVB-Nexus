# bbframe-b2-corrupt — Verification Note (SPEC-506 §4 evidence)

- Vector: `bbframe-b2-corrupt` (faulted_ts, SPEC-601/§Phase2 SPEC-204, ticket #123)
- Transform: `tools/golden_bbframe_fault_transform.py --mode corrupt`
  (independent script, no `src/ts` involvement; pair baseline
  `fault_plan_ref=bbframe-nups3`)
- sha256: `205a3c2f41d2cdd80088a215d190de0321f1e3ad56b914beda42b916de2464d8`

## Frozen transform semantics (BBHEADER_SYNC_FAULT, field=SYNCD, mode=corrupt)

Frame 0's SYNCD high byte (absolute offset 7) is XOR-ed with mask
`0x02`; the stored BBHEADER CRC-8 byte is **left verbatim** (no
recompute). SYNCD 0x0000 → 0x0200 (512 bits — within the declared data
field, so the pure field damage alone would be silent; only the CRC-8
check exposes it). The corrupt mask is bit 1 rather than bit 0 so the
CRC-8 byte can never alias NM↔HEM (the stored byte is CRC-8 XOR MODE;
residue 0x02 is outside the valid MODE set).

Byte-difference to the baseline: exactly one byte at offset 7 — pinned
by the conformance suite against `manifest.fault_parameters`.

## Expected parse face (SPEC-601 §8)

`crc8_valid=false`, state `crc8_invalid`, UP boundaries withheld
(`up_count=0`) — the frame's header bytes are preserved but untrusted.
This is the `bbframe.recovery_failed` evidence face, and the red-line
inversion of the TSDuck 3.45 defect (#104: BBHEADER corruption
propagates silently into the extracted TS).

## Verification path (L1 bit-level-review)

Independent transform → self-parse cross. TSDuck has zero user-side
BBFrame capability (#104; see the baseline's verification note), so no
L2 cross exists for this layer — NOT TRUSTED framing per ruling §10-9.
The sibling vector `bbframe-b2-shift` applies the same field damage
with the CRC-8 recomputed: the pair pins the two distinguishable B2
evidence shapes (integrity break vs internally-consistent misalignment).
