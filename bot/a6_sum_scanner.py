#!/usr/bin/env python3
"""Guaranteed-dollar scanner for A-6 neg-risk events."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import time
from typing import TYPE_CHECKING, Any, Mapping, Sequence

try:
    from bot.execution_readiness import (
        ExecutionReadinessInputs,
        builder_relayer_available,
        evaluate_execution_readiness,
    )
    from bot.resolution_normalizer import (
        NormalizedMarket,
        outcome_block_reasons,
        selected_outcome_for_market,
    )
except ImportError:  # pragma: no cover - direct script mode
    from execution_readiness import (  # type: ignore
        ExecutionReadinessInputs,
        builder_relayer_available,
        evaluate_execution_readiness,
    )
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


def _midpoint_bucket(midpoint: float) -> str:
    value = max(0.0, min(1.0, float(midpoint)))
    if value < 0.05:
        return "tail_0_5pct"
    if value < 0.15:
        return "tail_5_15pct"
    if value < 0.35:
        return "mid_15_35pct"
    if value < 0.65:
        return "mid_35_65pct"
    return "favorite_65_100pct"


@dataclass(frozen=True)
class A6ScannerConfig:
    buy_threshold: float = 0.97
    upper_signal_threshold: float = 1.03
    stale_quote_seconds: int = 30
    dedupe_window_seconds: int = 15
    max_leg_notional_usd: float = 5.0
    max_one_leg_loss_usd: float = 5.0
    require_builder_for_full_basket: bool = False


@dataclass(frozen=True)
class A6LegSnapshot:
    leg_id: str
    market_id: str
    condition_id: str
    token_id: str
    no_token_id: str | None
    outcome_name: str
    yes_bid: float | None
    yes_ask: float | None
    no_bid: float | None
    no_ask: float | None
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
    full_basket_guaranteed: bool
    filtered_outcomes_present: bool


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
    quote_side: str = "YES"


@dataclass(frozen=True)
class A6RankedConstruction:
    construction_type: str
    total_cost: float
    gross_edge: float
    leg_count: int
    executable: bool
    event_exhaustive: bool
    anchor_market_id: str | None
    reasons: tuple[str, ...]
    legs: tuple[A6OpportunityLeg, ...]


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
    selected_construction: str = "full_event_basket"
    ranked_constructions: tuple[A6RankedConstruction, ...] = tuple()
    readiness_status: str = "unchecked"
    readiness_reasons: tuple[str, ...] = tuple()
    estimated_one_leg_loss_usd: float = 0.0
    neg_risk: bool = True


@dataclass(frozen=True)
class A6ScanBatch:
    scanned_at_ts: int
    snapshots: tuple[A6MarketSnapshot, ...]
    opportunities: tuple[A6Opportunity, ...]


@dataclass(frozen=True)
class A6MeasurementLegInput:
    leg_id: str
    market_id: str
    condition_id: str
    token_id: str
    quote_side: str
    quote_price: float
    midpoint: float
    spread: float
    required_size: float
    quote_age_seconds: float | None
    price_bucket: str


@dataclass(frozen=True)
class A6MeasurementRecord:
    event_id: str
    signal_id: str
    snapshot_ts: int
    state: str
    selected_construction: str
    top_of_book_cost: float | None
    maker_target_cost: float | None
    gross_edge: float | None
    quote_dwell_seconds: float | None
    refresh_cadence_seconds: float | None
    expected_legs: int
    fresh_legs: int
    blocked_reasons: tuple[str, ...]
    fill_proxy_inputs: tuple[A6MeasurementLegInput, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "signal_id": self.signal_id,
            "snapshot_ts": self.snapshot_ts,
            "state": self.state,
            "selected_construction": self.selected_construction,
            "construction": {
                "top_of_book_cost": self.top_of_book_cost,
                "maker_target_cost": self.maker_target_cost,
                "gross_edge": self.gross_edge,
            },
            "quote": {
                "dwell_seconds": self.quote_dwell_seconds,
                "refresh_cadence_seconds": self.refresh_cadence_seconds,
                "expected_legs": self.expected_legs,
                "fresh_legs": self.fresh_legs,
            },
            "blocked_reasons": list(self.blocked_reasons),
            "fill_proxy_inputs": [
                {
                    "leg_id": leg.leg_id,
                    "market_id": leg.market_id,
                    "condition_id": leg.condition_id,
                    "token_id": leg.token_id,
                    "quote_side": leg.quote_side,
                    "quote_price": leg.quote_price,
                    "midpoint": leg.midpoint,
                    "spread": leg.spread,
                    "required_size": leg.required_size,
                    "quote_age_seconds": leg.quote_age_seconds,
                    "price_bucket": leg.price_bucket,
                }
                for leg in self.fill_proxy_inputs
            ],
        }


class A6SumScanner:
    """Rank the cheapest executable guaranteed-dollar constructions per event."""

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
            if not market.profile.is_neg_risk:
                continue
            by_event.setdefault(market.event_id, []).append(market)

        snapshots: list[A6MarketSnapshot] = []
        for event_id, event_markets in sorted(by_event.items()):
            tradable = self._tradable_markets(event_markets)
            if len(tradable) < 1:
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
            full_basket_guaranteed = self._supports_full_basket(tradable)
            sum_yes_ask = (
                float(sum(leg.yes_ask or 0.0 for leg in executable_legs))
                if executable_legs and full_basket_guaranteed
                else None
            )
            sum_yes_bid = (
                float(sum(leg.yes_bid or 0.0 for leg in executable_legs))
                if executable_legs and full_basket_guaranteed
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
                    full_basket_guaranteed=full_basket_guaranteed,
                    filtered_outcomes_present=not full_basket_guaranteed,
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
            ranked = self._rank_constructions(snapshot)
            best = ranked[0] if ranked else None
            if best is not None and best.executable and best.total_cost < self.config.buy_threshold:
                signal_type = "buy_yes_basket" if best.construction_type == "full_event_basket" else "buy_yes_no_straddle"
                opportunity = self._make_ranked_opportunity(
                    snapshot,
                    ranked,
                    signal_type=signal_type,
                    executable=True,
                )
                if opportunity.readiness_status == "ready" and not self._is_duplicate(snapshot.event_id, signal_type, best.total_cost, now):
                    opportunities.append(opportunity)
                continue

            if snapshot.sum_yes_bid is not None and snapshot.sum_yes_bid > self.config.upper_signal_threshold:
                if self._is_duplicate(snapshot.event_id, "unwind_inventory_only", snapshot.sum_yes_bid, now):
                    continue
                opportunities.append(
                    self._make_ranked_opportunity(snapshot, ranked, signal_type="unwind_inventory_only", executable=False)
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

    def build_measurement_records(
        self,
        batch: A6ScanBatch,
        *,
        refresh_cadence_seconds: float | None = None,
    ) -> tuple[A6MeasurementRecord, ...]:
        by_event_opportunity = {opp.event_id: opp for opp in batch.opportunities}
        records: list[A6MeasurementRecord] = []

        for snapshot in batch.snapshots:
            ranked = self._rank_constructions(snapshot)
            best = ranked[0] if ranked else None
            opportunity = by_event_opportunity.get(snapshot.event_id)
            selected_construction = (
                opportunity.selected_construction if opportunity is not None else (best.construction_type if best is not None else "none")
            )
            top_of_book_cost = (
                float(best.total_cost)
                if best is not None
                else (float(snapshot.sum_yes_ask) if snapshot.sum_yes_ask is not None else None)
            )
            gross_edge = max(0.0, 1.0 - float(top_of_book_cost)) if top_of_book_cost is not None else None

            measurement_legs = tuple(opportunity.legs) if opportunity is not None else tuple(best.legs if best is not None else ())
            maker_target_cost = (
                float(sum(max(0.0, leg.best_ask - leg.tick_size) for leg in measurement_legs))
                if measurement_legs
                else None
            )

            quote_ages = [
                max(0.0, float(batch.scanned_at_ts - int(leg.updated_ts)))
                for leg in snapshot.legs
                if leg.updated_ts is not None
            ]
            quote_dwell_seconds = max(quote_ages) if quote_ages else None

            fill_proxy_inputs: list[A6MeasurementLegInput] = []
            for leg in measurement_legs:
                midpoint = max(0.0, min(1.0, (float(leg.best_bid) + float(leg.best_ask)) / 2.0))
                required_size = float(self.config.max_leg_notional_usd) / max(float(leg.best_ask), float(leg.tick_size), 0.001)
                fill_proxy_inputs.append(
                    A6MeasurementLegInput(
                        leg_id=leg.leg_id,
                        market_id=leg.market_id,
                        condition_id=leg.condition_id,
                        token_id=leg.token_id,
                        quote_side=leg.quote_side,
                        quote_price=float(leg.best_ask),
                        midpoint=midpoint,
                        spread=max(0.0, float(leg.best_ask) - float(leg.best_bid)),
                        required_size=required_size,
                        quote_age_seconds=quote_dwell_seconds,
                        price_bucket=_midpoint_bucket(midpoint),
                    )
                )

            blocked_reasons = list(snapshot.invalidation_reasons)
            if opportunity is not None and opportunity.readiness_status != "ready":
                blocked_reasons.extend(opportunity.readiness_reasons)
            state = "executable" if snapshot.executable and best is not None and best.executable else "blocked"
            records.append(
                A6MeasurementRecord(
                    event_id=snapshot.event_id,
                    signal_id=(opportunity.signal_id if opportunity is not None else f"measurement-{snapshot.event_id}"),
                    snapshot_ts=int(snapshot.detected_at_ts),
                    state=state,
                    selected_construction=selected_construction,
                    top_of_book_cost=top_of_book_cost,
                    maker_target_cost=maker_target_cost,
                    gross_edge=gross_edge,
                    quote_dwell_seconds=quote_dwell_seconds,
                    refresh_cadence_seconds=refresh_cadence_seconds,
                    expected_legs=int(snapshot.expected_legs),
                    fresh_legs=int(snapshot.fresh_legs),
                    blocked_reasons=tuple(dict.fromkeys(blocked_reasons)),
                    fill_proxy_inputs=tuple(fill_proxy_inputs),
                )
            )
        return tuple(records)

    def _build_leg_snapshot(
        self,
        *,
        market: NormalizedMarket,
        quote: MarketQuote | None,
        now_ts: int,
    ) -> A6LegSnapshot:
        reasons = list(outcome_block_reasons(market, selected_outcome_for_market(market)))
        token_id = str(market.yes_token_id or "").strip()
        no_token_id = str(market.no_token_id or "").strip() or None
        if not token_id:
            reasons.append("missing_yes_token")
        if not no_token_id:
            reasons.append("missing_no_token")
        if not market.accepting_orders:
            reasons.append("market_not_accepting_orders")
        if not market.enable_order_book:
            reasons.append("order_book_disabled")

        yes_bid: float | None = None
        yes_ask: float | None = None
        no_bid: float | None = None
        no_ask: float | None = None
        updated_ts: int | None = None
        if quote is None:
            reasons.append("quote_missing")
        else:
            updated_ts = int(quote.updated_ts)
            yes_bid = float(quote.yes_bid)
            yes_ask = float(quote.yes_ask)
            no_bid = float(quote.no_bid)
            no_ask = float(quote.no_ask)
            if yes_bid < 0.0 or yes_ask < 0.0 or yes_bid > 1.0 or yes_ask > 1.0:
                reasons.append("invalid_price_bounds")
            elif yes_ask < yes_bid:
                reasons.append("crossed_book")
            if no_bid < 0.0 or no_ask < 0.0 or no_bid > 1.0 or no_ask > 1.0:
                reasons.append("invalid_no_price_bounds")
            elif no_ask < no_bid:
                reasons.append("crossed_no_book")
            if now_ts - updated_ts > self.config.stale_quote_seconds:
                reasons.append("stale_quote")

        executable = not reasons
        return A6LegSnapshot(
            leg_id=f"{market.market_id}:YES",
            market_id=market.market_id,
            condition_id=market.market_id,
            token_id=token_id,
            no_token_id=no_token_id,
            outcome_name=selected_outcome_for_market(market),
            yes_bid=yes_bid,
            yes_ask=yes_ask,
            no_bid=no_bid,
            no_ask=no_ask,
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

    @staticmethod
    def _supports_full_basket(markets: Sequence[NormalizedMarket]) -> bool:
        if len(markets) < 2:
            return False
        for market in markets:
            profile = market.profile
            if not profile.is_neg_risk:
                return False
            if profile.is_augmented_neg_risk and (
                profile.has_other_outcome
                or profile.has_placeholder_outcome
                or profile.has_catch_all_outcome
                or profile.has_ambiguous_named_mapping
            ):
                return False
        return True

    def _rank_constructions(self, snapshot: A6MarketSnapshot) -> tuple[A6RankedConstruction, ...]:
        ranked: list[A6RankedConstruction] = []

        if snapshot.full_basket_guaranteed and snapshot.executable and snapshot.sum_yes_ask is not None:
            ranked.append(
                A6RankedConstruction(
                    construction_type="full_event_basket",
                    total_cost=float(snapshot.sum_yes_ask),
                    gross_edge=max(0.0, 1.0 - float(snapshot.sum_yes_ask)),
                    leg_count=len(snapshot.legs),
                    executable=True,
                    event_exhaustive=True,
                    anchor_market_id=None,
                    reasons=tuple(),
                    legs=tuple(
                        A6OpportunityLeg(
                            leg_id=leg.leg_id,
                            market_id=leg.market_id,
                            condition_id=leg.condition_id,
                            token_id=leg.token_id,
                            outcome_name=leg.outcome_name,
                            best_bid=float(leg.yes_bid or 0.0),
                            best_ask=float(leg.yes_ask or 0.0),
                            tick_size=float(leg.tick_size),
                            quote_side="YES",
                        )
                        for leg in snapshot.legs
                        if leg.yes_bid is not None and leg.yes_ask is not None
                    ),
                )
            )

        for leg in snapshot.legs:
            if (
                not leg.executable
                or leg.yes_bid is None
                or leg.yes_ask is None
                or leg.no_bid is None
                or leg.no_ask is None
                or not leg.no_token_id
            ):
                continue
            rest_yes_sum = sum(
                float(other.yes_ask or 0.0)
                for other in snapshot.legs
                if other.market_id != leg.market_id and other.yes_ask is not None
            )
            reasons: list[str] = []
            if snapshot.full_basket_guaranteed and rest_yes_sum > 0 and leg.no_ask + 1e-9 < rest_yes_sum:
                reasons.append("no_cheaper_than_rest_yes")
            if not snapshot.full_basket_guaranteed:
                reasons.append("full_basket_blocked_filtered_outcomes")
            total_cost = float(leg.yes_ask + leg.no_ask)
            ranked.append(
                A6RankedConstruction(
                    construction_type="binary_straddle",
                    total_cost=total_cost,
                    gross_edge=max(0.0, 1.0 - total_cost),
                    leg_count=2,
                    executable=True,
                    event_exhaustive=True,
                    anchor_market_id=leg.market_id,
                    reasons=tuple(reasons),
                    legs=(
                        A6OpportunityLeg(
                            leg_id=f"{leg.market_id}:YES",
                            market_id=leg.market_id,
                            condition_id=leg.condition_id,
                            token_id=leg.token_id,
                            outcome_name=leg.outcome_name,
                            best_bid=float(leg.yes_bid),
                            best_ask=float(leg.yes_ask),
                            tick_size=float(leg.tick_size),
                            quote_side="YES",
                        ),
                        A6OpportunityLeg(
                            leg_id=f"{leg.market_id}:NO",
                            market_id=leg.market_id,
                            condition_id=leg.condition_id,
                            token_id=str(leg.no_token_id),
                            outcome_name=f"NO:{leg.outcome_name}",
                            best_bid=float(leg.no_bid),
                            best_ask=float(leg.no_ask),
                            tick_size=float(leg.tick_size),
                            quote_side="NO",
                        ),
                    ),
                )
            )

        ranked.sort(
            key=lambda row: (
                float(row.total_cost),
                int(row.leg_count),
                0 if row.construction_type == "binary_straddle" else 1,
            )
        )
        return tuple(ranked)

    def _make_ranked_opportunity(
        self,
        snapshot: A6MarketSnapshot,
        ranked_constructions: Sequence[A6RankedConstruction],
        *,
        signal_type: str,
        executable: bool,
    ) -> A6Opportunity:
        if signal_type in {"buy_yes_basket", "buy_yes_no_straddle"}:
            selected = ranked_constructions[0]
            edge = float(selected.gross_edge)
            threshold = float(self.config.buy_threshold)
            legs = tuple(selected.legs)
            builder_required = (
                self.config.require_builder_for_full_basket
                and selected.construction_type == "full_event_basket"
            )
            readiness = evaluate_execution_readiness(
                ExecutionReadinessInputs(
                    feed_healthy=bool(executable),
                    tick_size_ok=all(leg.tick_size > 0 for leg in legs),
                    quote_surface_ok=all(leg.best_ask > 0 and leg.best_bid >= 0 for leg in legs),
                    estimated_one_leg_loss_usd=float(self.config.max_leg_notional_usd),
                    max_one_leg_loss_threshold_usd=float(self.config.max_one_leg_loss_usd),
                    neg_risk=True,
                    neg_risk_flag_configured=True,
                    builder_required=builder_required,
                    builder_available=builder_relayer_available(),
                    now=int(snapshot.detected_at_ts),
                )
            )
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
                    quote_side="YES",
                )
                for leg in snapshot.legs
                if leg.yes_bid is not None and leg.yes_ask is not None
            )
            readiness = evaluate_execution_readiness(
                ExecutionReadinessInputs(
                    feed_healthy=False,
                    tick_size_ok=all(leg.tick_size > 0 for leg in legs),
                    quote_surface_ok=all(leg.best_ask > 0 and leg.best_bid >= 0 for leg in legs),
                    estimated_one_leg_loss_usd=float(self.config.max_leg_notional_usd),
                    max_one_leg_loss_threshold_usd=float(self.config.max_one_leg_loss_usd),
                    neg_risk=True,
                    neg_risk_flag_configured=True,
                    builder_required=False,
                    builder_available=False,
                    now=int(snapshot.detected_at_ts),
                )
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
            selected_construction=(
                ranked_constructions[0].construction_type
                if signal_type in {"buy_yes_basket", "buy_yes_no_straddle"} and ranked_constructions
                else "inventory_only"
            ),
            ranked_constructions=tuple(ranked_constructions),
            readiness_status=readiness.status,
            readiness_reasons=readiness.reasons,
            estimated_one_leg_loss_usd=readiness.estimated_one_leg_loss_usd,
            neg_risk=True,
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


def scan_neg_risk_events() -> dict[str, object]:
    """Compatibility wrapper for the documented A-6 live-surface scan command."""

    from bot.runtime_profile import load_runtime_profile
    from bot.sum_violation_scanner import SumViolationScanner

    profile_bundle = load_runtime_profile()
    scanner = SumViolationScanner(
        use_websocket=False,
        max_pages=3,
        page_size=50,
        max_events=20,
        buy_threshold=float(profile_bundle.profile.combinatorial_thresholds.a6_buy_threshold),
        execute_threshold=0.95,
        unwind_threshold=float(profile_bundle.profile.combinatorial_thresholds.a6_unwind_threshold),
        stale_quote_seconds=int(profile_bundle.profile.combinatorial_thresholds.stale_book_max_age_seconds),
        timeout_seconds=10.0,
    )
    try:
        stats = scanner.scan_once()
        opportunities = list(getattr(scanner, "_latest_opportunities", []))
        return {
            "status": "active" if stats.violations_found else "idle",
            "stats": asdict(stats),
            "candidates": int(stats.candidate_markets),
            "executable": len(opportunities),
            "opportunities": [
                {
                    "event_id": opp.event_id,
                    "signal_type": opp.signal_type,
                    "theoretical_edge": float(opp.theoretical_edge),
                    "sum_yes_ask": (float(opp.sum_yes_ask) if opp.sum_yes_ask is not None else None),
                    "selected_construction": opp.selected_construction,
                    "readiness_status": opp.readiness_status,
                    "legs": len(opp.legs),
                }
                for opp in opportunities[:10]
            ],
        }
    finally:
        scanner.close()
