"""``rf.state_observed`` → ``tuner.lock_state``/``tuner.ber_state`` derivation
(ticket #166, SPEC-304 §Phase3 alert-input wiring).

Seam: ``MetricsEngine.handle_record`` (the journal-tailing ingestion face).
The two additive catalog metrics carry the state_evaluator observation into
the metrics plane so the alert rules read them through the unchanged
``MetricWindowReader`` — the AlertEngine lifecycle machine stays untouched
(ruling A6 preferred path).

Discrete-state comparison semantics pinned here (frozen for the REPORT):

- ``tuner.lock_state`` code: ``locked=0.0`` / ``unlocked=1.0`` — the
  alert-worthy state is 1 (boolean-style gauge, alarm=1);
- ``tuner.ber_state`` code: ``normal=0.0`` / ``elevated=1.0`` / ``severe=2.0``
  — the ordinal ladder (a higher code is a worse grade); ``elevated`` (1)
  must therefore satisfy NO open condition (SPEC-304 §Phase3: elevated
  不告警 — the SPEC-307 combination judgement owns that tier);
- ``ber_state=null`` (unlocked keeps no grade — the #164 registry face)
  yields NO sample (缺失 ≠ 零, the engine never fabricates); the
  ``lock_state`` sample still rides the same snapshot (unlocked is a fresh,
  per-evaluation fact — ``stale`` only marks the retired BER grade);
- out-of-vocabulary state strings yield no sample (a second line of
  defence behind the payload registry's strict validation);
- samples carry the observed ``node_id`` dimension (per-node rule grouping,
  SPEC-304 §6) and the source-event provenance stamp (SPEC-302 §1).

Unit layer: pure in-memory, injected integers only.
"""

from application.observation.metrics.engine import MetricsEngine

from tests.unit.application.observation.metrics._metrics_fixtures import (
    raw_envelope,
    record,
)

SESSION_ID = "sess-1"
DOMAIN = f"sim:{SESSION_ID}"
NODE_ID = "tuner-a"


def rf_snapshot(
    *,
    lock_state: str,
    ber_state: str | None = "normal",
    stale: bool = False,
    source_ns: int = 1_000,
    journal_seq: int = 1,
    node_id: str = NODE_ID,
    session_id: str = SESSION_ID,
    validate: bool = True,
):
    """A full ``rf.state_observed`` payload per RF_TUNER_SNAPSHOT_KEYS."""
    payload = {
        "node_id": node_id,
        "health": "error" if lock_state == "unlocked" else "ok",
        "causes": [],
        "source": "state_evaluator",
        "confidence": "simulated",
        "lock_state": lock_state,
        "if_frequency_khz": 1_230_000 if lock_state == "locked" else None,
        "ber_state": ber_state,
        "locked_transponder_id": "tp-1" if lock_state == "locked" else None,
        "stale": stale,
    }
    return record(
        raw_envelope(
            event_type="rf.state_observed",
            session_id=session_id,
            source_ns=source_ns,
            payload=payload,
            validate=validate,
        ),
        journal_seq=journal_seq,
    )


def _engine() -> MetricsEngine:
    return MetricsEngine()


def test_unlocked_snapshot_derives_the_lock_state_alarm_code() -> None:
    engine = _engine()
    engine.handle_record(
        rf_snapshot(lock_state="unlocked", ber_state=None, stale=True)
    )
    samples = engine.samples("tuner.lock_state", clock_domain=DOMAIN)
    assert len(samples) == 1
    sample = samples[0]
    assert sample.value == 1.0  # unlocked = the alert-worthy state
    assert sample.dimensions == {"session_id": SESSION_ID, "node_id": NODE_ID}
    assert sample.time.clock_domain == DOMAIN
    assert sample.time.semantics.value == "source"


def test_locked_snapshot_derives_the_quiescent_code_zero() -> None:
    engine = _engine()
    engine.handle_record(rf_snapshot(lock_state="locked"))
    samples = engine.samples("tuner.lock_state", clock_domain=DOMAIN)
    assert len(samples) == 1
    assert samples[0].value == 0.0


def test_ber_state_codes_are_the_ordinal_ladder() -> None:
    engine = _engine()
    for seq, (grade, expected) in enumerate(
        (("normal", 0.0), ("elevated", 1.0), ("severe", 2.0)),
        start=1,
    ):
        engine.handle_record(
            rf_snapshot(
                lock_state="locked",
                ber_state=grade,
                source_ns=seq * 1_000,
                journal_seq=seq,
            )
        )
    values = [
        sample.value
        for sample in engine.samples("tuner.ber_state", clock_domain=DOMAIN)
    ]
    assert values == [0.0, 1.0, 2.0]


def test_null_ber_state_yields_no_sample_but_lock_state_still_rides() -> None:
    """``ber_state=null`` (unlocked keeps no grade) → no fabricated sample;
    the same snapshot's ``lock_state`` is still a fresh per-evaluation fact."""
    engine = _engine()
    engine.handle_record(
        rf_snapshot(lock_state="unlocked", ber_state=None, stale=True)
    )
    assert engine.samples("tuner.ber_state", clock_domain=DOMAIN) == ()
    assert len(engine.samples("tuner.lock_state", clock_domain=DOMAIN)) == 1


def test_out_of_vocabulary_state_string_yields_no_sample() -> None:
    """Second line of defence: the payload registry refuses unknown state
    strings at the journal face; the derivation skips them (never fabricates)
    even if one arrives through an unvalidated consumer path."""
    engine = _engine()
    engine.handle_record(
        rf_snapshot(lock_state="half-locked", ber_state=None, validate=False)
    )
    engine.handle_record(
        rf_snapshot(lock_state="locked", ber_state="catastrophic", validate=False)
    )
    # Each invalid field contributed nothing; the second record's VALID
    # lock_state still derived — only its bad ber_state was skipped.
    assert len(engine.samples("tuner.lock_state", clock_domain=DOMAIN)) == 1
    assert engine.samples("tuner.ber_state", clock_domain=DOMAIN) == ()


def test_samples_carry_the_source_event_provenance() -> None:
    engine = _engine()
    engine.handle_record(rf_snapshot(lock_state="locked", journal_seq=7))
    sample = engine.samples("tuner.lock_state", clock_domain=DOMAIN)[0]
    assert sample.provenance.journal_watermark == 7
    assert sample.provenance.source_event_ids, "provenance must trace the snapshot"


def test_non_rf_events_never_fabricate_tuner_state_samples() -> None:
    engine = _engine()
    engine.handle_record(
        record(
            raw_envelope(
                event_type="sec.state_observed",
                session_id=SESSION_ID,
                source_ns=1_000,
                payload={
                    "node_id": "lnb-0",
                    "health": "ok",
                    "causes": [],
                    "source": "state_evaluator",
                    "confidence": "simulated",
                    "voltage": "13V",
                    "tone_commanded": "none",
                    "tone_actual": "none",
                    "tone_composite": "none",
                    "band_selected": "low",
                    "lo_frequency_khz": 9_750_000,
                    "polarization_delivered": "vertical",
                    "short_circuit_state": "normal",
                    "ub_assignments": [],
                },
            ),
            journal_seq=1,
        )
    )
    assert engine.samples("tuner.lock_state", clock_domain=DOMAIN) == ()
    assert engine.samples("tuner.ber_state", clock_domain=DOMAIN) == ()
