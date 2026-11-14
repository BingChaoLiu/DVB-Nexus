"""SPEC-107 — MPEG-TS multiplexer and CBR packet-slot scheduler (ticket #33).

The mux merges multi-PID packet sources into a single deterministic CBR
output sequence: fixed target bitrate, packet-slot scheduling on an exact
integer 27 MHz lattice, PAT/PMT repetition, PCR scheduling (ruling #11:
*value* = SPEC-105, *timing* = SPEC-107, *construction* = SPEC-106) and
Null Packet (PID 0x1FFF) padding.  The mux never re-frames PSI/PES and
never modifies a finished TS packet or an adaptation field (contract §9).

Public surface (SPEC-107 §6 — import submodules directly, no re-exports
here, per the ``ts`` package export discipline):

- :class:`ts.mux.config.MuxConfig` / ``PIDRateConfig`` /
  ``TableRepetitionConfig`` / ``PCRScheduleConfig``
- :class:`ts.mux.scheduler.TSMux` / ``ScheduledPacket`` / ``MuxSummary``
- :class:`ts.mux.sources.PacketSource` protocol plus the built-in
  :class:`ts.mux.sources.TablePacketSource` and
  :class:`ts.mux.sources.PESPacketSource` source kinds
- :func:`ts.mux.null_packet.build_null_packet`

Error-code constants (SPEC-107 §7, module-owned per contract §7 归属约定)
live in :mod:`ts.mux.codes`; the six configuration codes map onto
:class:`ts.errors.InvalidMuxConfigError` and the three runtime codes onto
:class:`ts.errors.MuxSchedulingError`.
"""
