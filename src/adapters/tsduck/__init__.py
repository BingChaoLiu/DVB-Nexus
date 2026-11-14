"""TSDuck adapter: CLI subprocess integration (ADR-0005 decision 6).

Planned modules: process management (spawn/timeout/cancel), client for
analyze/inject/generate, whitelisted command builder, report parser (JSON to
Observation) and version detection. Never imported by ``ts``; TSDuck output is
never treated as absolute truth and never labelled ``measured``.
"""
