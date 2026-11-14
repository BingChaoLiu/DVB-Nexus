"""SPEC-106 — PSI/PES to TS packetization subpackage (ticket #32).

The one and only framing layer between complete PSI sections / PES byte
sequences (SPEC-102/SPEC-104 output) and 188-byte TS packets (SPEC-100).
Public surface (SPEC-106 §4, no re-exports here — import the submodules
directly, per the ``ts`` package export discipline):

- :class:`ts.packetizer.section_packetizer.SectionPacketizer`
- :class:`ts.packetizer.pes_packetizer.PESPacketizer`
- :func:`ts.packetizer.pes_packetizer.build_pcr_only_packet` — the single
  construction authority for adaptation-only PCR packets (ruling #11:
  PCR *value* = SPEC-105, insertion *timing* = SPEC-107, *construction* =
  this module; the Mux calls it and never modifies AF itself).

Error-code constants (SPEC-106 §9, module-owned per contract §7 归属约定)
live in :mod:`ts.packetizer.codes`; all of them map onto
:class:`ts.errors.PacketizationError`.
"""
