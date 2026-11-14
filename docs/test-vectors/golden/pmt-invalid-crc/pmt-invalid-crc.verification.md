# pmt-invalid-crc — independent verification evidence

SPEC-506 §5 verification record for golden vector `pmt-invalid-crc`.
Tool: tsp (TSDuck - The MPEG Transport Stream Toolkit) 3.40-4165 (local reference machine; CI installs its own TSDuck — version drift never invalidates the frozen sha256, #14 Q8).

- Verification path: **L2 independent-transform → tsduck-analyze**
  (SPEC-204 §6.2, mode=persistent, corruption=invert; all three PMT
  instances' CRC bytes inverted in place).
- Independent readback — `tsanalyze` on baseline vs faulted, PMT PID row:

```
baseline : PMT PID: 0x1000 (4096), PCR PID: 0x0100 (256)   — PMT accepted
faulted  : PMT PID: 0x1000 (4096), PCR PID: None           — PMT rejected
```

  TSDuck's demuxer silently drops the CRC-invalid PMT sections: the
  service stays unknown and the ES usage rows disappear from the report.

- Self-parse side: the SectionAssembler reports exactly 3
  `SECTION_CRC_INVALID` issues (one per instance) and emits no section.
