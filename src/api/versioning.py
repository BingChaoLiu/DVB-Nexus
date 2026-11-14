"""API versioning policy (ticket #24, SPEC-500 §3).

SPEC-500 §3 freezes the version strategy — quoted verbatim as the binding
policy statement:

    版本路径 ``/api/v1`` **冻结**:只增不改——新增可选字段为 additive;
    删字段、改名、改枚举语义属破坏性变化,须开 ``/api/v2``。

Deprecation/breaking rules in force (per the quoted spec):

- Adding optional request/response fields: additive, allowed inside ``/api/v1``.
- Removing fields, renaming fields, changing enum semantics: breaking —
  forbidden inside ``/api/v1``; requires opening ``/api/v2``.
- Error-code additions are compatibility-reviewed per SPEC-300 §13 before
  entering the registry.

Every route ever mounted by ``api.app.create_app`` must live under
:data:`API_V1_PREFIX`; ``api.app`` enforces the prefix as the single mount
point, and the integration test suite asserts the OpenAPI path invariant.
"""

from __future__ import annotations

#: Frozen version path prefix (SPEC-500 §3). All routes mount under it.
API_V1_PREFIX = "/api/v1"

#: Version token of the frozen prefix, without the leading slash.
API_VERSION_TOKEN = "v1"

#: The only allowed evolution strategy inside ``/api/v1`` (SPEC-500 §3).
VERSION_POLICY = "additive-only"
