"""Builtin rule declarations (SPEC-307 section 6, ticket #55).

Pure data package: one canonical JSON declaration per builtin rule.
The loader reads these through importlib.resources; the Python dual
form lives in ``domain.diagnosis.rules.declarations`` and the two
are cross-checked at load (SPEC-307 section 7).
"""
