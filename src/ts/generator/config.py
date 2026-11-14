"""SPEC-108 §4 — frozen generator configuration model (ticket #34).

Pure typed dataclasses in the exact §4 shape: validation is NOT performed
here.  SPEC-108's public interface (:func:`ts.generator.validator.validate_config`,
``TSGenerator.validate_config``) is the single validation authority for the
§5 constraint set, returning :class:`ts.issues.ValidationIssue` findings;
``iter_packets`` / ``generate_to`` refuse to run when any error-severity
finding exists (SPEC-108 §7 step 1/step 9 — no implicit fixes, no
pseudo-success).

The JSON↔DTO field mapping for these dataclasses is the SPEC-108 §4 table
(ruling #11): snake_case field names, ``program_descriptors`` hex-encoded,
implemented by :mod:`ts.generator.json_map` (stdlib only — the Pydantic DTO
authority stays in SPEC-500 / the API layer, contract §2.2: ``ts`` has no
pydantic dependency).
"""

from __future__ import annotations

from dataclasses import dataclass

#: The only MVP generation profile (SPEC-108 §2).  ``playback_ready`` is a
#: future capability this spec does not implement.
PROFILE_ANALYSIS_ONLY = "analysis_only"

#: The only MVP payload profile: deterministic synthetic test data.  UI and
#: reports must mark ``payload_profile=synthetic_test_data`` and must never
#: claim "player-playable" or "real H.264/AAC" output (SPEC-108 §2/§9).
PAYLOAD_PROFILE_SYNTHETIC_TEST_DATA = "synthetic_test_data"


@dataclass(frozen=True)
class ElementaryStreamConfig:
    """One elementary stream of the program (SPEC-108 §4, exact shape).

    ``stream_type`` is declared verbatim into the PMT ES loop (declaration
    consistency is the §2 obligation); ``stream_id`` selects the PES
    stream_id; ``payload_seed_offset`` shifts the deterministic payload PRNG
    seed for this stream only (never a protocol field — SPEC-108 §8).
    """

    pid: int
    stream_type: int
    stream_id: int
    bitrate_bps: int
    payload_profile: str = PAYLOAD_PROFILE_SYNTHETIC_TEST_DATA
    payload_seed_offset: int = 0


@dataclass(frozen=True)
class ProgramConfig:
    """Single-program MVP program description (SPEC-108 §4, exact shape).

    ``version_number`` seeds both the PAT and the PMT version fields (MVP
    single-version generation).  ``program_descriptors`` are carried verbatim
    into the PMT program-info loop (SPEC-103 owns the framing).
    """

    transport_stream_id: int
    program_number: int
    pmt_pid: int
    pcr_pid: int
    version_number: int
    streams: tuple[ElementaryStreamConfig, ...]
    program_descriptors: bytes = b""


@dataclass(frozen=True)
class GeneratorConfig:
    """Complete generator configuration (SPEC-108 §4, exact shape).

    ``seed`` and ``initial_media_clock_27mhz`` are part of the generation
    fingerprint (§5/§8): identical values reproduce byte-identical output;
    no wall-clock input is ever read.  ``pcr_insertion_policy`` accepts the
    two ruling-#11 values frozen in SPEC-107 (``payload_packet_first`` /
    ``adaptation_only_fallback``); the mux owns the insertion semantics.
    """

    schema_version: int
    profile: str  # only "analysis_only" in MVP
    deterministic: bool
    seed: int
    initial_media_clock_27mhz: int
    target_bitrate_bps: int
    output_packet_count: int
    program: ProgramConfig
    # Out-of-phase defaults (ruling #72): same-phase PAT/PMT grids plus a
    # routine ES pull structurally violate the SPEC-107 §5 deadline window.
    pat_period_ms: int = 101
    pmt_period_ms: int = 103
    pcr_interval_ms: int = 40
    pcr_insertion_policy: str = "payload_packet_first"
