"""Deterministic session/run factory (SPEC-505 §4 ``session_run`` fixture,
serving SPEC-200/203).

Identity derivation is a pure hash of the seed — the same seed always
yields the same session_id/run_id, with **no wall clock participation**
(CONTEXT.md 确定性复现, SPEC-201: "相同配置 + 种子 + 引擎版本必须产生相同的
事件顺序与 TS 字节"). The clock config mirrors SPEC-201 §4
``SimulationClockConfig`` (frozen, rational integer speed, range-validated).

Seam note (ticket #22 report): this is the test-side factory. When the
SPEC-200 domain models land (concurrent ticket #21 / runtime tickets), the
fixture migrates to constructing real ``Session``/``SimulationClockConfig``
objects; the field names here already match SPEC-200 §4/SPEC-201 §4.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal

from tests._support.deterministic import check_seed

#: Fixed default seed of the shared factory instance (any constant works —
#: determinism, not secrecy; override per test via ``create(seed=...)``).
DEFAULT_SEED: int = 20260101

#: SPEC-201 §4 clock modes.
ClockMode = Literal["deterministic", "realtime"]

_VALID_MODES: tuple[str, ...] = ("deterministic", "realtime")


def _derive_hex(seed: int, prefix: str, domain_tag: bytes) -> str:
    digest = hashlib.blake2b(
        seed.to_bytes(8, "big", signed=False) + domain_tag, digest_size=8
    ).hexdigest()
    return f"{prefix}-{digest}"


@dataclass(frozen=True)
class SimulationClockConfig:
    """SPEC-201 §4 ``SimulationClockConfig`` mirror (frozen, validated)."""

    mode: ClockMode = "deterministic"
    start_time_ns: int = 0
    speed_num: int = 1
    speed_den: int = 1
    tick_quantum_ns: int = 1_000_000

    def __post_init__(self) -> None:
        if self.mode not in _VALID_MODES:
            raise ValueError(
                f"mode must be one of {_VALID_MODES} (SPEC-201 §4), got {self.mode!r}"
            )
        if self.start_time_ns < 0:
            raise ValueError(f"start_time_ns must be >= 0, got {self.start_time_ns}")
        if self.tick_quantum_ns <= 0:
            raise ValueError(
                f"tick_quantum_ns must be > 0 (SPEC-201 §4), got {self.tick_quantum_ns}"
            )
        if self.speed_num <= 0 or self.speed_den <= 0:
            raise ValueError(
                "speed_num/speed_den must both be > 0 (SPEC-201 §4 rational speed), "
                f"got {self.speed_num}/{self.speed_den}"
            )


@dataclass(frozen=True)
class SessionPlan:
    """Immutable session/run identity + deterministic configuration."""

    session_id: str
    run_id: str
    seed: int
    clock_config: SimulationClockConfig


class SessionRunFactory:
    """Deterministic session/run factory yielded by the ``session_run`` fixture.

    The factory itself is stateless (immutable defaults only); every
    ``create()`` call builds a brand-new frozen plan — no shared mutable
    state between tests (SPEC-505 §4 隔离纪律).
    """

    def __init__(self, default_seed: int = DEFAULT_SEED) -> None:
        self._default_seed = check_seed(default_seed)

    @property
    def default_seed(self) -> int:
        return self._default_seed

    def create(
        self,
        seed: int | None = None,
        clock_config: SimulationClockConfig | None = None,
    ) -> SessionPlan:
        """Build a fresh deterministic plan (same seed ⇒ same identity)."""
        effective_seed = check_seed(self._default_seed if seed is None else seed)
        effective_clock = clock_config if clock_config is not None else SimulationClockConfig()
        return SessionPlan(
            session_id=_derive_hex(effective_seed, "session", b"session-id"),
            run_id=_derive_hex(effective_seed, "run", b"run-id"),
            seed=effective_seed,
            clock_config=effective_clock,
        )
