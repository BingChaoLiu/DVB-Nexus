"""CBR end-to-end integration fixtures — ticket #35 (TASK-TS-INT).

Seams (contract §12 集成完成条件, ticket #35 acceptance):

1. **Generation**: ``ts.generator.generator.TSGenerator.generate_to`` — the
   #34-proven pull-safe geometry (slot = 13,500 ticks = exactly 0.5 ms at
   B = 3,008,000; PAT @ 0/202/404; PMT @ 1/206/412; PCR @ 80k step 80;
   ES pulls every 25/50 slots; one PES item every 3 ES packets).
2. **Independent self-parse** (the "独立自研 parser" of contract §12):
   strict ``TSPacket.from_bytes`` → ``SectionAssembler`` + ``parse_pat`` /
   ``parse_pmt`` → ``PESAssembler`` → ``packet.adaptation_field.pcr`` →
   per-PID continuity walk (duplicate-aware).
3. **TSDuck cross validation**: real ``tsanalyze --json`` subprocess driven
   by ``tests/_support/ts_e2e.py``. Ticket #3 discipline: exit 0 is not
   trusted — the JSON content gates (``ts.bytes > 0``,
   ``ts.services.total >= 1``) are asserted before any field comparison.

Independent truth (anti-tautology discipline): every expected value below is
either (a) a hand-expanded literal of the frozen SPEC-107 §3.1 integer
arithmetic (never recomputed through ts-core inside the assertion), or (b) a
frozen literal cross-observed from the TSDuck run recorded in
``.scratch/m1/task-35/DIFFERENCE-REPORT.md``. No assertion recomputes an
expectation by calling ts-core.

Layer discipline (SPEC-505 §8): this directory is the integration layer —
real subprocesses, real TSDuck, real tmp files. ``tsduck``/``windows_only``
markers per tests/README.md §6: shape assertions only, environment literals
(TSDuck version strings, install paths) are never pinned.
"""

from __future__ import annotations

import pytest

from tests._support import ts_e2e

pytestmark = pytest.mark.integration

# --- hand-expanded literals of the pull-safe geometry (SPEC-107 §3.1) --------
# B = 3,008,000 -> slot = 40,608,000,000 // 3,008,000 = 13,500 ticks (0.5 ms).
# PAT period 101 ms = 202 slots -> slots 0/202/404 (3 repetitions in 600 slots).
# PMT period 103 ms = 206 slots -> slots 1/206/412 (3 repetitions).
# PCR interval 40 ms = 80 slots -> slots 80k, k=0..6 (7 carriers; the slot-400
# carrier rides the ES1 PES-start packet per payload_packet_first).
# ES1 (B/25): packet k due at (k+1)*25 slots -> 23 pulls in slots 25..575;
#   one PES item per 3 packets -> 8 items started, item 7 truncated at EOF
#   (packet 23 due at slot 600 >= run end).
# ES2 (B/50): packet k due at (k+1)*50 slots -> 11 pulls in slots 50..550;
#   4 items started, item 3 truncated at EOF.
# PTS schedule (90 kHz): item k PTS = k * ticks_per_item // 300 where
#   ticks_per_item = 526 * 8 * 27e6 // R (526 = serialized item bytes).
#   ES1: ticks_per_item = 944,281 -> complete items 0..6:
#   0, 3147, 6295, 9442, 12590, 15738, 18885 (started item 7 -> 22,033).
#   ES2: ticks_per_item = 1,888,563 -> complete items 0..2:
#   0, 6295, 12590 (started item 3 -> 18,885).
ES1_COMPLETE_PTS = (0, 3147, 6295, 9442, 12590, 15738, 18885)
ES1_STARTED_TAIL_PTS = 22033
ES2_COMPLETE_PTS = (0, 6295, 12590)
ES2_STARTED_TAIL_PTS = 18885
PCR_CARRIERS = (
    (80, 1_080_000),
    (160, 2_160_000),
    (240, 3_240_000),
    (320, 4_320_000),
    (400, 5_400_000),
    (480, 6_480_000),
    (560, 7_560_000),
)


