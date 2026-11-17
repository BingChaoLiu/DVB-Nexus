# t2mi-minimal — independent verification evidence

SPEC-506 §5 verification record for golden vector `t2mi-minimal` (ticket #122, SPEC-600 §11.1).

- Verification path: **L1 bit-level-review** — standard-table derivation (ETSI TS 102 773 V1.4.1 §5.1 + EN 302 755 §5.1.7) by the independent constructor `tools/make_golden_t2mi_vectors.py` (no `src/ts` involvement) → self-parse cross in `tests/conformance/test_t2mi_golden_vectors.py` + human review.
- Frozen identity: sha256 `ab726f79bb692debf78225a948c26e98f878a4fdd791d81653e5c28d695a5e44`, 9845 bytes, 3 T2-MI packets.
- Geometry: NM user packets (CRC-8 poly 0xD5 + 187 body bytes, UPL 1504 bits), BBHEADER 10 bytes per EN 302 755 §5.1.7, user-packet counts `[20, 20, 12]` (third frame = smaller whole-UP tail — the #105 multi-UP-tail shape TSDuck 3.45 loses), PLP assignment `[0, 0, 1]`, packet_counter/frame_idx from 0, back-to-back tight packing (no padding between packets).

## Independent derivation cross-checks

1. **Standard table cross (#104/#107 prior art)**: header layout (6 bytes; payload length in bits; CRC-32/MPEG-2 poly 0x04C11DB7 trailer), packet type table (0x00 = BBFRAME; no padding packet_type exists in the standard — 0xFF is the stuffing byte identity), and BBHEADER layout were cross-checked against two independent implementations of the same tables: TSDuck `tsT2MI.h`/`tsT2MIPacket.h` and the dvb-t2mi crate (vendored TS 102 773 V1.4.1, #107). The research baseline `gen_t2mi.py` (branch `research/tsduck-t2mi-plugin`) uses the same construction recipe; this vector re-derives it deterministically with its own CRC implementations.
2. **L2 TSDuck 3.45-4798 live cross — NOT TRUSTED (ruling §10-9)**: with `--emit-outer`, the constructor writes outer-framed NM/HEM sibling streams (PID 0x0015, data piping per Annex E.2.1). Recorded 2026-11-17, TSDuck 3.45-4798:
   - `tsp -I file outer_hem.ts -P t2mi --extract --pid 0x15 --output-file extracted_hem.ts -O drop` → 7520 bytes, **byte-identical** (`cmp` clean) to the expected reconstructed inner TS prefix (40 packets); the 12-UP tail frame (T2-MI packet 2) was **silently dropped** — the exact #105 TSDuck 3.45 tail-loss defect, independently reproduced on this vector's construction.
   - `tsp -I file outer_nm.ts …` → 7520 bytes, content **mangled** (differs from byte 2) — the known 3.45 Normal-Mode defect (master commit 147deab3, unreleased, fixes NM/ISSY/NPD).
   - Per SPEC-600 §11.2 and orchestrator ruling §10-9, **all TSDuck 对拍 results here are annotated NOT TRUSTED**: the validator version has known defects (silent tail drop, NM failure, silent error paths). The cross validates the framing/CRC layer on what it does produce; acceptance for the NM face is the L1 derivation above, not "对拍绿".
3. **Self-parse round-trip (L3, regression only)**: `tests/conformance/test_t2mi_golden_vectors.py` asserts the self parser reads the vector with all expectations satisfied and that `build()` from the parsed BBFRAMEs re-encodes byte-identically (same config, double run). Per SPEC-506 §5 this is regression coverage and never stands as independent acceptance evidence.

## Regeneration

```bash
python tools/make_golden_t2mi_vectors.py --output-dir docs/test-vectors/golden
# sha256 must equal the manifest sha256 (re-registration required on drift, SPEC-506 §6)
```
