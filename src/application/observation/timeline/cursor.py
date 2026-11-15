"""Opaque timeline pagination cursor (SPEC-303 §6, REQ-OBS-303-004).

The cursor token is opaque to clients: base64url over a canonical JSON
document binding the session scope, the filter fingerprint, the resume
position and the anchor record id. Binding rules:

- scope binding: the token carries ``session_id``; replaying it against a
  query for another session is an expired cursor (``OBS_CURSOR_EXPIRED``);
- filter binding: ``filter_hash`` is the SHA-256 of the canonical filter
  document — replaying an old cursor under a changed filter MUST fail
  (SPEC-303 §10);
- anchor binding: the token records the record id at the resume position;
  if that record no longer sits there (deleted/tombstoned or reordered),
  the cursor is expired instead of silently skipping or duplicating.

Serialization is deterministic (``sort_keys`` canonical JSON), so equal
cursor states encode to equal tokens — export/query reproducibility never
depends on dict ordering. Any decode failure (bad base64, unknown version,
missing fields, wrong types) surfaces as expired, never as a raw parse
error: clients get one structured signal to restart from page one.
"""

from __future__ import annotations

import base64
import binascii
import dataclasses
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from application.observation.timeline.errors import OBS_CURSOR_EXPIRED, TimelineError

_CURSOR_VERSION = 1


@dataclass(frozen=True)
class TimelineCursorState:
    """The decoded cursor payload (SPEC-303 §6 binding fields)."""

    session_id: str
    filter_hash: str
    position: int
    anchor_record_id: str


def filter_fingerprint(filter_obj: Any) -> str:
    """SHA-256 of the canonical filter document (the cursor's filter half).

    Structural: any frozen dataclass filter works — the field set itself is
    the contract, so a changed filter always changes the fingerprint.
    """
    document = dataclasses.asdict(filter_obj)
    canonical = json.dumps(
        document, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def encode_cursor(state: TimelineCursorState) -> str:
    """Serialize the cursor state to an opaque token (deterministic)."""
    payload = {
        "v": _CURSOR_VERSION,
        "session_id": state.session_id,
        "filter_hash": state.filter_hash,
        "position": state.position,
        "anchor_record_id": state.anchor_record_id,
    }
    raw = json.dumps(
        payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_cursor(token: str) -> TimelineCursorState:
    """Decode an opaque token; ANY failure is an expired cursor.

    Raises :class:`TimelineError` with ``OBS_CURSOR_EXPIRED`` — malformed,
    tampered, unknown-version and truncated tokens all get the single
    structured expiry signal (SPEC-303 §6).
    """
    try:
        padded = token + "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict) or payload.get("v") != _CURSOR_VERSION:
            raise ValueError("unsupported cursor version")
        return TimelineCursorState(
            session_id=_required_str(payload, "session_id"),
            filter_hash=_required_str(payload, "filter_hash"),
            position=_required_int(payload, "position"),
            anchor_record_id=_required_str(payload, "anchor_record_id"),
        )
    except (ValueError, TypeError, KeyError) as exc:
        # binascii.Error subclasses ValueError; json/KeyError/TypeError cover
        # the rest of the malformed-token family.
        raise TimelineError(
            OBS_CURSOR_EXPIRED,
            f"cursor token is malformed or expired (SPEC-303 §6): {exc}",
            details={"reason": "malformed_token"},
        ) from exc


def _required_str(payload: dict, key: str) -> str:
    value = payload[key]
    if not isinstance(value, str) or not value:
        raise ValueError(f"cursor field {key!r} must be a non-empty string")
    return value


def _required_int(payload: dict, key: str) -> int:
    value = payload[key]
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"cursor field {key!r} must be a non-negative int")
    return value


__all__ = ["TimelineCursorState", "decode_cursor", "encode_cursor", "filter_fingerprint"]
