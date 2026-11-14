"""Domain layer container (ADR-0005 decision 4 directory fusion).

Groups ``domain.topology``, ``domain.observation`` and ``domain.diagnosis``.
Domain code must not import FastAPI, SQLite, the filesystem or the TSDuck
adapter, and must not import Application/API packages.
"""
