#!/usr/bin/env python3
"""Phase-1 B-1 two-leg shadow executor with deterministic rollback handling."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import time
from typing import Any

try:
    from bot.b1_monitor import B1Opportunity
except ImportError:  # pragma: no cover - direct script mode
    from b1_monitor import B1Opportunity  # type: ignore


def _now_ts() -> int:
    return int(time.time())


class BasketState(str, Enum):
    DETECTED = "DETECTED"
    QUOTING = "QUOTING"
    PARTIAL = "PARTIAL"
    HEDGED = "HEDGED"
    COMPLETE = "COMPLETE"
    ABORTING = "ABORTING"
    ROLLED_BACK = "ROLLED_BACK"
    EXPIRED = "EXPIRED"


TERMINAL_STATES = {
    BasketState.COMPLETE,
    BasketState.ROLLED_BACK,
    BasketState.EXPIRED,
}


@dataclass(frozen=True)
class B1ExecutorConfig:
    shadow_mode: bool = True
    signature_type: int = 1
    post_only: bool = True
    tick_size: float = 0.01
    fill_timeout_seconds: int = 30
    stale_book_seconds: int = 30
    max_leg_notional_usd: float = 5.0
    daily_loss_limit_usd: float = 5.0
    max_open_positions: int = 5
    max_cancel_replace: int = 1
    one_sided_loss_cap_usd: float = 5.0
    min_price: float = 0.01
    max_price: float = 0.99


@dataclass
class B1BasketLeg:
    leg_id: str
    market_id: str
    side: str
    target_qty: float
    best_bid: float
    best_ask: float
    updated_ts: int
    quote_price: float
    filled_qty: float = 0.0
    avg_fill_price: float = 0.0
    reprices: int = 0
    status: str = "QUOTED"
    quote_history: list[float] = field(default_factory=list)


@dataclass
class B1Basket:
    basket_id: str
    opportunity_id: str
    edge_id: str
    relation_type: str
    basket_action: str
    state: BasketState
    target_qty: float
    legs: list[B1BasketLeg]
    theoretical_edge: float
    quoted_edge: float
    filled_edge: float
    payoff_floor: float
    relation_confidence: float
    resolution_gate_status: str
    resolution_gate_reasons: tuple[str, ...]
    created_at_ts: int
    updated_at_ts: int
    detected_at_ts: int
    quoted_at_ts: int | None = None
    first_fill_ts: int | None = None
    last_fill_ts: int | None = None
    one_sided_exposure_started_ts: int | None = None
    one_sided_exposure_seconds: float = 0.0
    rollback_loss: float = 0.0
    realized_pnl: float = 0.0
    capture_rate: float = 0.0
    cancel_replace_count: int = 0
    false_positive_trace: list[str] = field(default_factory=list)
    transition_log: list[tuple[int, str, str]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    @property
    def expected_pnl_total(self) -> float:
        return self.theoretical_edge * self.target_qty


class B1Executor:
    """Shadow state machine for maker-only B-1 baskets."""

    def __init__(self, config: B1ExecutorConfig | None = None) -> None:
        self.config = config or B1ExecutorConfig()
        self._baskets: dict[str, B1Basket] = {}
        self._daily_realized_pnl = 0.0

    @property
    def daily_realized_pnl(self) -> float:
        return float(self._daily_realized_pnl)

    @property
    def baskets(self) -> dict[str, B1Basket]:
        return dict(self._baskets)

    def get_basket(self, basket_id: str) -> B1Basket | None:
        return self._baskets.get(basket_id)

    def submit(self, opportunity: B1Opportunity, *, now_ts: int | None = None) -> B1Basket | None:
        now_ts = int(now_ts or _now_ts())
        if self._daily_realized_pnl <= -self.config.daily_loss_limit_usd:
            return None
        if self._active_basket_count() >= self.config.max_open_positions:
            return None

        basket_id = hashlib.sha1(opportunity.opportunity_id.encode("utf-8")).hexdigest()[:20]
        existing = self._baskets.get(basket_id)
        if existing and not existing.is_terminal:
            return existing

        target_qty = self._target_quantity(opportunity)
        if target_qty <= 0:
            return None

        basket = B1Basket(
            basket_id=basket_id,
            opportunity_id=opportunity.opportunity_id,
            edge_id=opportunity.edge_id,
            relation_type=opportunity.relation_type,
            basket_action=opportunity.basket_action,
            state=BasketState.DETECTED,
            target_qty=target_qty,
            legs=[],
            theoretical_edge=float(opportunity.theoretical_edge),
            quoted_edge=0.0,
            filled_edge=0.0,
            payoff_floor=float(opportunity.payoff_floor),
            relation_confidence=float(opportunity.relation_confidence),
            resolution_gate_status=opportunity.resolution_gate_status,
            resolution_gate_reasons=tuple(opportunity.resolution_gate_reasons),
            created_at_ts=now_ts,
            updated_at_ts=now_ts,
            detected_at_ts=int(opportunity.detected_at_ts),
            transition_log=[(now_ts, BasketState.DETECTED.value, "created")],
            metadata={
                "shadow_mode": self.config.shadow_mode,
                "signature_type": self.config.signature_type,
                "post_only": self.config.post_only,
            },
        )
        self._baskets[basket_id] = basket
        return self._quote_basket(basket, opportunity, now_ts=now_ts)

    def sync_opportunity(
        self,
        basket_id: str,
        opportunity: B1Opportunity | None,
        *,
        now_ts: int | None = None,
    ) -> B1Basket:
        now_ts = int(now_ts or _now_ts())
        basket = self._require_basket(basket_id)
        if basket.is_terminal:
            return basket

        if opportunity is None:
            return self._expire_or_abort(basket, reason="violation_collapsed", now_ts=now_ts)

        self._apply_opportunity_quotes(basket, opportunity)
        if self._quotes_stale(basket, now_ts):
            return self._expire_or_abort(basket, reason="stale_book", now_ts=now_ts)
        if opportunity.theoretical_edge <= 0:
            return self._expire_or_abort(basket, reason="non_positive_edge", now_ts=now_ts)

        timed_out = self._timed_out(basket, now_ts)
        if timed_out:
            if basket.state == BasketState.QUOTING and self._total_filled_qty(basket) <= 0:
                if self._reprice_open_legs(basket, opportunity, now_ts=now_ts):
                    return basket
                return self._expire_or_abort(basket, reason="fill_timeout", now_ts=now_ts)
            return self._expire_or_abort(basket, reason="fill_timeout", now_ts=now_ts)

        if self._unhedged_notional(basket) > self.config.one_sided_loss_cap_usd:
            return self._expire_or_abort(basket, reason="one_sided_loss_cap", now_ts=now_ts)
        return basket

    def apply_fill(
        self,
        basket_id: str,
        leg_id: str,
        *,
        filled_qty: float,
        avg_price: float,
        status: str = "filled",
        now_ts: int | None = None,
    ) -> B1Basket:
        now_ts = int(now_ts or _now_ts())
        basket = self._require_basket(basket_id)
        if basket.is_terminal:
            return basket

        leg = self._require_leg(basket, leg_id)
        fill_qty = max(0.0, min(float(filled_qty), max(0.0, leg.target_qty - leg.filled_qty)))
        if fill_qty > 0:
            prev_notional = leg.avg_fill_price * leg.filled_qty
            new_qty = leg.filled_qty + fill_qty
            leg.avg_fill_price = (prev_notional + (fill_qty * float(avg_price))) / new_qty
            leg.filled_qty = new_qty
            leg.status = "FILLED" if new_qty + 1e-9 >= leg.target_qty else "PARTIAL"
            basket.first_fill_ts = basket.first_fill_ts or now_ts
            basket.last_fill_ts = now_ts
        else:
            leg.status = status.upper()

        basket.updated_at_ts = now_ts
        self._refresh_exposure_clock(basket, now_ts=now_ts)
        self._advance_fill_state(basket, now_ts=now_ts)
        if self._unhedged_notional(basket) > self.config.one_sided_loss_cap_usd:
            self._expire_or_abort(basket, reason="one_sided_loss_cap", now_ts=now_ts)
        return basket

    def summary_metrics(self) -> dict[str, float | int]:
        rolled_back = sum(1 for row in self._baskets.values() if row.state == BasketState.ROLLED_BACK)
        complete = sum(1 for row in self._baskets.values() if row.state == BasketState.COMPLETE)
        expired = sum(1 for row in self._baskets.values() if row.state == BasketState.EXPIRED)
        return {
            "active_baskets": self._active_basket_count(),
            "complete_baskets": complete,
            "rolled_back_baskets": rolled_back,
            "expired_baskets": expired,
            "daily_realized_pnl": round(self._daily_realized_pnl, 6),
        }

    def _quote_basket(self, basket: B1Basket, opportunity: B1Opportunity, *, now_ts: int) -> B1Basket:
        if opportunity.resolution_gate_status != "passed":
            return self._expire_or_abort(basket, reason="resolution_gate_failed", now_ts=now_ts)

        legs: list[B1BasketLeg] = []
        for source_leg in opportunity.legs:
            if now_ts - source_leg.updated_ts > self.config.stale_book_seconds:
                return self._expire_or_abort(basket, reason="stale_book", now_ts=now_ts)
            quote_price = _choose_passive_buy_price(
                best_bid=source_leg.best_bid,
                best_ask=source_leg.best_ask,
                tick_size=self.config.tick_size,
                min_price=self.config.min_price,
                max_price=self.config.max_price,
            )
            if quote_price is None:
                return self._expire_or_abort(basket, reason="no_passive_quote", now_ts=now_ts)
            legs.append(
                B1BasketLeg(
                    leg_id=source_leg.leg_id,
                    market_id=source_leg.market_id,
                    side=source_leg.side,
                    target_qty=basket.target_qty,
                    best_bid=float(source_leg.best_bid),
                    best_ask=float(source_leg.best_ask),
                    updated_ts=int(source_leg.updated_ts),
                    quote_price=float(quote_price),
                    quote_history=[float(quote_price)],
                )
            )

        basket.legs = legs
        basket.quoted_edge = basket.payoff_floor - sum(leg.quote_price for leg in basket.legs)
        if basket.quoted_edge <= 0:
            return self._expire_or_abort(basket, reason="non_positive_quoted_edge", now_ts=now_ts)

        basket.quoted_at_ts = now_ts
        self._set_state(basket, BasketState.QUOTING, reason="orders_posted", now_ts=now_ts)
        return basket

    def _apply_opportunity_quotes(self, basket: B1Basket, opportunity: B1Opportunity) -> None:
        leg_map = {(row.market_id, row.side): row for row in opportunity.legs}
        for leg in basket.legs:
            updated = leg_map.get((leg.market_id, leg.side))
            if updated is None:
                continue
            leg.best_bid = float(updated.best_bid)
            leg.best_ask = float(updated.best_ask)
            leg.updated_ts = int(updated.updated_ts)

    def _reprice_open_legs(self, basket: B1Basket, opportunity: B1Opportunity, *, now_ts: int) -> bool:
        leg_map = {(row.market_id, row.side): row for row in opportunity.legs}
        repriced = False
        for leg in basket.legs:
            if leg.filled_qty + 1e-9 >= leg.target_qty:
                continue
            if leg.reprices >= self.config.max_cancel_replace:
                return False

            source_leg = leg_map.get((leg.market_id, leg.side))
            if source_leg is None:
                return False
            if now_ts - source_leg.updated_ts > self.config.stale_book_seconds:
                return False

            new_price = _choose_passive_buy_price(
                best_bid=source_leg.best_bid,
                best_ask=source_leg.best_ask,
                tick_size=self.config.tick_size,
                min_price=self.config.min_price,
                max_price=self.config.max_price,
            )
            if new_price is None:
                return False

            leg.best_bid = float(source_leg.best_bid)
            leg.best_ask = float(source_leg.best_ask)
            leg.updated_ts = int(source_leg.updated_ts)
            leg.quote_price = float(new_price)
            leg.quote_history.append(float(new_price))
            leg.reprices += 1
            leg.status = "REPRICED"
            basket.cancel_replace_count += 1
            repriced = True

        if repriced:
            basket.quoted_edge = basket.payoff_floor - sum(leg.quote_price for leg in basket.legs)
            basket.quoted_at_ts = now_ts
            basket.updated_at_ts = now_ts
            basket.metadata["last_reprice_ts"] = now_ts
            return True
        return False

    def _advance_fill_state(self, basket: B1Basket, *, now_ts: int) -> None:
        filled = [leg for leg in basket.legs if leg.filled_qty > 0]
        all_complete = all(leg.filled_qty + 1e-9 >= leg.target_qty for leg in basket.legs)
        all_started = all(leg.filled_qty > 0 for leg in basket.legs)

        if all_complete:
            self._set_state(basket, BasketState.HEDGED, reason="hedge_complete", now_ts=now_ts)
            self._finalize_complete(basket, now_ts=now_ts)
            return

        if all_started:
            self._set_state(basket, BasketState.HEDGED, reason="both_legs_started", now_ts=now_ts)
            return

        if filled:
            self._set_state(basket, BasketState.PARTIAL, reason="one_sided_fill", now_ts=now_ts)

    def _finalize_complete(self, basket: B1Basket, *, now_ts: int) -> None:
        total_cost = sum(leg.avg_fill_price * leg.target_qty for leg in basket.legs)
        realized = (basket.payoff_floor * basket.target_qty) - total_cost
        basket.realized_pnl = float(realized)
        basket.rollback_loss = 0.0
        basket.filled_edge = float(realized / basket.target_qty) if basket.target_qty > 0 else 0.0
        basket.capture_rate = (
            float(realized / basket.expected_pnl_total)
            if abs(basket.expected_pnl_total) > 1e-9
            else 0.0
        )
        self._daily_realized_pnl += float(realized)
        self._refresh_exposure_clock(basket, now_ts=now_ts, terminal=True)
        self._set_state(basket, BasketState.COMPLETE, reason="all_legs_filled", now_ts=now_ts)

    def _expire_or_abort(self, basket: B1Basket, *, reason: str, now_ts: int) -> B1Basket:
        self._note_false_positive(basket, reason=reason, now_ts=now_ts)
        if self._total_filled_qty(basket) <= 0:
            self._refresh_exposure_clock(basket, now_ts=now_ts, terminal=True)
            self._set_state(basket, BasketState.EXPIRED, reason=reason, now_ts=now_ts)
            return basket

        self._set_state(basket, BasketState.ABORTING, reason=reason, now_ts=now_ts)
        realized = 0.0
        for leg in basket.legs:
            if leg.filled_qty <= 0:
                continue
            realized += leg.filled_qty * (leg.best_bid - leg.avg_fill_price)
            leg.status = "ROLLED_BACK"

        basket.realized_pnl = float(realized)
        basket.rollback_loss = float(max(0.0, -realized))
        basket.filled_edge = 0.0
        basket.capture_rate = (
            float(realized / basket.expected_pnl_total)
            if abs(basket.expected_pnl_total) > 1e-9
            else 0.0
        )
        self._daily_realized_pnl += float(realized)
        self._refresh_exposure_clock(basket, now_ts=now_ts, terminal=True)
        self._set_state(basket, BasketState.ROLLED_BACK, reason=reason, now_ts=now_ts)
        return basket

    def _refresh_exposure_clock(self, basket: B1Basket, *, now_ts: int, terminal: bool = False) -> None:
        unhedged = self._unhedged_notional(basket)
        if unhedged > 0 and basket.one_sided_exposure_started_ts is None and not terminal:
            basket.one_sided_exposure_started_ts = now_ts
            return

        if basket.one_sided_exposure_started_ts is not None and (unhedged <= 0 or terminal):
            basket.one_sided_exposure_seconds += float(now_ts - basket.one_sided_exposure_started_ts)
            basket.one_sided_exposure_started_ts = None

    def _timed_out(self, basket: B1Basket, now_ts: int) -> bool:
        anchor = basket.last_fill_ts or basket.quoted_at_ts or basket.created_at_ts
        return (now_ts - anchor) >= self.config.fill_timeout_seconds

    def _quotes_stale(self, basket: B1Basket, now_ts: int) -> bool:
        return any((now_ts - leg.updated_ts) > self.config.stale_book_seconds for leg in basket.legs)

    def _target_quantity(self, opportunity: B1Opportunity) -> float:
        cap = min(self.config.max_leg_notional_usd, self.config.one_sided_loss_cap_usd)
        if cap <= 0:
            return 0.0
        quantities = []
        for leg in opportunity.legs:
            if leg.best_ask <= 0:
                return 0.0
            quantities.append(cap / leg.best_ask)
        if not quantities:
            return 0.0
        return round(min(quantities), 6)

    def _unhedged_notional(self, basket: B1Basket) -> float:
        if not basket.legs:
            return 0.0
        hedged_qty = min(leg.filled_qty for leg in basket.legs)
        total = 0.0
        for leg in basket.legs:
            extra_qty = max(0.0, leg.filled_qty - hedged_qty)
            total += extra_qty * (leg.avg_fill_price or leg.quote_price)
        return float(total)

    def _total_filled_qty(self, basket: B1Basket) -> float:
        return float(sum(leg.filled_qty for leg in basket.legs))

    def _active_basket_count(self) -> int:
        return sum(1 for row in self._baskets.values() if row.state not in TERMINAL_STATES)

    def _note_false_positive(self, basket: B1Basket, *, reason: str, now_ts: int) -> None:
        basket.false_positive_trace.append(f"{now_ts}:{reason}")
        basket.updated_at_ts = now_ts

    @staticmethod
    def _set_state(basket: B1Basket, state: BasketState, *, reason: str, now_ts: int) -> None:
        if basket.state == state:
            return
        basket.state = state
        basket.updated_at_ts = now_ts
        basket.transition_log.append((now_ts, state.value, reason))

    @staticmethod
    def _require_leg(basket: B1Basket, leg_id: str) -> B1BasketLeg:
        for leg in basket.legs:
            if leg.leg_id == leg_id:
                return leg
        raise KeyError(f"unknown leg_id: {leg_id}")

    def _require_basket(self, basket_id: str) -> B1Basket:
        basket = self._baskets.get(basket_id)
        if basket is None:
            raise KeyError(f"unknown basket_id: {basket_id}")
        return basket


def _choose_passive_buy_price(
    *,
    best_bid: float,
    best_ask: float,
    tick_size: float,
    min_price: float,
    max_price: float,
) -> float | None:
    if best_bid < 0 or best_ask <= 0 or best_ask <= best_bid:
        return None
    candidate = best_bid + tick_size
    ceiling = min(best_ask - tick_size, max_price)
    if ceiling <= 0:
        return None
    price = min(candidate, ceiling)
    price = max(price, min_price)
    if price >= best_ask:
        return None
    return round(price, 4)
