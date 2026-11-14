"""Version policy constants (SPEC-500 §3, ticket #24).

The version path ``/api/v1`` is frozen: additive-only. New optional fields
are additive; removing/renaming fields or changing enum semantics are
breaking changes and require a new ``/api/v2``. The single-machine posture
(Q4) fixes ``tenant_id`` to ``"local"`` — the constant lives in
``application`` so future use-cases stamp it without importing ``api``.
"""

from __future__ import annotations

from api.versioning import API_V1_PREFIX, VERSION_POLICY
from application.context import LOCAL_TENANT_ID


def test_api_v1_prefix_is_frozen_value():
    assert API_V1_PREFIX == "/api/v1"


def test_version_policy_is_additive_only():
    assert VERSION_POLICY == "additive-only"


def test_local_tenant_id_constant():
    assert LOCAL_TENANT_ID == "local"
