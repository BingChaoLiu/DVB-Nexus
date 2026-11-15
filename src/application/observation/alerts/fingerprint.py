"""Alert fingerprint derivation (SPEC-304 §6, ticket #52).

REQ-OBS-304-004: 指纹 = 规则 ID + 配置的稳定维度派生；不含易变值或原始
payload 文本. The derivation hashes a canonical JSON document of the rule id
and the SORTED stable dimension mapping (values normalized to strings), so
insertion order, value type (``256`` vs ``"256"``) and reading values cannot
influence the token. Grouping/dedup scoping stays on the record's
tenant/session columns — the fingerprint itself is scope-free (SPEC-304 §6:
分组必须遵守 tenant/session scope, enforced by the store, not the hash).

Deterministic and stable across processes (pure hash of a canonical
document — no wall clock, no randomness, no uuid).
"""

from __future__ import annotations

import hashlib
import json
from typing import Mapping

#: Self-describing token prefix (schema example uses the ``sha256:`` label).
FINGERPRINT_PREFIX = "sha256:"


def alert_fingerprint(rule_id: str, group_dimensions: Mapping[str, object]) -> str:
    """Derive the dedup fingerprint for one alert group.

    ``group_dimensions`` carries ONLY the rule's configured stable dimensions
    (validated against the SPEC-302 baseline whitelist by the rule model);
    volatile values (metric readings, payload text, timestamps) have no path
    into this function.
    """
    document = {
        "rule_id": rule_id,
        "dimensions": {
            str(key): str(value) for key, value in sorted(group_dimensions.items())
        },
    }
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return FINGERPRINT_PREFIX + digest


__all__ = ["FINGERPRINT_PREFIX", "alert_fingerprint"]
