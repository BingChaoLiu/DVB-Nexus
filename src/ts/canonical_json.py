"""Canonical JSON serialization — the shared determinism primitive.

One serialization for every cross-run identity fingerprint: the TS plan
fingerprint (SPEC-203 §5.2), the mutation-log bytes (ADR-0007 item 2) and
the scenario content hash (SPEC-205 §5). All three must agree on the byte
form or ``same input ⇒ same hash`` breaks at one site while holding at
another.

Contract (unified by the M3 code-review round; previously
``ensure_ascii=True`` at the plan-fingerprint/mutation-log sites and
``ensure_ascii=False`` at the scenario site):

- ``ensure_ascii=True`` — non-ASCII becomes ``\\uXXXX`` escapes, so the
  byte stream is ASCII-only and never depends on the producer's locale or
  filesystem encoding;
- ``sort_keys=True`` — key order is canonical, insertion order is not
  observable;
- ``separators=(",", ":")`` — compact form, no insignificant whitespace.

``ts`` is the lowest shared layer (imports no other project package), so
both ``faults`` and ``simulation`` may depend on it (ADR-0005 D4-4
import contracts).
"""

import json
from typing import Any

__all__ = ["canonical_json"]


def canonical_json(document: Any) -> str:
    """Serialize ``document`` to the canonical JSON string form."""
    return json.dumps(
        document, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )
