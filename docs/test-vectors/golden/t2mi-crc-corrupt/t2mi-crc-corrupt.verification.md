# t2mi-crc-corrupt — independent verification evidence

SPEC-506 §5 verification record for golden vector `t2mi-crc-corrupt` (ticket #122, SPEC-600 §11.1 负向集).

- Verification path: **L1 bit-level-review** — independent transform script `tools/golden_t2mi_fault_transform.py` (no `src/ts` involvement) applies the frozen bit flip to the registered baseline `t2mi-minimal`; the conformance test asserts the self parser surfaces the explicit bad-packet state and continues.
- Frozen identity: sha256 `23b43824b5f0b3701ecedcbb0d6a0fbcc0a2ef6731bf3f97386efaa522482b85`, 9845 bytes (same size as baseline — one bit flipped, nothing added or removed).
- Transform parameters (also frozen in `manifest.json.fault_parameters`): flip LSB (`mask 0x01`) of byte offset 19 of the stream = inside packet 0's first encapsulated user packet body (header 6 + transport prefix 3 + BBHEADER 10 + 5). The CRC-32 trailer is **not** recomputed (`crc_recomputed=false`) → packet 0 must parse as `crc32_valid=False`.

## What this vector pins (SPEC-600 §8)

1. **坏包显式标记**: packet 0 parses with `crc32_valid=False`; its header fields, payload bytes (one bit differing from the baseline), and stored CRC stay verbatim — no silent repair, no silent drop.
2. **继续解析**: packets 1 and 2 still parse with `crc32_valid=True` (expectations entries 1–2) — a CRC failure never aborts or truncates the stream (对照 TSDuck 3.45 静默丢弃教训, #104).
3. **Byte-precision evidence**: the conformance test compares this vector's packet 0 payload against the baseline parse and asserts the difference is exactly the single flipped bit recorded in `fault_parameters`.

## TSDuck cross — NOT TRUSTED by default

The #104 research measurement already recorded TSDuck 3.45's silent behavior on CRC-corrupted T2-MI packets ("该包静默丢弃, 不报错") — the exact pathology this vector exists to make visible in the self parser. Per orchestrator ruling §10-9 no "对拍绿" claim is made for this vector; the NOT TRUSTED annotation logic and the executable cross protocol are recorded in `t2mi-minimal.verification.md`.

## Regeneration

```bash
python tools/golden_t2mi_fault_transform.py \
  --baseline docs/test-vectors/golden/t2mi-minimal/t2mi-minimal.ts \
  --output-dir docs/test-vectors/golden
# sha256 must equal the manifest sha256 (re-registration required on drift, SPEC-506 §6)
```
