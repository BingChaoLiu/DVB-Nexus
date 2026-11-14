"""SPEC-108 §6/§7 — TSGenerator: config-driven deterministic orchestration (#34).

The Generator is the ts-core entry point that turns a validated
:class:`ts.generator.config.GeneratorConfig` into a fixed-length 188-byte
TS packet sequence.  Per SPEC-108 §7 it orchestrates the frozen upstream
components without ever duplicating their encodings (contract §2.3/§9):

1. validate the config (:func:`ts.generator.validator.validate_config`);
   any error-severity finding aborts before a single byte is produced
   (§7 step 1, §10 ``GENERATOR_*`` codes).
2. build PAT / PMT sections with the SPEC-103 builders (#31).
3. initialize the SPEC-105 media clock at ``initial_media_clock_27mhz``.
4. build one deterministic :class:`ts.generator.sources.SyntheticPESSource`
   per ES (#30 analysis-only PES profile).
5. frame tables and PES through SPEC-106 (#32) — PSI via
   ``SectionPacketizer``, PES lazily inside the mux's ``PESPacketSource``.
6. hand the packet sources, table repetition and PCR schedule to the
   SPEC-107 CBR mux (#33) — scheduling is never re-implemented here.
7. emit exactly ``output_packet_count`` packets; every sink write carries
   exactly 188 bytes (§7 step 8).
8. return the :class:`GenerationSummary` (§6); any protocol/scheduling
   failure raises :class:`ts.errors.GenerationError` instead of a
   pseudo-success summary (§7 step 9).

Fault-injection separation (§9, REQ-TS-108-006): this module contains zero
fault branches; the ADR-0007 semantic filter lives downstream of the
Generator→sink edge (faults package), and TSDuck stays behind the adapters
boundary (``ts``/``adapters.tsduck`` independence, lint contract).

Determinism (§8): the run consumes no wall clock, no ``hash()``, no
unseeded randomness; the mux slot lattice, the PES schedules and the payload
PRNG are pure integer functions of the config.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol

from ts.errors import GenerationError, TSCoreError
from ts.generator.codes import (
    GENERATOR_INTERNAL_COMPONENT_FAILED,
    GENERATOR_OUTPUT_WRITE_FAILED,
    GENERATOR_PACKET_SIZE_INVARIANT_FAILED,
)
from ts.generator.config import GeneratorConfig
from ts.generator.sources import SyntheticPESSource, synthetic_pes_byte_budget
from ts.generator.validator import validate_config
from ts.mux.config import MuxConfig, PIDRateConfig, PCRScheduleConfig, TableRepetitionConfig
from ts.mux.scheduler import TSMux
from ts.mux.sources import (
    PAT_SOURCE_ID,
    PMT_SOURCE_ID,
    PESPacketSource,
    TablePacketSource,
)
from ts.packet import TS_PACKET_SIZE
from ts.packetizer.section_packetizer import SectionPacketizer
from ts.cc import CCAllocator
from ts.tables.pat import PATBuilder, PATSection, PATProgram
from ts.tables.pmt import PMTBuilder, PMTSection, ElementaryStream as PMTElementaryStream

#: Version-pinned generator identity — part of the generation fingerprint
#: (SPEC-108 §8: "Generator implementation/version") and reported in every
#: :class:`GenerationSummary`.
GENERATOR_VERSION = "dvb-nexus-ts-generator/0.5.0 (SPEC-108)"

#: Prefix of the per-ES mux source ids (stable, collision-free against the
#: reserved ``"pat"``/``"pmt"`` table source ids).
ES_SOURCE_ID_PREFIX = "es:"


@dataclass(frozen=True)
class GenerationSummary:
    """Run digest (SPEC-108 §6, exact field set).

    ``pcr_packet_indices`` lists the slot indices of every PCR-carrying
    packet in emission order (payload-riding and adaptation-only alike).
    ``pid_packet_counts`` registers every emitted PID **including the null
    PID** as a transport statistic — the null PID is never a business ES
    (§9); the invariants ``sum(pid_packet_counts.values()) == packet_count``
    and ``pid_packet_counts[0x1FFF] == null_packet_count`` hold for every
    run and are pinned by the tests.  The summary makes no playback claim
    (§2/§9: ``analysis_only`` never asserts player-playable output).
    """

    packet_count: int
    byte_count: int
    target_bitrate_bps: int
    null_packet_count: int
    pcr_packet_indices: tuple[int, ...]
    pid_packet_counts: dict[int, int]
    generator_version: str


class OutputSink(Protocol):
    """Minimal write-protocol ``generate_to`` emits through (§6).

    A standard binary writer (``sys.stdout.buffer``, an open file, any
    object with a compatible ``write``); TS Core never touches artifact
    paths or databases — Artifact Storage wraps the sink and computes
    SHA-256 downstream of the Generator→sink edge.
    """

    def write(self, data: bytes) -> int | None:
        """Accept exactly one 188-byte packet per call (§7 step 8).

        Returns the number of bytes accepted (``None``-returning writers
        are tolerated; a short count raises ``GENERATOR_OUTPUT_WRITE_FAILED``).
        """


class TSGenerator:
    """Configuration-driven deterministic TS generator (SPEC-108 §6)."""

    def validate_config(self, config: GeneratorConfig) -> list:
        """Public §6 surface: the §5 findings for ``config`` (may be empty)."""
        return validate_config(config)

    def iter_packets(self, config: GeneratorConfig) -> Iterator:
        """Yield exactly ``output_packet_count`` finished TS packets (§6).

        Validation happens eagerly at call time (a rejected config raises
        :class:`ts.errors.GenerationError` before the iterator exists);
        each call builds a fresh run, so repeated calls on the same config
        are byte-identical (§8 determinism).
        """
        self._require_generatable(config)
        return self._iter_run(config)

    def generate_to(self, config: GeneratorConfig, sink: OutputSink) -> GenerationSummary:
        """Write the whole run through ``sink.write`` and return the digest.

        ``sink`` is the minimal :class:`OutputSink` ``write(bytes)`` protocol
        object (§6: a standard binary writer; TS Core never touches artifact
        paths or databases — Artifact Storage wraps it and computes SHA-256).
        Every call hands the sink exactly one 188-byte packet (§7 step 8); a
        failing or short write raises ``GENERATOR_OUTPUT_WRITE_FAILED``.
        """
        self._require_generatable(config)
        mux = self._build_run(config)
        pid_counts: dict[int, int] = {}
        packet_count = 0
        for packet in mux.iter_packets():
            data = packet.to_bytes()
            if len(data) != TS_PACKET_SIZE:  # internal invariant (§9)
                raise GenerationError(
                    f"{GENERATOR_PACKET_SIZE_INVARIANT_FAILED}: serialized "
                    f"packet is {len(data)} bytes, invariant requires "
                    f"exactly {TS_PACKET_SIZE} (pid {packet.pid:#06x}, "
                    f"output index {packet_count})"
                )
            try:
                written = sink.write(data)
            except TSCoreError:
                raise
            except Exception as exc:  # sink failures are generator failures
                raise GenerationError(
                    f"{GENERATOR_OUTPUT_WRITE_FAILED}: sink.write failed at "
                    f"output index {packet_count} (pid "
                    f"{packet.pid:#06x}): {type(exc).__name__}: {exc}"
                ) from exc
            if written is not None and written != TS_PACKET_SIZE:
                raise GenerationError(
                    f"{GENERATOR_OUTPUT_WRITE_FAILED}: sink.write accepted "
                    f"{written} of {TS_PACKET_SIZE} bytes at output index "
                    f"{packet_count} (pid {packet.pid:#06x}); partial "
                    "writes cannot produce a valid 188-byte stream"
                )
            packet_count += 1
            pid_counts[packet.pid] = pid_counts.get(packet.pid, 0) + 1

        mux_summary = mux.summary()
        if packet_count != config.output_packet_count:
            raise GenerationError(
                f"{GENERATOR_INTERNAL_COMPONENT_FAILED}: the run produced "
                f"{packet_count} packets but output_packet_count is "
                f"{config.output_packet_count} (the mux must emit exactly "
                "one packet per slot, SPEC-107 §3.2)"
            )
        null_count = pid_counts.get(0x1FFF, 0)
        if mux_summary.null_packet_count != null_count:
            raise GenerationError(
                f"{GENERATOR_INTERNAL_COMPONENT_FAILED}: mux null-packet "
                f"accounting ({mux_summary.null_packet_count}) disagrees "
                f"with the emitted stream ({null_count})"
            )
        return GenerationSummary(
            packet_count=packet_count,
            byte_count=packet_count * TS_PACKET_SIZE,
            target_bitrate_bps=config.target_bitrate_bps,
            null_packet_count=null_count,
            pcr_packet_indices=tuple(mux_summary.pcr_positions),
            pid_packet_counts={pid: pid_counts[pid] for pid in sorted(pid_counts)},
            generator_version=GENERATOR_VERSION,
        )

    # --- internals ---

    def _require_generatable(self, config: object) -> None:
        """Refuse invalid configs before any byte is produced (§7 step 1)."""
        if not isinstance(config, GeneratorConfig):
            raise TypeError(
                f"config must be GeneratorConfig, got {type(config).__name__}"
            )
        findings = validate_config(config)
        errors = [f for f in findings if f.severity == "error"]
        if errors:
            first = errors[0]
            raise GenerationError(f"{first.code}: {first.message}")

    def _build_run(self, config: GeneratorConfig) -> TSMux:
        """Wire the §7 pipeline: tables + PES sources + CBR mux (steps 2-6).

        Any upstream component failure is re-raised as
        ``GENERATOR_INTERNAL_COMPONENT_FAILED`` chained from the original
        error (§7 step 9: the Generator owns the run, so component failures
        surface as GenerationError — never silently swallowed, never a
        pseudo-success).
        """
        try:
            program = config.program
            pat_section = PATBuilder().build(
                PATSection(
                    transport_stream_id=program.transport_stream_id,
                    version_number=program.version_number,
                    current_next_indicator=True,
                    section_number=0,
                    last_section_number=0,
                    programs=(
                        PATProgram(
                            program_number=program.program_number,
                            program_map_pid=program.pmt_pid,
                        ),
                    ),
                )
            )
            pmt_section = PMTBuilder().build(
                PMTSection(
                    program_number=program.program_number,
                    version_number=program.version_number,
                    current_next_indicator=True,
                    section_number=0,
                    last_section_number=0,
                    pcr_pid=program.pcr_pid,
                    program_descriptors=bytes(program.program_descriptors),
                    streams=tuple(
                        PMTElementaryStream(
                            stream_type=stream.stream_type,
                            elementary_pid=stream.pid,
                            descriptors=b"",
                        )
                        for stream in program.streams
                    ),
                )
            )
            pat_packets = list(
                SectionPacketizer(0x0000, CCAllocator()).packetize(pat_section)
            )
            pmt_packets = list(
                SectionPacketizer(program.pmt_pid, CCAllocator()).packetize(
                    pmt_section
                )
            )
            sources = [
                TablePacketSource(PAT_SOURCE_ID, pat_packets),
                TablePacketSource(PMT_SOURCE_ID, pmt_packets),
            ]
            pid_rates = []
            for stream in program.streams:
                source_id = f"{ES_SOURCE_ID_PREFIX}{stream.pid:04x}"
                pes_source = SyntheticPESSource(
                    stream_config=stream,
                    seed=config.seed,
                    initial_media_clock_27mhz=config.initial_media_clock_27mhz,
                    byte_budget=synthetic_pes_byte_budget(
                        config.output_packet_count,
                        config.target_bitrate_bps,
                        stream.bitrate_bps,
                    ),
                )
                sources.append(
                    PESPacketSource(source_id, stream.pid, pes_source.iter_pes())
                )
                pid_rates.append(
                    PIDRateConfig(
                        pid=stream.pid,
                        bitrate_bps=stream.bitrate_bps,
                        source_id=source_id,
                    )
                )
            mux_config = MuxConfig(
                target_bitrate_bps=config.target_bitrate_bps,
                output_packet_count=config.output_packet_count,
                pid_rates=tuple(pid_rates),
                tables=TableRepetitionConfig(
                    pat_period_ms=config.pat_period_ms,
                    pmt_period_ms=config.pmt_period_ms,
                ),
                pcr=PCRScheduleConfig(
                    pcr_pid=program.pcr_pid,
                    target_interval_ms=config.pcr_interval_ms,
                    insertion_policy=config.pcr_insertion_policy,
                ),
                initial_media_clock_27mhz=config.initial_media_clock_27mhz,
            )
            return TSMux(mux_config, sources)
        except TSCoreError as exc:
            raise GenerationError(
                f"{GENERATOR_INTERNAL_COMPONENT_FAILED}: an orchestrated "
                "component refused the generation run — the original "
                f"component error is chained ({type(exc).__name__}: {exc})"
            ) from exc

    def _iter_run(self, config: GeneratorConfig) -> Iterator:
        """Fresh-run packet iterator backing :meth:`iter_packets`."""
        mux = self._build_run(config)
        return iter(mux.iter_packets())
