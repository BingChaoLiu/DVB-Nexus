# cc-wrap — independent verification evidence

SPEC-506 §5 verification record for golden vector `cc-wrap`.
Tool: tsp (TSDuck - The MPEG Transport Stream Toolkit) 3.40-4165 (local reference machine; CI installs its own TSDuck — version drift never invalidates the frozen sha256, #14 Q8).

- Verification path: **L2 script-construct → tsduck-analyze** (SPEC-506 §5).
- Construction: `tools/make_golden_ts_vectors.py cc-wrap` (byte-level,
  CC = index mod 16 on 18 payload packets of PID 0x0123).
- Independent readback — `tsp -I file cc-wrap.ts -O drop -P continuity`:
  **empty output, exit 0** — the continuity checker is silent across the
  15→0 wrap (a wrong wrap is reported, e.g. a +3 jump yields
  `missing 3 packets`; verified during construction experiments).

Negative-control note (not part of the vector): the same plugin flags
`packet index: 10, PID: ..., missing 3 packets` on a hand-broken stream,
so the silence above is discriminating evidence.
