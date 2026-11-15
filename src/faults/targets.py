"""Fault target addressing (ADR-0006 item 3, SPEC-204 §3).

Targets are topology semantic slugs in the ADR-0006 item 3 dual form:

- node-level (state plane): the bare ``node_id`` slug, e.g. ``demux-0``;
- stream-level (SIM_TS, pid 0..0x1FFF): ``{node_id}:pid:0x{hex}``, e.g.
  ``demux-0:pid:0x0100``.

Fault event correlation addresses with the same forms (``correlation.
node_id`` alone = node-level; ``node_id + pid`` = stream-level).  All four
MVP fault types are stream-level PSI/CC faults, so their registry
validation requires the pid form; the node-level form stays parseable for
future state-plane fault types (SPEC-204 §3 target 寻址条款).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["FaultTarget", "parse_target_id"]

_PID_MAX = 0x1FFF

#: node_id semantic slug (ADR-0006 item 3: "demux-0" style).
_NODE_PATTERN = r"[A-Za-z0-9][A-Za-z0-9_-]*"
#: Stream-level: {node_id}:pid:0x{1..4 hex digits} (13-bit range checked below).
_STREAM_PATTERN = re.compile(
    rf"^(?P<node>{_NODE_PATTERN}):pid:0x(?P<pid>[0-9A-Fa-f]{{1,4}})$"
)
#: Node-level: bare {node_id}.
_NODE_ONLY_PATTERN = re.compile(rf"^{_NODE_PATTERN}$")


@dataclass(frozen=True)
class FaultTarget:
    """A parsed fault target (ADR-0006 item 3 dual form).

    ``pid`` is ``None`` for a node-level target; stream-level targets carry
    the 13-bit pid on the shared packet frame.
    """

    node_id: str
    pid: int | None


def parse_target_id(target_id: str) -> FaultTarget:
    """Parse a target slug into :class:`FaultTarget`.

    Malformed slugs raise ``ValueError`` — the caller (registry validator /
    prepare stage) turns that into ``SIM_FAULT_TARGET_INVALID`` (SPEC-204
    §11).  Whitespace, empty segments, missing ``0x`` prefixes, non-hex
    digits and out-of-range pids are all rejected (no silent coercion).
    """
    if isinstance(target_id, str):
        stream = _STREAM_PATTERN.match(target_id)
        if stream is not None:
            pid = int(stream.group("pid"), 16)
            if pid > _PID_MAX:
                raise ValueError(
                    f"target pid {target_id!r} exceeds the 13-bit range "
                    f"(0x0000..{_PID_MAX:#07x})"
                )
            return FaultTarget(node_id=stream.group("node"), pid=pid)
        if _NODE_ONLY_PATTERN.match(target_id) is not None:
            return FaultTarget(node_id=target_id, pid=None)
    raise ValueError(f"target_id {target_id!r} is not a valid fault target slug")
