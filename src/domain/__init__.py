"""Domain layer container (ADR-0005 decision 4 directory fusion).

Groups ``domain.topology``, ``domain.observation`` and ``domain.diagnosis``.
Domain code must not import FastAPI, SQLite, the filesystem or the TSDuck
adapter, and must not import Application/API packages.

The three subpackages carry the SPEC-003 shared contracts (ticket #21):
topology = section 2.1 configuration model; observation = section 2.2/2.4/2.5/
2.7 run-scoped records plus the section 3 status vocabulary and the ADR-0006
ID-strategy types; diagnosis = section 2.6 root-cause candidates (consumes
only observation). Import the subpackages, not this container — it stays an
import-free docstring module on purpose.
"""
