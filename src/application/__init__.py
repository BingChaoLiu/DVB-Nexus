"""Application layer: use-case orchestration, Session lifecycle, transaction boundaries.

May depend on all packages except ``api`` (ADR-0005 decision 4); must not
encode TS bytes (SPEC-001 section 4).
"""
