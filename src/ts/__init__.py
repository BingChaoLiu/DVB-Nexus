"""TS Core: the self-developed MPEG-TS semantic layer (core technical asset).

TS packet / Section / PSI / PCR scheduling / Mux / Generator (ADR-0005
decision 3). Kept top-level, outside ``adapters/``: it is not an external
dependency and must stay replaceable behind stable upper interfaces. Imports
no other project package and never imports ``adapters.tsduck``.
"""
