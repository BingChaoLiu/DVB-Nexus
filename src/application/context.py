"""Single-machine request context constants (ticket #24, SPEC-500 §3).

SPEC-500 §3 (ticket #13 Q4): "单机单用户:服务绑定 ``127.0.0.1``,无认证,
``tenant_id`` 恒为 ``"local"``;token/多租户/远程访问为 non-goal".

The constant lives in ``application`` because M3 use-cases stamp the tenant
onto session/run context; ``api`` imports it from here (import-linter C6).
The 127.0.0.1 binding itself is a uvicorn deployment posture — documented in
``api`` (module docstrings + ``src/api/README.md``), never hardcoded into
the app factory.
"""

from __future__ import annotations

#: Fixed tenant identity for the MVP single-machine posture (SPEC-500 §3).
LOCAL_TENANT_ID = "local"
