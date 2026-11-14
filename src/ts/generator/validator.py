"""SPEC-108 §5 — GeneratorConfig constraint validation (ticket #34).

``validate_config`` is the single validation authority for the §5 constraint
set.  It returns a list of :class:`ts.issues.ValidationIssue` findings (the
SPEC-108 §6 public-interface signature); every rejection is
``severity="error"`` and names the offending ``field``, so the Generator can
refuse to run (``iter_packets`` / ``generate_to`` raise
``GenerationError`` chained onto the first error finding — §7 step 1/step 9,
"非法配置明确拒绝", no implicit fixes, no pseudo-success summaries).

§5-constraint → §10-code mapping (two constraints have no dedicated §10
code; the mapping is frozen by ticket #34 and recorded in the implementation
report):

====================================  =========================================
§5 constraint                          §10 code / field
====================================  =========================================
schema_version unsupported             GENERATOR_SCHEMA_VERSION_UNSUPPORTED
profile != analysis_only               GENERATOR_PROFILE_UNSUPPORTED
deterministic=False                    GENERATOR_NONDETERMINISTIC_SOURCE
output_packet_count <= 0               GENERATOR_INVALID_PACKET_COUNT
target_bitrate outside 1..100 Mbps     GENERATOR_INVALID_BITRATE
ES bitrate_bps <= 0                    GENERATOR_INVALID_BITRATE
pat/pmt/pcr period <= 0                GENERATOR_INVALID_PROGRAM_CONFIG
insertion_policy not in the 2 values   GENERATOR_INVALID_PROGRAM_CONFIG
payload_profile != synthetic_test_data GENERATOR_INVALID_PROGRAM_CONFIG
program_number == 0 / width violations GENERATOR_INVALID_PROGRAM_CONFIG
descriptors exceed the PMT section     GENERATOR_INVALID_PROGRAM_CONFIG
initial_media_clock_27mhz < 0          GENERATOR_INVALID_PROGRAM_CONFIG
reserved / colliding / duplicate PIDs  GENERATOR_PID_COLLISION
ES sum + overhead > target bitrate     GENERATOR_RATE_OVERCOMMITTED
====================================  =========================================

Findings are produced in a fixed check order (schema → profile → global
scalars → program structure → per-ES → PID policy → rate fit), so the
"first error" a caller sees is stable and reproducible (contract §2.6
determinism discipline extends to the diagnostic surface).

No float ever participates: the overhead estimate is exact integer
arithmetic over the SPEC-107 slot size and whole-millisecond periods
(contract §2.4).
"""

from __future__ import annotations

from ts.generator.codes import (
    GENERATOR_INVALID_BITRATE,
    GENERATOR_INVALID_PACKET_COUNT,
    GENERATOR_INVALID_PROGRAM_CONFIG,
    GENERATOR_NONDETERMINISTIC_SOURCE,
    GENERATOR_PID_COLLISION,
    GENERATOR_PROFILE_UNSUPPORTED,
    GENERATOR_RATE_OVERCOMMITTED,
    GENERATOR_SCHEMA_VERSION_UNSUPPORTED,
)
from ts.generator.config import (
    PAYLOAD_PROFILE_SYNTHETIC_TEST_DATA,
    PROFILE_ANALYSIS_ONLY,
    ElementaryStreamConfig,
    GeneratorConfig,
    ProgramConfig,
)
from ts._bytesutil import PID_MAX, _require_int
from ts.issues import ValidationIssue
from ts.mux.scheduler import SLOT_BITS
from ts.pes import SPECIAL_STREAM_IDS

#: Supported config schema versions (MVP: exactly schema 1; SPEC-500 may
#: extend the set and must keep its Pydantic DTO aligned with §4).
SUPPORTED_SCHEMA_VERSIONS: tuple[int, ...] = (1,)

#: Frozen bitrate envelope (SPEC-108 §5 ← ADR-0008 §2): 1..100 Mbps.
TARGET_BITRATE_BPS_MIN = 1
TARGET_BITRATE_BPS_MAX = 100_000_000

#: Project-forbidden reserved PIDs for generator-owned PIDs (PMT / ES /
#: PCR): the ISO/ITU-T + DVB PSI range 0x0000..0x001F (PAT 0x0000, CAT
#: 0x0001, TSDT/reserved ..0x000F, NIT/SDT/EIT/... ..0x001F) and the null
#: PID 0x1FFF (project rule, SPEC-103 §8.6 / SPEC-107 §5.1).
RESERVED_PID_LOW = 0x0000
RESERVED_PID_HIGH = 0x001F
PID_NULL = 0x1FFF
RESERVED_PIDS = frozenset(range(RESERVED_PID_LOW, RESERVED_PID_HIGH + 1)) | {
    PID_NULL
}

