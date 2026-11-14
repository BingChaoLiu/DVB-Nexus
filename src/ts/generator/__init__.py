"""SPEC-108 — Deterministic MPEG-TS Generator (ticket #34).

Configuration-driven, deterministic, testable TS generation entry point
(SPEC-108 §1): converts program / bitrate / clock configuration into a
188-byte MPEG-2 TS packet sequence.  The Generator produces ONLY the clean
baseline stream — fault injection is SPEC-204's job downstream of the
Generator→sink edge (ADR-0007), so the generation path has zero fault
branches (REQ-TS-108-006).

Determinism contract (SPEC-108 §8, TS-CORE-INTEGRATION-CONTRACT §2.6): the
same generator version + normalized :class:`ts.generator.config.GeneratorConfig`
+ ``seed`` + ``initial_media_clock_27mhz`` produce byte-identical output.  No
wall clock, no ``hash()``, no randomness outside the version-pinned seeded
payload PRNG, no filesystem paths enter TS bytes.

The Generator orchestrates the frozen upstream components and never
duplicates their encodings (contract §2.3/§9):

- PAT/PMT sections: :mod:`ts.tables.pat` / :mod:`ts.tables.pmt` (#31)
- PES payloads: :mod:`ts.pes` analysis-only profile (#30)
- PSI/PES framing: :mod:`ts.packetizer` (#32)
- CBR packet-slot scheduling, PCR timing, null padding: :mod:`ts.mux` (#33)
- PCR/PTS/media-clock values: :mod:`ts.pcr` / :mod:`ts.clock` (#27)

Public surface (SPEC-108 §6 — import submodules directly, no re-exports
here, per the ``ts`` package export discipline):

- :class:`ts.generator.config.GeneratorConfig` / ``ProgramConfig`` /
  ``ElementaryStreamConfig`` (frozen dataclasses, §4 exact shape)
- :func:`ts.generator.validator.validate_config` — §5 constraint set as
  :class:`ts.issues.ValidationIssue` findings
- :class:`ts.generator.generator.TSGenerator` with ``validate_config`` /
  ``iter_packets`` / ``generate_to`` and the :class:`ts.generator.generator.GenerationSummary`
- :class:`ts.generator.sources.SyntheticPESSource` — deterministic
  analysis-only PES payload source per ES
- :mod:`ts.generator.json_map` — the §4 JSON↔DTO field mapping (snake_case,
  ``program_descriptors`` hex; the Pydantic DTO authority stays in SPEC-500)

Error-code constants (SPEC-108 §10, module-owned per contract §7 归属约定)
live in :mod:`ts.generator.codes`; the whole ``GENERATOR_*`` family raises
:class:`ts.errors.GenerationError`.
"""
