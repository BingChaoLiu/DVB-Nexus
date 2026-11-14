"""API layer: HTTP/WS protocol, request/response models and connection management.

Depends only on ``application`` (ADR-0005 decision 4); must not contain TS
binary encoding details (SPEC-001 section 3.2) and must not touch Domain or
Adapters packages directly.
"""

from api.app import create_app

__all__ = ["create_app"]
