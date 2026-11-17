# inner-ts-roundtrip — independent verification evidence

SPEC-506 §5 verification record for golden vector `inner-ts-roundtrip` (ticket #125, SPEC-603 §11 正向).

- Vector role: the **expected side** of the three-level demux chain round-trip — the reconstructed Inner TS baseline (SPEC-603 §11: "外层 TS → Inner TS 与原始生成流逐字节一致；#105 expected_inner.ts 基准入册").
- Frozen identity: sha256 `08fcc6347a4e358c59c856371240610e46933ad5ca239ce80314a348075cb5d6`, 1128 bytes, 6 TS packets.
- Geometry (research generator, `N_UPS=3 N_T2MI=2`): two T2-MI BBFRAME packets, each carrying one **HEM** BBFrame (MATYPE 0xC000, UPL 1496 bits, DFL 4488 bits, SYNC 0x47, SYNCD 0, per-frame 3 sync-stripped 187-byte UPs = PAT / PMT / null), transport prefix `frame_idx / PLP_id=0 / flags`, T2-MI counters 24-bit big-endian (research-generator convention; the #122 parser reads the low 8 bits — both read 0 here, reserved bytes preserved verbatim). Expected output = `[PAT, PMT, null] × 2`.

## Provenance (来源 / 身份 / 消费方)

- 来源: branch `research/ffmpeg-t2mi-demuxer` @ `2935ab68683247dbdf58ee007e1d919e89a60684`, `docs/research/phase2/ffmpeg-t2mi-data/expected_inner.ts`, extracted verbatim with `git show` (只读取材, brief §7bis). The generator `gen_t2mi_sample.py` (blob sha256 `b779da048dfaf5db8108387283ebf17492bc0a22494ba45c72219aeb673e62b7`) is a stdlib-only independent constructor — no `src/ts` involvement (L1 independence).
- 身份: vector sha256 above; chain input captured alongside as checked-in assets with the same provenance: `tests/data/t2mi/inner_ts_roundtrip_input.bin` (sha256 `b215c997fc515463b44476208889fc2a80b1f42f276eac788c71416de6921985`, the 2-packet back-to-back T2-MI stream) and `tests/data/t2mi/inner_ts_roundtrip_outer.ts` (sha256 `8c1a282961742a3b7435b9b4addd775b5d54dbdbf95043fd9bfa155fc8c0876d`, the PID-0x64 TS-framed variant for the live TSDuck cross).
- 消费方: `tests/conformance/test_inner_ts_golden_vector.py` (chain round-trip + L2 record), `tests/integration/ts/test_t2mi_inner_ts_chain.py` (demux chain → artifact kind=inner_ts → analyze/inspect consumption), `tests/unit/ts/test_t2mi_inner_ts.py` (procedural interface faces only — no golden bytes).

## Independent derivation cross-checks

1. **External baseline (L1, independent source)**: the expected bytes come from the external research generator, not from the implementation under test. The chain round-trip asserts `reconstruct(parse(input)) == vector bytes` — the reconstruction target is externally authoritative; the only self-consistency involved is that the input and expected sides of the research pair were produced by the same external script (their mutual byte agreement is the #105 report's recorded `cmp` evidence, reproduced here on every conformance run).
2. **L2 TSDuck live cross — NOT TRUSTED (ruling §10-9 / SPEC-603 §8 row 4)**: recorded 2026-11-17, TSDuck 3.45-4798. Two honest faces coexist and both stay inside the NOT TRUSTED envelope:
   - the research report (`docs/research/phase2/ffmpeg-t2mi-demuxer.md` §5.3, evidence row 12) recorded, on its own multi-UP run shapes (raw T2-MI pair / single-frame outer variants), the #105 tail-loss face: 4 of 6 packets out, byte-identical prefix, **UP2/UP3 of the last frame silently lost**;
   - the checked-in conformance live cross (`tests/conformance/test_inner_ts_golden_vector.py`, `tsduck`-marked) runs `tsp -I file <this vector's outer TS> -P t2mi --extract --pid 100` on the **PID-0x64 TS-framed variant** (`inner_ts_roundtrip_outer.ts`, 0xFF-padded final outer chunk) and observed **byte-identical** extraction (all 6 packets, sha256 equal to this vector) on the same 3.45-4798 build — the TS framing flushes the demux on this shape. The discrepancy between the two faces is itself recorded evidence: behavior is version- and framing-dependent, exactly why a passing single extraction is NOT acceptance.
   - The NM/ISSY/NPD demux rewrite (master commit 147deab3, 2026-11-09) is **unreleased**, so `ts.t2mi.inner_ts.TSDUCK_TRUSTED_VERSIONS` is honestly empty and every L2 record carries `trust_annotation="NOT TRUSTED"` until an official release passes the §5.3 retest matrix. The live cross asserts shape, never "对拍绿": byte identity **or** the 188-aligned-prefix face, annotated by the trust registry either way.
3. **Self round-trip (L3, regression only)**: the conformance/integration chain runs the implementation's parse → filter → reconstruct and requires byte identity with this vector. Per SPEC-506 §5 this is regression coverage and never stands as independent acceptance evidence.

## Regeneration

The vector bytes are a research-branch capture — no re-generation script runs against `src/`. Provenance re-derivation:

```bash
git show research/ffmpeg-t2mi-demuxer:docs/research/phase2/ffmpeg-t2mi-data/expected_inner.ts \
  | sha256sum   # must equal 08fcc6347a4e358c59c856371240610e46933ad5ca239ce80314a348075cb5d6
```

Byte drift (upstream research rebase) = re-registration event (SPEC-506 §6).
