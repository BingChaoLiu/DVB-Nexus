"""Phase 3 state-lab E2E — the SC-10/SC-11 full teaching loops (ticket
#172, the M7 集成收口票).

Each chain drives the PRODUCTION composition (``build_production_app`` —
the #57/#58 e2e posture) through the state-domain eight-step equivalent
(ADR-0012 decision 2, SPEC-406 §Phase3): Lab 开实验 (the #80 加载即建
session over the registry scenario — READY) → 注入 (the SIM_STATE Run
with the scenario fault plan, #165) → 状态观测 (the journal evidence:
``rf.*``/``sec.*`` snapshots + ``topology.state_changed`` + ``fault.*``,
honestly NO ``gen.*`` — SPEC-303 §Phase3 journal composition) →
diagnose 候选断言 (the A21-lit diagnose face: the SPEC-307 §Phase3 rules
fire on the REAL faulted snapshots — presence assertions, the #168
predicate overlap asserted honestly, never exclusivity) → 恢复 (the
empty-fault-plan re-run = the recovery Run) → fault_inactive 通关三查
(the SC-10 hidden_reference_solution 口径: ①Inject Run ``fault.*``
lifecycle closed injected→cleared; ②the recovery Run's prepared plan
excludes the fault_id — no ``fault.injected``; ③no recurrence on the
recovery Run) + 确定性复现 (same-scenario double run: equal
``config_hash`` + equal terminal node health + field-identical snapshot
streams) + the alerts face (the #166 Phase 3 rules through the metrics
engine, ruling A6).

与既有 journal 证据断言双轨并存 (#59/#113 诚实判据纪律): the journal
evidence assertions (snapshots, payload key sets, fault lifecycle) and
the criterion verdict (fault_inactive PASS) are TWO tracks — the
evidence track never replaces the criterion, the criterion never swallows
the evidence.

Determinism: runs are awaited to their terminal state and the gateway is
drained before every read (event-driven, POLL_BOUND yields — no
wall-clock waits); the alerts tick anchors ``now_ns`` to the newest
observed virtual time.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.e2e

from domain.observation.registry import (
    RF_TUNER_SNAPSHOT_KEYS,
    SEC_LNB_SNAPSHOT_KEYS,
    validate_payload,
)

from tests.e2e._fault_lab import FaultLab, fault_plan_wire, load_runtime_scenario

SC10 = "SC-10-unicable_ub_conflict"
SC11 = "SC-11-tone_residue"

UB_CONFLICT_FAULT_ID = "fd000000-0000-4000-8000-00000000f110"
TONE_RESIDUE_FAULT_ID = "fd000000-0000-4000-8000-00000000f111"

RF_STATE = "rf.state_observed"
SEC_STATE = "sec.state_observed"

CODE_UB = "DIAG_UB_CONFLICT_SUSPECT"
CODE_TON = "DIAG_TONE_RESIDUE_SUSPECT"

#: The 850 MHz asymmetry arithmetic (roadmap §4 A2 订正口径 / SPEC-621
#: appendix A 尾段): the universal LO arms differ by exactly 850 MHz.
ASYMMETRY_KHZ = 850_000


def _events_of(lab: FaultLab, session_id: str, run_id: str, event_type: str):
    return [
        item
        for item in lab.events(session_id)
        if item["event_type"] == event_type and item["scope"]["run_id"] == run_id
    ]


def _payloads(lab: FaultLab, session_id: str, run_id: str, event_type: str):
    return [item["payload"] for item in _events_of(lab, session_id, run_id, event_type)]


def _snapshots_of_node(payloads: list[dict[str, Any]], node_id: str) -> list[dict]:
    """One node's snapshots in emission order (trigger 1 baseline first,
    trigger 2 faulted last)."""
    return [p for p in payloads if p["node_id"] == node_id]


def _last(payloads: list[dict[str, Any]], node_id: str) -> dict[str, Any]:
    snaps = _snapshots_of_node(payloads, node_id)
    assert snaps, f"no snapshot for {node_id}"
    return snaps[-1]


def _assert_state_journal_composition(
    lab: FaultLab, session_id: str, inject_run_id: str
) -> None:
    """The SPEC-303 §Phase3 journal composition face, asserted on the
    REAL committed journal: snapshots + topology diff + fault lifecycle,
    honestly no gen.* (构造事件是 TS 构造域)."""
    types = {item["event_type"] for item in lab.events(session_id)}
    assert {RF_STATE, SEC_STATE, "topology.state_changed"} <= types
    assert "fault.injected" in types and "fault.cleared" in types
    assert not any(t.startswith("gen.") for t in types), sorted(types)
    # run-scope correlation: the state events ride their run.
    for event_type in (RF_STATE, SEC_STATE, "topology.state_changed"):
        for item in _events_of(lab, session_id, inject_run_id, event_type):
            assert item["scope"]["session_id"] == session_id


def _assert_snapshot_payload_registry_shape(payloads: list[dict]) -> None:
    assert payloads, "the snapshot family never fired"
    for payload in payloads:
        validate_payload(RF_STATE, payload)
        assert set(payload) == set(RF_TUNER_SNAPSHOT_KEYS)


def _replay_journal(ws, *, max_frames: int = 4000) -> list[dict[str, Any]]:
    """Collect the replayed journal envelopes until the ready frame."""
    envelopes: list[dict[str, Any]] = []
    for _ in range(max_frames):
        frame = ws.receive_json()
        if frame["type"] == "ready":
            return envelopes
        assert frame["type"] == "journal", frame
        envelopes.append(frame["envelope"])
    raise AssertionError(f"journal replay never ended within {max_frames} frames")


def _assert_deterministic_replay(
    lab: FaultLab, session_id: str, first_run_id: str, second_run_id: str
) -> None:
    """确定性复现 (AC-620-06 / AC-621-05 posture over the REST face): two
    same-config empty-plan runs share the config fingerprint and deliver
    field-identical per-node snapshot streams (identity/time fields
    aside — those carry the run identity, not the state facts)."""
    first = lab.await_state_run(session_id, first_run_id)
    second = lab.await_state_run(session_id, second_run_id)
    lab.drain()  # commit the second run's queued events before reading
    assert first["config_hash"] == second["config_hash"]
    assert first["node_health"] == second["node_health"]
    for event_type in (RF_STATE, SEC_STATE):
        first_payloads = [
            p for p in _payloads(lab, session_id, first_run_id, event_type)
        ]
        second_payloads = [
            p for p in _payloads(lab, session_id, second_run_id, event_type)
        ]
        assert [dict(p) for p in first_payloads] == [
            dict(p) for p in second_payloads
        ], f"{event_type} streams diverge between identical runs"


class TestSC10UbConflictStateLab:
    """SC-10 — A1 Unicable UB 槽位冲突全链（共享同轴 SCR 拓扑）."""

    def test_full_chain_inject_observe_diagnose_recover_verify(self, tmp_path) -> None:
        _raw, document = load_runtime_scenario(SC10)
        with FaultLab(db_path=tmp_path / "sc10-state-lab.sqlite") as lab:
            # --- Lab 开实验: the registry scenario opens READY ---------
            session_id = lab.create_scenario_session(document)

            # --- 注入: the SIM_STATE Run with the scenario fault plan --
            inject_run_id = lab.submit_state_run(
                session_id, fault_plan_wire(document)
            )
            inject_status = lab.await_state_run(session_id, inject_run_id)
            assert inject_status["config_hash"], inject_status
            # The L0 products ride the status face (decision 5): the
            # faulted walk ends error (tuner-b unlocked); the baseline
            # was ok.
            assert inject_status["graph_health"] == "error"
            assert inject_status["node_health"]["tuner-b"] == "error"
            assert inject_status["node_health"]["tuner-a"] == "ok"

            lab.drain()  # commit the run's queued events (in queue order)
            lab.drain()  # commit the run-end trigger's diagnosis events

            # --- 状态观测: the journal evidence track -------------------
            _assert_state_journal_composition(lab, session_id, inject_run_id)

            rf_payloads = _payloads(lab, session_id, inject_run_id, RF_STATE)
            _assert_snapshot_payload_registry_shape(rf_payloads)
            sec_payloads = _payloads(lab, session_id, inject_run_id, SEC_STATE)
            for payload in sec_payloads:
                validate_payload(SEC_STATE, payload)
            lnb_payloads = [
                p for p in sec_payloads if "voltage" in p
            ]
            assert lnb_payloads, "the lnb snapshot family never fired"
            assert all(
                set(p) == set(SEC_LNB_SNAPSHOT_KEYS) for p in lnb_payloads
            )

            # The A1 measured faces (#171 落库实测): baseline both locked;
            # faulted tuner-b unlocked + severe + the conflict peer, the
            # SCR-shared tuner-a stays locked normal.
            baseline_b = _snapshots_of_node(rf_payloads, "tuner-b")[0]
            assert baseline_b["lock_state"] == "locked"
            assert baseline_b["ber_state"] == "normal"
            assert baseline_b["locked_transponder_id"] == "ub:1:1420"
            faulted_b = _last(rf_payloads, "tuner-b")
            assert faulted_b["lock_state"] == "unlocked"
            assert faulted_b["ber_state"] == "severe"
            assert faulted_b["locked_transponder_id"] is None
            assert faulted_b["stale"] is True
            assert [c["node_id"] for c in faulted_b["causes"]] == ["tuner-a"]
            faulted_a = _last(rf_payloads, "tuner-a")
            assert faulted_a["lock_state"] == "locked"
            assert faulted_a["ber_state"] == "normal"
            assert faulted_a["stale"] is False

            # The SCR face rides the lnb snapshot (ub_assignments 表).
            faulted_lnb = lnb_payloads[-1]
            table = faulted_lnb["ub_assignments"]
            assert {entry["tuner_node"] for entry in table} == {
                "tuner-a",
                "tuner-b",
            }

            # --- diagnose 候选断言 (A21 点亮后的真引擎输出) --------------
            report = lab.diagnose(session_id, inject_run_id)
            codes = [c["code"] for c in report["candidates"]]
            # presence 断言 — the paired rule fired on the real faulted
            # snapshot through the lit anchor path (No fake evidence).
            assert CODE_UB in codes, codes
            # overlap 如实 (#168 REPORT deviation 3): the faulted face is
            # UNLOCKED — both rules' predicate sets hold there, so the
            # tone suspect is honestly present TOO (presence never
            # exclusivity; the CauseRef discrimination rides the
            # evidence locator, not the frozen predicate set).
            assert CODE_TON in codes, codes
            ub_candidate = next(
                c for c in report["candidates"] if c["code"] == CODE_UB
            )
            assert ub_candidate["rule_id"] == "DIA-UB-CONFLICT-SUSPECT"
            assert ub_candidate["confidence"] == "high"
            assert ub_candidate["affected_node_ids"] == ["tuner-b"]
            # The anchor chain resolves: the evidence locator carries the
            # state face verbatim (the conflict pair included); the wire
            # is the locator form — no fabricated pid/packet_index keys.
            evidence = ub_candidate["evidence"]
            assert "pid" not in evidence and "packet_index" not in evidence
            assert evidence["locator"]["lock_state"] == "unlocked"
            assert evidence["locator"]["causes"] == [
                {"node_id": "tuner-a", "port_id": None}
            ]
            ton_candidate = next(
                c for c in report["candidates"] if c["code"] == CODE_TON
            )
            assert ton_candidate["affected_node_ids"] == ["tuner-b"]

            # The stored row + the raised event agree (the lifecycle
            # committed through the two-state registry gate). The
            # diagnosis.* envelopes are session-scoped (no run_id in
            # scope — the run attribution rides observation_refs), so
            # the anchor chain is asserted through the refs: every
            # raised payload's journal_seq anchors INTO the inject run.
            rows = [
                row
                for row in lab.diagnoses(session_id)
                if row["run_id"] == inject_run_id
            ]
            assert {row["code"] for row in rows} == {CODE_UB, CODE_TON}
            raised = [
                item
                for item in lab.events(session_id)
                if item["event_type"] == "diagnosis.raised"
            ]
            assert raised, "the raised lifecycle never committed"
            raised_codes = {item["payload"]["code"] for item in raised}
            assert raised_codes == {CODE_UB, CODE_TON}
            inject_seqs = {
                item["journal_seq"]
                for item in lab.events(session_id)
                if item["scope"]["run_id"] == inject_run_id
            }
            for item in raised:
                refs = item["payload"]["observation_refs"]
                assert refs, "a raised candidate without observation refs"
                assert {ref["journal_seq"] for ref in refs} <= inject_seqs

            # --- alerts 面 (the #166 rules through the metrics engine,
            #     ruling A6): the FAULTED state is the newest window
            #     sample here — the unlocked tuner opens TUNER_UNLOCKED
            #     (warning) and the severe grade opens BER_SEVERE (error)
            #     with per-node attribution (the fingerprint); the
            #     healthy tuner-a opens nothing.  The pre-existing
            #     TOPOLOGY_PATH_DOWN rule may honestly fire alongside
            #     (the degraded-node face) — presence form, never
            #     exclusivity.
            lab.evaluate_alerts(session_id)
            alerts = lab.alerts(session_id)
            from application.observation.alerts.fingerprint import (
                alert_fingerprint,
            )

            by_rule: dict[str, list[dict[str, Any]]] = {}
            for alert in alerts["items"]:
                by_rule.setdefault(alert["rule_id"], []).append(alert)
            assert ("TUNER_UNLOCKED", "firing") in {
                (a["rule_id"], a["state"]) for a in alerts["items"]
            }, sorted({a["rule_id"] for a in alerts["items"]})
            assert ("BER_SEVERE", "firing") in {
                (a["rule_id"], a["state"]) for a in alerts["items"]
            }
            assert len(by_rule["TUNER_UNLOCKED"]) == 1
            assert by_rule["TUNER_UNLOCKED"][0]["severity"] == "warning"
            assert (
                by_rule["TUNER_UNLOCKED"][0]["fingerprint"]
                == alert_fingerprint("TUNER_UNLOCKED", {"node_id": "tuner-b"})
            )
            assert by_rule["BER_SEVERE"][0]["severity"] == "error"
            assert (
                by_rule["BER_SEVERE"][0]["fingerprint"]
                == alert_fingerprint("BER_SEVERE", {"node_id": "tuner-b"})
            )

            # --- WS 真链路: the committed journal replays rf./sec. ------
            lab.drain()
            with TestClient(lab.stack.app) as client:
                with client.websocket_connect(
                    f"/ws/v1/sessions/{session_id}"
                ) as ws:
                    ws.send_json(
                        {
                            "type": "subscribe",
                            "session_id": session_id,
                            "last_journal_seq": 0,
                        }
                    )
                    envelopes = _replay_journal(ws)
            ws_types = {e["event_type"] for e in envelopes}
            assert {RF_STATE, SEC_STATE} <= ws_types
            assert not any(t.startswith("gen.") for t in ws_types)

            # --- 恢复: the empty-fault-plan re-run -----------------------
            recovery_run_id = lab.submit_state_run(session_id, [])
            recovery_status = lab.await_state_run(session_id, recovery_run_id)
            assert recovery_status["graph_health"] == "ok"
            assert recovery_status["node_health"]["tuner-a"] == "ok"
            assert recovery_status["node_health"]["tuner-b"] == "ok"
            lab.drain()

            # The recovery snapshot stream is the clean face again.
            recovery_rf = _payloads(lab, session_id, recovery_run_id, RF_STATE)
            _assert_snapshot_payload_registry_shape(recovery_rf)
            assert _last(recovery_rf, "tuner-b")["lock_state"] == "locked"

            # --- fault_inactive 通关三查 (SC-10 hidden_reference_solution
            #     口径) + the SPEC-206 three-state verdict ---------------
            # ① Inject Run fault.* lifecycle closed (injected→cleared; the
            #    state layer has no activated/applied packet phases).
            inject_fault_events = [
                item
                for item in lab.events(session_id)
                if item["event_type"].startswith("fault.")
                and item["scope"]["run_id"] == inject_run_id
            ]
            inject_fault_types = sorted(
                {item["event_type"] for item in inject_fault_events}
            )
            assert inject_fault_types == ["fault.cleared", "fault.injected"]
            assert {
                item["payload"]["fault_id"] for item in inject_fault_events
            } == {UB_CONFLICT_FAULT_ID}
            # ②③ The recovery Run's prepared plan excludes the fault_id
            #     (no fault.injected) and no recurrence anywhere.
            recovery_fault_events = [
                item
                for item in lab.events(session_id)
                if item["event_type"].startswith("fault.")
                and item["scope"]["run_id"] == recovery_run_id
            ]
            assert recovery_fault_events == []
            verdict = lab.verify(session_id, recovery_run_id, inject_run_id, document)
            assert verdict["verdict"] == "PASS", verdict
            criterion_results = {
                c["criterion_id"]: c["result"] for c in verdict["criteria"]
            }
            assert criterion_results["fault-cleared"] == "PASS"

            # --- 确定性复现: same-scenario double empty-plan run --------
            replay_run_id = lab.submit_state_run(session_id, [])
            _assert_deterministic_replay(
                lab, session_id, recovery_run_id, replay_run_id
            )

            # The symptom alerts LEFT the firing face after the recovery
            # (the clean snapshots are the newest window sample — the #52
            # lifecycle's measured close: firing → resolving; the
            # resolve_duration settle is window semantics, not a wall
            # clock).
            lab.evaluate_alerts(session_id)
            alerts = lab.alerts(session_id)
            by_rule = {}
            for alert in alerts["items"]:
                by_rule.setdefault(alert["rule_id"], []).append(alert)
            assert by_rule["TUNER_UNLOCKED"][0]["state"] != "firing"
            assert by_rule["BER_SEVERE"][0]["state"] != "firing"


class TestSC11ToneResidueStateLab:
    """SC-11 — A2 22kHz 持续音调残留全链（双 lnb 直连对照拓扑）."""

    def test_full_chain_inject_observe_diagnose_recover_verify(self, tmp_path) -> None:
        _raw, document = load_runtime_scenario(SC11)
        with FaultLab(db_path=tmp_path / "sc11-state-lab.sqlite") as lab:
            session_id = lab.create_scenario_session(document)

            inject_run_id = lab.submit_state_run(
                session_id, fault_plan_wire(document)
            )
            inject_status = lab.await_state_run(session_id, inject_run_id)
            assert inject_status["graph_health"] == "error"
            assert inject_status["node_health"]["tuner-low"] == "error"
            assert inject_status["node_health"]["tuner-high"] == "ok"
            lab.drain()
            lab.drain()

            _assert_state_journal_composition(lab, session_id, inject_run_id)

            rf_payloads = _payloads(lab, session_id, inject_run_id, RF_STATE)
            _assert_snapshot_payload_registry_shape(rf_payloads)
            lnb_payloads = [
                p
                for p in _payloads(lab, session_id, inject_run_id, SEC_STATE)
                if "voltage" in p
            ]
            assert lnb_payloads

            # The A2 measured faces (#171 落库实测): the ASYMMETRY — the
            # low-band request wrong-locks the 850 MHz-shifted high-band
            # alias (severe, causes → lnb-0); the high-band request whose
            # intent matches the residue stays normal.
            faulted_low = _last(rf_payloads, "tuner-low")
            assert faulted_low["lock_state"] == "locked"
            assert faulted_low["ber_state"] == "severe"
            assert faulted_low["locked_transponder_id"] == "high@11945000"
            assert faulted_low["stale"] is False
            assert [c["node_id"] for c in faulted_low["causes"]] == ["lnb-0"]
            # The 850 MHz 不对称算术 on the REAL output: alias − target.
            alias_khz = int(faulted_low["locked_transponder_id"].split("@")[1])
            assert alias_khz - 11_095_000 == ASYMMETRY_KHZ
            faulted_high = _last(rf_payloads, "tuner-high")
            assert faulted_high["lock_state"] == "locked"
            assert faulted_high["ber_state"] == "normal"
            assert faulted_high["locked_transponder_id"] == "high@12070000"

            # The tone 双字段分离缝 rides the faulted lnb snapshot.
            faulted_lnb = _snapshots_of_node(lnb_payloads, "lnb-0")[-1]
            assert faulted_lnb["tone_commanded"] == "none"
            assert faulted_lnb["tone_actual"] == "continuous"
            assert faulted_lnb["band_selected"] == "high"
            assert faulted_lnb["lo_frequency_khz"] == 10_600_000

            # --- diagnose 候选断言: the wrong-LOCK face discriminates —--
            report = lab.diagnose(session_id, inject_run_id)
            codes = [c["code"] for c in report["candidates"]]
            assert CODE_TON in codes, codes
            # The lock_state discriminator separates the 错锁面 (locked):
            # the UB rule's eq pin fails here — honestly ABSENT, not
            # hidden (the unlocked-face overlap is SC-10's face).
            assert CODE_UB not in codes, codes
            ton_candidate = next(
                c for c in report["candidates"] if c["code"] == CODE_TON
            )
            assert ton_candidate["rule_id"] == "DIA-TONE-RESIDUE-SUSPECT"
            assert ton_candidate["confidence"] == "medium"
            assert ton_candidate["affected_node_ids"] == ["tuner-low"]
            assert ton_candidate["evidence"]["locator"]["causes"] == [
                {"node_id": "lnb-0", "port_id": None}
            ]

            # --- alerts 面: the severe grade fires BER_SEVERE (error) on
            #     the faulted tuner-low; NOTHING fires TUNER_UNLOCKED (no
            #     unlocked tuner on this chain — the honest absence face;
            #     the pre-existing TOPOLOGY_PATH_DOWN rule may fire
            #     alongside — presence form, never exclusivity) -----------
            lab.evaluate_alerts(session_id)
            alerts = lab.alerts(session_id)
            from application.observation.alerts.fingerprint import (
                alert_fingerprint,
            )

            by_rule = {}
            for alert in alerts["items"]:
                by_rule.setdefault(alert["rule_id"], []).append(alert)
            assert "TUNER_UNLOCKED" not in by_rule, set(by_rule)
            assert by_rule["BER_SEVERE"][0]["state"] == "firing"
            assert by_rule["BER_SEVERE"][0]["severity"] == "error"
            assert (
                by_rule["BER_SEVERE"][0]["fingerprint"]
                == alert_fingerprint("BER_SEVERE", {"node_id": "tuner-low"})
            )

            # --- 恢复 + 通关三查 -----------------------------------------
            recovery_run_id = lab.submit_state_run(session_id, [])
            recovery_status = lab.await_state_run(session_id, recovery_run_id)
            assert recovery_status["graph_health"] == "ok"
            lab.drain()

            inject_fault_types = sorted(
                {
                    item["event_type"]
                    for item in lab.events(session_id)
                    if item["event_type"].startswith("fault.")
                    and item["scope"]["run_id"] == inject_run_id
                }
            )
            assert inject_fault_types == ["fault.cleared", "fault.injected"]
            recovery_fault_events = [
                item
                for item in lab.events(session_id)
                if item["event_type"].startswith("fault.")
                and item["scope"]["run_id"] == recovery_run_id
            ]
            assert recovery_fault_events == []
            verdict = lab.verify(session_id, recovery_run_id, inject_run_id, document)
            assert verdict["verdict"] == "PASS", verdict
            assert (
                verdict["criteria"][0]["result"] == "PASS"
            )  # fault-cleared (fault_inactive)

            # 确定性复现.
            replay_run_id = lab.submit_state_run(session_id, [])
            _assert_deterministic_replay(
                lab, session_id, recovery_run_id, replay_run_id
            )

            # The symptom alert LEFT the firing face after the recovery
            # (clean snapshots are the newest window sample — the #52
            # measured close).
            lab.evaluate_alerts(session_id)
            alerts = lab.alerts(session_id)
            by_rule = {}
            for alert in alerts["items"]:
                by_rule.setdefault(alert["rule_id"], []).append(alert)
            assert by_rule["BER_SEVERE"][0]["state"] != "firing"
