"""Adapters layer container (ADR-0005 decision 4 directory fusion).

Groups ``adapters.tsduck`` (TSDuck CLI subprocess adapter) and
``adapters.storage`` (SQLite repository and file Artifact store). External
dependencies must not leak back into the Domain layer (SPEC-001 section 3.5).
"""
