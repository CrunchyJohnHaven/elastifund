#!/usr/bin/env python3
"""Signal generation for multi-outcome sum violations."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping, Sequence

try:
    from bot.sum_violation_scanner import SumViolationOpportunity, SumViolationScanner
except ImportError:  # pragma: no cover - direct script mode
    from sum_violation_scanner import SumViolationOpportunity, SumViolationScanner  # type: ignore


TAKER_FEE_RATES = {
    "crypto": 0.025,
    "sports": 0.007,
    "default": 0.0,
}


def calculate_taker_fee(price: float, category: str) -> float:
    rate = TAKER_FEE_RATES.get(str(category or "").lower(), TAKER_FEE_RATES["default"])
    return max(0.0, float(price) * (1.0 - float(price)) * rate)


def choose_maker_price(*, best_bid: float, best_ask: float, tick_size: float) -> float | None:
    tick = max(0.001, float(tick_size))
    bid = max(0.0, float(best_bid))
    ask = max(bid, float(best_ask))
    if ask <= 0.0:
        return None
    if ask - bid <= tick:
        return round(bid, 4)
    return round(min(ask - tick, bid + tick), 4)


@dataclass(frozen=True)
class SumViolationSignalLeg:
    market_id: str
    outcome: str
    question: str
    category: str
    quote_side: str
    token_id: str
    best_bid: float
    best_ask: float
    limit_price: float
    tick_size: float
    depth_usd: float
    resolution_hours: float | None
    position_size_usd: float


@dataclass(frozen=True)
class SumViolationSignal:
    signal_id: str
    event_id: str
    event_title: str
    market_ids: tuple[str, ...]
    violation_amount: float
    trade_side: str
    gross_profit_per_basket: float
    fee_drag_per_basket: float
    net_profit_per_basket: float
    expected_profit_per_dollar: float
    legs: tuple[SumViolationSignalLeg, ...]

    def to_signal_dict(self) -> dict:
        direction = "buy_yes" if self.trade_side == "buy_yes_basket" else "buy_no"
        return {
            "signal_id": self.signal_id,
            "violation_id": self.signal_id,
            "basket_id": f"sumv-{self.signal_id}",
            "event_id": self.event_id,
            "market_id": self.market_ids[0] if self.market_ids else self.event_id,
            "market_ids": list(self.market_ids),
            "question": self.event_title,
            "direction": direction,
            "trade_side": self.trade_side,
            "edge": self.expected_profit_per_dollar,
            "theoretical_edge": self.expected_profit_per_dollar,
            "confidence": 0.95,
            "reasoning": (
                f"Multi-outcome sum violation {self.violation_amount:.3f}; "
                f"net basket edge {self.expected_profit_per_dollar:.3%} after fee drag."
            ),
            "source": "sum_violation",
            "source_key": "sum_violation",
            "strategy_type": "combinatorial",
            "relation_type": "same_event_sum",
            "confirmation_mode": "bypass",
            "live_eligible": True,
            "details": {
                "violation_amount": self.violation_amount,
                "gross_profit_per_basket": self.gross_profit_per_basket,
                "fee_drag_per_basket": self.fee_drag_per_basket,
                "net_profit_per_basket": self.net_profit_per_basket,
                "expected_profit_per_dollar": self.expected_profit_per_dollar,
                "trade_side": self.trade_side,
            },
            "sum_violation_legs": [
                {
                    "market_id": leg.market_id,
                    "outcome": leg.outcome,
                    "question": leg.question,
                    "category": leg.category,
                    "quote_side": leg.quote_side,
                    "token_id": leg.token_id,
                    "best_bid": leg.best_bid,
                    "best_ask": leg.best_ask,
                    "limit_price": leg.limit_price,
                    "tick_size": leg.tick_size,
                    "depth_usd": leg.depth_usd,
                    "resolution_hours": leg.resolution_hours,
                    "position_size_usd": leg.position_size_usd,
                }
                for leg in self.legs
            ],
        }


@dataclass(frozen=True)
class SumViolationEvaluation:
    signal_id: str
    event_id: str
    event_title: str
    trade_side: str
    violation_amount: float
    gross_profit_per_basket: float
    fee_drag_per_basket: float
    net_profit_per_basket: float
    expected_profit_per_dollar: float
    action: str
    reason: str


class SumViolationStrategy:
    """Convert raw scanner opportunities into execution-ready signals."""

    def __init__(
        self,
        *,
        scanner: SumViolationScanner | None = None,
        threshold: float | None = None,
        min_depth_usd: float | None = None,
        max_resolution_hours: float | None = None,
        position_size_usd: float | None = None,
        report_path: str | Path = Path("reports") / "sum_violations_log.md",
    ) -> None:
        self.scanner = scanner or SumViolationScanner(use_websocket=False)
        self.threshold = float(threshold if threshold is not None else os.environ.get("JJ_SUM_VIOLATION_THRESHOLD", 0.05))
        self.min_depth_usd = float(
            min_depth_usd if min_depth_usd is not None else os.environ.get("JJ_SUM_VIOLATION_MIN_DEPTH_USD", 50.0)
        )
        self.max_resolution_hours = float(
            max_resolution_hours if max_resolution_hours is not None else os.environ.get("JJ_MAX_RESOLUTION_HOURS", 24.0)
        )
        self.position_size_usd = float(
            position_size_usd if position_size_usd is not None else min(0.50, float(os.environ.get("JJ_MAX_POSITION_USD", 0.50)))
        )
        self.report_path = Path(report_path)
        self.report_path.parent.mkdir(parents=True, exist_ok=True)
        self.last_evaluations: list[SumViolationEvaluation] = []

    def _build_signal_legs(self, opportunity: SumViolationOpportunity) -> tuple[SumViolationSignalLeg, ...] | None:
        quote_side = "YES" if opportunity.trade_side == "buy_yes_basket" else "NO"
        signal_legs: list[SumViolationSignalLeg] = []
        for leg in opportunity.legs:
            token_id = leg.yes_token_id if quote_side == "YES" else leg.no_token_id
            best_bid = leg.yes_bid if quote_side == "YES" else leg.no_bid
            best_ask = leg.yes_ask if quote_side == "YES" else leg.no_ask
            depth_usd = leg.yes_depth_usd if quote_side == "YES" else leg.no_depth_usd
            if not token_id or best_bid is None or best_ask is None:
                return None
            limit_price = choose_maker_price(
                best_bid=float(best_bid),
                best_ask=float(best_ask),
                tick_size=float(leg.tick_size),
            )
            if limit_price is None or not (0.0 < limit_price < 1.0):
                return None
            signal_legs.append(
                SumViolationSignalLeg(
                    market_id=leg.market_id,
                    outcome=leg.outcome,
                    question=leg.question,
                    category=leg.category,
                    quote_side=quote_side,
                    token_id=str(token_id),
                    best_bid=float(best_bid),
                    best_ask=float(best_ask),
                    limit_price=float(limit_price),
                    tick_size=float(leg.tick_size),
                    depth_usd=float(depth_usd),
                    resolution_hours=leg.resolution_hours,
                    position_size_usd=float(self.position_size_usd),
                )
            )
        return tuple(signal_legs)

    def generate_signals(self, markets: Sequence[Mapping[str, object]] | None = None) -> list[SumViolationSignal]:
        self.last_evaluations = []
        signals: list[SumViolationSignal] = []
        opportunities = self.scanner.scan_market_violations(markets, threshold=self.threshold)
        for opportunity in opportunities:
            legs = self._build_signal_legs(opportunity)
            if legs is None:
                self.last_evaluations.append(
                    SumViolationEvaluation(
                        signal_id=opportunity.violation_id,
                        event_id=opportunity.event_id,
                        event_title=opportunity.event_title,
                        trade_side=opportunity.trade_side,
                        violation_amount=opportunity.violation_amount,
                        gross_profit_per_basket=opportunity.gross_profit_per_basket,
                        fee_drag_per_basket=0.0,
                        net_profit_per_basket=0.0,
                        expected_profit_per_dollar=0.0,
                        action="killed_by_filter",
                        reason="missing_executable_prices",
                    )
                )
                continue

            if any(leg.depth_usd + 1e-9 < self.min_depth_usd for leg in legs):
                self.last_evaluations.append(
                    SumViolationEvaluation(
                        signal_id=opportunity.violation_id,
                        event_id=opportunity.event_id,
                        event_title=opportunity.event_title,
                        trade_side=opportunity.trade_side,
                        violation_amount=opportunity.violation_amount,
                        gross_profit_per_basket=opportunity.gross_profit_per_basket,
                        fee_drag_per_basket=0.0,
                        net_profit_per_basket=0.0,
                        expected_profit_per_dollar=0.0,
                        action="insufficient_liquidity",
                        reason=f"depth_below_${self.min_depth_usd:.0f}",
                    )
                )
                continue

            if self.max_resolution_hours > 0 and any(
                leg.resolution_hours is not None and leg.resolution_hours > self.max_resolution_hours
                for leg in legs
            ):
                self.last_evaluations.append(
                    SumViolationEvaluation(
                        signal_id=opportunity.violation_id,
                        event_id=opportunity.event_id,
                        event_title=opportunity.event_title,
                        trade_side=opportunity.trade_side,
                        violation_amount=opportunity.violation_amount,
                        gross_profit_per_basket=opportunity.gross_profit_per_basket,
                        fee_drag_per_basket=0.0,
                        net_profit_per_basket=0.0,
                        expected_profit_per_dollar=0.0,
                        action="killed_by_filter",
                        reason=f"resolution>{self.max_resolution_hours:.1f}h",
                    )
                )
                continue

            fee_drag = sum(calculate_taker_fee(leg.limit_price, leg.category) for leg in legs)
            net_profit = float(opportunity.gross_profit_per_basket) - float(fee_drag)
            expected_profit_per_dollar = (
                net_profit / float(opportunity.execution_cost)
                if opportunity.execution_cost > 0.0
                else 0.0
            )
            if net_profit <= 0.0 or expected_profit_per_dollar <= 0.0:
                self.last_evaluations.append(
                    SumViolationEvaluation(
                        signal_id=opportunity.violation_id,
                        event_id=opportunity.event_id,
                        event_title=opportunity.event_title,
                        trade_side=opportunity.trade_side,
                        violation_amount=opportunity.violation_amount,
                        gross_profit_per_basket=opportunity.gross_profit_per_basket,
                        fee_drag_per_basket=float(fee_drag),
                        net_profit_per_basket=float(net_profit),
                        expected_profit_per_dollar=float(expected_profit_per_dollar),
                        action="killed_by_filter",
                        reason="fee_drag",
                    )
                )
                continue

            signal = SumViolationSignal(
                signal_id=opportunity.violation_id,
                event_id=opportunity.event_id,
                event_title=opportunity.event_title,
                market_ids=tuple(leg.market_id for leg in legs),
                violation_amount=float(opportunity.violation_amount),
                trade_side=opportunity.trade_side,
                gross_profit_per_basket=float(opportunity.gross_profit_per_basket),
                fee_drag_per_basket=float(fee_drag),
                net_profit_per_basket=float(net_profit),
                expected_profit_per_dollar=float(expected_profit_per_dollar),
                legs=legs,
            )
            signals.append(signal)
            self.last_evaluations.append(
                SumViolationEvaluation(
                    signal_id=signal.signal_id,
                    event_id=signal.event_id,
                    event_title=signal.event_title,
                    trade_side=signal.trade_side,
                    violation_amount=signal.violation_amount,
                    gross_profit_per_basket=signal.gross_profit_per_basket,
                    fee_drag_per_basket=signal.fee_drag_per_basket,
                    net_profit_per_basket=signal.net_profit_per_basket,
                    expected_profit_per_dollar=signal.expected_profit_per_dollar,
                    action="ready",
                    reason="passes_filters",
                )
            )
        return signals

    def write_report(self, action_overrides: Mapping[str, str] | None = None) -> None:
        rows = []
        overrides = dict(action_overrides or {})
        for evaluation in self.last_evaluations:
            final_action = overrides.get(evaluation.signal_id, evaluation.action)
            rows.append(
                "| {signal_id} | {event} | {side} | {violation:.3f} | {gross:.3f} | {fee:.3f} | {net:.3f} | {edge:.3%} | {action} | {reason} |".format(
                    signal_id=evaluation.signal_id,
                    event=evaluation.event_title.replace("|", "/"),
                    side=evaluation.trade_side,
                    violation=evaluation.violation_amount,
                    gross=evaluation.gross_profit_per_basket,
                    fee=evaluation.fee_drag_per_basket,
                    net=evaluation.net_profit_per_basket,
                    edge=evaluation.expected_profit_per_dollar,
                    action=final_action,
                    reason=evaluation.reason.replace("|", "/"),
                )
            )
        if not rows:
            return
        if not self.report_path.exists() or not self.report_path.read_text(encoding="utf-8").strip():
            self.report_path.write_text(
                "# Sum Violations Log\n\n"
                "| Signal ID | Event | Side | Violation | Gross Basket PnL | Fee Drag | Net Basket PnL | Edge After Fees | Action | Reason |\n"
                "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |\n",
                encoding="utf-8",
            )
        with self.report_path.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(rows) + "\n")
