"""SPEC-103 — PAT/PMT table semantics package (ticket #31).

Table-specific PSI semantics layered on the SPEC-102 framing
(:mod:`ts.section`) and the SPEC-101 CRC (:mod:`ts.crc`):

- :mod:`ts.tables.pat` — PAT data model, builder, parser, multi-section
  aggregation, and the table-family ``TABLE_*`` error codes.
- :mod:`ts.tables.pmt` — PMT data model, builder, parser, multi-section
  aggregation.
- :mod:`ts.tables.table_validation` — SPEC-103 §8 PID-association validator
  reporting :class:`ts.issues.ValidationIssue` diagnostics.

Imports go through the submodules directly (``from ts.tables.pat import
PATBuilder``) per the M0 export posture; this ``__init__`` carries no
re-exports.
"""
