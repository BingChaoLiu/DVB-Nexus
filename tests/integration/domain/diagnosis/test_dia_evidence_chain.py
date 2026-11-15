"""Evidence chain end-to-end (ticket #54, REQ-DIA-306-003).

The SPEC-306 §6 obligation: every diagnosis anchors at least one evidence
ref and the chain is resolvable END TO END over the real stack —

    diagnosis → event (journal_seq) → payload (pid / packet_index)
              → artifact_id → SPEC-503 physical bytes

The test walks each hop: the ``diagnosis.raised`` envelope is read back
from the real SQLite journal, its ``observation_refs`` journal_seq points
at the committed observation record whose payload carries the
pid/packet_index pair, and the evidence ``artifact_id`` resolves through
the SPEC-502 artifacts row to the content-addressed store file whose
bytes hash back to the registered SHA-256 (packet_index semantics =
ADR-0007 item 4: baseline and faulted share one packet-order frame, so
the index names the SAME slot on both streams).
"""

import pytest

from adapters.storage.artifact_store import ArtifactStore
from adapters.storage.db import connect
from adapters.storage.journal import SqliteEventJournal
from adapters.storage.repositories import SqliteArtifactRepository, SqliteDiagnosisRepository
from application.diagnosis import DiagnosisService
from application.observation.gateway import EventGateway
from adapters.storage.artifact_errors import ArtifactNotFoundError

from tests._support.artifact_paths import compute_sha256
from tests._support.deterministic import seeded_ts_stream
from tests._support.diagnosis_fixtures import (
    NODE_ID,
    PSI_PID,
    RUN_ID,
    SESSION_ID,
    builtin_fixture_rules,
    observation_envelope,
    observation_record,
)

NOW_MS = 1_700_000_000_000


@pytest.fixture
def chain_stack(journal, artifact_store):
    connection = connect(journal.db_path, check_same_thread=False)
    journal_adapter = SqliteEventJournal(connection)
    repository = SqliteArtifactRepository(connection)
    store = ArtifactStore(artifact_store.root, index=repository)
    gateway = EventGateway(journal_adapter)
    service = DiagnosisService(
        journal_adapter,
        gateway,
        SqliteDiagnosisRepository(connection),
        now_utc_ms=lambda: NOW_MS,
    )
    return {
        "connection": connection,
        "journal": journal_adapter,
        "store": store,
        "repository": repository,
        "gateway": gateway,
        "service": service,
    }


def _store_faulted_artifact(stack, *, packet_count: int) -> tuple[str, bytes, str]:
    """Store a faulted-stream artifact via the #42 face; return its id,
    bytes and sha256."""
    payload_bytes = seeded_ts_stream(7, packet_count)
    sink = stack["store"].open_sink("ts")
    sink.write(payload_bytes)
    committed = sink.commit()
    artifact_id = stack["store"].register(
        committed,
        run_id=RUN_ID,
        session_id=SESSION_ID,
        kind="faulted_ts",
        packet_size=188,
        packet_count=packet_count,
    )
    return artifact_id, payload_bytes, committed.sha256


def _publish_observation(stack, *, artifact_id: str, packet_index: int):
    payload = {
        "source": "internal_parser",
        "confidence": "parsed",
        "pid": PSI_PID,
        "section": "PAT",
        "present": False,
        "artifact_id": artifact_id,
        "packet_index": packet_index,
    }
    assert stack["gateway"].publish(
        observation_envelope(
            event_type="ts.psi_section_observed",
            payload=payload,
            session_id=SESSION_ID,
            run_id=RUN_ID,
            pid=PSI_PID,
            node_id=NODE_ID,
            source_ns=5_000,
        )
    ).accepted
    stack["gateway"].drain()


class TestEvidenceChain:
    def test_diagnosis_to_artifact_resolves_end_to_end(self, chain_stack):
        stack = chain_stack
        packet_count = 20_000
        artifact_id, artifact_bytes, sha256 = _store_faulted_artifact(
            stack, packet_count=packet_count
        )
        # The PAT window anchor sits INSIDE the artifact's packet space
        # (ADR-0007 item 4: one shared packet-order frame — the index
        # names the same slot on baseline and faulted).
        packet_index = 12_000
        _publish_observation(
            stack, artifact_id=artifact_id, packet_index=packet_index
        )

        report = stack["service"].evaluate(
            SESSION_ID, RUN_ID, rules=builtin_fixture_rules()
        )
        stack["gateway"].drain()

        assert len(report.candidates) == 1
        candidate = report.candidates[0]

        # Hop 1: the diagnosis exists as a committed journal event.
        events = stack["journal"].query(SESSION_ID, limit=100)
        raised = [e for e in events if e.event_type == "diagnosis.raised"]
        assert len(raised) == 1
        raised_envelope = raised[0].envelope
        assert raised_envelope["payload"]["diagnosis_id"] == candidate.diagnosis_id

        # Hop 2: observation_refs → the committed observation record
        # (journal_seq is the per-session total order).
        refs = raised_envelope["payload"]["observation_refs"]
        assert len(refs) == 1
        observation_seq = refs[0]["journal_seq"]
        observation = [e for e in events if e.journal_seq == observation_seq]
        assert len(observation) == 1
        assert observation[0].event_type == "ts.psi_section_observed"

        # Hop 3: the observation payload carries the pid/packet_index pair.
        observation_payload = observation[0].envelope["payload"]
        assert observation_payload["pid"] == PSI_PID
        assert observation_payload["packet_index"] == packet_index
        assert packet_index < packet_count  # inside the artifact's frame

        # Hop 4: evidence artifact_id → SPEC-503 physical bytes.
        evidence = raised_envelope["payload"]["evidence"]
        assert evidence["artifact_id"] == artifact_id
        assert evidence["pid"] == PSI_PID
        assert evidence["packet_index"] == packet_index
        resolved = stack["store"].read_by_artifact(artifact_id)
        assert resolved == artifact_bytes
        assert compute_sha256(resolved) == sha256

        # The SPEC-502 artifacts row resolves the run/session ownership.
        row = stack["repository"].get(artifact_id)
        assert row is not None
        assert row.run_id == RUN_ID
        assert row.session_id == SESSION_ID
        assert row.kind == "faulted_ts"

    def test_unknown_artifact_id_is_a_resolver_error(self, chain_stack):
        with pytest.raises(ArtifactNotFoundError):
            chain_stack["store"].read_by_artifact("not-a-real-artifact")