def test_cbr_chain_self_parse_full_chain():
    """Generate -> strict packet parse -> PAT/PMT/PES/PCR/CC full readback.

    Contract §12: the self parser must re-derive every protocol fact from
    the emitted bytes alone. Expected values are the hand-expanded literals
    above (independent truth), never ts-core recomputation.
    """
    chunks, summary = ts_e2e.generate_chunks(ts_e2e.integration_config())

    # Artifact invariants (§9 of SPEC-108): exact count, 188-byte frames.
    assert len(chunks) == 600
    assert all(len(chunk) == 188 for chunk in chunks)
    assert summary.packet_count == 600
    assert summary.byte_count == 112_800

    # Per-PID transport statistics, hand-derived:
    # PAT 3 + PMT 3 + ES1 29 + ES2 11 = 46 business packets,
    # null fill 554 -> total 600. ES1 = 23 ES pulls + 6 PCR-only carriers
    # (slot 400 rides payload, counted once); ES2 = 11 pulls.
    assert summary.pid_packet_counts == {
        0: 3,
        256: 29,
        257: 11,
        4096: 3,
        8191: 554,
    }
    assert summary.null_packet_count == 554

    evidence = ts_e2e.self_parse_evidence(chunks)

    # --- PAT (PID 0x0000): one program -> PMT PID 4096, 3 repetitions ---
    assert evidence.pat_section_count == 3
    first_pat = evidence.pat_sections[0]
    assert first_pat.transport_stream_id == 1
    assert [
        (program.program_number, program.program_map_pid)
        for program in first_pat.programs
    ] == [(1, 4096)]
    # All repetitions carry the same version and content (frozen config).
    assert all(section.version_number == 0 for section in evidence.pat_sections)

    # --- PMT (PID 4096): PCR PID 256, ES declarations verbatim ---
    assert evidence.pmt_section_count == 3
    first_pmt = evidence.pmt_sections[0]
    assert first_pmt.program_number == 1
    assert first_pmt.pcr_pid == 256
    assert [
        (stream.stream_type, stream.elementary_pid)
        for stream in first_pmt.streams
    ] == [(27, 256), (3, 257)]

    # --- PES (PIDs 256/257): starts, completes, tail-truncation evidence ---
    es1 = evidence.pes_by_pid[256]
    es2 = evidence.pes_by_pid[257]
    assert es1.starts == 8
    assert es2.starts == 4
    # Reassembled completes: items 0..6 (ES1) / 0..2 (ES2); the last item of
    # each ES is truncated at EOF and reported as evidence, never fabricated.
    assert [packet.header.pts for packet in es1.complete] == list(ES1_COMPLETE_PTS)
    assert [packet.header.pts for packet in es2.complete] == list(ES2_COMPLETE_PTS)
    assert [packet.header.stream_id for packet in es1.complete] == [0xE0] * 7
    assert [packet.header.stream_id for packet in es2.complete] == [0xC0] * 3
    assert es1.tail_issue_codes == ("PES_TRUNCATED_AT_EOF",)
    assert es2.tail_issue_codes == ("PES_TRUNCATED_AT_EOF",)

    # --- PCR (PID 256): 7 carriers at the hand-derived slots and values ---
    assert evidence.pcr_carriers == PCR_CARRIERS

    # --- CC walk (duplicate-aware; null PID skipped, ISO CC undefined) ---
    cc = evidence.cc_by_pid
    # ES PIDs: strict continuity, no duplicates.
    assert cc[256].duplicates == 0
    assert cc[256].discontinuities == 0
    assert cc[256].packet_count == 29
    assert cc[257].duplicates == 0
    assert cc[257].discontinuities == 0
    assert cc[257].packet_count == 11
    # PSI PIDs: the mux re-emits the SAME packetized table run per repetition
    # (contract §9 / SPEC-107), so repetitions carry an unchanged CC and read
    # as duplicate packets on the wire. 3 repetitions -> 2 duplicates.
    # Recorded as interface issue PI-1 / difference report D1; asserted here
    # so the wire shape stays visible until the orchestrator rules on it.
    assert cc[0].packet_count == 3
    assert cc[0].duplicates == 2
    assert cc[0].discontinuities == 0
    assert cc[4096].packet_count == 3
    assert cc[4096].duplicates == 2
    assert cc[4096].discontinuities == 0


def _pid_entry(document: dict, pid: int) -> dict:
    """Fetch one PID entry from the tsanalyze JSON (KeyError = loud failure)."""
    matches = [entry for entry in document["pids"] if entry["id"] == pid]
    assert len(matches) == 1, f"PID {pid} appears {len(matches)} times"
    return matches[0]


