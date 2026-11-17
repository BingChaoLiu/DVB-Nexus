"""Artifact routes (SPEC-500 §4.6, ticket #48).

Read boundary over the #42 artifact storage adapter (SPEC-503 §5):

- ``GET /artifacts/{id}`` — metadata from the SPEC-502 index half;
  ``relative_path`` is forwarded verbatim and never absolute (SPEC-003
  §2.7). Unknown id → **404**.
- ``GET /artifacts/{id}/content`` — the download path goes through the
  store's ``read_by_artifact`` (artifact_id → index row → relative_path →
  local stream). Unknown id → 404; a verified-read digest mismatch is
  **corruption → 503** (SPEC-503 §7 row 4, ``OBS_STORAGE_WRITE_FAILURE``
  family) — both are raiser-owned via the application error categories, so
  the SPEC-500 §6 mapping stays declarative. Single-range ``Range``
  requests are honored with **206** + ``Content-Range``; a syntactically
  malformed header is 400, an unsatisfiable range is **416**
  (``Content-Range: bytes */size``) — HTTP download semantics outside the
  §6 application-category table, rendered through the same envelope.

``POST /artifacts/{id}/analyze`` (TSDuck re-analysis, SPEC-308) is mounted
per the frozen table but **501 Not Implemented**: the REST-facing analyze
job service is wired with the M4 diagnosis chain (SPEC-306) — the route
presence is the freeze obligation, the trigger semantics are not M3.

Backend seam: :class:`ArtifactsPort` is structural (import-linter C6); the
composition root binds it to ``adapters.storage.artifact_store.ArtifactStore``
+ the ``SqliteArtifactRepository`` index (consume-only).
"""

from __future__ import annotations

import re
from typing import Protocol

from fastapi import APIRouter, Request, Response
from starlette.exceptions import HTTPException

from api.dto.artifacts import ArtifactMetaDTO
from application.errors import BadRequestError, NotFoundError

__all__ = ["ArtifactsPort", "build_artifacts_router"]

#: Single-range ``Range`` header only (MVP): ``bytes=start-end`` /
#: ``bytes=start-`` / ``bytes=-suffix``. Multi-range is a 400.
_RANGE_PATTERN = re.compile(r"^bytes=(\d*)-(\d*)$")

_CONTENT_OCTET_STREAM = "application/octet-stream"


class ArtifactsPort(Protocol):
    """The #42 read boundary as seen from the REST layer.

    ``get_meta`` returns ``None`` for an unknown artifact (uniform 404).
    ``read_content`` raises ``NotFoundError`` (unknown id) or
    ``ServiceUnavailableError`` (corrupt content / storage unavailable) —
    the raiser owns the registry codes.
    """

    def get_meta(self, artifact_id: str) -> ArtifactMetaDTO | None: ...

    def read_content(self, artifact_id: str) -> bytes: ...

    def structure_view(
        self,
        artifact_id: str,
        *,
        view: str = "ts",
        expected_plp: int | None = None,
    ) -> dict:
        """The layered structure JSON face (#128, additive; the json_map
        chain assembly, SPEC-404 §Phase2 data source).  Raises
        ``NotFoundError`` (unknown id) / ``BadRequestError`` (unknown view
        or a plain MPEG-TS artifact)."""


def _parse_single_range(
    header_value: str | None, size: int
) -> tuple[int, int] | None:
    """Parse one ``bytes=`` range into an inclusive (start, end) slice.

    Returns ``None`` for an absent header (full download). Raises
    ``BadRequestError`` for malformed syntax and ``HTTPException(416)`` for
    an unsatisfiable range (RFC 9110 §14.2 single-range MVP posture).
    """
    if header_value is None:
        return None
    match = _RANGE_PATTERN.match(header_value.strip())
    if match is None or match.group(1) == match.group(2) == "":
        raise BadRequestError(
            "HTTP_RANGE_MALFORMED",
            f"unsupported Range header {header_value!r}: single "
            "'bytes=start-end' | 'bytes=start-' | 'bytes=-suffix' only",
        )
    start_text, end_text = match.groups()
    if start_text == "":
        # suffix form: last N bytes (clamped to the whole body when N>size).
        length = int(end_text)
        if length == 0:
            raise HTTPException(status_code=416, detail="unsatisfiable range")
        start = max(0, size - length)
        end = size - 1
    else:
        start = int(start_text)
        if start >= size:
            raise HTTPException(
                status_code=416,
                headers={"Content-Range": f"bytes */{size}"},
                detail="unsatisfiable range",
            )
        end = size - 1 if end_text == "" else min(int(end_text), size - 1)
        if end < start:
            raise BadRequestError(
                "HTTP_RANGE_MALFORMED",
                f"Range end {end_text} precedes start {start_text}",
            )
    return start, end


def build_artifacts_router(port: ArtifactsPort) -> APIRouter:
    """Build the §4.6 artifact router (mounted under the frozen prefix)."""
    router = APIRouter()

    @router.get("/artifacts/{artifact_id}", response_model=ArtifactMetaDTO)
    async def get_artifact(artifact_id: str) -> ArtifactMetaDTO:
        meta = port.get_meta(artifact_id)
        if meta is None:
            raise NotFoundError(
                "PLT_ARTIFACT_NOT_FOUND",
                f"unknown artifact {artifact_id!r} (SPEC-503 §7 row 3)",
            )
        return meta

    @router.get("/artifacts/{artifact_id}/content")
    async def get_artifact_content(artifact_id: str, request: Request) -> Response:
        data = port.read_content(artifact_id)
        size = len(data)
        range_slice = _parse_single_range(request.headers.get("range"), size)
        if range_slice is None:
            return Response(
                content=data,
                media_type=_CONTENT_OCTET_STREAM,
                headers={"Accept-Ranges": "bytes"},
            )
        start, end = range_slice
        return Response(
            content=data[start : end + 1],
            status_code=206,
            media_type=_CONTENT_OCTET_STREAM,
            headers={
                "Content-Range": f"bytes {start}-{end}/{size}",
                "Accept-Ranges": "bytes",
            },
        )

    @router.get("/artifacts/{artifact_id}/structure")
    async def get_artifact_structure(
        artifact_id: str,
        view: str = "ts",
        expected_plp: int | None = None,
    ) -> dict:
        """The layered structure JSON face (#128, additive; SPEC-404
        §Phase2 data source — the json_map chain assembly, keys = the
        upstream frozen projections).  Ports without the face keep the
        honest 501."""
        structure_face = getattr(port, "structure_view", None)
        if structure_face is None:
            raise HTTPException(
                status_code=501,
                detail=(
                    "artifact structure face is not wired on this "
                    "artifacts port"
                ),
            )
        return structure_face(artifact_id, view=view, expected_plp=expected_plp)

    @router.post("/artifacts/{artifact_id}/analyze", status_code=501)
    async def analyze_artifact(artifact_id: str) -> dict:
        # Frozen-table presence only: the TSDuck re-analysis trigger is
        # wired with the M4 diagnosis chain (SPEC-306/§4.6 note).
        raise HTTPException(
            status_code=501,
            detail=(
                "artifact analyze trigger is not implemented yet "
                "(TSDuck job service lands with the M4 diagnosis chain)"
            ),
        )

    return router
