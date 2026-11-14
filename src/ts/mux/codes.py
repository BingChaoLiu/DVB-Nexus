"""SPEC-107 §7 — mux-owned error-code constants (ticket #33).

Module-owned per the contract §7 归属约定: the ``MUX_*`` family is split by
the §7 mapping table — the six configuration codes raise
:class:`ts.errors.InvalidMuxConfigError`, the three runtime scheduling
codes raise :class:`ts.errors.MuxSchedulingError`.  SPEC-107 §7 enumerates
the family verbatim; the firing conditions are documented on the raising
sites.

None of these codes triggers an implicit fix: every one of them aborts the
run (or refuses the configuration) with a typed exception carrying
run-independent, reproducible context — slot index, source_id, PID and
target bitrate — and never an uncontrolled temporary path (SPEC-107 §7).
"""

from __future__ import annotations

#: ``target_bitrate_bps`` is not a positive integer, or a per-PID
#: ``PIDRateConfig.bitrate_bps`` is not positive (SPEC-107 §4).
MUX_INVALID_BITRATE = "MUX_INVALID_BITRATE"

#: ``output_packet_count`` is not a positive integer (SPEC-107 §4).
MUX_INVALID_PACKET_COUNT = "MUX_INVALID_PACKET_COUNT"

#: PID/source identity policy violation (SPEC-107 §4 "PID 唯一策略"):
#: a duplicate PID or duplicate source_id inside ``pid_rates``, a source
#: id that appears twice in the source list, a source without a matching
#: ``PIDRateConfig`` entry (or an entry without a source), a non-table
#: source squatting on the reserved ``"pat"``/``"pmt"`` table source ids,
#: a PIDRateConfig PID outside the 13-bit range or on the null PID, or a
#: PESPacketSource whose own PID disagrees with its PIDRateConfig entry.
MUX_PID_DUPLICATE_SOURCE = "MUX_PID_DUPLICATE_SOURCE"

#: The configured ES bitrates cannot fit the target transport bitrate
#: (SPEC-107 §4: sum of ``PIDRateConfig.bitrate_bps`` > ``target_bitrate_bps``;
#: table/PCR protocol overhead is accounted separately per the spec).
MUX_PID_RATE_OVERCOMMITTED = "MUX_PID_RATE_OVERCOMMITTED"

#: ``TableRepetitionConfig`` carries a non-positive PAT or PMT period.
MUX_TABLE_PERIOD_INVALID = "MUX_TABLE_PERIOD_INVALID"

#: ``PCRScheduleConfig`` is unusable: non-positive ``target_interval_ms``,
#: an ``insertion_policy`` other than the two frozen values, or a
#: ``pcr_pid`` outside the 13-bit range / on the null PID (project rule
#: per SPEC-103 §8.6: PCR_PID never 0x1FFF).
MUX_PCR_INTERVAL_INVALID = "MUX_PCR_INTERVAL_INVALID"

#: A released packet could not be emitted within its deadline window
#: (release slot + one slot period, ruling #11).  The mux aborts the run
#: naming the slot index, source_id, PID, release/deadline ticks and the
#: target bitrate — packets are never silently dropped (SPEC-107 §5.6).
MUX_PACKET_DEADLINE_MISSED = "MUX_PACKET_DEADLINE_MISSED"

#: Internal invariant breach: a slot produced something other than exactly
#: one 188-byte TS packet, or the run ended with a packet count that
#: disagrees with ``output_packet_count`` (SPEC-107 §3.2 CBR invariant).
MUX_SLOT_COUNT_MISMATCH = "MUX_SLOT_COUNT_MISMATCH"

#: A source breached its own delivery contract: it reported an available
#: PES start for the armed PCR attachment yet produced nothing.  Defined
#: per source (the error names the source_id) — normal end-of-stream
#: exhaustion is NOT this error; the mux simply stops scheduling the dry
#: source and nulls fill its slots (SPEC-107 §7 "不应误判为全局错误").
MUX_SOURCE_EXHAUSTED = "MUX_SOURCE_EXHAUSTED"