def test_cbr_chain_tsduck_cross_validation(tsduck, tmp_path):
    """Same artifact, independent analyzer: field-level JSON cross validation.

    Contract §12: "TS 输出经独立自研 parser 和 TSDuck 分析，比较字段有明确
    映射". Every asserted value is a hand-derived literal of the frozen
    geometry or a shape assertion (never an environment literal — the
    TSDuck version/install path differ per machine, tests/README §6).
    The full mapping table lives in
    ``.scratch/m1/task-35/DIFFERENCE-REPORT.md``.
    """
    ts_file = tmp_path / "cbr_e2e.ts"
    chunks, summary = ts_e2e.generate_chunks(ts_e2e.integration_config())
    ts_file.write_bytes(b"".join(chunks))

    run = ts_e2e.run_tsanalyze(tsduck, ts_file)

    # --- ticket #3 discipline: JSON content gates first, exit code never ---
    assert run.content_gates == {
        "ts_bytes_positive": True,
        "services_total_at_least_one": True,
        "packets_total_positive": True,
    }
    assert run.content_valid is True
    document = run.json_document
    assert isinstance(document, dict)

    # --- TS level (ts-core: summary / config) ---
    ts_section = document["ts"]
    assert ts_section["bytes"] == 112_800 == summary.byte_count
    assert ts_section["packets"]["total"] == 600 == summary.packet_count
    assert ts_section["packets"]["invalid-syncs"] == 0
    assert ts_section["packets"]["transport-errors"] == 0
    assert ts_section["packets"]["suspect-ignored"] == 0
    assert ts_section["id"] == 1  # transport_stream_id
    # TSDuck derives the bitrate from the PCR pair: slot lattice is exact
    # (13,500 ticks), so the measured value equals the configured target.
    assert ts_section["bitrate"] == 3_008_000
    assert ts_section["pcr-bitrate"] == 3_008_000
    assert ts_section["services"]["total"] == 1
    assert ts_section["pids"]["total"] == 5
    assert ts_section["pids"]["unreferenced"] == 0

    # --- service level (ts-core: PAT/PMT join) ---
    services = document["services"]
    assert len(services) == 1
    service = services[0]
    assert service["id"] == 1  # program_number
    assert service["tsid"] == 1
    assert service["pmt-pid"] == 4096
    assert service["pcr-pid"] == 256
    assert sorted(service["pids"]) == [256, 257, 4096]

    # --- PID level (ts-core: summary.pid_packet_counts) ---
    assert {entry["id"] for entry in document["pids"]} == {0, 256, 257, 4096, 8191}
    for pid, count in summary.pid_packet_counts.items():
        assert _pid_entry(document, pid)["packets"]["total"] == count

    # --- ES PID 256: PES/PTS/PCR counters vs the hand-derived schedule ---
    video = _pid_entry(document, 256)
    assert video["pes"] == 8  # PES starts seen on the wire
    assert video["pes-stream-id"] == 224
    assert video["video"] is True and video["audio"] is False
    assert video["packets"]["pcr"] == 7 == len(summary.pcr_packet_indices)
    assert video["packets"]["discontinuities"] == 0
    assert video["packets"]["duplicated"] == 0
    # PCR pair: exact 40 ms lattice (1,080,000 ticks apart, 7 carriers).
    assert video["first-pcr"] == 1_080_000
    assert video["last-pcr"] == 7_560_000
    # PTS: first item k=0 -> 0; last STARTED item k=7 -> 22,033
    # (hand-derived schedule literal; TSDuck counts started PES headers,
    # not completed reassemblies — mapping note D7 in the difference report).
    assert video["first-pts"] == 0
    assert video["last-pts"] == ES1_STARTED_TAIL_PTS

    # --- ES PID 257 ---
    audio = _pid_entry(document, 257)
    assert audio["pes"] == 4
    assert audio["pes-stream-id"] == 192
    assert audio["audio"] is True and audio["video"] is False
    assert audio["packets"]["pcr"] == 0
    assert audio["packets"]["discontinuities"] == 0
    assert audio["first-pts"] == 0
    assert audio["last-pts"] == ES2_STARTED_TAIL_PTS

    # --- PSI PIDs: the re-emitted-table duplicate pattern (D1 / PI-1) ---
    pat_entry = _pid_entry(document, 0)
    assert pat_entry["packets"]["duplicated"] == 2
    assert pat_entry["packets"]["discontinuities"] == 0
    pmt_entry = _pid_entry(document, 4096)
    assert pmt_entry["packets"]["duplicated"] == 2
    assert pmt_entry["packets"]["discontinuities"] == 0

    # --- null PID: stuffing, CC undefined (ISO/IEC 13818-1) ---
    null_entry = _pid_entry(document, 8191)
    assert null_entry["packets"]["duplicated"] == 0
    assert null_entry["packets"]["discontinuities"] == 0

    # --- table level (ts-core: PAT/PMT parse) ---
    tables = {(entry["pid"], entry["tid"], entry["tid-ext"]): entry for entry in document["tables"]}
    assert set(tables) == {(0, 0, 1), (4096, 2, 1)}
    assert tables[(0, 0, 1)]["versions"] == [0]
    assert tables[(4096, 2, 1)]["versions"] == [0]


