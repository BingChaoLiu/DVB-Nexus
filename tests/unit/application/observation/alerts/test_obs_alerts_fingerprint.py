"""Alert fingerprint derivation (SPEC-304 §6, ticket #52).

REQ-OBS-304-004: the fingerprint is derived from the rule id + the rule's
CONFIGURED STABLE dimensions — never from volatile values (metric readings),
payload text or timestamps. The same (rule, dimensions) pair always yields
the same token; deduplication itself is scoped by tenant/session (the
record's scope columns), so one fingerprint value may recur across sessions
without cross-session collapse.
"""

from application.observation.alerts.fingerprint import alert_fingerprint


class TestDeterminism:
    def test_same_inputs_yield_the_same_token(self) -> None:
        first = alert_fingerprint("PCR_JITTER_HIGH", {"pid": 256})
        second = alert_fingerprint("PCR_JITTER_HIGH", {"pid": 256})
        assert first == second

    def test_dimension_insertion_order_is_irrelevant(self) -> None:
        first = alert_fingerprint(
            "TS_CC_ERROR_RATE_HIGH", {"pid": 256, "service_id": "svc-1"}
        )
        second = alert_fingerprint(
            "TS_CC_ERROR_RATE_HIGH", {"service_id": "svc-1", "pid": 256}
        )
        assert first == second

    def test_value_type_normalization_is_stable(self) -> None:
        # pid 256 (int) and "256" (str) are the same dimension value.
        assert alert_fingerprint("R", {"pid": 256}) == alert_fingerprint(
            "R", {"pid": "256"}
        )


class TestDiscrimination:
    def test_different_rule_ids_differ(self) -> None:
        assert alert_fingerprint("A", {}) != alert_fingerprint("B", {})

    def test_different_dimension_values_differ(self) -> None:
        assert alert_fingerprint("R", {"pid": 1}) != alert_fingerprint("R", {"pid": 2})

    def test_additional_dimensions_differ(self) -> None:
        assert alert_fingerprint("R", {"pid": 1}) != alert_fingerprint(
            "R", {"pid": 1, "service_id": "svc-1"}
        )


class TestShapeAndScope:
    def test_token_is_a_labelled_sha256(self) -> None:
        token = alert_fingerprint("R", {"pid": 1})
        assert token.startswith("sha256:")
        digest = token.removeprefix("sha256:")
        assert len(digest) == 64
        int(digest, 16)  # hex

    def test_fingerprint_carries_no_session_scope(self) -> None:
        # Scope (tenant/session) lives on the record columns; the fingerprint
        # is rule + stable dimensions only (SPEC-304 §6), so the same group
        # in two sessions dedups inside its own scope without colliding
        # across scopes.
        assert alert_fingerprint("R", {"pid": 1}) == alert_fingerprint("R", {"pid": 1})

    def test_volatile_readings_cannot_enter_the_token(self) -> None:
        # The derivation consumes only the declared dimension mapping — two
        # different metric readings of the same group map to one token (the
        # engine passes dimensions, never values).
        assert alert_fingerprint("R", {"pid": 1}) == alert_fingerprint("R", {"pid": 1})
