# bbframe-nups3 — Verification Note (SPEC-506 §4 evidence)

- Vector: `bbframe-nups3` (generated_ts, SPEC-601, ticket #123)
- Constructor: `tools/make_golden_bbframe_vectors.py` (deterministic, no `src/ts` involvement)
- sha256: `fdf4b4e3d4ef813c20affad19766218d3197356372e8544575b0c2ed108fb30b`

## Shape

Back-to-back **BBFRAME byte stream** — the layered pipeline's inter-layer
hand-off form (ADR-0010 §3: BBFRAME layer emits frames to the T2-MI
encapsulator). 3 frames, frozen geometry:

- UPL = 188 bytes (BBHEADER carries 1504 bits), N_UPS = 3;
- frame UP counts `[3, 3, 2]` — the tail frame carries 2 real UPs plus
  one UP's worth of `0xFF` baseband stuffing; DFL declares the real
  payload bits only (SPEC-601 §7 deterministic tail rule; the #105
  multi-UP-tail defect class pinned byte-exactly);
- MATYPE `0xD000` (TS_GS=11, NPD/ISSYI clear — same convention as the
  registered `t2mi-minimal` vector), SYNC `0x47`, SYNCD 0 (first UP at
  data-field start), Normal Mode (stored CRC-8 = plain CRC-8);
- frame size = 10 + 3×188 = 574 bytes; stream = 1722 bytes.

## Verification path (L1 bit-level-review)

1. **Standard-table derivation** (independent source of truth): every
   byte derives from ETSI EN 302 755 V1.4.1 §5.1.7 (BBHEADER field
   table, CRC-8 poly 0xD5 annex F) and §5.1.8 (NM transmitted UP =
   per-UP CRC-8 + 187 body bytes). The constructor imports nothing from
   `src/ts`; its CRC-8 is a self-contained table implementation
   cross-checked against the two independent research constructors
   (#104 tsduck-t2mi-plugin `gen_t2mi.py`, ffmpeg-t2mi-demuxer
   `gen_t2mi_sample.py`) and TSDuck master `T2MIDemux::BBHeaderCRC8`
   (four implementations of the same standard table).
2. **Self-parse cross** (L3 regression only, never acceptance): the
   conformance suite parses the vector with `ts.t2mi.bbframe.parse` and
   asserts the registered expectations (SPEC-601 §5 wire keys + §8
   state) plus byte-identical re-encapsulation. 同源自证 excludes this
   path from acceptance per SPEC-506 §5.

## TSDuck cross — NOT TRUSTED / impossible (ruling §10-9)

TSDuck 3.45-4798 has **zero user-side BBFrame capability** (#104 实测:
User Guide/Dev docs contain no BBFrame tool, plugin or option; BBHEADER
is only an internal detail of the t2mi demux, parsed without CRC-8
verification; NM streams decode to garbage). SPEC-601 §13 therefore
rules out a TSDuck BBFrame cross entirely — there is no L2 path for
this layer, and any future TSDuck-based claim stays NOT TRUSTED until
the master 147deab3 fixes ship in a release (and even then TSDuck only
reaches the t2mi-demux internal face, not a BBFrame parse API).

## Consumption

- Conformance: `tests/conformance/test_bbframe_golden_vectors.py`
  (expectations-driven parse; tail-stuffing byte pinning; determinism).
- Pair baseline for the B2 faulted形态对 `bbframe-b2-corrupt` /
  `bbframe-b2-shift` (independent transform script, no self-code path).
