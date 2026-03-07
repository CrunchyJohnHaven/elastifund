#!/usr/bin/env python3
"""Phase-1 A-6 executable YES-sum scanner."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import time
from typing import TYPE_CHECKING, Mapping, Sequence

try:
    from bot.resolution_normalizer import (
        NormalizedMarket,
        outcome_block_reasons,
        selected_outcome_for_market,
    )
except ImportError:  # pragma: no cover - direct script mode
    from resolution_normalizer import (  # type: ignore
        NormalizedMarket,
        outcome_block_reasons,
        selected_outcome_for_market,
    )

if TYPE_CHECKING:  # pragma: no cover - typing only
    try:
        from bot.constraint_arb_engine import ConstraintArbEngine, MarketQuote
    except ImportError:  # pragma: no cover - direct script mode
        from constraint_arb_engine import ConstraintArbEngine, MarketQuote  # type: ignore


def _now_ts() -> int:
    return int(time.time())


def _round_bucket(value: float, *, multiplier: int = 10_000) -> int:
    return int(round(float(value) * float(multiplier)))


@dataclass(frozen=True)
class A6ScannerConfig:
    buy_threshold: float = 0.97
    upper_signal_threshold: float = 1.03
    stale_quote_seconds: int = 30
    dedupe_window_seconds: int = 15


@dataclass(frozen=True)
class A6LegSnapshot:
    leg_id: str
    market_id: str
    condition_id: str
    token_id: str
    outcome_name: str
    yes_bid: float | None
    yes_ask: float | None
    tick_size: float
    updated_ts: int | None
    fresh: bool
    executable: bool
    invalidation_reasons: tuple[str, ...]

    @property
    def spread(self) -> float | None:
        if self.yes_bid is None or self.yes_ask is None:
            return None
        return max(0.0, float(self.yes_ask) - float(self.yes_bid))


@dataclass(frozen=True)
class A6MarketSnapshot:
    event_id: str
    event_label: str
    category: str
    resolution_key: str
    detected_at_ts: int
    legs: tuple[A6LegSnapshot, ...]
    expected_legs: int
    fresh_legs: int
    executable: bool
    invalidation_reasons: tuple[str, ...]
    missing_leg_ids: tuple[str, ...]
    stale_leg_ids: tuple[str, ...]
    blocked_leg_ids: tuple[str, ...]
    sum_yes_ask: float | None
    sum_yes_bid: float | None


@dataclass(frozen=True)
class A6OpportunityLeg:
    leg_id: str
    market_id: str
    condition_id: str
    token_id: str
    outcome_name: str
    best_bid: float
    best_ask: float
    tick_size: float


@dataclass(frozen=True)
class A6Opportunity:
    signal_id: str
    basket_id: str
    event_id: str
    signal_type: str
    executable: bool
    threshold: float
    theoretical_edge: float
    sum_yes_ask: float | None
    sum_yes_bid: float | None
    detected_at_ts: int
    invalidation_reasons: tuple[str, ...]
    legs: tuple[A6OpportunityLeg, ...]


@dataclass(frozen=True)
class A6ScanBatch:
    scanned_at_ts: int
    snapshots: tuple[A6MarketSnapshot, ...]
    opportunities: tuple[A6Opportunity, ...]


class A6SumScanner:
    """Build executable multi-outcome snapshots and phase-1 A-6 signals."""

    def __init__(self, config: A6ScannerConfig | None = None) -> None:
        self.config = config or A6ScannerConfig()
        self._recent_signals: dict[tuple[str, str, int], int] = {}

    def build_event_snapshots(
        self,
        *,
        markets: Sequence[NormalizedMarket],
        quotes: Mapping[str, MarketQuote],
        now_ts: int | None = None,
    ) -> tuple[A6MarketSnapshot, ...]:
        now = int(now_ts or _now_ts())
        by_event: dict[str, list[NormalizedMarket]] = {}
        for market in markets:
            if not (market.profile.is_neg_risk or market.is_multi_outcome):
                continue
            by_event.setdefault(market.event_id, []).append(market)

        snapshots: list[A6MarketSnapshot] = []
        for event_id, event_markets in sorted(by_event.items()):
            tradable = self._tradable_markets(event_markets)
            if len(tradable) < 2:
                continue

            legs: list[A6LegSnapshot] = []
            missing_leg_ids: list[str] = []
            stale_leg_ids: list[str] = []
            blocked_leg_ids: list[str] = []
            invalidation_reasons: list[str] = []
            fresh_legs = 0

            for market in sorted(tradable, key=lambda item: ((item.outcome or "").lower(), item.market_id)):
                leg = self._build_leg_snapshot(market=market, quote=quotes.get(market.market_id), now_ts=now)
                legs.append(leg)
                if leg.fresh:
                    fresh_legs += 1
                if not leg.executable:
                    blocked_leg_ids.append(leg.market_id)
                    invalidation_reasons.extend(leg.invalidation_reasons)
                if "quote_missing" in leg.invalidation_reasons or "missing_yes_token" in leg.invalidation_reasons:
                    missing_leg_ids.append(leg.market_id)
                if "stale_quote" in leg.invalidation_reasons:
                    stale_leg_ids.append(leg.market_id)

            executable_legs = [leg for leg in legs if leg.executable]
            executable = len(executable_legs) == len(legs)
            sum_yes_ask = (
                float(sum(leg.yes_ask or 0.0 for leg in executable_legs))
                if executable_legs
                else None
            )
            sum_yes_bid = (
                float(sum(leg.yes_bid or 0.0 for leg in executable_legs))
                if executable_legs
                else None
            )

            snapshots.append(
                A6MarketSnapshot(
                    event_id=event_id,
                    event_label=self._event_label(tradable),
                    category=tradable[0].category,
                    resolution_key=tradable[0].resolution_key,
                    detected_at_ts=now,
                    legs=tuple(legs),
                    expected_legs=len(legs),
                    fresh_legs=fresh_legs,
                    executable=executable,
                    invalidation_reasons=tuple(dict.fromkeys(invalidation_reasons)),
                    missing_leg_ids=tuple(sorted(set(missing_leg_ids))),
                    stale_leg_ids=tuple(sorted(set(stale_leg_ids))),
                    blocked_leg_ids=tuple(sorted(set(blocked_leg_ids))),
                    sum_yes_ask=(sum_yes_ask if executable else None),
                    sum_yes_bid=(sum_yes_bid if executable else None),
                )
            )

        return tuple(snapshots)

    def scan_snapshots(
        self,
        snapshots: Sequence[A6MarketSnapshot],
        *,
        now_ts: int | None = None,
    ) -> tuple[A6Opportunity, ...]:
        now = int(now_ts or _now_ts())
        self._trim_recent(now)

        opportunities: list[A6Opportunity] = []
        for snapshot in snapshots:
            if snapshot.executable and snapshot.sum_yes_ask is not None and snapshot.sum_yes_ask < self.config.buy_threshold:
                if self._is_duplicate(snapshot.event_id, "buy_yes_basket", snapshot.sum_yes_ask, now):
                    continue
                opportunities.append(self._make_opportunity(snapshot, signal_type="buy_yes_basket", executable=True))
                continue

            if snapshot.sum_yes_bid is not None and snapshot.sum_yes_bid > self.config.upper_signal_threshold:
                if self._is_duplicate(snapshot.event_id, "unwind_inventory_only", snapshot.sum_yes_bid, now):
                    continue
                opportunities.append(
                    self._make_opportunity(snapshot, signal_type="unwind_inventory_only", executable=False)
                )

        return tuple(opportunities)

    def scan_engine(self, engine: ConstraintArbEngine, *, now_ts: int | None = None) -> A6ScanBatch:
        now = int(now_ts or _now_ts())
        snapshots = self.build_event_snapshots(
            markets=list(engine.markets.values()),
            quotes=engine.quotes,
            now_ts=now,
        )
        opportunities = self.scan_snapshots(snapshots, now_ts=now)
        return A6ScanBatch(
            scanned_at_ts=now,
            snapshots=tuple(snapshots),
            opportunities=tuple(opportunities),
        )

    def _build_leg_snapshot(
        self,
        *,
        market: NormalizedMarket,
        quote: MarketQuote | None,
        now_ts: int,
    ) -> A6LegSnapshot:
        reasons = list(outcome_block_reasons(market, selected_outcome_for_market(market)))
        token_id = str(market.yes_token_id or "").strip()
        if not token_id:
            reasons.append("missing_yes_token")
        if not market.accepting_orders:
            reasons.append("market_not_accepting_orders")
        if not market.enable_order_book:
            reasons.append("order_book_disabled")

        yes_bid: float | None = None
        yes_ask: float | None = None
        updated_ts: int | None = None
        if quote is None:
            reasons.append("quote_missing")
        else:
            updated_ts = int(quote.updated_ts)
            yes_bid = float(quote.yes_bid)
            yes_ask = float(quote.yes_ask)
            if yes_bid < 0.0 or yes_ask < 0.0 or yes_bid > 1.0 or yes_ask > 1.0:
                reasons.append("invalid_price_bounds")
            elif yes_ask < yes_bid:
                reasons.append("crossed_book")
            if now_ts - updated_ts > self.config.stale_quote_seconds:
                reasons.append("stale_quote")

        executable = not reasons
        return A6LegSnapshot(
            leg_id=f"{market.market_id}:YES",
            market_id=market.market_id,
            condition_id=market.market_id,
            token_id=token_id,
            outcome_name=selected_outcome_for_market(market),
            yes_bid=yes_bid,
            yes_ask=yes_ask,
            tick_size=max(0.001, float(market.tick_size)),
            updated_ts=updated_ts,
            fresh="stale_quote" not in reasons and updated_ts is not None,
            executable=executable,
            invalidation_reasons=tuple(dict.fromkeys(reasons)),
        )

    @staticmethod
    def _event_label(markets: Sequence[NormalizedMarket]) -> str:
        questions = {market.question.strip() for market in markets if market.question.strip()}
        if len(questions) == 1:
            return next(iter(questions))
        longest = max(questions, key=len, default="")
        return longest or markets[0].event_id

    @staticmethod
    def _tradable_markets(markets: Sequence[NormalizedMarket]) -> list[NormalizedMarket]:
        tradable: list[NormalizedMarket] = []
        for market in markets:
            outcome = selected_outcome_for_market(market)
            if outcome_block_reasons(market, outcome):
                continue
            tradable.append(market)
        return tradable

    def _make_opportunity(
        self,
        snapshot: A6MarketSnapshot,
        *,
        signal_type: str,
        executable: bool,
    ) -> A6Opportunity:
        if signal_type == "buy_yes_basket":
            assert snapshot.sum_yes_ask is not None
            edge = max(0.0, 1.0 - float(snapshot.sum_yes_ask))
            threshold = float(self.config.buy_threshold)
        else:
            assert snapshot.sum_yes_bid is not None
            edge = max(0.0, float(snapshot.sum_yes_bid) - 1.0)
            threshold = float(self.config.upper_signal_threshold)

        legs = tuple(
            A6OpportunityLeg(
                leg_id=leg.leg_id,
                market_id=leg.market_id,
                condition_id=leg.condition_id,
                token_id=leg.token_id,
                outcome_name=leg.outcome_name,
                best_bid=float(leg.yes_bid or 0.0),
                best_ask=float(leg.yes_ask or 0.0),
                tick_size=float(leg.tick_size),
            )
            for leg in snapshot.legs
            if leg.yes_bid is not None and leg.yes_ask is not None
        )
        payload = f"{signal_type}|{snapshot.event_id}|{snapshot.detected_at_ts}|{edge:.6f}"
        signal_id = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:20]
        return A6Opportunity(
            signal_id=signal_id,
            basket_id=f"a6-{signal_id}",
            event_id=snapshot.event_id,
            signal_type=signal_type,
            executable=executable,
            threshold=threshold,
            theoretical_edge=float(edge),
            sum_yes_ask=snapshot.sum_yes_ask,
            sum_yes_bid=snapshot.sum_yes_bid,
            detected_at_ts=int(snapshot.detected_at_ts),
            invalidation_reasons=tuple(snapshot.invalidation_reasons),
            legs=legs,
        )

    def _is_duplicate(self, event_id: str, signal_type: str, price_sum: float, now_ts: int) -> bool:
        key = (event_id, signal_type, _round_bucket(price_sum))
        last_seen = self._recent_signals.get(key)
        if last_seen is not None and now_ts - last_seen < self.config.dedupe_window_seconds:
            return True
        self._recent_signals[key] = now_ts
        return False

    def _trim_recent(self, now_ts: int) -> None:
        cutoff = now_ts - max(1, int(self.config.dedupe_window_seconds)) * 4
        stale_keys = [key for key, seen_ts in self._recent_signals.items() if seen_ts < cutoff]
        for key in stale_keys:
            self._recent_signals.pop(key, None)
