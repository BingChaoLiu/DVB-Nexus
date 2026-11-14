"""Storage adapter: repository, Artifact files and metadata persistence.

SQLite plus filesystem-backed persistence for topology/experiment/Run
metadata, diagnosis summaries and Artifact metadata (SPEC-001 section 10).
Domain packages must not import this adapter.
"""
