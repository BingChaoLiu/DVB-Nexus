"""``SqliteTopologyRepository`` — SPEC-502 §4/§5 topologies-table storage
(ticket #80, REQ-API-500-001).

Integration layer: real tmp-file SQLite through the ``journal`` fixture.
The ``topologies`` table is a SPEC-502 §4 frozen table that has existed in
migration 0001 since the M3 slice — this repository is the first reader,
so the row encoding contract is pinned here at RAW-SQL level:

- ``(topology_id, revision)`` composite PK — one row per revision,
  immutable append (PUT never updates an existing row, it adds the next);
- ``spec_json`` = the SPEC-003 §2.1 configuration model verbatim (the
  wire payload the REST face stored — the repository is schema-agnostic);
- ``created_at_utc`` / ``updated_at_utc`` = ISO-8601 TEXT (R6). Rows are
  immutable, so both stamps are row-creation facts; ``updated_at_utc``
  mirrors ``created_at_utc`` per row (the column pair is the SPEC-502 §4
  letter, not an update signal).
"""

import json

import pytest

from adapters.storage.db import connect
from adapters.storage.errors import StorageConflictError
from adapters.storage.topologies import TopologyRow, SqliteTopologyRepository


def _spec_json(topology_id: str = "topo-x") -> str:
    """A SPEC-003 §2.1-shaped spec payload (opaque TEXT to the store)."""
    return json.dumps(
        {
            "nodes": [
                {
                    "node_id": "mux-0",
                    "node_type": "muxer",
                    "config": {},
                    "ports": [
                        {
                            "port_id": "out",
                            "direction": "output",
                            "plane": "MPEG_TS",
                            "max_connections": 1,
                        }
                    ],
                }
            ],
            "connections": [],
            "_topology_id": topology_id,
        }
    )


@pytest.fixture
def repository(journal):
    connection = connect(journal.db_path)
    return SqliteTopologyRepository(connection), connection


class TestSaveAndGet:
    def test_save_then_get_latest_round_trip(self, repository):
        repo, _ = repository
        repo.save("topo-x", 1, _spec_json())
        row = repo.get("topo-x")
        assert row == TopologyRow(
            topology_id="topo-x",
            revision=1,
            spec_json=_spec_json(),
            created_at_utc=row.created_at_utc,
            updated_at_utc=row.updated_at_utc,
        )
        assert row.spec_json == _spec_json()

    def test_get_explicit_revision(self, repository):
        repo, _ = repository
        repo.save("topo-x", 1, _spec_json())
        repo.save("topo-x", 2, _spec_json("topo-x-r2"))
        row = repo.get("topo-x", 1)
        assert row is not None
        assert row.revision == 1
        assert row.spec_json == _spec_json()

    def test_get_latest_is_max_revision(self, repository):
        repo, _ = repository
        repo.save("topo-x", 1, _spec_json())
        repo.save("topo-x", 2, _spec_json("r2"))
        row = repo.get("topo-x")
        assert row.revision == 2

    def test_unknown_topology_returns_none(self, repository):
        repo, _ = repository
        assert repo.get("no-such-topology") is None

    def test_unknown_revision_returns_none(self, repository):
        repo, _ = repository
        repo.save("topo-x", 1, _spec_json())
        assert repo.get("topo-x", 9) is None

    def test_duplicate_composite_key_conflicts(self, repository):
        """SPEC-502 §4: the composite uniqueness is the primary key — a
        repeat save of the same (topology_id, revision) is the 409 family
        (StorageConflictError), never a silent overwrite (immutable rows)."""
        repo, _ = repository
        repo.save("topo-x", 1, _spec_json())
        with pytest.raises(StorageConflictError):
            repo.save("topo-x", 1, _spec_json())


class TestListLatest:
    def test_latest_revision_row_per_topology_id(self, repository):
        repo, _ = repository
        repo.save("topo-b", 1, _spec_json("b1"))
        repo.save("topo-a", 1, _spec_json("a1"))
        repo.save("topo-b", 2, _spec_json("b2"))
        rows = repo.list_latest()
        assert [(row.topology_id, row.revision) for row in rows] == [
            ("topo-a", 1),
            ("topo-b", 2),
        ]

    def test_empty_table_lists_empty(self, repository):
        repo, _ = repository
        assert repo.list_latest() == []


class TestRawRowEncoding:
    def test_r6_timestamps_are_iso8601_text_and_row_immutable(self, repository):
        """R6: *_utc = ISO-8601 TEXT; a saved row never changes — the
        store exposes no update/delete path at all."""
        repo, connection = repository
        repo.save("topo-x", 1, _spec_json())
        raw = connection.execute(
            "SELECT spec_json, created_at_utc, updated_at_utc FROM topologies"
            " WHERE topology_id = 'topo-x'"
        ).fetchone()
        assert json.loads(raw["spec_json"]) == json.loads(_spec_json())
        assert isinstance(raw["created_at_utc"], str)
        assert "T" in raw["created_at_utc"]
        assert raw["updated_at_utc"] == raw["created_at_utc"]
