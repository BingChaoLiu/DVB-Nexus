"""First-batch golden registry — the frozen identity gate (SPEC-506 §6/§7).

The #14 pre-approved first batch is 10 entries / 14 byte files.  This
module pins:

- the exact registered id set (no foreign registration, none missing);
- the **frozen sha256 digest table** — an independent record of the
  approved bytes, separate from each manifest.  Per SPEC-506 §6 a byte
  change is a re-registration event (new approval): if the bytes drift,
  the manifest and this table disagree and the CI gate fails *before* any
  semantic assertion runs;
- registration-consistency: the SPEC-506 §8 validator tool passes;
- index consistency: every first-batch id is listed ``registered`` in
  TEST-VECTOR-INDEX.md.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

pytestmark = pytest.mark.conformance

from tests._support.paths import REPO_ROOT

#: The #14 first batch (SPEC-506 §7): 10 entries / 14 files.  Each faulted
#: pair entry registers two vectors (``<id>-baseline`` + ``<id>``).
FIRST_BATCH_IDS: tuple[str, ...] = (
    "packet-header-set",
    "pat-minimal",
    "pat-pmt-multi",
    "cc-wrap",
    "pcr-wrap",
    "section-fragmentation",
    "pat-missing-baseline",
    "pat-missing",
    "pmt-invalid-crc-baseline",
    "pmt-invalid-crc",
    "cc-discontinuity-baseline",
    "cc-discontinuity",
    "pmt-pid-mismatch-baseline",
    "pmt-pid-mismatch",
)

#: Frozen byte identities at registration time (2026-11-15, #14 batch).
#: An intentional byte change must land together with a re-approval of the
#: digest row (SPEC-506 §6: 变更 = 重新登记 + 批准).
FIRST_BATCH_SHA256: dict[str, str] = {
    "packet-header-set": "eb6ff7f3b4ffbb3746b9f6030b621c2df0e43bc8b37398226eb4c073c3b05770",
    "pat-minimal": "4c812bb2ef712b4190c9aaa8561b4fd72d2edb60bb6fe4e61ac90336bbe7481d",
    "pat-pmt-multi": "4f790a74c8b020d203d98e03aa7e0f907a26a98f66d938626584e9c59a631ff5",
    "cc-wrap": "5b707c72edf7739c567ddf659a58e00a03a27992c6697421f634a118baacbbbf",
    "pcr-wrap": "009eacdfa5f6d1b5a8da745cc69ab10a1cb0e38a3505a4c1f1ad854127e5c1f6",
    "section-fragmentation": "43297aa2754fd8b8376e031a1863e8605f0cc28a1b9b6a470aa356dcb27b8f42",
    "pat-missing-baseline": "b0afe1ef6068b9f1f0d3ed788cbaaf95d48f4f23bc1c7f8623895de6888a8f4c",
    "pat-missing": "e2c6a43a9bb1025cc3856b8cb2e6f85043578176c28eba4b675c8cef2fa251f2",
    "pmt-invalid-crc-baseline": "b0afe1ef6068b9f1f0d3ed788cbaaf95d48f4f23bc1c7f8623895de6888a8f4c",
    "pmt-invalid-crc": "d3db32f63e4af99365dd54d7a5272588556f9439dde704d497bfb59466d7fbb7",
    "cc-discontinuity-baseline": "b0afe1ef6068b9f1f0d3ed788cbaaf95d48f4f23bc1c7f8623895de6888a8f4c",
    "cc-discontinuity": "be2acc4dc6f8ea682397338681d15b69220ea9caf99e3fd497335c6ec7754ef3",
    "pmt-pid-mismatch-baseline": "b0afe1ef6068b9f1f0d3ed788cbaaf95d48f4f23bc1c7f8623895de6888a8f4c",
    "pmt-pid-mismatch": "7e1e2da2e00045039f7f05b3a5a7d732fd5df7e1fcad8036e9851cf2fa205493",
}

EXPECTED_KINDS: dict[str, str] = {
    "packet-header-set": "bit_level",
    "pat-minimal": "generated_ts",
    "pat-pmt-multi": "generated_ts",
    "cc-wrap": "generated_ts",
    "pcr-wrap": "generated_ts",
    "section-fragmentation": "generated_ts",
    "pat-missing-baseline": "generated_ts",
    "pat-missing": "faulted_ts",
    "pmt-invalid-crc-baseline": "generated_ts",
    "pmt-invalid-crc": "faulted_ts",
    "cc-discontinuity-baseline": "generated_ts",
    "cc-discontinuity": "faulted_ts",
    "pmt-pid-mismatch-baseline": "generated_ts",
    "pmt-pid-mismatch": "faulted_ts",
}


#: Phase 2 additive registrations (SPEC-506 §6: 新登记 = 新三件套 + 索引行
#: + 本文件 additive 扩行；冻结行本身不动，#136 统一收口 — brief §3.6-5).
PHASE2_ADDITIONAL_IDS: tuple[str, ...] = (
    "biss-j96-mode1",
)

#: Frozen byte identities of the Phase 2 additive registrations.
PHASE2_ADDITIONAL_SHA256: dict[str, str] = {
    "biss-j96-mode1": "9647d274cc8a96b73f4f6b4aaabeaa1c9227935bc2a2294c5e596e6a81db9f94",
}

PHASE2_ADDITIONAL_KINDS: dict[str, str] = {
    "biss-j96-mode1": "bit_level",
}


def test_first_batch_registered_set_is_exact(golden_loader):
    # registered_ids() enumerates in directory order (sorted); the batch is
    # compared as a sorted set.  Phase 2 tickets extend the registered tree
    # additively (PHASE2_ADDITIONAL_IDS); the #14 frozen batch rows are
    # untouched and #136 closes the file (brief §3.6-5).
    registered = tuple(golden_loader.registered_ids())
    expected = tuple(
        sorted(FIRST_BATCH_IDS + PHASE2_ADDITIONAL_IDS)
    )
    assert registered == expected


def test_first_batch_registry_manifests_consistent_with_frozen_table():
    from tests._support.paths import GOLDEN_ROOT

    assert set(FIRST_BATCH_SHA256) == set(FIRST_BATCH_IDS)
    assert len(FIRST_BATCH_IDS) == 14  # 10 entries / 14 files (#14)
    for vector_id in FIRST_BATCH_IDS:
        manifest = json.loads(
            (GOLDEN_ROOT / vector_id / "manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["sha256"].removeprefix("sha256:") == FIRST_BATCH_SHA256[vector_id]
        assert manifest["kind"] == EXPECTED_KINDS[vector_id]
        assert manifest["verification"]["path"] in {
            "tsduck-cross",
            "bit-level-review",
        }
        assert manifest["verification"]["evidence_ref"]


@pytest.mark.parametrize("fault_id", ("pat-missing", "pmt-invalid-crc", "cc-discontinuity", "pmt-pid-mismatch"))
def test_faulted_pair_plan_refs_and_shared_baseline(golden_loader, fault_id: str):
    faulted = golden_loader.load(fault_id)
    assert faulted.fault_plan_ref == f"{fault_id}-baseline"
    baseline = golden_loader.load(faulted.fault_plan_ref)
    assert baseline.kind == "generated_ts"
    assert faulted.ts_bytes != baseline.ts_bytes


def test_phase2_additive_registrations_consistent():
    from tests._support.paths import GOLDEN_ROOT

    assert set(PHASE2_ADDITIONAL_SHA256) == set(PHASE2_ADDITIONAL_IDS)
    for vector_id in PHASE2_ADDITIONAL_IDS:
        manifest = json.loads(
            (GOLDEN_ROOT / vector_id / "manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["sha256"].removeprefix("sha256:") == PHASE2_ADDITIONAL_SHA256[vector_id]
        assert manifest["kind"] == PHASE2_ADDITIONAL_KINDS[vector_id]


def test_spec506_registration_validator_passes(tmp_path):
    """SPEC-506 §8 validator tool: trio/sha/event-type/pair/index gates."""
    result = subprocess.run(
        [
            sys.executable, "-I",
            str(REPO_ROOT / "tools" / "validate_golden_registration.py"),
        ],
        capture_output=True,
        timeout=120,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, (
        result.stdout.decode("utf-8", "replace")
        + result.stderr.decode("utf-8", "replace")
    )
    # The frozen "14 registered" count pin retired to #136 (brief §3.6-5):
    # Phase 2 golden tickets extend the tree additively, so the validator
    # gate asserts success + the marker line, not a pinned count.
    assert "registered vector(s) validated" in result.stdout.decode(
        "utf-8", "replace"
    )


def test_index_lists_every_first_batch_id_as_registered():
    from tests._support.paths import REPO_ROOT

    index = (REPO_ROOT / "docs" / "test-vectors" / "TEST-VECTOR-INDEX.md").read_text(
        encoding="utf-8"
    )
    for vector_id in FIRST_BATCH_IDS:
        assert f"`{vector_id}`" in index, f"{vector_id} missing from index"
    # No first-batch table row remains in planned state (the status-flow
    # bullet legitimately names `planned` as a lifecycle stage).
    golden_section = index.split("## golden", 1)[1]
    assert "| planned |" not in golden_section
