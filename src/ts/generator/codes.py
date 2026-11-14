"""SPEC-108 §10 — generator-owned error-code constants (ticket #34).

Module-owned per the contract §7 归属约定: every ``GENERATOR_*`` code raises
:class:`ts.errors.GenerationError` (the §7 mapping-table row for this
family).  SPEC-108 §10 enumerates the family verbatim; the firing conditions
are documented on the raising sites (:mod:`ts.generator.validator` maps §5
constraint violations onto this family, :mod:`ts.generator.generator` owns
the run-time codes).

Two §5 constraints have no dedicated §10 code — the mapping below is the
frozen ticket-#34 decision, recorded in the implementation report:

- non-positive ``pat_period_ms`` / ``pmt_period_ms`` / ``pcr_interval_ms``
  and an ``pcr_insertion_policy`` outside the two ruling-#11 values raise
  ``GENERATOR_INVALID_PROGRAM_CONFIG`` (transport scheduling parameters are
  part of the program's generation configuration);
- ``deterministic=False`` raises ``GENERATOR_NONDETERMINISTIC_SOURCE`` (the
  nondeterminism code of this family); a ``payload_profile`` other than
  ``"synthetic_test_data"`` raises ``GENERATOR_INVALID_PROGRAM_CONFIG``.

None of these codes triggers an implicit fix: validation rejects the config
before any byte is produced, and run-time failures abort with
run-independent context chained from the upstream component error.
"""

from __future__ import annotations

#: ``schema_version`` is not in the supported set (SPEC-108 §5).
GENERATOR_SCHEMA_VERSION_UNSUPPORTED = "GENERATOR_SCHEMA_VERSION_UNSUPPORTED"

#: ``profile`` is not the MVP ``analysis_only`` profile (SPEC-108 §2/§5).
GENERATOR_PROFILE_UNSUPPORTED = "GENERATOR_PROFILE_UNSUPPORTED"

#: Program-level configuration violation (SPEC-108 §5): ``program_number=0``,
#: field-width violations (TSID / program_number / stream_type / stream_id),
#: a non-positive PAT/PMT/PCR period, an unsupported ``pcr_insertion_policy``,
#: a ``payload_profile`` other than ``"synthetic_test_data"``, or program
#: descriptors that cannot fit the single-section PMT.
GENERATOR_INVALID_PROGRAM_CONFIG = "GENERATOR_INVALID_PROGRAM_CONFIG"

#: PID policy violation (SPEC-108 §5): a generator-owned PID on a reserved
#: PID (project set: 0x0000..0x001F PSI range + 0x1FFF null), a duplicate
#: ES PID inside the program, or a pairwise collision between PMT / ES /
#: PCR PIDs beyond the explicitly allowed ``pcr_pid == one ES PID`` reuse.
GENERATOR_PID_COLLISION = "GENERATOR_PID_COLLISION"

#: A bitrate field is unusable (SPEC-108 §5): non-positive
#: ``target_bitrate_bps``, outside the frozen 1..100 Mbps envelope
#: (ADR-0008 §2), or a non-positive per-ES ``bitrate_bps``.
GENERATOR_INVALID_BITRATE = "GENERATOR_INVALID_BITRATE"

#: The configured ES bitrates plus the conservative table/PCR overhead
#: estimate cannot fit the target transport bitrate (SPEC-108 §5: refuse,
#: never silently lower ES rates).
GENERATOR_RATE_OVERCOMMITTED = "GENERATOR_RATE_OVERCOMMITTED"

#: ``output_packet_count`` is not a positive integer (SPEC-108 §5).
GENERATOR_INVALID_PACKET_COUNT = "GENERATOR_INVALID_PACKET_COUNT"

#: The configuration asks for a nondeterministic source (SPEC-108 §5/§8):
#: ``deterministic=False`` — MVP generation is deterministic-only.
GENERATOR_NONDETERMINISTIC_SOURCE = "GENERATOR_NONDETERMINISTIC_SOURCE"

#: Writing one 188-byte packet through the caller's sink failed
#: (SPEC-108 §6: the sink is a minimal ``write(bytes)`` protocol object).
GENERATOR_OUTPUT_WRITE_FAILED = "GENERATOR_OUTPUT_WRITE_FAILED"

#: Internal invariant breach: a serialized packet is not exactly 188 bytes,
#: or the run accounting disagrees with the mux summary (SPEC-108 §9).
GENERATOR_PACKET_SIZE_INVARIANT_FAILED = "GENERATOR_PACKET_SIZE_INVARIANT_FAILED"

#: An orchestrated upstream component (PAT/PMT builder, packetizer, mux,
#: media clock) failed during generation (SPEC-108 §7 step 9: raise
#: ``GenerationError``, never return a pseudo-success summary).  The
#: original component error is chained (``raise ... from``).
GENERATOR_INTERNAL_COMPONENT_FAILED = "GENERATOR_INTERNAL_COMPONENT_FAILED"
