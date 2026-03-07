"""A-6 multi-outcome sum-violation watchlist and signal logic."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
import time
from typing import Any, Mapping, Sequence

from infra.clob_ws import BestBidAskStore


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_clob_token_ids(raw: Any) -> tuple[str | None, str | None]:
    values: list[str] = []
    if isinstance(raw, str):
        stripped = raw.strip()
        if not stripped:
            return None, None
        try:
            decoded = json.loads(stripped)
        except json.JSONDecodeError:
            decoded = [part.strip() for part in stripped.split(",") if part.strip()]
        if isinstance(decoded, list):
            values = [str(item).strip() for item in decoded if str(item).strip()]
    elif isinstance(raw, list):
        values = [str(item).strip() for item in raw if str(item).strip()]

    if len(values) < 2:
        return None, None
    return values[0], values[1]


def floor_to_tick(value: float, tick_size: float) -> float:
    if tick_size <= 0:
        return float(value)
    steps = math.floor((float(value) + 1e-12) / float(tick_size))
    return round(steps * float(tick_size), 10)


@dataclass(frozen=True)
class OutcomeLeg:
    market_id: str
    question: str
    outcome: str
    yes_token_id: str
    no_token_id: str
    tick_size: float
    min_order_size: float
    accepting_orders: bool
    enable_order_book: bool


@dataclass(frozen=True)
class EventWatch:
    event_id: str
    title: str
    neg_risk: bool
    is_augmented: bool
    legs: tuple[OutcomeLeg, ...]
    raw_event: dict[str, Any] = field(default_factory=dict)
    a6_mode: str = "neg_risk_sum"
    settlement_path: str = "hold_to_resolution"

    @property
    def yes_token_ids(self) -> tuple[str, ...]:
        return tuple(leg.yes_token_id for leg in self.legs)


@dataclass(frozen=True)
class A6LegQuote:
    market_id: str
    token_id: str
    best_bid: float
    best_ask: float
    tick_size: float
    maker_bid_target: float
    spread: float
    stale_seconds: float
    no_orderbook: bool


@dataclass(frozen=True)
class A6Opportunity:
    event_id: str
    title: str
    a6_mode: str
    settlement_path: str
    maker_sum_bid: float
    sum_yes_ask: float
    detect_threshold: float
    execute_threshold: float
    execute_ready: bool
    liquidity_ok: bool
    orderbook_ok: bool
    reasons: tuple[str, ...]
    legs: tuple[A6LegQuote, ...]


class A6WatchlistBuilder:
    """Build a safe v1 A-6 universe from Gamma event payloads."""

    def __init__(self, *, min_event_markets: int = 3, max_legs: int = 12, exclude_augmented: bool = True) -> None:
        self.min_event_markets = max(3, int(min_event_markets))
        self.max_legs = max(3, int(max_legs))
        self.exclude_augmented = bool(exclude_augmented)

    def build_watchlist(self, raw_events: Sequence[Mapping[str, Any]]) -> list[EventWatch]:
        watches: list[EventWatch] = []
        for raw_event in raw_events:
            watch = self._build_event_watch(raw_event)
            if watch is not None:
                watches.append(watch)
        return watches

    def flatten_markets(self, raw_events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for watch in self.build_watchlist(raw_events):
            event_meta = dict(watch.raw_event)
            event_outcomes = [leg.outcome for leg in watch.legs]
            for leg in watch.legs:
                out.append(
                    {
                        "id": leg.market_id,
                        "event_id": watch.event_id,
                        "events": [{"id": watch.event_id}],
                        "question": leg.question,
                        "outcome": leg.outcome,
                        "outcomes": list(event_outcomes),
                        "clobTokenIds": json.dumps([leg.yes_token_id, leg.no_token_id]),
                        "orderPriceMinTickSize": leg.tick_size,
                        "orderMinSize": leg.min_order_size,
                        "acceptingOrders": leg.accepting_orders,
                        "enableOrderBook": leg.enable_order_book,
                        "negRisk": watch.neg_risk,
                        "negRiskAugmented": watch.is_augmented,
                        "eventCategory": event_meta.get("eventCategory") or event_meta.get("category"),
                        "endDate": event_meta.get("endDate"),
                        "resolutionSource": event_meta.get("resolutionSource"),
                        "rules": event_meta.get("rules") or event_meta.get("description"),
                    }
                )
        return out

    def _build_event_watch(self, raw_event: Mapping[str, Any]) -> EventWatch | None:
        if not _as_bool(raw_event.get("active")) or _as_bool(raw_event.get("closed")):
            return None
        if not _as_bool(raw_event.get("negRisk")):
            return None

        event_augmented = _as_bool(raw_event.get("negRiskAugmented"))
        if self.exclude_augmented and event_augmented:
            return None

        raw_markets = raw_event.get("markets")
        if not isinstance(raw_markets, list) or len(raw_markets) < self.min_event_markets:
            return None
        if len(raw_markets) > self.max_legs:
            return None

        if raw_event.get("enableOrderBook") is False:
            return None

        legs: list[OutcomeLeg] = []
        for raw_market in raw_markets:
            if not isinstance(raw_market, Mapping):
                return None
            market_augmented = _as_bool(raw_market.get("negRiskAugmented")) or event_augmented
            if self.exclude_augmented and market_augmented:
                return None
            if _as_bool(raw_market.get("closed")):
                return None
            if not _as_bool(raw_market.get("acceptingOrders", True)):
                return None
            if not _as_bool(raw_market.get("enableOrderBook", raw_event.get("enableOrderBook", True))):
                return None

            yes_token_id, no_token_id = parse_clob_token_ids(raw_market.get("clobTokenIds"))
            if not yes_token_id or not no_token_id:
                return None

            market_id = str(raw_market.get("id") or raw_market.get("market_id") or "").strip()
            if not market_id:
                return None

            legs.append(
                OutcomeLeg(
                    market_id=market_id,
                    question=str(raw_market.get("question") or raw_event.get("title") or "").strip(),
                    outcome=str(
                        raw_market.get("groupItemTitle")
                        or raw_market.get("outcome")
                        or raw_market.get("outcomeName")
                        or raw_market.get("title")
                        or market_id
                    ).strip(),
                    yes_token_id=yes_token_id,
                    no_token_id=no_token_id,
                    tick_size=max(0.001, _as_float(raw_market.get("orderPriceMinTickSize"), 0.01)),
                    min_order_size=max(0.0, _as_float(raw_market.get("orderMinSize"), 0.0)),
                    accepting_orders=True,
                    enable_order_book=True,
                )
            )

        if len(legs) < self.min_event_markets:
            return None

        event_id = str(raw_event.get("id") or raw_event.get("event_id") or "").strip()
        if not event_id:
            return None

        title = str(raw_event.get("title") or raw_event.get("question") or event_id).strip()
        return EventWatch(
            event_id=event_id,
            title=title,
            neg_risk=True,
            is_augmented=event_augmented,
            legs=tuple(legs),
            raw_event=dict(raw_event),
        )


class A6SignalEngine:
    """Execution-aware opportunity scoring for complete-set maker baskets."""

    def __init__(
        self,
        *,
        detect_threshold: float = 0.97,
        execute_threshold: float = 0.95,
        max_spread: float = 0.03,
        max_stale_seconds: float = 2.0,
        settlement_path: str = "hold_to_resolution",
    ) -> None:
        self.detect_threshold = float(detect_threshold)
        self.execute_threshold = float(execute_threshold)
        self.max_spread = float(max_spread)
        self.max_stale_seconds = float(max_stale_seconds)
        self.settlement_path = str(settlement_path)

    def evaluate_event(
        self,
        watch: EventWatch,
        quote_store: BestBidAskStore,
        *,
        now_ts: float | None = None,
    ) -> A6Opportunity | None:
        now = float(now_ts or time.time())
        reasons: list[str] = []
        leg_quotes: list[A6LegQuote] = []
        orderbook_ok = True
        liquidity_ok = True

        for leg in watch.legs:
            if quote_store.has_no_orderbook(leg.yes_token_id):
                orderbook_ok = False
                reasons.append(f"no_orderbook:{leg.market_id}")
                break

            quote = quote_store.get(leg.yes_token_id)
            if quote is None:
                reasons.append(f"missing_quote:{leg.market_id}")
                return None

            stale_seconds = max(0.0, now - quote.updated_ts)
            if stale_seconds > self.max_stale_seconds:
                reasons.append(f"stale_quote:{leg.market_id}")
                return None

            live_tick_size = quote_store.get_tick_size(leg.yes_token_id)
            tick_size = max(0.001, float(live_tick_size if live_tick_size is not None else leg.tick_size))
            spread = max(0.0, float(quote.best_ask - quote.best_bid))
            if spread > self.max_spread:
                liquidity_ok = False
                reasons.append(f"wide_spread:{leg.market_id}")

            maker_bid_target = floor_to_tick(max(0.0, quote.best_ask - tick_size), tick_size)
            if maker_bid_target >= quote.best_ask:
                maker_bid_target = floor_to_tick(max(0.0, quote.best_ask - tick_size), tick_size)
            if maker_bid_target <= 0.0:
                liquidity_ok = False
                reasons.append(f"non_positive_bid_target:{leg.market_id}")

            leg_quotes.append(
                A6LegQuote(
                    market_id=leg.market_id,
                    token_id=leg.yes_token_id,
                    best_bid=float(quote.best_bid),
                    best_ask=float(quote.best_ask),
                    tick_size=float(tick_size),
                    maker_bid_target=float(maker_bid_target),
                    spread=float(spread),
                    stale_seconds=float(stale_seconds),
                    no_orderbook=False,
                )
            )

        if not leg_quotes:
            return None

        maker_sum_bid = sum(leg.maker_bid_target for leg in leg_quotes)
        sum_yes_ask = sum(leg.best_ask for leg in leg_quotes)

        if maker_sum_bid >= self.detect_threshold:
            return None

        execute_ready = orderbook_ok and (
            maker_sum_bid < self.execute_threshold or liquidity_ok
        )

        return A6Opportunity(
            event_id=watch.event_id,
            title=watch.title,
            a6_mode=watch.a6_mode,
            settlement_path=self.settlement_path,
            maker_sum_bid=float(maker_sum_bid),
            sum_yes_ask=float(sum_yes_ask),
            detect_threshold=self.detect_threshold,
            execute_threshold=self.execute_threshold,
            execute_ready=bool(execute_ready),
            liquidity_ok=bool(liquidity_ok),
            orderbook_ok=bool(orderbook_ok),
            reasons=tuple(dict.fromkeys(reasons)),
            legs=tuple(leg_quotes),
        )
