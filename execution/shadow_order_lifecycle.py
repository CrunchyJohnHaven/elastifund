"""Synthetic maker-order lifecycle for shadow execution readiness."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import time
import uuid
from typing import Any, Mapping


class ShadowOrderState(str, Enum):
    RESTING = "resting"
    FILLED = "filled"
    PARTIAL = "partial"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    RESOLVED = "resolved"


@dataclass
class ShadowOrder:
    order_id: str
    market_id: str
    side: str
    reference_price: float
    size_usd: float
    expected_fill_probability: float
    expected_fill_window_seconds: float
    ttl_seconds: float
    created_ts: float
    expires_ts: float
    state: ShadowOrderState = ShadowOrderState.RESTING
    filled_size_usd: float = 0.0
    fill_price: float | None = None
    cancelled_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    markouts_bps: dict[str, float] = field(default_factory=dict)

    @property
    def dedup_key(self) -> str:
        return f"{self.market_id}:{self.side}"


class ShadowOrderLifecycle:
    """Tracks synthetic resting maker orders with TTL and markout windows."""

    def __init__(
        self,
        *,
        ttl_seconds: float = 120.0,
        expected_fill_window_seconds: float = 30.0,
        markout_windows_seconds: tuple[int, ...] = (5, 30, 120),
    ) -> None:
        self.ttl_seconds = max(1.0, float(ttl_seconds))
        self.expected_fill_window_seconds = max(1.0, float(expected_fill_window_seconds))
        self.markout_windows_seconds = tuple(sorted({int(max(1, window)) for window in markout_windows_seconds}))
        self._orders: dict[str, ShadowOrder] = {}
        self._active_by_key: dict[str, str] = {}

    def place_synthetic_order(
        self,
        *,
        market_id: str,
        side: str,
        reference_price: float,
        size_usd: float,
        expected_fill_probability: float,
        expected_fill_window_seconds: float | None = None,
        ttl_seconds: float | None = None,
        now_ts: float | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ShadowOrder | None:
        market_key = str(market_id).strip()
        side_key = str(side).strip().lower()
        if not market_key or not side_key:
            return None
        if float(size_usd) <= 0.0:
            return None
        if not 0.0 <= float(reference_price) <= 1.0:
            return None

        current = float(now_ts or time.time())
        key = f"{market_key}:{side_key}"
        active_order_id = self._active_by_key.get(key)
        if active_order_id:
            active = self._orders.get(active_order_id)
            if active and active.state in {ShadowOrderState.RESTING, ShadowOrderState.PARTIAL}:
                return None

        resolved_expected_window = (
            self.expected_fill_window_seconds
            if expected_fill_window_seconds is None
            else max(1.0, float(expected_fill_window_seconds))
        )
        resolved_ttl = self.ttl_seconds if ttl_seconds is None else max(1.0, float(ttl_seconds))
        order_id = f"shadow-{uuid.uuid4().hex[:12]}"
        order = ShadowOrder(
            order_id=order_id,
            market_id=market_key,
            side=side_key,
            reference_price=float(reference_price),
            size_usd=round(float(size_usd), 4),
            expected_fill_probability=max(0.0, min(1.0, float(expected_fill_probability))),
            expected_fill_window_seconds=resolved_expected_window,
            ttl_seconds=resolved_ttl,
            created_ts=current,
            expires_ts=current + resolved_ttl,
            metadata=dict(metadata or {}),
        )
        self._orders[order_id] = order
        self._active_by_key[key] = order_id
        return order

    def record_fill(
        self,
        order_id: str,
        *,
        fill_size_usd: float,
        fill_price: float | None = None,
    ) -> ShadowOrder | None:
        order = self._orders.get(str(order_id))
        if order is None:
            return None
        if order.state not in {ShadowOrderState.RESTING, ShadowOrderState.PARTIAL}:
            return order

        order.filled_size_usd = round(max(0.0, order.filled_size_usd + float(fill_size_usd)), 4)
        if fill_price is not None:
            order.fill_price = float(fill_price)
        if order.filled_size_usd + 1e-9 >= order.size_usd:
            order.state = ShadowOrderState.FILLED
            self._active_by_key.pop(order.dedup_key, None)
        elif order.filled_size_usd > 0:
            order.state = ShadowOrderState.PARTIAL
        return order

    def cancel(self, order_id: str, reason: str) -> ShadowOrder | None:
        order = self._orders.get(str(order_id))
        if order is None:
            return None
        if order.state not in {ShadowOrderState.RESTING, ShadowOrderState.PARTIAL}:
            return order
        order.state = ShadowOrderState.CANCELLED
        order.cancelled_reason = str(reason)
        self._active_by_key.pop(order.dedup_key, None)
        return order

    def expire(self, now_ts: float | None = None) -> int:
        current = float(now_ts or time.time())
        expired = 0
        for order in self._orders.values():
            if order.state not in {ShadowOrderState.RESTING, ShadowOrderState.PARTIAL}:
                continue
            if current < order.expires_ts:
                continue
            order.state = ShadowOrderState.EXPIRED
            order.cancelled_reason = "ttl_expired"
            self._active_by_key.pop(order.dedup_key, None)
            expired += 1
        return expired

    def record_markouts(
        self,
        *,
        now_ts: float | None = None,
        market_prices: Mapping[str, float],
    ) -> int:
        current = float(now_ts or time.time())
        updated = 0
        for order in self._orders.values():
            market_price = market_prices.get(order.market_id)
            if market_price is None:
                continue
            try:
                current_price = float(market_price)
            except (TypeError, ValueError):
                continue
            side_sign = 1.0 if order.side in {"buy_yes", "buy"} else -1.0
            for window in self.markout_windows_seconds:
                key = f"{window}s"
                if key in order.markouts_bps:
                    continue
                if current - order.created_ts < float(window):
                    continue
                markout_bps = (current_price - order.reference_price) * side_sign * 10_000.0
                order.markouts_bps[key] = round(markout_bps, 3)
                updated += 1
        return updated

    def to_report(self) -> dict[str, Any]:
        states: dict[str, int] = {}
        cancellation_reasons: dict[str, int] = {}
        markouts: dict[str, list[float]] = {}
        for order in self._orders.values():
            state_key = str(order.state.value)
            states[state_key] = states.get(state_key, 0) + 1
            if order.cancelled_reason:
                cancellation_reasons[order.cancelled_reason] = (
                    cancellation_reasons.get(order.cancelled_reason, 0) + 1
                )
            for window, value in order.markouts_bps.items():
                markouts.setdefault(window, []).append(float(value))

        markout_summary: dict[str, Any] = {}
        for window, values in sorted(markouts.items()):
            if not values:
                continue
            markout_summary[window] = {
                "count": len(values),
                "avg_bps": round(sum(values) / len(values), 3),
                "min_bps": round(min(values), 3),
                "max_bps": round(max(values), 3),
            }

        return {
            "orders_total": len(self._orders),
            "orders_active": len(self._active_by_key),
            "states": states,
            "cancellation_reasons": cancellation_reasons,
            "markouts_bps": markout_summary,
            "markout_windows_seconds": list(self.markout_windows_seconds),
        }

    def list_orders(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for order in sorted(self._orders.values(), key=lambda item: item.created_ts):
            out.append(
                {
                    "order_id": order.order_id,
                    "market_id": order.market_id,
                    "side": order.side,
                    "state": order.state.value,
                    "reference_price": order.reference_price,
                    "size_usd": order.size_usd,
                    "expected_fill_probability": order.expected_fill_probability,
                    "expected_fill_window_seconds": order.expected_fill_window_seconds,
                    "ttl_seconds": order.ttl_seconds,
                    "created_ts": order.created_ts,
                    "expires_ts": order.expires_ts,
                    "filled_size_usd": order.filled_size_usd,
                    "fill_price": order.fill_price,
                    "cancelled_reason": order.cancelled_reason,
                    "markouts_bps": dict(order.markouts_bps),
                    "metadata": dict(order.metadata),
                }
            )
        return out
