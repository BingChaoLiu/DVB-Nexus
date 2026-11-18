"""The analysis-bridge service — artifact bytes → ``ts.*`` observation
events (ticket #58, 裁定 A; the 裁定 B in-process Analyze anchor).

Orchestration half of the minimal analysis bridge: one run artifact's
bytes are parsed by the pure :mod:`application.analysis.parser` (the
four fault-signal families) and every fact is normalized into a
SPEC-301-conformant ``ts.*`` observation envelope published through the
SPEC-300 §12 producer face (production binding: the #47 gateway). The
gateway stamps ``journal_seq`` at durable append; producers never fill
it — these documents go straight into ``EventGateway.publish``.

Producer identity and provenance axes (the registry enforces both axes
on the ``ts.*`` family — #13 Q3-i):

- ``producer_id = "internal-parser-analysis"`` — the application-layer
  in-process bridge, distinct from the simulation emitter and the
  (future) TSDuck analysis path;
- ``payload.source = "internal_parser"`` (the five-value
  ``ObservationSource`` vocabulary) — the parsing operation IS a real
  parse of real produced bytes (the SIM_TS artifact), never a fixture
  replay;
- ``payload.confidence = "parsed"`` (the four-value ``ConfidenceKind``
  axis) — facts derived by parsing, not measured on hardware and not
  simulated (the axis discipline: the SIM_STATE product itself is
  ``simulated`` at the generator; the parse of that product is
  ``parsed``).

Payload key contract (the diagnosis-side fixture contract registered in
``tests/_support/diagnosis_fixtures.py``; the SPEC-307 builtin rules and
the SPEC-206 observation criteria both consume these keys):

- every record carries ``artifact_id`` / ``pid`` / ``packet_index``
  (the SPEC-306 §6 evidence triple; ADR-0007 item 4 — baseline and
  faulted artifacts share the packet-order frame, so the packet_index
  addresses the same slot in either);
- PAT records: ``section="PAT"`` + ``present`` + the parsed
  ``actual_program_map_pid`` declaration (single-program MVP);
  contradicting records (declaration ≠ the config-declared PMT PID)
  additionally carry ``expected_program_map_pid`` — the pair appears
  ONLY on contradiction, so the DIA-PMT-PID-MISMATCH rule cannot
  false-fire on clean streams;
- PMT records: ``section="PMT"`` + ``present`` + ``crc_valid``;
- continuity records: ``expected_cc`` / ``actual_cc`` / ``delta``;
- the batch record: ``packet_count`` / ``byte_count`` / ``duration_ns``
  / ``null_packet_count`` / ``continuity_error_count`` (the #50 metrics
  catalog contract + the SPEC-206 cc-coverage fact).
"""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol

from domain.observation import new_event_id, parse_envelope
from ts.generator.config import GeneratorConfig

from application.analysis.parser import (
    BatchFact,
    ContinuityErrorFact,
    PatMissingFact,
    PatSectionFact,
    PmtSectionFact,
    analyze_transport_stream,
    slot_duration_ns,
)

__all__ = [
    "CONFIDENCE",
    "PRODUCER_ID",
    "PRODUCER_VERSION",
    "SOURCE",
    "AnalysisReport",
    "AnalysisService",
]

#: The application-layer bridge's producer identity.
PRODUCER_ID = "internal-parser-analysis"
PRODUCER_VERSION = "0.1.0"

#: The provenance axes (registry-enforced on the ``ts.*`` family).
SOURCE = "internal_parser"
CONFIDENCE = "parsed"

#: Wall-clock injection (SPEC-201 discipline) — the observed axis only.
NowWallNs = Callable[[], int]


class Publisher(Protocol):
    """SPEC-300 §12 producer face (structural; production: the gateway)."""

    def publish(self, event: Any) -> Any: ...


class ArtifactReader(Protocol):
    """The #42 read boundary (structural; production: ArtifactStore)."""

    def read_by_artifact(self, artifact_id: str) -> bytes: ...


