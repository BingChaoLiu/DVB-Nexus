"""T2-MI (DVB-T2 Modulator Interface) packet parse/build — SPEC-600.

Package root stays thin (house convention, M4 retro / brief §8.4 R3):
public seams live in their submodules and downstream tickets import them
directly, e.g. ``from ts.t2mi.parser import parse`` and
``from ts.t2mi.builder import build, T2miBuildConfig``.

Submodule map (SPEC-600 §6):

- ``ts.t2mi.packet``    — packet model, field encoding, derived faces;
- ``ts.t2mi.parser``    — ``parse(stream)`` byte stream → packet sequence;
- ``ts.t2mi.builder``   — ``build(bbframes, config)`` BBFRAME sequence →
  packet sequence (deterministic, back-to-back);
- ``ts.t2mi.summary``   — ``t2mi.stage_summary`` collection/emission seam;
- ``ts.t2mi.errors``    — ``T2miError`` base + module-owned error codes.

Imports no other project package (``ts`` purity, ADR-0005 decision 4);
only ``ts.crc`` / ``ts._bytesutil`` within the TS Core layer.
"""
