# packet-header-set — independent verification evidence

SPEC-506 §5 verification record for golden vector `packet-header-set`.
Tool: tsp (TSDuck - The MPEG Transport Stream Toolkit) 3.40-4165 (local reference machine; CI installs its own TSDuck — version drift never invalidates the frozen sha256, #14 Q8).

- Verification path: **L1 bit-level review** (SPEC-506 §5: authoritative
  basis, no TSDuck needed).
- Derivation: `tools/make_golden_packet_header_set.py` builds each 4-byte
  header bit-by-bit from the SPEC-100 §3 wire table; expected field values
  are independently pinned in
  `tests/conformance/test_packet_header_set_vector.py` (derived from the
  spec table, not from the script).
- Derivation doc: `docs/test-vectors/PACKET-HEADER-SET.md`.
- Cross-check performed: self strict parser agrees with the hand-derived
  bytes on all 10 samples (10 conformance assertions), including the
  reserved-scrambling ValidationIssue, the s6/s7 CC-reuse pair and the
  hand-set PCR value.