@dataclass(frozen=True)
class AnalysisReport:
    """What one analysis published (the caller's receipt)."""

    session_id: str
    run_id: str
    artifact_id: str
    packet_count: int
    event_counts: Mapping[str, int]


class AnalysisService:
    """In-process Analyze step: run artifact → observation events."""

    def __init__(
        self,
        publisher: Publisher,
        *,
        store: ArtifactReader,
        now_wall_ns: NowWallNs | None = None,
    ) -> None:
        self._publisher = publisher
        self._store = store
        self._now_wall_ns: NowWallNs = now_wall_ns or (
            lambda: time.time_ns()
        )

    def analyze_artifact(
        self,
        *,
        session_id: str,
        run_id: str,
        artifact_id: str,
        config: GeneratorConfig,
        node_id: str | None = None,
    ) -> AnalysisReport:
        """Analyze one artifact and publish its ``ts.*`` facts.

        The caller picks the artifact (the run's ``faulted_ts`` leg for
        symptom analysis, its ``generated_ts`` leg for clean coverage)
        and supplies the config the run ran with (the PSI-periodicity
        expectation source). Publishing is acceptance-into-gateway only;
        the caller drives the deterministic ``drain`` (the #53 driver
        discipline — the bridge starts no threads).
        """
        ts_bytes = self._store.read_by_artifact(artifact_id)
        facts = analyze_transport_stream(ts_bytes, config)
        slot_ns = slot_duration_ns(config)
        counts: Counter[str] = Counter()
        for fact in facts:
            document = self._envelope_for(
                fact,
                session_id=session_id,
                run_id=run_id,
                artifact_id=artifact_id,
                config=config,
                node_id=node_id,
                slot_ns=slot_ns,
            )
            self._publisher.publish(document)
            counts[document["event_type"]] += 1
        batch = next(f for f in facts if isinstance(f, BatchFact))
        return AnalysisReport(
            session_id=session_id,
            run_id=run_id,
            artifact_id=artifact_id,
            packet_count=batch.packet_count,
            event_counts=dict(counts),
        )

    # --- fact → envelope normalization -----------------------------------

    def _envelope_for(
        self,
        fact: Any,
        *,
        session_id: str,
        run_id: str,
        artifact_id: str,
        config: GeneratorConfig,
        node_id: str | None,
        slot_ns: int,
    ) -> dict[str, Any]:
        payload, correlation_pid, packet_index = self._payload_for(
            fact,
            artifact_id=artifact_id,
            config=config,
        )
        document = {
            "schema_version": "1.0",
            "event_id": new_event_id(),
            "event_type": self._event_type_of(fact),
            "producer": {
                "producer_id": PRODUCER_ID,
                "producer_version": PRODUCER_VERSION,
                "instance_id": "in-process",
            },
            "scope": {
                "tenant_id": "local",
                "session_id": session_id,
                "run_id": run_id,
            },
            "time": {
                "source": {
                    "value_ns": slot_ns * packet_index,
                    "clock_domain": f"sim:{session_id}",
                    "clock_epoch": 0,
                },
                "observed": {
                    "value_ns": self._now_wall_ns(),
                    "clock_domain": "wall:utc",
                    "clock_epoch": 0,
                },
            },
            "correlation": {
                "trace_id": None,
                "span_id": None,
                "parent_event_id": None,
                "fault_id": None,
                "node_id": node_id,
                "port_id": None,
                "service_id": None,
                "pid": correlation_pid,
            },
            "severity": "info",
            "payload": payload,
            "tags": [],
        }
        # Construction guarantee: a non-conformant analysis event can
        # never reach the gateway (parse_envelope validates the full
        # contract, registry payload schemas included).
        return parse_envelope(document).model_dump(mode="json")

    def _payload_for(
        self,
        fact: Any,
        *,
        artifact_id: str,
        config: GeneratorConfig,
    ) -> tuple[dict[str, Any], int | None, int]:
        """(payload, correlation pid, anchor packet index) per fact."""
        if isinstance(fact, PatSectionFact):
            packet_index = fact.packet_index
            payload = self._psi_payload(
                section="PAT",
                present=True,
                packet_index=packet_index,
                artifact_id=artifact_id,
                gap_ms=fact.gap_ms,
            )
            payload["pid"] = 0
            # The mapping-declaration facts (single-program MVP): the
            # parsed declaration always rides the record; the declared
            # expectation rides ONLY a contradiction (see docstring).
            if len(fact.program_map_pids) == 1:
                actual = fact.program_map_pids[0]
                payload["actual_program_map_pid"] = actual
                if actual != config.program.pmt_pid:
                    payload["expected_program_map_pid"] = (
                        config.program.pmt_pid
                    )
            return payload, 0, packet_index
        if isinstance(fact, PmtSectionFact):
            packet_index = fact.packet_index
            payload = self._psi_payload(
                section="PMT",
                present=True,
                packet_index=packet_index,
                artifact_id=artifact_id,
                gap_ms=fact.gap_ms,
            )
            payload["crc_valid"] = fact.crc_valid
            payload["pid"] = config.program.pmt_pid
            # The parsed version face always rides the record (mirroring the
            # PAT declaration face above); the seeded expectation rides ONLY
            # a contradiction — the DIA-PMT-PID-DRIFT rule's version
            # predicates fire on symptoms, never on clean streams (#139).
            if fact.version_number is not None:
                payload["pmt_version"] = fact.version_number
                if fact.version_number != config.program.version_number:
                    payload["expected_pmt_version"] = (
                        config.program.version_number
                    )
            return payload, config.program.pmt_pid, packet_index
        if isinstance(fact, PatMissingFact):
            packet_index = fact.packet_index
            payload = self._psi_payload(
                section="PAT",
                present=False,
                packet_index=packet_index,
                artifact_id=artifact_id,
                gap_ms=None,
            )
            payload["pid"] = 0
            return payload, 0, packet_index
        if isinstance(fact, ContinuityErrorFact):
            packet_index = fact.packet_index
            payload = {
                "source": SOURCE,
                "confidence": CONFIDENCE,
                "pid": fact.pid,
                "artifact_id": artifact_id,
                "packet_index": packet_index,
                "expected_cc": fact.expected_cc,
                "actual_cc": fact.actual_cc,
                "delta": (fact.actual_cc - fact.expected_cc) & 0x0F,
            }
            return payload, fact.pid, packet_index
        if isinstance(fact, BatchFact):
            payload = {
                "source": SOURCE,
                "confidence": CONFIDENCE,
                "artifact_id": artifact_id,
                "packet_index": 0,
                "packet_count": fact.packet_count,
                "byte_count": fact.byte_count,
                "duration_ns": fact.duration_ns,
                "null_packet_count": fact.null_packet_count,
                "continuity_error_count": fact.continuity_error_count,
            }
            return payload, None, 0
        raise TypeError(f"unknown analysis fact: {type(fact).__name__}")

    @staticmethod
    def _psi_payload(
        *,
        section: str,
        present: bool,
        packet_index: int,
        artifact_id: str,
        gap_ms: int | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "source": SOURCE,
            "confidence": CONFIDENCE,
            "artifact_id": artifact_id,
            "packet_index": packet_index,
            "section": section,
            "present": present,
        }
        if gap_ms is not None:
            payload["gap_ms"] = gap_ms
        return payload

    @staticmethod
    def _event_type_of(fact: Any) -> str:
        if isinstance(fact, (PatSectionFact, PmtSectionFact, PatMissingFact)):
            return "ts.psi_section_observed"
        if isinstance(fact, ContinuityErrorFact):
            return "ts.continuity_error"
        if isinstance(fact, BatchFact):
            return "ts.packet_batch_observed"
        raise TypeError(f"unknown analysis fact: {type(fact).__name__}")
