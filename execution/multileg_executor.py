"""Generic state machine for maker-only multi-leg attempts."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
import time
from typing import Any


class MultiLegState(str, Enum):
    IDLE = "IDLE"
    ARMED = "ARMED"
    SIGNALLED = "SIGNALLED"
    ORDERS_LIVE = "ORDERS_LIVE"
    FILLED_ALL = "FILLED_ALL"
    FILLED_SOME = "FILLED_SOME"
    CANCELLED_NONE_FILLED = "CANCELLED_NONE_FILLED"
    SALVAGE = "SALVAGE"
    ROLLBACK = "ROLLBACK"
    DONE = "DONE"
    FROZEN = "FROZEN"


@dataclass(frozen=True)
class LegSpec:
    leg_id: str
    market_id: str
    token_id: str
    side: str
    price: float
    size: float
    tick_size: float = 0.01
    min_size: float = 0.0


@dataclass(frozen=True)
class LegFillUpdate:
    leg_id: str
    filled_size: float
    fill_price: float
    ts: float
    status: str = "filled"


@dataclass
class LegRuntime:
    spec: LegSpec
    order_id: str | None = None
    unwind_order_id: str | None = None
    filled_size: float = 0.0
    avg_fill_price: float = 0.0
    status: str = "pending"
    last_update_ts: float | None = None

    def apply_fill(self, update: LegFillUpdate) -> None:
        delta = max(0.0, float(update.filled_size))
        if delta <= 0:
            self.status = update.status
            self.last_update_ts = float(update.ts)
            return
        new_total = self.filled_size + delta
        if new_total <= 0:
            return
        self.avg_fill_price = (
            ((self.avg_fill_price * self.filled_size) + (float(update.fill_price) * delta)) / new_total
        )
        self.filled_size = new_total
        self.status = update.status
        self.last_update_ts = float(update.ts)


@dataclass(frozen=True)
class MultiLegExecutorConfig:
    small_attempt_fill_ttl_seconds: float = 20.0
    large_attempt_fill_ttl_seconds: float = 35.0
    unwind_ttl_seconds: float = 120.0
    total_unhedged_ttl_seconds: float = 300.0
    max_legs_per_attempt: int = 12


@dataclass
class MultiLegAttempt:
    attempt_id: str
    strategy_id: str
    group_id: str
    legs: list[LegRuntime]
    state: MultiLegState = MultiLegState.ARMED
    created_ts: float = field(default_factory=time.time)
    signal_ts: float | None = None
    orders_live_ts: float | None = None
    fill_ttl_seconds: float = 20.0
    unwind_started_ts: float | None = None
    frozen_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def filled_legs(self) -> list[LegRuntime]:
        return [leg for leg in self.legs if leg.filled_size > 0]

    @property
    def unfilled_legs(self) -> list[LegRuntime]:
        return [leg for leg in self.legs if leg.filled_size + 1e-9 < leg.spec.size]

    @property
    def complete(self) -> bool:
        return all(leg.filled_size + 1e-9 >= leg.spec.size for leg in self.legs)

    @property
    def has_any_fill(self) -> bool:
        return any(leg.filled_size > 0 for leg in self.legs)

    @property
    def exposure_slots(self) -> int:
        return len(self.filled_legs)


@dataclass(frozen=True)
class MultiLegDecision:
    next_state: MultiLegState
    reason: str
    should_cancel_open_orders: bool = False
    should_start_unwind: bool = False
    should_freeze_strategy: bool = False


class MultiLegExecutor:
    """Pure state machine for A-6/B-1 maker-only attempts."""

    def __init__(self, config: MultiLegExecutorConfig | None = None) -> None:
        self.config = config or MultiLegExecutorConfig()

    def create_attempt(
        self,
        *,
        attempt_id: str,
        strategy_id: str,
        group_id: str,
        leg_specs: list[LegSpec],
        metadata: dict[str, Any] | None = None,
        now_ts: float | None = None,
    ) -> MultiLegAttempt:
        if not leg_specs:
            raise ValueError("leg_specs cannot be empty")
        if len(leg_specs) > self.config.max_legs_per_attempt:
            raise ValueError("too many legs for a single attempt")
        fill_ttl = (
            self.config.large_attempt_fill_ttl_seconds
            if len(leg_specs) > 6
            else self.config.small_attempt_fill_ttl_seconds
        )
        return MultiLegAttempt(
            attempt_id=attempt_id,
            strategy_id=strategy_id,
            group_id=group_id,
            legs=[LegRuntime(spec=spec) for spec in leg_specs],
            state=MultiLegState.ARMED,
            created_ts=float(now_ts or time.time()),
            fill_ttl_seconds=float(fill_ttl),
            metadata=dict(metadata or {}),
        )

    def mark_signalled(self, attempt: MultiLegAttempt, *, now_ts: float | None = None) -> None:
        attempt.state = MultiLegState.SIGNALLED
        attempt.signal_ts = float(now_ts or time.time())

    def mark_orders_live(
        self,
        attempt: MultiLegAttempt,
        *,
        order_ids: dict[str, str],
        now_ts: float | None = None,
    ) -> None:
        for leg in attempt.legs:
            leg.order_id = order_ids.get(leg.spec.leg_id)
            leg.status = "live"
        attempt.state = MultiLegState.ORDERS_LIVE
        attempt.orders_live_ts = float(now_ts or time.time())

    def apply_fill(self, attempt: MultiLegAttempt, update: LegFillUpdate) -> None:
        for leg in attempt.legs:
            if leg.spec.leg_id != update.leg_id:
                continue
            leg.apply_fill(update)
            break
        if attempt.complete:
            attempt.state = MultiLegState.FILLED_ALL
        elif attempt.has_any_fill:
            attempt.state = MultiLegState.FILLED_SOME

    def evaluate(self, attempt: MultiLegAttempt, *, now_ts: float | None = None) -> MultiLegDecision:
        now = float(now_ts or time.time())

        if attempt.state == MultiLegState.FROZEN:
            return MultiLegDecision(MultiLegState.FROZEN, attempt.frozen_reason or "frozen")

        if attempt.complete:
            attempt.state = MultiLegState.FILLED_ALL
            return MultiLegDecision(MultiLegState.FILLED_ALL, "all_legs_filled")

        if attempt.state == MultiLegState.ORDERS_LIVE and attempt.signal_ts is not None:
            if now - attempt.signal_ts > attempt.fill_ttl_seconds:
                if not attempt.has_any_fill:
                    attempt.state = MultiLegState.CANCELLED_NONE_FILLED
                    return MultiLegDecision(
                        MultiLegState.CANCELLED_NONE_FILLED,
                        "fill_ttl_expired_without_fills",
                        should_cancel_open_orders=True,
                    )
                attempt.state = MultiLegState.ROLLBACK
                attempt.unwind_started_ts = now
                return MultiLegDecision(
                    MultiLegState.ROLLBACK,
                    "fill_ttl_expired_partial_fill",
                    should_cancel_open_orders=True,
                    should_start_unwind=True,
                )

        if attempt.state in {MultiLegState.FILLED_SOME, MultiLegState.ROLLBACK, MultiLegState.SALVAGE}:
            first_fill_ts = min(
                (leg.last_update_ts for leg in attempt.filled_legs if leg.last_update_ts is not None),
                default=None,
            )
            if first_fill_ts is not None and (now - first_fill_ts) > self.config.total_unhedged_ttl_seconds:
                attempt.state = MultiLegState.FROZEN
                attempt.frozen_reason = "UNHEDGED_EXPOSURE_TIMEOUT"
                return MultiLegDecision(
                    MultiLegState.FROZEN,
                    "unhedged_exposure_timeout",
                    should_cancel_open_orders=True,
                    should_freeze_strategy=True,
                )

        if attempt.state == MultiLegState.ROLLBACK and attempt.unwind_started_ts is not None:
            if now - attempt.unwind_started_ts > self.config.unwind_ttl_seconds:
                attempt.state = MultiLegState.FROZEN
                attempt.frozen_reason = "UNWIND_FAILED"
                return MultiLegDecision(
                    MultiLegState.FROZEN,
                    "unwind_ttl_expired",
                    should_cancel_open_orders=True,
                    should_freeze_strategy=True,
                )

        return MultiLegDecision(attempt.state, "no_transition")

    def mark_done(self, attempt: MultiLegAttempt) -> None:
        attempt.state = MultiLegState.DONE

    def freeze(self, attempt: MultiLegAttempt, *, reason: str) -> None:
        attempt.state = MultiLegState.FROZEN
        attempt.frozen_reason = reason