_U16_MAX = 0xFFFF
_U8_MAX = 0xFF
_VERSION_MAX = 0x1F

#: Single-section PMT capacity (SPEC-103 §4/§7): section_length =
#: 13 + program_descriptors + Σ(5 + es_descriptors); MVP ES entries carry no
#: descriptors, so the per-ES cost is the fixed 5-byte prefix.
PMT_FIXED_SECTION_OVERHEAD = 13
PMT_ES_ENTRY_COST = 5
PMT_SECTION_LENGTH_MAX = 1021


def _error(code: str, message: str, field: str) -> ValidationIssue:
    """One error-severity, field-named validation finding."""
    return ValidationIssue(code=code, message=message, severity="error", field=field)


def validate_config(config: object) -> list[ValidationIssue]:
    """Validate a :class:`ts.generator.config.GeneratorConfig` (SPEC-108 §5).

    Returns every finding in fixed check order; an empty list means the
    configuration is generatable.  Non-``GeneratorConfig`` input and wrong
    field types are programming errors (``TypeError``), mirroring the
    upstream model-boundary guards; wire-side/semantic violations come back
    as error-severity :class:`ts.issues.ValidationIssue` findings instead of
    raised exceptions (SPEC-108 §6 signature).
    """
    if not isinstance(config, GeneratorConfig):
        raise TypeError(
            f"config must be GeneratorConfig, got {type(config).__name__}"
        )
    issues: list[ValidationIssue] = []

    # --- global scalars (§5 rows 1-4 + seed/clock fingerprint fields) ---
    if config.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        issues.append(
            _error(
                GENERATOR_SCHEMA_VERSION_UNSUPPORTED,
                f"schema_version {config.schema_version!r} is not supported; "
                f"supported versions: {list(SUPPORTED_SCHEMA_VERSIONS)}",
                "schema_version",
            )
        )
    if config.profile != PROFILE_ANALYSIS_ONLY:
        issues.append(
            _error(
                GENERATOR_PROFILE_UNSUPPORTED,
                f"profile {config.profile!r} is unsupported; the only MVP "
                f"profile is {PROFILE_ANALYSIS_ONLY!r} (SPEC-108 §2; "
                "playback_ready is a future capability, not implemented)",
                "profile",
            )
        )
    if config.deterministic is not True:
        issues.append(
            _error(
                GENERATOR_NONDETERMINISTIC_SOURCE,
                "deterministic must be True in MVP: generation is "
                "deterministic-only and seed/initial clock form the "
                "generation fingerprint (SPEC-108 §5/§8)",
                "deterministic",
            )
        )
    _require_int(config.output_packet_count, "output_packet_count")
    if config.output_packet_count <= 0:
        issues.append(
            _error(
                GENERATOR_INVALID_PACKET_COUNT,
                f"output_packet_count must be positive, got "
                f"{config.output_packet_count}",
                "output_packet_count",
            )
        )
    _require_int(config.target_bitrate_bps, "target_bitrate_bps")
    if not TARGET_BITRATE_BPS_MIN <= config.target_bitrate_bps <= TARGET_BITRATE_BPS_MAX:
        issues.append(
            _error(
                GENERATOR_INVALID_BITRATE,
                f"target_bitrate_bps must be in "
                f"{TARGET_BITRATE_BPS_MIN}..{TARGET_BITRATE_BPS_MAX} bps "
                "(frozen envelope, ADR-0008 §2), got "
                f"{config.target_bitrate_bps}",
                "target_bitrate_bps",
            )
        )
    _require_int(config.initial_media_clock_27mhz, "initial_media_clock_27mhz")
    if config.initial_media_clock_27mhz < 0:
        issues.append(
            _error(
                GENERATOR_INVALID_PROGRAM_CONFIG,
                f"initial_media_clock_27mhz must be non-negative, got "
                f"{config.initial_media_clock_27mhz}",
                "initial_media_clock_27mhz",
            )
        )
    for name in ("pat_period_ms", "pmt_period_ms", "pcr_interval_ms"):
        period = getattr(config, name)
        _require_int(period, name)
        if period <= 0:
            issues.append(
                _error(
                    GENERATOR_INVALID_PROGRAM_CONFIG,
                    f"{name} must be positive, got {period}",
                    name,
                )
            )
    if config.pcr_insertion_policy not in ("payload_packet_first", "adaptation_only_fallback"):
        issues.append(
            _error(
                GENERATOR_INVALID_PROGRAM_CONFIG,
                f"pcr_insertion_policy {config.pcr_insertion_policy!r} is "
                "not one of the two frozen values (ruling #11 / SPEC-107 "
                "§5.3): 'payload_packet_first' or 'adaptation_only_fallback'",
                "pcr_insertion_policy",
            )
        )

    # --- program structure (§5 field-width and descriptor rows) ---
    program = config.program
    if not isinstance(program, ProgramConfig):
        raise TypeError(
            f"program must be ProgramConfig, got {type(program).__name__}"
        )
    _require_int(program.transport_stream_id, "transport_stream_id")
    if not 0 <= program.transport_stream_id <= _U16_MAX:
        issues.append(
            _error(
                GENERATOR_INVALID_PROGRAM_CONFIG,
                f"transport_stream_id must fit 16 bits (0..{_U16_MAX}), got "
                f"{program.transport_stream_id}",
                "transport_stream_id",
            )
        )
    _require_int(program.program_number, "program_number")
    if program.program_number == 0:
        issues.append(
            _error(
                GENERATOR_INVALID_PROGRAM_CONFIG,
                "program_number must be non-zero: program 0 is the PAT's "
                "network_PID (NIT) slot (SPEC-108 §5 / SPEC-103 §5)",
                "program_number",
            )
        )
    elif not 0 <= program.program_number <= _U16_MAX:
        issues.append(
            _error(
                GENERATOR_INVALID_PROGRAM_CONFIG,
                f"program_number must fit 16 bits (0..{_U16_MAX}), got "
                f"{program.program_number}",
                "program_number",
            )
        )
    _require_int(program.version_number, "version_number")
    if not 0 <= program.version_number <= _VERSION_MAX:
        issues.append(
            _error(
                GENERATOR_INVALID_PROGRAM_CONFIG,
                f"version_number must fit 5 bits (0..{_VERSION_MAX}), got "
                f"{program.version_number}",
                "version_number",
            )
        )
    if not isinstance(program.program_descriptors, (bytes, bytearray, memoryview)):
        raise TypeError(
            "program_descriptors must be bytes-like, got "
            f"{type(program.program_descriptors).__name__}"
        )
    descriptors_length = len(program.program_descriptors)
    streams = tuple(program.streams)
    pmt_section_length = (
        PMT_FIXED_SECTION_OVERHEAD
        + descriptors_length
        + PMT_ES_ENTRY_COST * len(streams)
    )
    if pmt_section_length > PMT_SECTION_LENGTH_MAX:
        issues.append(
            _error(
                GENERATOR_INVALID_PROGRAM_CONFIG,
                f"program_descriptors ({descriptors_length} bytes) plus "
                f"{len(streams)} ES entries would encode a PMT "
                f"section_length {pmt_section_length} beyond the "
                f"single-section maximum {PMT_SECTION_LENGTH_MAX} "
                "(SPEC-103 §7); shrink the descriptor loop",
                "program_descriptors",
            )
        )

    # --- per-ES fields (§5 width / bitrate / payload-profile rows) ---
    for stream in streams:
        if not isinstance(stream, ElementaryStreamConfig):
            raise TypeError(
                "program.streams entries must be ElementaryStreamConfig, "
                f"got {type(stream).__name__}"
            )
        _require_int(stream.stream_type, "stream_type")
        if not 0 <= stream.stream_type <= _U8_MAX:
            issues.append(
                _error(
                    GENERATOR_INVALID_PROGRAM_CONFIG,
                    f"stream_type must fit 8 bits (0..{_U8_MAX}), got "
                    f"{stream.stream_type} (pid {stream.pid})",
                    "stream_type",
                )
            )
        _require_int(stream.stream_id, "stream_id")
        if not 0 <= stream.stream_id <= _U8_MAX:
            issues.append(
                _error(
                    GENERATOR_INVALID_PROGRAM_CONFIG,
                    f"stream_id must fit 8 bits (0..{_U8_MAX}), got "
                    f"{stream.stream_id} (pid {stream.pid})",
                    "stream_id",
                )
            )
        elif stream.stream_id in SPECIAL_STREAM_IDS:
            issues.append(
                _error(
                    GENERATOR_INVALID_PROGRAM_CONFIG,
                    f"stream_id {stream.stream_id:#04x} uses a special PES "
                    "grammar the standard profile does not implement "
                    "(SPEC-104 §3)",
                    "stream_id",
                )
            )
        _require_int(stream.bitrate_bps, "bitrate_bps")
        if stream.bitrate_bps <= 0:
            issues.append(
                _error(
                    GENERATOR_INVALID_BITRATE,
                    f"bitrate_bps must be positive, got {stream.bitrate_bps} "
                    f"(pid {stream.pid})",
                    "bitrate_bps",
                )
            )
        if stream.payload_profile != PAYLOAD_PROFILE_SYNTHETIC_TEST_DATA:
            issues.append(
                _error(
                    GENERATOR_INVALID_PROGRAM_CONFIG,
                    f"payload_profile {stream.payload_profile!r} is "
                    "unsupported; the MVP analysis_only profile carries "
                    f"{PAYLOAD_PROFILE_SYNTHETIC_TEST_DATA!r} only "
                    "(SPEC-108 §2)",
                    "payload_profile",
                )
            )
        _require_int(stream.payload_seed_offset, "payload_seed_offset")

    # --- PID policy (§5: reserved PIDs, uniqueness, pairwise collisions) ---
    pid_fields: list[tuple[int, str]] = [
        (program.pmt_pid, "pmt_pid"),
        (program.pcr_pid, "pcr_pid"),
    ]
    for stream in streams:
        pid_fields.append((stream.pid, "pid"))
    for pid, field in pid_fields:
        _require_int(pid, field)
        if not 0 <= pid <= PID_MAX:
            issues.append(
                _error(
                    GENERATOR_PID_COLLISION,
                    f"{field} must be a 13-bit PID (0..{PID_MAX}), got {pid}",
                    field,
                )
            )
        elif pid in RESERVED_PIDS:
            issues.append(
                _error(
                    GENERATOR_PID_COLLISION,
                    f"{field} {pid:#06x} is a project-reserved PID "
                    f"({RESERVED_PID_LOW:#06x}..{RESERVED_PID_HIGH:#06x} "
                    f"PSI range or null PID {PID_NULL:#06x}) and can never "
                    "carry PMT/ES/PCR traffic (SPEC-108 §5)",
                    field,
                )
            )
    seen_es_pids: dict[int, str] = {}
    for stream in streams:
        if stream.pid in seen_es_pids:
            issues.append(
                _error(
                    GENERATOR_PID_COLLISION,
                    f"ES PID {stream.pid:#06x} appears more than once in "
                    "program.streams (ES PIDs are unique per program, "
                    "SPEC-108 §5)",
                    "pid",
                )
            )
        seen_es_pids[stream.pid] = "pid"

    def _pid_clean(pid: int) -> bool:
        """In-range and not reserved (those cases were already reported)."""
        return (
            isinstance(pid, int)
            and not isinstance(pid, bool)
            and 0 <= pid <= PID_MAX
            and pid not in RESERVED_PIDS
        )

    if _pid_clean(program.pmt_pid) and program.pmt_pid in seen_es_pids:
        issues.append(
            _error(
                GENERATOR_PID_COLLISION,
                f"pmt_pid {program.pmt_pid:#06x} collides with an ES PID "
                "(PMT and ES PIDs must not conflict, SPEC-108 §5)",
                "pid",
            )
        )
    if program.pcr_pid == program.pmt_pid and _pid_clean(program.pcr_pid):
        issues.append(
            _error(
                GENERATOR_PID_COLLISION,
                f"pcr_pid {program.pcr_pid:#06x} collides with pmt_pid "
                "(the only allowed PID reuse is PCR on one ES PID, "
                "SPEC-108 §5)",
                "pcr_pid",
            )
        )

    # --- rate fit (§5: ES sum + overhead must fit the target bitrate) ---
    if not issues:
        es_sum = sum(stream.bitrate_bps for stream in streams)
        overhead_bps = SLOT_BITS * (
            -(-1000 // config.pat_period_ms)
            + -(-1000 // config.pmt_period_ms)
            + -(-1000 // config.pcr_interval_ms)
        )
        total_bps = es_sum + overhead_bps
        if total_bps > config.target_bitrate_bps:
            issues.append(
                _error(
                    GENERATOR_RATE_OVERCOMMITTED,
                    f"ES bitrates sum to {es_sum} bps and the conservative "
                    f"table/PCR overhead estimate is {overhead_bps} bps "
                    f"(PAT {config.pat_period_ms} ms / PMT "
                    f"{config.pmt_period_ms} ms / PCR "
                    f"{config.pcr_interval_ms} ms periods), exceeding the "
                    f"target bitrate {config.target_bitrate_bps} bps; "
                    "refusing instead of silently lowering ES rates "
                    "(SPEC-108 §5)",
                    "target_bitrate_bps",
                )
            )

    return issues
