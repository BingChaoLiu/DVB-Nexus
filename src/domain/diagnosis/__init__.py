"""Diagnosis domain: maps Observations to root-cause candidates and suggestions.

Consumes only ``domain.observation`` (plus static reference data from
``knowledge``); never touches TSDuck processes, never parses raw TS and never
starts processes (ADR-0005 decision 4).
"""
