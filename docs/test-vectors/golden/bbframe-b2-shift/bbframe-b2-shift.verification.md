# bbframe-b2-shift — Verification Note (SPEC-506 §4 evidence)

- Vector: `bbframe-b2-shift` (faulted_ts, SPEC-601/§Phase2 SPEC-204, ticket #123)
- Transform: `tools/golden_bbframe_fault_transform.py --mode shift`
  (independent script, no `src/ts` involvement; pair baseline
  `fault_plan_ref=bbframe-nups3`)
- sha256: `49fc82db109fba728b086f931bcde83e537721aeb6e8b8ce9702f78bdc5d27c9`

## Frozen transform semantics (BBHEADER_SYNC_FAULT, field=SYNCD, mode=shift)

Frame 0's SYNCD value advances by one step in its natural unit — one
**bit** (0x0000 → 0x0001; the shift writes the low byte at absolute
offset 8) — and the BBHEADER CRC-8 is **recomputed with the MODE
residue preserved** (byte 9 = CRC-8(header9) XOR 0x00 NM). The faulted
header is internally consistent: a realistic mis-declaring encapsulator
whose output passes every integrity check while slicing UPs wrong.

Byte-difference to the baseline: exactly two bytes — offsets 7→8 (the
SYNCD value byte) and 9 (the recomputed CRC-8) — pinned by the
conformance suite against `manifest.fault_parameters`.

## Expected parse face (SPEC-601 §8)

`crc8_valid=true`, state `syncd_misaligned` (SYNCD not a whole byte
multiple → UP 边界错位), `up_count=0`. Teaching anchor (SPEC-404 §Phase2,
rendered verbatim by the #132 BBFrame view): **SYNCD 是数据字段内首个
UP 的位距离，不是同步字节** — the shifted vector shows exactly why: one
bit of SYNCD displaces the first-UP boundary without tripping any
checksum.

## Verification path (L1 bit-level-review)

Independent transform → self-parse cross. TSDuck has zero user-side
BBFrame capability (#104; see the baseline's verification note), so no
L2 cross exists for this layer — NOT TRUSTED framing per ruling §10-9.
The sibling vector `bbframe-b2-corrupt` applies the same SYNCD damage
without the CRC-8 recompute: the pair pins the two distinguishable B2
evidence shapes (internally-consistent misalignment vs integrity break).
