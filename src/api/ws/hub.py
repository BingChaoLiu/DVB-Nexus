"""WS session hub — connection lifecycle, cursor replay and live pump
(SPEC-501 §3/§5/§6, ticket #49, REQ-WS-501-001/002/003/004).

The hub is the transport-side seam between the #47 observation plane and
WebSocket connections:

- **commit fan-out**: the hub subscribes to the EventGateway's commit
  callbacks (``EventGateway.subscribe``) and routes each stamped envelope
  into the per-client :class:`api.ws.backpressure.ClientQueue` of every
  connection bound to that session. The hub never touches the ingestion
  path — it only consumes what the journal already committed (the
  observer boundary discipline, OBSERVATION-INTEGRATION-CONTRACT §9).
- **connection lifecycle** (:meth:`SessionHub.serve`, mounted by
  ``api.ws.router``): accept → session-directory check (close 4404) →
  wait for the §4.2 ``subscribe`` (route/session mismatch → close 4400)
  → register for fan-out → cursor replay from the SPEC-502 journal →
  ``ready`` → live pump (journal + hint frames) until disconnect,
  saturation (close 1013 + cursor) or pong timeout (close 1008).
- **cursor replay** (SPEC-501 §5): the client's ``last_journal_seq`` is
  replayed through ``journal.query(session_id, after_seq=cursor)`` — the
  seq order comes from the journal stamps, never from the transport
  (CONTEXT.md 流水号). Omitted cursor = live from now (no replay). Events
  committed during replay land via fan-out and are deduplicated at the
  pump against the replay watermark, so the combined stream is hole-free.
- **hints**: :meth:`SessionHub.publish_hint` routes record-state pointers
  (SPEC-305 §8 topics, validated by the frame layer) to session clients.

Threading posture: fan-out callbacks run on the journal drain thread and
hand items to per-client queues (thread-safe, non-blocking); the event
loop is woken via ``call_soon_threadsafe`` and the pump serializes frames.
"""
from __future__ import annotations

import asyncio
import threading
import time as _time
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from api.ws.backpressure import CoalescableOf, ClientQueue
from api.ws.frames import (
    CLOSE_PONG_TIMEOUT,
    CLOSE_SESSION_UNKNOWN,
    CLOSE_SLOW_CONSUMER,
    CLOSE_STORAGE_UNAVAILABLE,
    CLOSE_SUBSCRIBE_MISMATCH,
    WsFrameError,
    encode_hint_frame,
    encode_journal_frame,
    encode_pong,
    encode_ready,
    parse_upstream,
    slow_consumer_reason,
)


class JournalReader(Protocol):
    """Structural journal subset the hub replays from (SPEC-502 §5/§8).

    Typing-only duplicate of the #47 gateway's own ``EventJournal`` protocol
    shape (same precedent): the api layer may not import that module even
    transitively (ADR-0005 decision 4 — it imports domain), so the hub
    consumes the journal through this structural port. Rows are the
    SPEC-502 §5 ``EventRow`` shape (``journal_seq`` attribute + parsed
    ``envelope`` dict with the stamped seq).
    """

    def query(
        self, session_id: str, *, after_seq: int = 0, limit: int = 100
    ) -> Any: ...


class SessionDirectory(Protocol):
    """The session-existence seam (SPEC-501 §3: close 4404 on unknown/disposed).

    The authoritative session registry belongs to the simulation plane
    (ticket #41 is in flight); the hub consumes it through this port instead
    of fabricating session truth. ``None`` = unknown session; the literal
    ``"DISPOSED"`` status also closes 4404.
    """

    def status(self, session_id: str) -> str | None: ...


