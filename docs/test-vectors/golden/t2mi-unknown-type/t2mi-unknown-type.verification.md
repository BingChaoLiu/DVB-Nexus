# t2mi-unknown-type — independent verification evidence

SPEC-506 §5 verification record for golden vector `t2mi-unknown-type` (ticket #122, SPEC-600 §11.1 负向集 — M6 code-review 修复轮补齐).

- Verification path: **L1 bit-level-review** — independent transform script `tools/golden_t2mi_fault_transform.py` (no `src/ts` involvement) overwrites packet 0's `packet_type` header byte with the undefined value `0x55` and **recomputes** the CRC-32/MPEG-2 trailer; the conformance test asserts the self parser surfaces the explicit unknown-type state with the CRC face green and continues.
- Frozen identity: sha256 `ff146d1504734e60023f3c64135854bc35c812498143a4467591dfab39a8937f`, 9845 bytes (same size as baseline — one header byte overwritten + one trailer rewritten, nothing added or removed).
- Transform parameters (also frozen in `manifest.json.fault_parameters`): packet 0's type byte at stream offset 0 → `0x55`; `0x55` is outside the TS 102 773 §5.1 packet_type table and is **not** the `0xFF` stuffing identity, so the packet must land in the explicit `payload_kind="unknown"` state (not `bbframe`, not `padding`). The trailer is **recomputed** (`crc_recomputed=true`) so `crc32_valid=True` — the CRC face does not participate; this isolates the packet-type face (对照 `t2mi-crc-corrupt`，后者钉 CRC 面).

## What this vector pins (SPEC-600 §8 注册表渐进)

1. **未知类型显式标记**: packet 0 parses with `payload_kind="unknown"`, `packet_type=0x55`; BBFRAME-derived faces (`frame_index` / `plp_id`) are `None` — no guess, no silent reinterpretation as BBFRAME.
2. **继续解析**: packets 1 and 2 still parse with their baseline details verbatim (expectations entries 1–2) — an unknown type never aborts or truncates the stream (静默丢弃为零, #104 red line).
3. **Byte-precision evidence**: the conformance test asserts the faulted bytes differ from the baseline in exactly the 5 recorded bytes (type byte offset 0 + the 4 CRC trailer bytes 3779..3782) and that packet 0's payload bytes are verbatim-identical to the baseline's — the type override is header-only by construction.
4. **CRC 面隔离**: `crc32_valid=True` on packet 0 (recomputed trailer) proves the parser's unknown-type state is independent of the CRC failure path — the two negative faces are distinguishable evidence forms (与 bbframe-b2-corrupt/shift 的成对先例同构).

## TSDuck cross — NOT TRUSTED by default

No "对拍绿" claim is made for this vector. Per orchestrator ruling §10-9 the trusted TSDuck registry is empty until the retest matrix passes (3.45 known silent-error paths); any TSDuck cross here would be annotated NOT TRUSTED like `t2mi-minimal`'s. Acceptance is the L1 independent transform above plus the conformance byte-precision assertions.

## Regeneration

```bash
python tools/golden_t2mi_fault_transform.py \
  --vector t2mi-unknown-type \
  --baseline docs/test-vectors/golden/t2mi-minimal/t2mi-minimal.ts \
  --output-dir docs/test-vectors/golden
# sha256 must equal the manifest sha256 (re-registration required on drift, SPEC-506 §6)
```
