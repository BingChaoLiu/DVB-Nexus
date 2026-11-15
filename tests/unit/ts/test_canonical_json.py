"""Canonical JSON serialization contract (shared determinism primitive).

One ``canonical_json`` for every cross-run identity fingerprint: the plan
fingerprint (SPEC-203), the mutation-log bytes (ADR-0007) and the scenario
content hash (SPEC-205 §5) must serialize identically or equal-input
equal-output breaks somewhere. Contract: ``ensure_ascii=True`` (ASCII
escapes are the most stable cross-locale form — the byte stream never
depends on the producer's filesystem encoding), ``sort_keys=True`` and
compact ``(",", ":")`` separators.
"""

import json

from ts.canonical_json import canonical_json


def test_key_sorted_and_compact():
    document = {"b": 1, "a": {"d": 2, "c": 3}}
    assert canonical_json(document) == '{"a":{"c":3,"d":2},"b":1}'


def test_ascii_escapes_non_ascii_scalars():
    """Non-ASCII content becomes \\uXXXX escapes — bytes stay ASCII-only."""
    document = {"name": "频道", "pid": 1}
    serialized = canonical_json(document)
    assert serialized == '{"name":"\\u9891\\u9053","pid":1}'
    assert serialized.encode("utf-8").isascii()


def test_round_trip_recovers_the_original_value():
    """Escaping is a wire-form property only: parsing the canonical text
    recovers the original document (identity holds across locales)."""
    document = {"name": "频道", "nested": {"value": 1.5}}
    assert json.loads(canonical_json(document)) == document


def test_deterministic_across_calls_and_insertion_order():
    first = canonical_json({"x": 1, "y": 2})
    second = canonical_json({"y": 2, "x": 1})
    assert first == second
    assert canonical_json({"x": 1, "y": 2}) == first


def test_non_ascii_bytes_differ_from_ensure_ascii_false_form():
    """Pins the deliberate divergence from the raw-UTF-8 form: the helper
    never emits raw multi-byte UTF-8 (the unification decision for the
    three canonical call sites)."""
    document = {"k": "非"}
    assert "\\u" in canonical_json(document)
    assert canonical_json(document) != json.dumps(
        document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
