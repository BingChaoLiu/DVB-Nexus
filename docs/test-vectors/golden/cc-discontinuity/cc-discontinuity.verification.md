# cc-discontinuity — independent verification evidence

SPEC-506 §5 verification record for golden vector `cc-discontinuity`.
Tool: tsp (TSDuck - The MPEG Transport Stream Toolkit) 3.40-4165 (local reference machine; CI installs its own TSDuck — version drift never invalidates the frozen sha256, #14 Q8).

- Verification path: **L2 independent-transform → tsduck-analyze**
  (SPEC-204 §6.3, delta=3 on PID 256, landing on the first payload packet
  after activation slot 30, offset persists).
- Independent readback — `tsp -I file cc-discontinuity.ts -O drop
  -P continuity`:

```
* continuity: packet index: 50, PID: 0x0100 (256), missing 3 packets
* continuity: packet index: 404, PID: 0x0000 (0), 3 duplicate packets
* continuity: packet index: 412, PID: 0x1000 (4096), 3 duplicate packets
```

  The checker flags exactly the frozen landing slot (index 50) with the
  frozen delta (`missing 3 packets`).
- Self-parse side: the pair test asserts
  `faulted_cc[i] == (baseline_cc[i] + 3) mod 16` for every PID-256 payload
  packet from slot 50 on, and the reuse rule for adaptation-only packets.