@dataclass(frozen=True)
class WsConfig:
    """Transport knobs (SPEC-501 §3/§6: 可配置 defaults).

    Defaults follow the spec's stated values; capacity/timeout re-tuning is
    hooked to OPEN-006 (#16) like every other backpressure constant.
    """

    #: Per-client bounded queue depth (§6).
    queue_depth: int = 256
    #: Journal replay read batch (SPEC-502 §8 query limit default).
    replay_batch_size: int = 100
    #: Server ping interval in seconds (§3; default 30s). The §3 "服务端周期
    #: ping" is realized as a downstream application-level ``{"type":"ping"}`
    #: probe — starlette 1.7's WebSocket API exposes no protocol-ping call,
    #: and ASGI servers consume protocol pongs below the app boundary, so
    #: the application frame layer is the only observable ping surface.
    #: A client answers per §4.2 (upstream ``ping`` → server ``pong``);
    #: any other upstream frame refreshes liveness too.
    heartbeat_interval: float = 30.0
    #: Client liveness window in seconds (§3; default 30s): no upstream
    #: frame within the window → close 1008 (pong timeout; §8 does not
    #: enumerate this code — deviation recorded in the ticket report).
    pong_timeout: float = 30.0
    #: Pump fallback poll (seconds) when no wake arrives.
    pump_poll: float = 0.05
    #: Artificial per-frame pacing (seconds, tests only; 0 = off).
    send_pace: float = 0.0


class _ClientState:
    """One connected client's queue + loop wake + delivery watermark."""

    def __init__(self, loop: asyncio.AbstractEventLoop, queue: ClientQueue) -> None:
        self.loop = loop
        self.queue = queue
        self.wake = asyncio.Event()
        self.closed = False

    def notify(self) -> None:
        """Wake the pump (thread-safe; fan-out may run on any thread)."""
        try:
            self.loop.call_soon_threadsafe(self.wake.set)
        except RuntimeError:
            # The connection's loop is already gone (client disconnected
            # between fan-out and wake) — nothing to wake, nothing lost:
            # the journal replay recovers everything (best-effort layer).
            pass


