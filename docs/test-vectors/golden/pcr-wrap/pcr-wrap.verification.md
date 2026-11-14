# pcr-wrap — independent verification evidence

SPEC-506 §5 verification record for golden vector `pcr-wrap`.
Tool: tsp (TSDuck - The MPEG Transport Stream Toolkit) 3.40-4165 (local reference machine; CI installs its own TSDuck — version drift never invalidates the frozen sha256, #14 Q8).

- Verification path: **L2 script-construct → tsduck-analyze** (SPEC-506 §5).
- Construction: `tools/make_golden_ts_vectors.py pcr-wrap` — 6
  adaptation-only packets on PID 0x0100 with hand-set PCR base
  2^33-3 → 2^33-1 → 0 → 2 (ext 0).
- Independent readback — `tsp -I file pcr-wrap.ts -O drop -P pcrextract`
  (TSDuck decodes the 27 MHz values; the wrap step
  (2^33−1)·300 → 0 is visible as Value 2576980377300 → 0):

```
PID,Packet index in TS,Packet index in PID,Type,Count in PID,Value,Value offset in PID,Offset from PCR
256,0,0,PCR,1,2576980376700,0,
256,1,1,PCR,2,2576980377000,300,
256,2,2,PCR,3,2576980377300,600,
256,3,3,PCR,4,0,18446741496729174916,
256,4,4,PCR,5,300,18446741496729175216,
256,5,5,PCR,6,600,18446741496729175516,
```

- The conformance test additionally asserts the SPEC-105 §6 direction
  window: every forward modular delta (incl. the wrap step, 300 ticks) is
  below the half-period.
