"""Guaranteed-dollar construction ranking for neg-risk events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from infra.clob_ws import BestBidAsk, BestBidAskStore
from strategies.a6_sum_violation import EventWatch, OutcomeLeg, floor_to_tick


EASTERN_TZ = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class GuaranteedDollarConfig:
    detect_threshold: float = 0.95
    max_spread: float = 0.03
    max_stale_seconds: float = 45.0
    leg_size_usd: float = 5.0
    max_one_leg_loss: float = 0.05
    require_size_support: bool = False
    restart_pause_minutes: int = 20
    settlement_mode: str = "hold_to_resolution"
    builder_relayer_enabled: bool = False


@dataclass(frozen=True)
class GuaranteedDollarLeg:
    market_id: str
    outcome: str
    side: str
    token_id: str
    best_bid: float
    best_ask: float
    best_bid_size: float | None
    best_ask_size: float | None
    maker_target: float
    tick_size: float
    stale_seconds: float

    @property
    def spread(self) -> float:
        return max(0.0, float(self.best_ask) - float(self.best_bid))

    @property
    def top_size_known(self) -> bool:
        return self.best_ask_size is not None


@dataclass(frozen=True)
class ExecutionReadiness:
    ready: bool
    reasons: tuple[str, ...]
    feed_healthy: bool
    size_supported: bool
    size_verified: bool
    tick_size_ok: bool
    worst_case_one_leg_loss: float
    in_restart_window: bool
    relayer_ok: bool


@dataclass(frozen=True)
class GuaranteedDollarConstruction:
    construction_type: str
    label: str
    outcome: str | None
    top_of_book_cost: float
    maker_quote_cost: float
    gross_edge: float
    maker_gross_edge: float
    leg_count: int
    executable: bool
    requires_conversion: bool
    requires_builder: bool
    readiness: ExecutionReadiness
    legs: tuple[GuaranteedDollarLeg, ...]
    notes: tuple[str, ...]


@dataclass(frozen=True)
class GuaranteedDollarPlan:
    event_id: str
    title: str
    full_basket_cost: float | None
    best_construction: GuaranteedDollarConstruction | None
    constructions: tuple[GuaranteedDollarConstruction, ...]


def _needed_shares(*, leg_size_usd: float, price: float, tick_size: float) -> float:
    denom = max(float(price), float(tick_size), 0.001)
    return float(leg_size_usd) / denom


def _restart_window(now_ts: float, pause_minutes: int) -> bool:
    local = datetime.fromtimestamp(float(now_ts), tz=timezone.utc).astimezone(EASTERN_TZ)
    if local.weekday() != 1:
        return False
    restart_minutes = 7 * 60
    now_minutes = local.hour * 60 + local.minute
    return abs(now_minutes - restart_minutes) <= max(1, int(pause_minutes))


class GuaranteedDollarRanker:
    """Rank the cheapest executable guaranteed-dollar construction per neg-risk event."""

    def __init__(self, config: GuaranteedDollarConfig | None = None) -> None:
        self.config = config or GuaranteedDollarConfig()

    def evaluate_event(
        self,
        watch: EventWatch,
        quote_store: BestBidAskStore,
        *,
        now_ts: float,
    ) -> GuaranteedDollarPlan:
        if not watch.neg_risk:
            return GuaranteedDollarPlan(
                event_id=watch.event_id,
                title=watch.title,
                full_basket_cost=None,
                best_construction=None,
                constructions=tuple(),
            )

        yes_legs: dict[str, GuaranteedDollarLeg] = {}
        no_legs: dict[str, GuaranteedDollarLeg] = {}
        for leg in watch.legs:
            yes_quote = self._build_leg(leg, "YES", leg.yes_token_id, quote_store.get(leg.yes_token_id), now_ts=now_ts)
            if yes_quote is not None:
                yes_legs[leg.market_id] = yes_quote
            no_quote = self._build_leg(leg, "NO", leg.no_token_id, quote_store.get(leg.no_token_id), now_ts=now_ts)
            if no_quote is not None:
                no_legs[leg.market_id] = no_quote

        constructions: list[GuaranteedDollarConstruction] = []
        full_basket_legs = tuple(yes_legs[leg.market_id] for leg in watch.legs if leg.market_id in yes_legs)
        full_basket_complete = len(full_basket_legs) == len(watch.legs)
        full_basket_cost = None
        if full_basket_complete:
            full_basket_cost = float(sum(leg.best_ask for leg in full_basket_legs))
            constructions.append(
                self._make_construction(
                    watch=watch,
                    construction_type="full_event_basket",
                    label="Full YES basket",
                    outcome=None,
                    legs=full_basket_legs,
                    now_ts=now_ts,
                    requires_conversion=False,
                    notes=tuple(),
                )
            )

        for leg in watch.legs:
            yes_leg = yes_legs.get(leg.market_id)
            no_leg = no_legs.get(leg.market_id)
            if yes_leg is None or no_leg is None:
                continue

            notes: list[str] = []
            construction_type = "two_leg_straddle"
            if full_basket_cost is not None:
                rest_yes_cost = full_basket_cost - yes_leg.best_ask
                if no_leg.best_ask + 1e-9 < rest_yes_cost:
                    construction_type = "neg_risk_conversion"
                    notes.append("no_leg_cheaper_than_rest_yes")

            constructions.append(
                self._make_construction(
                    watch=watch,
                    construction_type=construction_type,
                    label=f"{leg.outcome} YES + {leg.outcome} NO",
                    outcome=leg.outcome,
                    legs=(yes_leg, no_leg),
                    now_ts=now_ts,
                    requires_conversion=construction_type == "neg_risk_conversion",
                    notes=tuple(notes),
                )
            )

        actionable = [
            construction
            for construction in constructions
            if construction.gross_edge >= (1.0 - float(self.config.detect_threshold))
        ]
        ranked = sorted(actionable or constructions, key=self._sort_key)
        best = ranked[0] if ranked else None
        return GuaranteedDollarPlan(
            event_id=watch.event_id,
            title=watch.title,
            full_basket_cost=full_basket_cost,
            best_construction=best,
            constructions=tuple(ranked),
        )

    def _build_leg(
        self,
        leg: OutcomeLeg,
        side: str,
        token_id: str,
        quote: BestBidAsk | None,
        *,
        now_ts: float,
    ) -> GuaranteedDollarLeg | None:
        if quote is None or not token_id:
            return None
        stale_seconds = max(0.0, float(now_ts) - float(quote.updated_ts))
        maker_target = floor_to_tick(max(0.0, float(quote.best_ask) - float(leg.tick_size)), leg.tick_size)
        return GuaranteedDollarLeg(
            market_id=leg.market_id,
            outcome=leg.outcome,
            side=side,
            token_id=token_id,
            best_bid=float(quote.best_bid),
            best_ask=float(quote.best_ask),
            best_bid_size=quote.best_bid_size,
            best_ask_size=quote.best_ask_size,
            maker_target=float(maker_target),
            tick_size=float(leg.tick_size),
            stale_seconds=float(stale_seconds),
        )

    def _make_construction(
        self,
        *,
        watch: EventWatch,
        construction_type: str,
        label: str,
        outcome: str | None,
        legs: tuple[GuaranteedDollarLeg, ...],
        now_ts: float,
        requires_conversion: bool,
        notes: tuple[str, ...],
    ) -> GuaranteedDollarConstruction:
        top_cost = float(sum(leg.best_ask for leg in legs))
        maker_cost = float(sum(max(leg.tick_size, leg.maker_target) for leg in legs))
        gross_edge = max(0.0, 1.0 - top_cost)
        maker_gross_edge = max(0.0, 1.0 - maker_cost)
        requires_builder = self.config.settlement_mode == "merge"
        readiness = self._evaluate_readiness(
            watch=watch,
            legs=legs,
            now_ts=now_ts,
            requires_builder=requires_builder,
        )
        return GuaranteedDollarConstruction(
            construction_type=construction_type,
            label=label,
            outcome=outcome,
            top_of_book_cost=top_cost,
            maker_quote_cost=maker_cost,
            gross_edge=gross_edge,
            maker_gross_edge=maker_gross_edge,
            leg_count=len(legs),
            executable=bool(gross_edge >= (1.0 - float(self.config.detect_threshold))),
            requires_conversion=requires_conversion,
            requires_builder=requires_builder,
            readiness=readiness,
            legs=legs,
            notes=notes,
        )

    def _evaluate_readiness(
        self,
        *,
        watch: EventWatch,
        legs: tuple[GuaranteedDollarLeg, ...],
        now_ts: float,
        requires_builder: bool,
    ) -> ExecutionReadiness:
        reasons: list[str] = []
        feed_healthy = all(leg.stale_seconds <= float(self.config.max_stale_seconds) for leg in legs)
        if not feed_healthy:
            reasons.append("stale_top_of_book")

        tick_size_ok = all(float(leg.tick_size) > 0.0 for leg in legs)
        if not tick_size_ok:
            reasons.append("tick_size_missing")

        worst_case_one_leg_loss = max((max(leg.spread, leg.best_ask - max(leg.maker_target, leg.tick_size)) for leg in legs), default=0.0)
        if worst_case_one_leg_loss > float(self.config.max_one_leg_loss):
            reasons.append("one_leg_loss_above_cap")

        size_verified = all(leg.top_size_known for leg in legs)
        size_supported = True
        if size_verified:
            for leg in legs:
                needed_shares = _needed_shares(
                    leg_size_usd=self.config.leg_size_usd,
                    price=max(leg.best_ask, leg.tick_size),
                    tick_size=leg.tick_size,
                )
                if leg.best_ask_size is not None and leg.best_ask_size + 1e-9 < needed_shares:
                    size_supported = False
                    break
        elif self.config.require_size_support:
            size_supported = False

        if not size_supported:
            reasons.append("top_of_book_size_insufficient_or_unverified")

        if any(leg.spread > (float(self.config.max_spread) + 1e-9) for leg in legs):
            reasons.append("spread_above_cap")

        if not watch.neg_risk:
            reasons.append("neg_risk_required")

        in_restart_window = _restart_window(now_ts, self.config.restart_pause_minutes)
        if in_restart_window:
            reasons.append("weekly_restart_window")

        relayer_ok = not requires_builder or bool(self.config.builder_relayer_enabled)
        if not relayer_ok:
            reasons.append("builder_relayer_required")

        return ExecutionReadiness(
            ready=not reasons,
            reasons=tuple(dict.fromkeys(reasons)),
            feed_healthy=feed_healthy,
            size_supported=size_supported,
            size_verified=size_verified,
            tick_size_ok=tick_size_ok,
            worst_case_one_leg_loss=float(worst_case_one_leg_loss),
            in_restart_window=in_restart_window,
            relayer_ok=relayer_ok,
        )

    @staticmethod
    def _sort_key(construction: GuaranteedDollarConstruction) -> tuple[float, int, int, int]:
        return (
            float(construction.top_of_book_cost),
            int(construction.leg_count),
            0 if construction.readiness.ready else 1,
            0 if construction.construction_type == "two_leg_straddle" else 1,
        )


def construction_to_dict(construction: GuaranteedDollarConstruction) -> dict[str, object]:
    return {
        "construction_type": construction.construction_type,
        "label": construction.label,
        "outcome": construction.outcome,
        "top_of_book_cost": construction.top_of_book_cost,
        "maker_quote_cost": construction.maker_quote_cost,
        "gross_edge": construction.gross_edge,
        "maker_gross_edge": construction.maker_gross_edge,
        "leg_count": construction.leg_count,
        "executable": construction.executable,
        "requires_conversion": construction.requires_conversion,
        "requires_builder": construction.requires_builder,
        "readiness": {
            "ready": construction.readiness.ready,
            "reasons": list(construction.readiness.reasons),
            "feed_healthy": construction.readiness.feed_healthy,
            "size_supported": construction.readiness.size_supported,
            "size_verified": construction.readiness.size_verified,
            "tick_size_ok": construction.readiness.tick_size_ok,
            "worst_case_one_leg_loss": construction.readiness.worst_case_one_leg_loss,
            "in_restart_window": construction.readiness.in_restart_window,
            "relayer_ok": construction.readiness.relayer_ok,
        },
        "legs": [
            {
                "market_id": leg.market_id,
                "outcome": leg.outcome,
                "side": leg.side,
                "token_id": leg.token_id,
                "best_bid": leg.best_bid,
                "best_ask": leg.best_ask,
                "best_bid_size": leg.best_bid_size,
                "best_ask_size": leg.best_ask_size,
                "maker_target": leg.maker_target,
                "tick_size": leg.tick_size,
                "stale_seconds": leg.stale_seconds,
                "spread": leg.spread,
            }
            for leg in construction.legs
        ],
        "notes": list(construction.notes),
    }


def plan_to_dict(plan: GuaranteedDollarPlan) -> dict[str, object]:
    return {
        "event_id": plan.event_id,
        "title": plan.title,
        "full_basket_cost": plan.full_basket_cost,
        "best_construction": construction_to_dict(plan.best_construction) if plan.best_construction else None,
        "constructions": [construction_to_dict(construction) for construction in plan.constructions],
    }