class SessionHub:
    """SPEC-501 transport hub: fan-out routing + connection lifecycle."""

    def __init__(
        self,
        journal: JournalReader,
        *,
        coalescable_of: CoalescableOf,
        config: WsConfig | None = None,
        session_directory: SessionDirectory | None = None,
    ) -> None:
        self._journal = journal
        self._coalescable_of = coalescable_of
        self._config = config or WsConfig()
        self._directory = session_directory
        self._clients: dict[str, list[_ClientState]] = {}
        #: Highest journal_seq seen per session through the fan-out stream —
        #: the "live from now" watermark for cursor-less subscribes (§5:
        #: 缺省 = 从当前起，不重放). The journal stays the authority for
        #: cursor replay; this only marks where the live stream starts.
        self._watermarks: dict[str, int] = {}
        self._registry_lock = threading.Lock()

    # --- commit fan-in (drain thread side) ------------------------------------

    def attach_gateway(self, gateway: Any) -> None:
        """Subscribe to the gateway's commit fan-out (SPEC-300 §7 step 5)."""
        gateway.subscribe(self._on_committed)

    def _on_committed(self, stamped: dict[str, Any]) -> None:
        """Route one freshly committed envelope to the session's clients.

        Runs on the drain thread: never blocks, never touches the socket.
        """
        scope = stamped.get("scope") or {}
        session_id = scope.get("session_id")
        if not session_id:
            return
        with self._registry_lock:
            seq = stamped.get("journal_seq")
            if isinstance(seq, int):
                if seq > self._watermarks.get(session_id, 0):
                    self._watermarks[session_id] = seq
            clients = tuple(self._clients.get(session_id, ()))
        for client in clients:
            client.queue.put_envelope(stamped)
            client.notify()

    def publish_hint(self, session_id: str, topic: str, data: dict[str, Any]) -> None:
        """Route one record-state pointer to the session's clients.

        Invalid topics raise :class:`WsFrameError` (the §4.1 five-topic
        contract); hints drop under a full client queue without ever
        saturating it (SPEC-501 §6: 丢的只是重复提示).
        """
        frame = encode_hint_frame(topic, data)  # validates the topic
        with self._registry_lock:
            clients = tuple(self._clients.get(session_id, ()))
        for client in clients:
            client.queue.put_hint(frame["topic"], frame["data"])
            client.notify()

    # --- connection lifecycle (event loop side) --------------------------------

    async def serve(self, websocket: Any, session_id: str) -> None:
        """Handle one WebSocket connection for one session (§3/§5/§6)."""
        await websocket.accept()
        if not self._session_admits(session_id):
            await websocket.close(
                code=CLOSE_SESSION_UNKNOWN, reason="session unknown or disposed"
            )
            return

        subscribe = await self._await_subscribe(websocket)
        if subscribe is None:
            return  # client vanished before subscribing; socket already closed
        if subscribe.session_id != session_id:
            await websocket.close(
                code=CLOSE_SUBSCRIBE_MISMATCH,
                reason="subscribe session_id does not match the route",
            )
            return

        client = _ClientState(
            loop=asyncio.get_running_loop(),
            queue=ClientQueue(self._config.queue_depth, coalescable_of=self._coalescable_of),
        )
        self._register(session_id, client)
        try:
            try:
                watermark = await self._replay(
                    websocket, session_id, subscribe.last_journal_seq
                )
            except Exception:
                # The 1011 close already went out in _replay; the client's
                # recovery path is reconnect + replay (SPEC-501 §8).
                return
            await websocket.send_json(encode_ready(replayed_from=watermark + 1))
            await self._live_phase(websocket, session_id, client, watermark)
        finally:
            self._unregister(session_id, client)

    # --- phases -------------------------------------------------------------------

    def _session_admits(self, session_id: str) -> bool:
        if self._directory is None:
            return True  # MVP wiring: no directory bound — do not fabricate truth
        status = self._directory.status(session_id)
        return status is not None and status != "DISPOSED"

    async def _await_subscribe(self, websocket: Any):
        """Read upstream frames until the §4.2 ``subscribe`` arrives.

        Application-level pings are answered while waiting. Returns ``None``
        when the client disconnects first.
        """
        while True:
            raw = await websocket.receive_json()
            if isinstance(raw, dict) and raw.get("type") == "ping":
                await websocket.send_json(encode_pong())
                continue
            try:
                msg = parse_upstream(raw)
            except WsFrameError as exc:
                await websocket.close(
                    code=CLOSE_SUBSCRIBE_MISMATCH, reason=f"malformed subscribe: {exc}"
                )
                return None
            if msg.type == "subscribe":
                return msg
            await websocket.close(
                code=CLOSE_SUBSCRIBE_MISMATCH,
                reason="the first upstream message must be subscribe",
            )
            return None

    async def _replay(
        self,
        websocket: Any,
        session_id: str,
        last_journal_seq: int | None,
    ) -> int:
        """Replay journal frames after the cursor; returns the watermark.

        The journal is the only order authority (SPEC-501 §5: 序号连续无洞).
        A journal failure closes 1011 — recovery is reconnect + replay (§8).
        """
        cursor = last_journal_seq
        if cursor is None:
            # No cursor = live from now (§5): everything committed up to this
            # subscribe is history the client opted out of replaying. The
            # watermark is the hub's own fan-out observation — never a
            # transport-fabricated order (stamped seqs only).
            with self._registry_lock:
                cursor = self._watermarks.get(session_id, 0)
        try:
            while True:
                rows = self._journal.query(
                    session_id, after_seq=cursor, limit=self._config.replay_batch_size
                )
                if not rows:
                    break
                for row in rows:
                    await websocket.send_json(encode_journal_frame(row.envelope))
                    cursor = row.journal_seq
                if len(rows) < self._config.replay_batch_size:
                    break
        except Exception:
            # Storage unavailable (adapters' error types are outside the api
            # layer's legal imports — any journal failure maps to 1011; the
            # client reconnects and the replay catches up, §8).
            await websocket.close(
                code=CLOSE_STORAGE_UNAVAILABLE,
                reason="journal unavailable; reconnect to replay",
            )
            raise
        return cursor

    async def _live_phase(
        self,
        websocket: Any,
        session_id: str,
        client: _ClientState,
        watermark: int,
    ) -> None:
        """Pump queue items as frames until a terminal condition.

        Terminal conditions: upstream disconnect (client closed), queue
        saturation (close 1013 + continuation cursor), or pong timeout
        (close 1008). Journal frames below the watermark (events that
        committed during the replay window and also rode the fan-out) are
        skipped — the combined stream stays hole-free and duplicate-free
        from the client's perspective.
        """
        last_sent_seq = watermark
        liveness = _Liveness(started_at=_time.monotonic())
        stop = asyncio.Event()
        upstream_task = asyncio.create_task(
            self._read_upstream(websocket, liveness, stop)
        )
        heartbeat_task = asyncio.create_task(
            self._heartbeat(websocket, self._config.heartbeat_interval)
        )
        try:
            while True:
                if client.queue.saturated:
                    await websocket.close(
                        code=CLOSE_SLOW_CONSUMER,
                        reason=slow_consumer_reason(last_sent_seq),
                    )
                    return
                if liveness.expired(self._config.pong_timeout):
                    await websocket.close(
                        code=CLOSE_PONG_TIMEOUT, reason="pong timeout"
                    )
                    return
                if stop.is_set():
                    return  # upstream disconnected; nothing more to pump
                items = client.queue.pop_batch()
                if not items:
                    await self._await_wake(client, stop)
                    continue
                for item in items:
                    if item.kind == "journal":
                        seq = item.seq
                        if seq is None or seq <= last_sent_seq:
                            continue  # replay/live overlap — already delivered
                        await websocket.send_json(encode_journal_frame(item.envelope))
                        last_sent_seq = seq
                    else:
                        await websocket.send_json(
                            encode_hint_frame(item.topic, item.data)
                        )
                    if self._config.send_pace > 0:
                        await asyncio.sleep(self._config.send_pace)
        finally:
            heartbeat_task.cancel()
            upstream_task.cancel()
            for task in (heartbeat_task, upstream_task):
                try:
                    await task
                except BaseException:
                    pass

    async def _await_wake(self, client: _ClientState, stop: asyncio.Event) -> None:
        """Wait for a fan-out wake or upstream stop, bounded by the poll.

        The bounded fallback poll keeps the pump responsive even if a wake
        was lost (e.g. a race with loop teardown) — cheap and correct.
        """
        waiter = asyncio.ensure_future(client.wake.wait())
        stopper = asyncio.ensure_future(stop.wait())
        try:
            await asyncio.wait(
                {waiter, stopper},
                timeout=self._config.pump_poll,
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            waiter.cancel()
            stopper.cancel()
        client.wake.clear()

    async def _heartbeat(self, websocket: Any, interval: float) -> None:
        """The §3 server-side periodic ping, at the application frame layer.

        See :attr:`WsConfig.heartbeat_interval` for why this is a downstream
        ``{"type":"ping"}`` frame rather than a protocol ping. Failures end
        the task silently — the pump's terminal conditions own the close.
        """
        while True:
            await asyncio.sleep(interval)
            try:
                await websocket.send_json({"type": "ping"})
            except Exception:
                return

    async def _read_upstream(
        self, websocket: Any, liveness: "_Liveness", stop: asyncio.Event
    ) -> None:
        """Serve upstream control traffic while the pump sends.

        Any received frame refreshes liveness (§3: the client proves it is
        alive between server pings); application-level pings are answered.
        A client disconnect ends the connection from the upstream side.
        """
        try:
            while True:
                raw = await websocket.receive_json()
                liveness.touch()
                if isinstance(raw, dict) and raw.get("type") == "ping":
                    await websocket.send_json(encode_pong())
        finally:
            stop.set()

    # --- registry --------------------------------------------------------------------

    def _register(self, session_id: str, client: _ClientState) -> None:
        with self._registry_lock:
            self._clients.setdefault(session_id, []).append(client)

    def _unregister(self, session_id: str, client: _ClientState) -> None:
        with self._registry_lock:
            clients = self._clients.get(session_id, [])
            if client in clients:
                clients.remove(client)
            if session_id in self._clients and not self._clients[session_id]:
                del self._clients[session_id]


class _Liveness:
    """Monotonic last-upstream-activity tracker for the §3 pong timeout."""

    def __init__(self, started_at: float) -> None:
        self._last = started_at

    def touch(self) -> None:
        self._last = _time.monotonic()

    def expired(self, timeout: float) -> bool:
        return (_time.monotonic() - self._last) > timeout
