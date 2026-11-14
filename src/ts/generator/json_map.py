"""SPEC-108 §4 — JSON↔DTO field mapping for GeneratorConfig (ticket #34).

The mapping table (ruling #11: snake_case field names, Pydantic DTO
authority stays in SPEC-500) maps a JSON request body onto the typed
:class:`ts.generator.config.GeneratorConfig` — this module is its stdlib-only
implementation so the API/Application layer (which owns Pydantic) can
delegate the JSON→DTO step without pulling pydantic into ``ts`` (contract
§2.2: the ts package has no pydantic/fastapi dependency).

=================================  =======================================
JSON field                          GeneratorConfig field
=================================  =======================================
schema_version                      schema_version
profile                             profile
deterministic                       deterministic
seed                                seed
initial_media_clock_27mhz           initial_media_clock_27mhz
target_bitrate_bps                  target_bitrate_bps
output_packet_count                 output_packet_count
program.transport_stream_id         program.transport_stream_id
program.program_number              program.program_number
program.pmt_pid                     program.pmt_pid
program.pcr_pid                     program.pcr_pid
program.version_number              program.version_number
program.program_descriptors         program.program_descriptors (hex)
program.streams[] (same names)      program.streams[] (same names)
pat_period_ms / pmt_period_ms /     same fields
pcr_interval_ms
pcr_insertion_policy                pcr_insertion_policy
=================================  =======================================

Responsibility split (single validation authority): the mapping enforces
only the §4 structural constraints (exact key sets, JSON types per the
table's 约束 column, even-length hex for bytes fields); every §5 semantic
constraint is enforced by :func:`ts.generator.validator.validate_config`.
Structural violations raise ``ValueError`` naming the offending field path;
non-dict/typing-level misuse raises ``TypeError`` (upstream model-boundary
convention).
"""

from __future__ import annotations

from ts.generator.config import (
    ElementaryStreamConfig,
    GeneratorConfig,
    ProgramConfig,
)

_BYTES_LIKE = (bytes, bytearray, memoryview)

_TOP_LEVEL_KEYS = (
    "schema_version",
    "profile",
    "deterministic",
    "seed",
    "initial_media_clock_27mhz",
    "target_bitrate_bps",
    "output_packet_count",
    "program",
    "pat_period_ms",
    "pmt_period_ms",
    "pcr_interval_ms",
    "pcr_insertion_policy",
)

_PROGRAM_KEYS = (
    "transport_stream_id",
    "program_number",
    "pmt_pid",
    "pcr_pid",
    "version_number",
    "program_descriptors",
    "streams",
)

_STREAM_KEYS = (
    "pid",
    "stream_type",
    "stream_id",
    "bitrate_bps",
    "payload_profile",
    "payload_seed_offset",
)

_INT_TOP_LEVEL_KEYS = (
    "schema_version",
    "seed",
    "initial_media_clock_27mhz",
    "target_bitrate_bps",
    "output_packet_count",
    "pat_period_ms",
    "pmt_period_ms",
    "pcr_interval_ms",
)

_STR_TOP_LEVEL_KEYS = ("profile", "pcr_insertion_policy")

_INT_PROGRAM_KEYS = (
    "transport_stream_id",
    "program_number",
    "pmt_pid",
    "pcr_pid",
    "version_number",
)

_INT_STREAM_KEYS = ("pid", "stream_type", "stream_id", "bitrate_bps", "payload_seed_offset")

_STR_STREAM_KEYS = ("payload_profile",)


def _require_dict(value: object, path: str) -> dict:
    if not isinstance(value, dict):
        raise TypeError(f"{path} must be a JSON object, got {type(value).__name__}")
    return value


def _require_keys(value: dict, keys: tuple[str, ...], path: str) -> None:
    """Exact key set: every mapped key present, no unknown keys (§4 table)."""
    missing = [key for key in keys if key not in value]
    if missing:
        raise ValueError(f"{path}: missing required field(s) {missing}")
    unknown = [key for key in value if key not in keys]
    if unknown:
        raise ValueError(
            f"{path}: unknown field(s) {unknown} — the SPEC-108 §4 mapping "
            "table enumerates the exact key set"
        )


def _require_int_field(value: dict, key: str, path: str) -> int:
    number = value[key]
    if isinstance(number, bool) or not isinstance(number, int):
        raise ValueError(f"{path}{key} must be an int, got {type(number).__name__}")
    return number


def _require_str_field(value: dict, key: str, path: str) -> str:
    text = value[key]
    if not isinstance(text, str):
        raise ValueError(f"{path}{key} must be a str, got {type(text).__name__}")
    return text


def _require_bool_field(value: dict, key: str, path: str) -> bool:
    flag = value[key]
    if not isinstance(flag, bool):
        raise ValueError(f"{path}{key} must be a bool, got {type(flag).__name__}")
    return flag


def _hex_to_bytes(value: dict, key: str, path: str) -> bytes:
    text = _require_str_field(value, key, path)
    try:
        return bytes.fromhex(text)
    except ValueError as exc:
        raise ValueError(
            f"{path}{key} must be a hex string (even-length, the §4 table's "
            f"bytes encoding), got {text!r}: {exc}"
        ) from exc


