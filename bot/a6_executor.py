#!/usr/bin/env python3
"""Phase-1 A-6 maker-only basket lifecycle."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import TypeAlias

try:
    from bot.a6_sum_scanner import A6MarketSnapshot, A6Opportunity, A6OpportunityLeg
    from bot.neg_risk_inventory import NegRiskInventory
except ImportError:  # pragma: no cover - direct script mode
    from a6_sum_scanner import A6MarketSnapshot, A6Opportunity, A6OpportunityLeg  # type: ignore
    from neg_risk_inventory import NegRiskInventory  # type: ignore


def _floor_quantity(value: float, decimals: int = 4) -> float:
    scale = 10**max(0, int(decimals))
    return math.floor(max(0.0, float(value)) * scale + 1e-12) / scale


def choose_maker_buy_price(*, best_bid: float, best_ask: float, tick_size: float, improvement_ticks: int = 1) -> float:
    tick = max(0.001, float(tick_size))
    bid = max(0.0, float(best_bid))
    ask = max(bid, float(best_ask))
    ceiling = max(0.0, ask - tick)
    if ceiling <= bid:
        return round(bid, 10)
    target = bid + (max(1, int(improvement_ticks)) * tick)
    return round(min(target, ceiling), 10)


def choose_maker_sell_price(*, best_bid: float, best_ask: float, tick_size: float) -> float:
    tick = max(0.001, float(tick_size))
    bid = max(0.0, float(best_bid))
    ask = max(bid, float(best_ask))
    if ask > bid:
        return round(max(bid + tick, ask - tick), 10)
    return round(bid + tick, 10)


class A6BasketState(str, Enum):
    DETECTED = "DETECTED"
    QUOTING = "QUOTING"
    PARTIAL = "PARTIAL"
    COMPLETE = "COMPLETE"
    MERGE_READY = "MERGE_READY"
    ABORTING = "ABORTING"
    ROLLED_BACK = "ROLLED_BACK"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True)
class A6ExecutorConfig:
    max_leg_notional_usd: float = 5.0
    max_open_baskets: int = 5
    max_daily_loss_usd: float = 5.0
    fill_timeout_ms: int = 3_000
    quote_improvement_ticks: int = 1
    max_reprices_per_leg: int = 1
    quantity_decimals: int = 4
    signature_type: int = 1


@dataclass(frozen=True)
class A6OrderCommand:
    action: str
    basket_id: str
    leg_id: str
    market_id: str
    token_id: str
    side: str
    quantity: float
    limit_price: float | None
    post_only: bool = True
    signature_type: int = 1
    replaces_order_id: str | None = None
    reason: str = ""


@dataclass(frozen=True)
class A6MergeReadyLeg:
    leg_id: str
    market_id: str
    condition_id: str
    token_id: str
    outcome_name: str
    filled_quantity: float
    avg_fill_price: float


@dataclass(frozen=True)
class A6LifecycleEvent:
    event_type: str
    basket_id: str
    event_id: str
    previous_state: str | None
    state: str
    reason: str
    ts: int
    theoretical_edge: float
    quoted_edge: float
    realized_profit_usd: float
    rollback_loss_usd: float
    capture_rate: float | None
    time_to_fill_ms: int | None
    one_sided_exposure_ms: int
    per_leg_fill_ratio: dict[str, float]
    invalidation_reasons: tuple[str, ...]


@dataclass(frozen=True)
class A6MergeReadyEvent:
    event_type: str
    basket_id: str
    signal_id: str
    event_id: str
    mergeable_quantity: float
    expected_redeem_value_usd: float
    filled_notional_usd: float
    quoted_notional_usd: float
    theoretical_profit_usd: float
    quoted_profit_usd: float
    emitted_at_ts: int
    legs: tuple[A6MergeReadyLeg, ...]


A6ExecutorEvent: TypeAlias = A6LifecycleEvent | A6MergeReadyEvent


@dataclass(frozen=True)
class A6ExecutorUpdate:
    basket: A6Basket
    commands: tuple[A6OrderCommand, ...]
    events: tuple[A6ExecutorEvent, ...]


@dataclass
class A6BasketLeg:
    leg_id: str
    market_id: str
    condition_id: str
    token_id: str
    outcome_name: str
    target_quantity: float
    best_bid: float
    best_ask: float
    tick_size: float
    quote_price: float
    order_id: str | None = None
    filled_quantity: float = 0.0
    avg_fill_price: float = 0.0
    replace_count: int = 0
    cancel_count: int = 0
    status: str = "pending"
    last_update_ts: int | None = None

    @property
    def remaining_quantity(self) -> float:
        return max(0.0, float(self.target_quantity) - float(self.filled_quantity))

    @property
    def fill_ratio(self) -> float:
        if self.target_quantity <= 0:
            return 0.0
        return min(1.0, float(self.filled_quantity) / float(self.target_quantity))

    def apply_fill(self, *, quantity: float, avg_price: float, ts: int, status: str) -> None:
        delta = max(0.0, min(float(quantity), self.remaining_quantity))
        if delta <= 0:
            self.status = status
            self.last_update_ts = int(ts)
            return
        new_total = self.filled_quantity + delta
        self.avg_fill_price = (
            ((self.avg_fill_price * self.filled_quantity) + (float(avg_price) * delta)) / new_total
        )
        self.filled_quantity = new_total
        self.status = status
        self.last_update_ts = int(ts)


@dataclass
class A6Basket:
    basket_id: str
    signal_id: str
    event_id: str
    state: A6BasketState
    threshold: float
    theoretical_edge: float
    quoted_edge: float
    target_quantity: float
    expected_payoff_usd: float
    theoretical_profit_usd: float
    quoted_profit_usd: float
    one_sided_loss_cap_usd: float
    legs: list[A6BasketLeg]
    detected_at_ts: int
    quoted_at_ts: int | None = None
    completed_at_ts: int | None = None
    current_quote_started_ts: int | None = None
    first_fill_ts: int | None = None
    last_fill_ts: int | None = None
    invalidation_reasons: list[str] = field(default_factory=list)
    rollback_loss_usd: float = 0.0
    realized_profit_usd: float = 0.0
    merge_ready_quantity_emitted: float = 0.0

    @property
    def has_any_fill(self) -> bool:
        return any(leg.filled_quantity > 0.0 for leg in self.legs)

    @property
    def is_complete(self) -> bool:
        return all(leg.remaining_quantity <= 1e-9 for leg in self.legs)

    @property
    def terminal(self) -> bool:
        return self.state in {
            A6BasketState.MERGE_READY,
            A6BasketState.ROLLED_BACK,
            A6BasketState.EXPIRED,
            A6BasketState.COMPLETE,
        }

    @property
    def open_legs(self) -> list[A6BasketLeg]:
        return [leg for leg in self.legs if leg.remaining_quantity > 1e-9]

    @property
    def filled_legs(self) -> list[A6BasketLeg]:
        return [leg for leg in self.legs if leg.filled_quantity > 0.0]

    @property
    def per_leg_fill_ratio(self) -> dict[str, float]:
        return {leg.leg_id: float(leg.fill_ratio) for leg in self.legs}

    @property
    def quoted_notional_usd(self) -> float:
        return float(sum(leg.target_quantity * leg.quote_price for leg in self.legs))

    @property
    def filled_notional_usd(self) -> float:
        return float(sum(leg.filled_quantity * leg.avg_fill_price for leg in self.legs))

    @property
    def one_sided_exposure_ms(self) -> int:
        if self.first_fill_ts is None:
            return 0
        end_ts = self.completed_at_ts or self.last_fill_ts or self.first_fill_ts
        return max(0, int(end_ts) - int(self.first_fill_ts))

    @property
    def time_to_fill_ms(self) -> int | None:
        if self.quoted_at_ts is None or self.completed_at_ts is None:
            return None
        return max(0, int(self.completed_at_ts) - int(self.quoted_at_ts))

    @property
    def capture_rate(self) -> float | None:
        if abs(self.theoretical_profit_usd) <= 1e-9:
            return None
        return float(self.realized_profit_usd) / float(self.theoretical_profit_usd)


class A6BasketExecutor:
    """Shadow-mode basket state machine for A-6 YES-basket execution."""

    def __init__(
        self,
        config: A6ExecutorConfig | None = None,
        inventory: NegRiskInventory | None = None,
    ) -> None:
        self.config = config or A6ExecutorConfig()
        self.inventory = inventory or NegRiskInventory()
        self._baskets: dict[str, A6Basket] = {}
        self._realized_pnl_usd = 0.0

    @property
    def baskets(self) -> dict[str, A6Basket]:
        return dict(self._baskets)

    @property
    def active_baskets(self) -> dict[str, A6Basket]:
        return {
            basket_id: basket
            for basket_id, basket in self._baskets.items()
            if basket.state not in {
                A6BasketState.MERGE_READY,
                A6BasketState.ROLLED_BACK,
                A6BasketState.EXPIRED,
                A6BasketState.COMPLETE,
            }
        }

    @property
    def remaining_daily_loss_usd(self) -> float:
        losses = max(0.0, -float(self._realized_pnl_usd))
        return max(0.0, float(self.config.max_daily_loss_usd) - losses)

    def submit_opportunity(self, opportunity: A6Opportunity, *, now_ts: int | None = None) -> A6ExecutorUpdate:
        now = int(now_ts or opportunity.detected_at_ts)
        self._validate_submission(opportunity)

        legs = self._build_basket_legs(opportunity)
        target_quantity = legs[0].target_quantity
        expected_payoff = float(target_quantity)
        theoretical_profit = float(opportunity.theoretical_edge * target_quantity)
        quoted_profit = float(expected_payoff - sum(leg.target_quantity * leg.quote_price for leg in legs))
        one_sided_loss_cap = min(theoretical_profit, self.remaining_daily_loss_usd)

        basket = A6Basket(
            basket_id=opportunity.basket_id,
            signal_id=opportunity.signal_id,
            event_id=opportunity.event_id,
            state=A6BasketState.DETECTED,
            threshold=float(opportunity.threshold),
            theoretical_edge=float(opportunity.theoretical_edge),
            quoted_edge=float(1.0 - sum(leg.quote_price for leg in legs)),
            target_quantity=float(target_quantity),
            expected_payoff_usd=float(expected_payoff),
            theoretical_profit_usd=float(theoretical_profit),
            quoted_profit_usd=float(quoted_profit),
            one_sided_loss_cap_usd=float(max(0.0, one_sided_loss_cap)),
            legs=legs,
            detected_at_ts=now,
        )
        self._baskets[basket.basket_id] = basket

        events: list[A6ExecutorEvent] = [
            self._make_lifecycle_event(basket, event_type="STATE", previous_state=None, reason="detected", ts=now)
        ]
        commands = self._place_initial_orders(basket, now_ts=now)
        events.append(
            self._make_lifecycle_event(
                basket,
                event_type="STATE",
                previous_state=A6BasketState.DETECTED.value,
                reason="orders_quoted",
                ts=now,
            )
        )
        return A6ExecutorUpdate(basket=basket, commands=tuple(commands), events=tuple(events))

    def apply_fill(
        self,
        basket_id: str,
        *,
        leg_id: str,
        filled_quantity: float,
        avg_price: float,
        now_ts: int | None = None,
        status: str = "filled",
    ) -> A6ExecutorUpdate:
        basket = self._require_basket(basket_id)
        now = int(now_ts or basket.detected_at_ts)
        if basket.state in {A6BasketState.EXPIRED, A6BasketState.ROLLED_BACK, A6BasketState.MERGE_READY}:
            return A6ExecutorUpdate(basket=basket, commands=tuple(), events=tuple())

        leg = self._require_leg(basket, leg_id)
        prior_filled = float(leg.filled_quantity)
        leg.apply_fill(quantity=filled_quantity, avg_price=avg_price, ts=now, status=status)
        delta = max(0.0, float(leg.filled_quantity) - prior_filled)
        if delta > 0:
            if basket.first_fill_ts is None:
                basket.first_fill_ts = now
            basket.last_fill_ts = now
            self.inventory.record_fill(
                event_id=basket.event_id,
                outcome=leg.outcome_name,
                side="YES",
                quantity=delta,
                price=float(avg_price),
            )

        events: list[A6ExecutorEvent] = []
        commands: list[A6OrderCommand] = []
        previous_state = basket.state.value

        if basket.is_complete:
            basket.completed_at_ts = now
            basket.realized_profit_usd = basket.expected_payoff_usd - basket.filled_notional_usd
            basket.state = A6BasketState.COMPLETE
            self._realized_pnl_usd += basket.realized_profit_usd
            events.append(
                self._make_lifecycle_event(
                    basket,
                    event_type="STATE",
                    previous_state=previous_state,
                    reason="all_legs_filled",
                    ts=now,
                )
            )
            merge_event = self._maybe_emit_merge_ready(basket, now_ts=now, promote_state=True)
            if merge_event is not None:
                events.append(merge_event)
            return A6ExecutorUpdate(basket=basket, commands=tuple(commands), events=tuple(events))

        if basket.has_any_fill and basket.state == A6BasketState.QUOTING:
            basket.state = A6BasketState.PARTIAL
            events.append(
                self._make_lifecycle_event(
                    basket,
                    event_type="STATE",
                    previous_state=previous_state,
                    reason="partial_fill_detected",
                    ts=now,
                )
            )

        merge_event = self._maybe_emit_merge_ready(basket, now_ts=now, promote_state=False)
        if merge_event is not None:
            events.append(merge_event)

        if basket.state == A6BasketState.PARTIAL and self._projected_rollback_loss_usd(basket) > basket.one_sided_loss_cap_usd > 0:
            update = self._abort_basket(
                basket,
                reason="one_sided_loss_cap_breached",
                now_ts=now,
            )
            return A6ExecutorUpdate(
                basket=update.basket,
                commands=tuple(commands) + update.commands,
                events=tuple(events) + update.events,
            )

        return A6ExecutorUpdate(basket=basket, commands=tuple(commands), events=tuple(events))

    def update_snapshot(
        self,
        basket_id: str,
        snapshot: A6MarketSnapshot,
        *,
        now_ts: int | None = None,
    ) -> A6ExecutorUpdate:
        basket = self._require_basket(basket_id)
        now = int(now_ts or snapshot.detected_at_ts)
        self._refresh_leg_books(basket, snapshot)
        if basket.state in {A6BasketState.COMPLETE, A6BasketState.MERGE_READY, A6BasketState.ROLLED_BACK, A6BasketState.EXPIRED}:
            return A6ExecutorUpdate(basket=basket, commands=tuple(), events=tuple())

        if snapshot.event_id != basket.event_id:
            return A6ExecutorUpdate(basket=basket, commands=tuple(), events=tuple())

        if not snapshot.executable or snapshot.sum_yes_ask is None or snapshot.sum_yes_ask >= basket.threshold:
            if snapshot.invalidation_reasons:
                basket.invalidation_reasons.extend(snapshot.invalidation_reasons)
            if basket.has_any_fill:
                return self._abort_basket(
                    basket,
                    reason="stale_book_invalidation" if snapshot.invalidation_reasons else "edge_collapsed",
                    now_ts=now,
                )
            return self._expire_basket(
                basket,
                reason="snapshot_invalidated_before_fill",
                now_ts=now,
            )

        return A6ExecutorUpdate(basket=basket, commands=tuple(), events=tuple())

    def advance_time(
        self,
        basket_id: str,
        *,
        now_ts: int,
        snapshot: A6MarketSnapshot | None = None,
    ) -> A6ExecutorUpdate:
        basket = self._require_basket(basket_id)
        now = int(now_ts)
        if snapshot is not None:
            self._refresh_leg_books(basket, snapshot)
            if snapshot.event_id == basket.event_id and (
                not snapshot.executable or snapshot.sum_yes_ask is None or snapshot.sum_yes_ask >= basket.threshold
            ):
                if basket.has_any_fill:
                    return self._abort_basket(basket, reason="edge_collapsed", now_ts=now)
                return self._expire_basket(basket, reason="no_fill_edge_collapsed", now_ts=now)

        if basket.state == A6BasketState.QUOTING:
            started = basket.current_quote_started_ts or basket.detected_at_ts
            if now - started >= int(self.config.fill_timeout_ms):
                return self._expire_basket(basket, reason="initial_fill_timeout", now_ts=now)
            return A6ExecutorUpdate(basket=basket, commands=tuple(), events=tuple())

        if basket.state == A6BasketState.PARTIAL:
            started = basket.current_quote_started_ts or basket.detected_at_ts
            if now - started < int(self.config.fill_timeout_ms):
                return A6ExecutorUpdate(basket=basket, commands=tuple(), events=tuple())

            reprice_update = self._maybe_reprice_open_legs(basket, now_ts=now)
            if reprice_update is not None:
                return reprice_update
            return self._abort_basket(basket, reason="partial_fill_timeout", now_ts=now)

        return A6ExecutorUpdate(basket=basket, commands=tuple(), events=tuple())

    def _validate_submission(self, opportunity: A6Opportunity) -> None:
        if opportunity.signal_type != "buy_yes_basket" or not opportunity.executable:
            raise ValueError("executor only accepts executable phase-1 buy_yes_basket opportunities")
        if len(self.active_baskets) >= int(self.config.max_open_baskets):
            raise ValueError("max active A-6 baskets reached")
        if self.remaining_daily_loss_usd <= 0.0:
            raise ValueError("daily loss cap exhausted")
        if not opportunity.legs:
            raise ValueError("opportunity has no executable legs")

    def _build_basket_legs(self, opportunity: A6Opportunity) -> list[A6BasketLeg]:
        quote_prices = [
            choose_maker_buy_price(
                best_bid=leg.best_bid,
                best_ask=leg.best_ask,
                tick_size=leg.tick_size,
                improvement_ticks=self.config.quote_improvement_ticks,
            )
            for leg in opportunity.legs
        ]
        max_quote = max(max(quote_prices), 0.001)
        target_quantity = _floor_quantity(
            float(self.config.max_leg_notional_usd) / max_quote,
            decimals=self.config.quantity_decimals,
        )
        if target_quantity <= 0.0:
            raise ValueError("basket quantity rounded to zero")

        legs: list[A6BasketLeg] = []
        for src, quote_price in zip(opportunity.legs, quote_prices):
            legs.append(
                A6BasketLeg(
                    leg_id=src.leg_id,
                    market_id=src.market_id,
                    condition_id=src.condition_id,
                    token_id=src.token_id,
                    outcome_name=src.outcome_name,
                    target_quantity=float(target_quantity),
                    best_bid=float(src.best_bid),
                    best_ask=float(src.best_ask),
                    tick_size=max(0.001, float(src.tick_size)),
                    quote_price=float(quote_price),
                )
            )
        return legs

    def _place_initial_orders(self, basket: A6Basket, *, now_ts: int) -> list[A6OrderCommand]:
        basket.state = A6BasketState.QUOTING
        basket.quoted_at_ts = int(now_ts)
        basket.current_quote_started_ts = int(now_ts)
        commands: list[A6OrderCommand] = []
        for leg in basket.legs:
            leg.order_id = self._order_id(basket.basket_id, leg.leg_id, leg.replace_count)
            leg.status = "open"
            commands.append(
                A6OrderCommand(
                    action="PLACE",
                    basket_id=basket.basket_id,
                    leg_id=leg.leg_id,
                    market_id=leg.market_id,
                    token_id=leg.token_id,
                    side="BUY",
                    quantity=float(leg.target_quantity),
                    limit_price=float(leg.quote_price),
                    signature_type=int(self.config.signature_type),
                    reason="initial_quote",
                )
            )
        return commands

    def _maybe_reprice_open_legs(self, basket: A6Basket, *, now_ts: int) -> A6ExecutorUpdate | None:
        commands: list[A6OrderCommand] = []
        for leg in basket.open_legs:
            if leg.replace_count >= int(self.config.max_reprices_per_leg):
                return None
            new_price = choose_maker_buy_price(
                best_bid=leg.best_bid,
                best_ask=leg.best_ask,
                tick_size=leg.tick_size,
                improvement_ticks=self.config.quote_improvement_ticks,
            )
            if new_price <= leg.quote_price + 1e-9:
                return None
            old_order_id = leg.order_id
            leg.replace_count += 1
            leg.quote_price = float(new_price)
            leg.order_id = self._order_id(basket.basket_id, leg.leg_id, leg.replace_count)
            leg.status = "repriced"
            leg.last_update_ts = int(now_ts)
            commands.append(
                A6OrderCommand(
                    action="REPLACE",
                    basket_id=basket.basket_id,
                    leg_id=leg.leg_id,
                    market_id=leg.market_id,
                    token_id=leg.token_id,
                    side="BUY",
                    quantity=float(leg.remaining_quantity),
                    limit_price=float(leg.quote_price),
                    signature_type=int(self.config.signature_type),
                    replaces_order_id=old_order_id,
                    reason="partial_timeout_reprice",
                )
            )

        if not commands:
            return None

        basket.current_quote_started_ts = int(now_ts)
        event = self._make_lifecycle_event(
            basket,
            event_type="REPRICE",
            previous_state=basket.state.value,
            reason="reprice_remaining_legs",
            ts=now_ts,
        )
        return A6ExecutorUpdate(basket=basket, commands=tuple(commands), events=(event,))

    def _expire_basket(self, basket: A6Basket, *, reason: str, now_ts: int) -> A6ExecutorUpdate:
        previous_state = basket.state.value
        basket.state = A6BasketState.EXPIRED
        commands = [
            A6OrderCommand(
                action="CANCEL",
                basket_id=basket.basket_id,
                leg_id=leg.leg_id,
                market_id=leg.market_id,
                token_id=leg.token_id,
                side="BUY",
                quantity=float(leg.remaining_quantity),
                limit_price=None,
                signature_type=int(self.config.signature_type),
                replaces_order_id=leg.order_id,
                reason=reason,
            )
            for leg in basket.open_legs
        ]
        for leg in basket.open_legs:
            leg.cancel_count += 1
            leg.status = "cancelled"
            leg.last_update_ts = int(now_ts)

        event = self._make_lifecycle_event(
            basket,
            event_type="STATE",
            previous_state=previous_state,
            reason=reason,
            ts=now_ts,
        )
        return A6ExecutorUpdate(basket=basket, commands=tuple(commands), events=(event,))

    def _abort_basket(self, basket: A6Basket, *, reason: str, now_ts: int) -> A6ExecutorUpdate:
        previous_state = basket.state.value
        basket.state = A6BasketState.ABORTING
        basket.invalidation_reasons.append(reason)

        commands: list[A6OrderCommand] = []
        for leg in basket.open_legs:
            commands.append(
                A6OrderCommand(
                    action="CANCEL",
                    basket_id=basket.basket_id,
                    leg_id=leg.leg_id,
                    market_id=leg.market_id,
                    token_id=leg.token_id,
                    side="BUY",
                    quantity=float(leg.remaining_quantity),
                    limit_price=None,
                    signature_type=int(self.config.signature_type),
                    replaces_order_id=leg.order_id,
                    reason=reason,
                )
            )
            leg.cancel_count += 1
            leg.status = "cancelled"
            leg.last_update_ts = int(now_ts)

        events: list[A6ExecutorEvent] = [
            self._make_lifecycle_event(
                basket,
                event_type="STATE",
                previous_state=previous_state,
                reason=reason,
                ts=now_ts,
            )
        ]

        rollback_loss = 0.0
        for leg in basket.filled_legs:
            rollback_order_price = choose_maker_sell_price(
                best_bid=leg.best_bid,
                best_ask=leg.best_ask,
                tick_size=leg.tick_size,
            )
            shadow_exit_price = max(0.0, float(leg.best_bid))
            rollback_loss += max(0.0, float(leg.avg_fill_price) - shadow_exit_price) * float(leg.filled_quantity)
            commands.append(
                A6OrderCommand(
                    action="ROLLBACK",
                    basket_id=basket.basket_id,
                    leg_id=leg.leg_id,
                    market_id=leg.market_id,
                    token_id=leg.token_id,
                    side="SELL",
                    quantity=float(leg.filled_quantity),
                    limit_price=float(rollback_order_price),
                    signature_type=int(self.config.signature_type),
                    reason=reason,
                )
            )
            self.inventory.record_fill(
                event_id=basket.event_id,
                outcome=leg.outcome_name,
                side="YES",
                quantity=-float(leg.filled_quantity),
                price=float(leg.avg_fill_price),
            )
            leg.status = "rolled_back"
            leg.last_update_ts = int(now_ts)

        basket.rollback_loss_usd = float(rollback_loss)
        basket.realized_profit_usd = float(-rollback_loss)
        self._realized_pnl_usd += basket.realized_profit_usd
        basket.state = A6BasketState.ROLLED_BACK
        events.append(
            self._make_lifecycle_event(
                basket,
                event_type="STATE",
                previous_state=A6BasketState.ABORTING.value,
                reason="rollback_completed",
                ts=now_ts,
            )
        )
        return A6ExecutorUpdate(basket=basket, commands=tuple(commands), events=tuple(events))

    def _refresh_leg_books(self, basket: A6Basket, snapshot: A6MarketSnapshot) -> None:
        by_market = {leg.market_id: leg for leg in snapshot.legs}
        for leg in basket.legs:
            snap_leg = by_market.get(leg.market_id)
            if snap_leg is None or snap_leg.yes_bid is None or snap_leg.yes_ask is None:
                continue
            leg.best_bid = float(snap_leg.yes_bid)
            leg.best_ask = float(snap_leg.yes_ask)
            leg.tick_size = max(0.001, float(snap_leg.tick_size))
            leg.last_update_ts = int(snapshot.detected_at_ts)

    def _maybe_emit_merge_ready(
        self,
        basket: A6Basket,
        *,
        now_ts: int,
        promote_state: bool,
    ) -> A6MergeReadyEvent | None:
        mergeable_quantity = self._mergeable_quantity(basket)
        if mergeable_quantity <= basket.merge_ready_quantity_emitted + 1e-9:
            return None

        basket.merge_ready_quantity_emitted = float(mergeable_quantity)
        if promote_state:
            basket.state = A6BasketState.MERGE_READY

        return A6MergeReadyEvent(
            event_type="MERGE_READY",
            basket_id=basket.basket_id,
            signal_id=basket.signal_id,
            event_id=basket.event_id,
            mergeable_quantity=float(mergeable_quantity),
            expected_redeem_value_usd=float(mergeable_quantity),
            filled_notional_usd=float(basket.filled_notional_usd),
            quoted_notional_usd=float(basket.quoted_notional_usd),
            theoretical_profit_usd=float(basket.theoretical_profit_usd),
            quoted_profit_usd=float(basket.quoted_profit_usd),
            emitted_at_ts=int(now_ts),
            legs=tuple(
                A6MergeReadyLeg(
                    leg_id=leg.leg_id,
                    market_id=leg.market_id,
                    condition_id=leg.condition_id,
                    token_id=leg.token_id,
                    outcome_name=leg.outcome_name,
                    filled_quantity=float(leg.filled_quantity),
                    avg_fill_price=float(leg.avg_fill_price),
                )
                for leg in basket.legs
            ),
        )

    def _mergeable_quantity(self, basket: A6Basket) -> float:
        if not basket.legs:
            return 0.0
        quantities = [
            self.inventory.quantity(basket.event_id, leg.outcome_name, "YES")
            for leg in basket.legs
        ]
        if not quantities or min(quantities) <= 0.0:
            return 0.0
        return float(min(quantities))

    def _projected_rollback_loss_usd(self, basket: A6Basket) -> float:
        loss = 0.0
        for leg in basket.filled_legs:
            shadow_exit_price = max(0.0, float(leg.best_bid))
            loss += max(0.0, float(leg.avg_fill_price) - shadow_exit_price) * float(leg.filled_quantity)
        return float(loss)

    def _make_lifecycle_event(
        self,
        basket: A6Basket,
        *,
        event_type: str,
        previous_state: str | None,
        reason: str,
        ts: int,
    ) -> A6LifecycleEvent:
        return A6LifecycleEvent(
            event_type=event_type,
            basket_id=basket.basket_id,
            event_id=basket.event_id,
            previous_state=previous_state,
            state=basket.state.value,
            reason=reason,
            ts=int(ts),
            theoretical_edge=float(basket.theoretical_edge),
            quoted_edge=float(basket.quoted_edge),
            realized_profit_usd=float(basket.realized_profit_usd),
            rollback_loss_usd=float(basket.rollback_loss_usd),
            capture_rate=basket.capture_rate,
            time_to_fill_ms=basket.time_to_fill_ms,
            one_sided_exposure_ms=basket.one_sided_exposure_ms,
            per_leg_fill_ratio=basket.per_leg_fill_ratio,
            invalidation_reasons=tuple(basket.invalidation_reasons),
        )

    @staticmethod
    def _order_id(basket_id: str, leg_id: str, replace_count: int) -> str:
        return f"{basket_id}:{leg_id}:r{int(replace_count)}"

    def _require_basket(self, basket_id: str) -> A6Basket:
        basket = self._baskets.get(basket_id)
        if basket is None:
            raise KeyError(f"unknown basket_id: {basket_id}")
        return basket

    @staticmethod
    def _require_leg(basket: A6Basket, leg_id: str) -> A6BasketLeg:
        for leg in basket.legs:
            if leg.leg_id == leg_id:
                return leg
        raise KeyError(f"unknown leg_id for basket {basket.basket_id}: {leg_id}")