# --- hand-expanded literals for the examples/ts-generator-minimal.json run ---
# Same slot lattice (B = 3,008,000), N = 1000, single ES (PID 256, B/25):
# PAT 5 reps (slots 0/202/404/606/808), PMT 5 reps (1/206/412/618/824),
# ES pulls = 39 (slots 25..975) -> exactly 13 complete PES items (no
# truncated tail), PCR carriers at 80k step 80 (12): slot 400 rides the
# PES-start pull (payload_packet_first), slot 800 is an adaptation-only
# carrier. Null fill = 1000 - 5 - 5 - 50 = 940.
EXAMPLES_PID_COUNTS = {0: 5, 256: 50, 4096: 5, 8191: 940}
EXAMPLES_PCR_FIRST_TICKS = 1_080_000
EXAMPLES_PCR_LAST_TICKS = 12_960_000  # slot 960 * 13,500
EXAMPLES_LAST_STARTED_PTS = 37_771  # item k=12: 12 * 944,281 // 300


@pytest.mark.tsduck
def test_examples_config_end_to_end(tsduck, tmp_path):
    """The checked-in example JSON drives the whole chain end to end.

    Proves the SPEC-108 §4 JSON↔DTO seam (ruling #11) at integration level:
    the example file is the single input; ts-core never sees another value.
    """
    import json

    from ts.generator.json_map import generator_config_from_json, generator_config_to_json
    from tests._support.paths import REPO_ROOT

    example_path = REPO_ROOT / "examples" / "ts-generator-minimal.json"
    payload = json.loads(example_path.read_text(encoding="utf-8"))
    config = generator_config_from_json(payload)
    # The example is canonical under the §4 mapping table: re-serializing the
    # parsed config reproduces the checked-in document verbatim.
    assert generator_config_to_json(config) == payload
    assert ts_e2e_content_valid_config(config) is True

    chunks, summary = ts_e2e.generate_chunks(config)
    assert len(chunks) == payload["output_packet_count"] == 1000
    assert summary.byte_count == 188_000
    assert summary.pid_packet_counts == EXAMPLES_PID_COUNTS

    evidence = ts_e2e.self_parse_evidence(chunks)
    assert evidence.pat_section_count == 5
    assert evidence.pmt_section_count == 5
    assert evidence.pat_sections[0].transport_stream_id == 1
    assert evidence.pmt_sections[0].pcr_pid == 256
    assert [
        (s.stream_type, s.elementary_pid) for s in evidence.pmt_sections[0].streams
    ] == [(27, 256)]
    es1 = evidence.pes_by_pid[256]
    assert es1.starts == 13
    assert len(es1.complete) == 13  # 39 pulls = 13 * 3 packets, no truncation
    assert es1.tail_issue_codes == ()
    assert es1.complete[0].header.pts == 0
    assert es1.complete[-1].header.pts == EXAMPLES_LAST_STARTED_PTS
    carriers = evidence.pcr_carriers
    assert len(carriers) == 12
    assert carriers[0] == (80, EXAMPLES_PCR_FIRST_TICKS)
    assert carriers[-1] == (960, EXAMPLES_PCR_LAST_TICKS)
    # The payload-riding carrier (slot 400) is present alongside the
    # adaptation-only ones — payload_packet_first honoured end to end.
    assert (400, 5_400_000) in carriers
    assert evidence.cc_by_pid[0].duplicates == 4
    assert evidence.cc_by_pid[4096].duplicates == 4
    assert evidence.cc_by_pid[256].duplicates == 0

    # --- TSDuck cross validation on the same artifact ---
    ts_file = tmp_path / "examples_e2e.ts"
    ts_file.write_bytes(b"".join(chunks))
    run = ts_e2e.run_tsanalyze(tsduck, ts_file)
    assert run.content_valid is True
    document = run.json_document
    assert document["ts"]["bytes"] == 188_000
    assert document["ts"]["packets"]["total"] == 1000
    assert document["ts"]["id"] == 1
    assert document["ts"]["bitrate"] == 3_008_000
    assert {entry["id"] for entry in document["pids"]} == {0, 256, 4096, 8191}
    for pid, count in EXAMPLES_PID_COUNTS.items():
        assert _pid_entry(document, pid)["packets"]["total"] == count
    video = _pid_entry(document, 256)
    assert video["pes"] == 13
    assert video["packets"]["pcr"] == 12
    assert video["first-pcr"] == EXAMPLES_PCR_FIRST_TICKS
    assert video["last-pcr"] == EXAMPLES_PCR_LAST_TICKS
    assert video["first-pts"] == 0
    assert video["last-pts"] == EXAMPLES_LAST_STARTED_PTS
    assert video["packets"]["duplicated"] == 0
    assert video["packets"]["discontinuities"] == 0
    assert _pid_entry(document, 0)["packets"]["duplicated"] == 4
    assert _pid_entry(document, 4096)["packets"]["duplicated"] == 4