def _stream_from_json(value: dict) -> ElementaryStreamConfig:
    value = _require_dict(value, "program.streams[]")
    _require_keys(value, _STREAM_KEYS, "program.streams[]")
    return ElementaryStreamConfig(
        pid=_require_int_field(value, "pid", "program.streams[]."),
        stream_type=_require_int_field(value, "stream_type", "program.streams[]."),
        stream_id=_require_int_field(value, "stream_id", "program.streams[]."),
        bitrate_bps=_require_int_field(value, "bitrate_bps", "program.streams[]."),
        payload_profile=_require_str_field(value, "payload_profile", "program.streams[]."),
        payload_seed_offset=_require_int_field(
            value, "payload_seed_offset", "program.streams[]."
        ),
    )


def _program_from_json(value: dict) -> ProgramConfig:
    value = _require_dict(value, "program.")
    _require_keys(value, _PROGRAM_KEYS, "program.")
    streams = value["streams"]
    if not isinstance(streams, list):
        raise ValueError(
            f"program.streams must be an array, got {type(streams).__name__}"
        )
    return ProgramConfig(
        transport_stream_id=_require_int_field(value, "transport_stream_id", "program."),
        program_number=_require_int_field(value, "program_number", "program."),
        pmt_pid=_require_int_field(value, "pmt_pid", "program."),
        pcr_pid=_require_int_field(value, "pcr_pid", "program."),
        version_number=_require_int_field(value, "version_number", "program."),
        program_descriptors=_hex_to_bytes(value, "program_descriptors", "program."),
        streams=tuple(_stream_from_json(item) for item in streams),
    )


def generator_config_from_json(payload: object) -> GeneratorConfig:
    """Decode the §4 JSON body shape into a typed ``GeneratorConfig``.

    Structural mapping only (see the module docstring): unknown or missing
    keys and mistyped fields raise ``ValueError`` naming the field path;
    a non-object payload raises ``TypeError``.  Semantic validation is
    :func:`ts.generator.validator.validate_config`'s job.
    """
    value = _require_dict(payload, "")
    _require_keys(value, _TOP_LEVEL_KEYS, "")
    for key in _INT_TOP_LEVEL_KEYS:
        _require_int_field(value, key, "")
    for key in _STR_TOP_LEVEL_KEYS:
        _require_str_field(value, key, "")
    _require_bool_field(value, "deterministic", "")
    return GeneratorConfig(
        schema_version=value["schema_version"],
        profile=value["profile"],
        deterministic=value["deterministic"],
        seed=value["seed"],
        initial_media_clock_27mhz=value["initial_media_clock_27mhz"],
        target_bitrate_bps=value["target_bitrate_bps"],
        output_packet_count=value["output_packet_count"],
        program=_program_from_json(value["program"]),
        pat_period_ms=value["pat_period_ms"],
        pmt_period_ms=value["pmt_period_ms"],
        pcr_interval_ms=value["pcr_interval_ms"],
        pcr_insertion_policy=value["pcr_insertion_policy"],
    )


def generator_config_to_json(config: GeneratorConfig) -> dict:
    """Encode a ``GeneratorConfig`` into the §4 JSON body shape (inverse).

    ``program_descriptors`` encodes as a lowercase hex string; every other
    field copies by name.  The round trip
    ``from_json(to_json(cfg)) == cfg`` is pinned by the tests.
    """
    if not isinstance(config, GeneratorConfig):
        raise TypeError(
            f"config must be GeneratorConfig, got {type(config).__name__}"
        )
    descriptors = config.program.program_descriptors
    if isinstance(descriptors, _BYTES_LIKE):
        hex_text = bytes(descriptors).hex()
    else:
        raise TypeError(
            "program.program_descriptors must be bytes-like, got "
            f"{type(descriptors).__name__}"
        )
    return {
        "schema_version": config.schema_version,
        "profile": config.profile,
        "deterministic": config.deterministic,
        "seed": config.seed,
        "initial_media_clock_27mhz": config.initial_media_clock_27mhz,
        "target_bitrate_bps": config.target_bitrate_bps,
        "output_packet_count": config.output_packet_count,
        "program": {
            "transport_stream_id": config.program.transport_stream_id,
            "program_number": config.program.program_number,
            "pmt_pid": config.program.pmt_pid,
            "pcr_pid": config.program.pcr_pid,
            "version_number": config.program.version_number,
            "program_descriptors": hex_text,
            "streams": [
                {
                    "pid": stream.pid,
                    "stream_type": stream.stream_type,
                    "stream_id": stream.stream_id,
                    "bitrate_bps": stream.bitrate_bps,
                    "payload_profile": stream.payload_profile,
                    "payload_seed_offset": stream.payload_seed_offset,
                }
                for stream in config.program.streams
            ],
        },
        "pat_period_ms": config.pat_period_ms,
        "pmt_period_ms": config.pmt_period_ms,
        "pcr_interval_ms": config.pcr_interval_ms,
        "pcr_insertion_policy": config.pcr_insertion_policy,
    }
