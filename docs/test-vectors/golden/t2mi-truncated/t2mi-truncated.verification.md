# t2mi-truncated — independent verification evidence

SPEC-506 §5 verification record for golden vector `t2mi-truncated` (ticket #122, SPEC-600 §11.1 负向集 — M6 code-review 修复轮补齐).

- Verification path: **L1 bit-level-review** — independent transform script `tools/golden_t2mi_fault_transform.py` (no `src/ts` involvement) cuts the registered baseline `t2mi-minimal` mid-final-packet (packets 0–1 complete + the first 100 bytes of packet 2); the conformance test asserts the self parser surfaces the explicit truncation state and preserves the verbatim trailing bytes.
- Frozen identity: sha256 `bda6da9e1b04359844a9cbf19cf54559b05c1f9bb274523c0a95edb2e39cbfe1`, 7666 bytes (= 3783 + 3783 + 100; baseline 9845 bytes — a pure prefix cut, no byte rewritten).
- Transform parameters (also frozen in `manifest.json.fault_parameters`): `tail_truncation` at packet index 2, `kept_tail_bytes=100` — more than the 6-byte header (the declared-length cut path is exercised) and far less than packet 2's 2279-byte total, so the parser must stop at the incomplete tail without scanning or resyncing.

## What this vector pins (SPEC-600 §8)

1. **截断显式状态**: parse result carries `truncated=True` and `trailing` = exactly the kept 100 tail bytes (verbatim prefix cut, byte-for-byte the baseline's own tail slice) — truncation is a first-class observable, never a silent stop.
2. **完整包不受损**: packets 0–1 parse with their full baseline details (expectations entries 0–1) — `len(result) == 2`; no scan/resync/skip mode exists (house ruling #11 precedent), so the incomplete tail is never partially consumed.
3. **Byte-precision evidence**: the conformance test asserts the faulted bytes are exactly `baseline[:7666]` and that `result.trailing == baseline[-100:]` — the truncation face is pinned against the registered baseline, the byte oracle.
4. **教学点 (#104)**: inter-packet garbage / demux stall pathologies surface as this explicit truncation state instead of being consumed silently — the TSDuck 3.45 silent-path lesson inverted into a visible mark.

## TSDuck cross — NOT TRUSTED by default

No "对拍绿" claim is made for this vector. Per orchestrator ruling §10-9 the trusted TSDuck registry is empty until the retest matrix passes; the #104 research measurement already recorded TSDuck 3.45's silent behavior around truncated/damaged T2-MI streams. Acceptance is the L1 independent transform above plus the conformance byte-precision assertions.

## Regeneration

```bash
python tools/golden_t2mi_fault_transform.py \
  --vector t2mi-truncated \
  --baseline docs/test-vectors/golden/t2mi-minimal/t2mi-minimal.ts \
  --output-dir docs/test-vectors/golden
# sha256 must equal the manifest sha256 (re-registration required on drift, SPEC-506 §6)
```