def ts_e2e_content_valid_config(config) -> bool:
    """The example config validates clean (no error-severity findings)."""
    from ts.generator.generator import TSGenerator

    return all(
        issue.severity != "error" for issue in TSGenerator().validate_config(config)
    )


@pytest.mark.tsduck
@pytest.mark.windows_only
def test_tsduck_real_run_evidence_req_ts_108_008(tsduck, tmp_path):
    """REQ-TS-108-008: the real ``tsanalyze --json`` evidence ticket #34 deferred.

    The #34 unit-layer seam test explicitly skipped the real run "owned by
    ticket #35" — this test IS that evidence, produced on the real machine:
    version-token shape (never a pinned literal, tests/README §6), a
    deterministic artifact (same config twice -> identical SHA-256), a real
    subprocess run whose JSON passes the #3 content gates, and the
    JSON-serializable evidence shape the integration report cites.
    """
    import hashlib
    import json
    import re

    ts_file = tmp_path / "req_ts_108_008_evidence.ts"

    # Version-token shape: measured-format regex, install path shape —
    # never a pinned version (CI runs a different TSDuck build, #69).
    assert tsduck.available is True
    assert re.fullmatch(r"\d+\.\d+-\d+", tsduck.version)
    assert tsduck.executable.lower().endswith("tsp.exe")

    chunks_first, summary = ts_e2e.generate_chunks(ts_e2e.integration_config())
    artifact = b"".join(chunks_first)
    chunks_second, _ = ts_e2e.generate_chunks(ts_e2e.integration_config())
    assert b"".join(chunks_second) == artifact  # §8 determinism, real bytes
    digest = hashlib.sha256(artifact).hexdigest()
    ts_file.write_bytes(artifact)

    run = ts_e2e.run_tsanalyze(tsduck, ts_file)
    # Exit code is recorded; validity comes from the JSON content (#3).
    assert run.exit_code == 0
    assert run.content_gates["ts_bytes_positive"] is True
    assert run.content_gates["services_total_at_least_one"] is True
    assert run.content_gates["packets_total_positive"] is True
    document = run.json_document
    assert document["ts"]["bytes"] == summary.byte_count == 112_800
    assert document["ts"]["services"]["total"] == 1

    # The evidence record cited by the implementation report — JSON round-trip
    # proves the report's evidence payload is machine-renderable.
    evidence = {
        "req": "REQ-TS-108-008",
        "tsduck_version_token": tsduck.version,
        "tsduck_executable_suffix": tsduck.executable[-8:],
        "command": ["tsanalyze.exe", "--json", "<artifact>"],
        "artifact_sha256": digest,
        "artifact_bytes": len(artifact),
        "exit_code": run.exit_code,
        "content_gates": run.content_gates,
        "ts_bytes": document["ts"]["bytes"],
        "services_total": document["ts"]["services"]["total"],
    }
    rendered = json.dumps(evidence)
    assert json.loads(rendered)["artifact_sha256"] == digest
