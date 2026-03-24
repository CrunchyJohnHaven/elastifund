"""
Paper-trade simulator engine.

Replays historical market snapshots chronologically, generates signals from
cached Claude estimates, sizes positions, simulates fills with realistic
market microstructure, and resolves trades against known outcomes.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

try:
    from .fill_model import FillResult, simulate_fill
    from .metrics import SimulationReport, TradeRecord, build_report
    from .sizing import compute_position_size
except ImportError:  # pragma: no cover - legacy direct-script compatibility
    from fill_model import FillResult, simulate_fill
    from metrics import SimulationReport, TradeRecord, build_report
    from sizing import compute_position_size


# Calibration map from 532-market backtest (same as production)
CALIBRATION_MAP = {
    0.05: 0.157, 0.15: 0.120, 0.25: 0.220, 0.35: 0.625,
    0.45: 0.417, 0.55: 0.466, 0.65: 0.455, 0.75: 0.528,
    0.85: 0.632, 0.95: 0.632,
}


def calibrate_probability(raw_prob: float) -> float:
    """Piecewise linear interpolation using empirical calibration map."""
    points = sorted(CALIBRATION_MAP.items())
    if raw_prob <= points[0][0]:
        return points[0][1]
    if raw_prob >= points[-1][0]:
        return points[-1][1]
    for i in range(len(points) - 1):
        x0, y0 = points[i]
        x1, y1 = points[i + 1]
        if x0 <= raw_prob <= x1:
            t = (raw_prob - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return raw_prob


@dataclass
class Signal:
    """Strategy output for a single market snapshot."""
    market_id: str
    question: str
    market_price: float           # YES price at snapshot time
    claude_prob: float            # Raw Claude probability
    calibrated_prob: float        # Post-calibration probability
    confidence: str               # low | medium | high
    direction: str                # buy_yes | buy_no | hold
    raw_edge: float               # |calibrated_prob - market_price|
    volume: float
    liquidity: float
    actual_outcome: str           # YES_WON | NO_WON
    end_date: str


def generate_signal(
    market: dict,
    claude_estimate: dict,
    entry_price: float,
    yes_threshold: float = 0.05,
    no_threshold: float = 0.05,
) -> Signal:
    """
    Generate a trading signal from a market snapshot + Claude estimate.

    Uses calibrated probability to determine direction and edge.
    """
    raw_prob = claude_estimate["probability"]
    calibrated = calibrate_probability(raw_prob)
    confidence = claude_estimate.get("confidence", "medium")

    # Edge vs market price
    yes_edge = calibrated - entry_price      # Positive when Claude thinks YES is underpriced
    buy_no_edge = entry_price - calibrated   # Positive when Claude thinks NO is underpriced

    if yes_edge >= yes_threshold:
        direction = "buy_yes"
        raw_edge = yes_edge
    elif buy_no_edge >= no_threshold:
        direction = "buy_no"
        raw_edge = buy_no_edge
    else:
        direction = "hold"
        raw_edge = 0.0

    return Signal(
        market_id=market["id"],
        question=market["question"],
        market_price=entry_price,
        claude_prob=raw_prob,
        calibrated_prob=calibrated,
        confidence=confidence,
        direction=direction,
        raw_edge=raw_edge,
        volume=market.get("volume", 0),
        liquidity=market.get("liquidity", 0),
        actual_outcome=market["actual_outcome"],
        end_date=market.get("end_date", ""),
    )


def _cache_key(question: str) -> str:
    """SHA256 hash key matching the backtest cache format."""
    return hashlib.sha256(question.encode()).hexdigest()[:16]


def resolve_trade_pnl(
    direction: str,
    fill_price: float,
    size_usd: float,
    actual_outcome: str,
    winner_fee_rate: float,
) -> tuple[float, float, bool]:
    """
    Compute PnL for a resolved trade.

    Returns (pnl, winner_fee, won).

    For buy_yes:
      - If YES_WON: payout = shares * 1.0 - winner_fee; PnL = payout - cost
      - If NO_WON: PnL = -cost (lost everything)

    For buy_no:
      - If NO_WON: payout = shares * 1.0 - winner_fee; PnL = payout - cost
      - If YES_WON: PnL = -cost
    """
    shares = size_usd / fill_price if fill_price > 0 else 0
    cost = size_usd  # What we paid

    won = (
        (direction == "buy_yes" and actual_outcome == "YES_WON") or
        (direction == "buy_no" and actual_outcome == "NO_WON")
    )

    if won:
        gross_payout = shares * 1.0  # Each share pays $1
        winner_fee = gross_payout * winner_fee_rate
        pnl = gross_payout - winner_fee - cost
    else:
        pnl = -cost
        winner_fee = 0.0

    return pnl, winner_fee, won


class PaperTradeSimulator:
    """
    Main simulator engine.

    Replays historical markets chronologically, applying strategy signals,
    position sizing, and fill simulation to produce realistic PnL.
    """

    def __init__(self, config_path: str | Path):
        self.config_path = Path(config_path)
        with open(self.config_path) as f:
            self.config = yaml.safe_load(f)

        self.rng = random.Random(self.config.get("random_seed", 42))
        self.initial_capital = self.config["capital"]["initial"]
        self.capital = self.initial_capital
        self.trades: list[TradeRecord] = []
        self.equity_curve: list[float] = [self.initial_capital]
        self.open_positions: dict[str, dict] = {}
        self.trade_counter = 0

    def load_data(
        self,
        markets_path: str | Path,
        cache_path: str | Path,
    ) -> tuple[list[dict], dict]:
        """Load historical markets and Claude probability cache."""
        with open(markets_path) as f:
            data = json.load(f)
        markets = data["markets"]

        with open(cache_path) as f:
            cache = json.load(f)

        return markets, cache

    def _passes_filters(self, signal: Signal) -> bool:
        """Check if a signal passes all configured filters."""
        filters = self.config["filters"]
        price_range = filters["price_range"]

        if signal.market_price < price_range[0] or signal.market_price > price_range[1]:
            return False
        if signal.liquidity < filters["min_liquidity"]:
            return False
        if signal.volume < filters["min_volume"]:
            return False
        if signal.raw_edge < self.config["execution"]["min_edge_threshold"]:
            return False
        if signal.direction == "hold":
            return False
        if len(self.open_positions) >= self.config["execution"]["max_concurrent_positions"]:
            return False
        return True

    def _process_signal(self, signal: Signal) -> Optional[TradeRecord]:
        """Process a single signal: size, fill, record trade."""
        if not self._passes_filters(signal):
            return None

        # Size the position
        size = compute_position_size(
            capital=self.capital,
            edge=signal.raw_edge,
            win_probability=signal.calibrated_prob if signal.direction == "buy_yes" else 1.0 - signal.calibrated_prob,
            config=self.config,
        )
        if size <= 0 or size > self.capital:
            return None

        # Simulate fill
        fill: FillResult = simulate_fill(
            market_price=signal.market_price,
            direction=signal.direction,
            edge=signal.raw_edge,
            order_size_usd=size,
            volume=signal.volume,
            liquidity=signal.liquidity,
            config=self.config,
            rng=self.rng,
        )

        if not fill.filled:
            # Record unfilled attempt
            self.trade_counter += 1
            return TradeRecord(
                trade_id=self.trade_counter,
                market_id=signal.market_id,
                question=signal.question,
                direction=signal.direction,
                entry_price=signal.market_price,
                fill_price=0.0,
                size_usd=size,
                shares=0.0,
                edge_pre_cost=signal.raw_edge,
                edge_post_cost=0.0,
                slippage=0.0,
                spread_cost=0.0,
                fee_paid=0.0,
                winner_fee=0.0,
                outcome=None,
                pnl=0.0,
                won=False,
                trade_date=signal.end_date[:10] if signal.end_date else "",
                capital_before=self.capital,
                capital_after=self.capital,
            )

        # Deduct capital for the position
        self.capital -= size

        # Resolve trade immediately (we know the outcome)
        pnl, winner_fee, won = resolve_trade_pnl(
            direction=signal.direction,
            fill_price=fill.fill_price,
            size_usd=size,
            actual_outcome=signal.actual_outcome,
            winner_fee_rate=self.config["fees"]["winner_fee"],
        )

        self.capital += size + pnl  # Return cost + profit/loss
        self.equity_curve.append(self.capital)

        self.trade_counter += 1
        shares = size / fill.fill_price if fill.fill_price > 0 else 0

        trade = TradeRecord(
            trade_id=self.trade_counter,
            market_id=signal.market_id,
            question=signal.question,
            direction=signal.direction,
            entry_price=signal.market_price,
            fill_price=fill.fill_price,
            size_usd=size,
            shares=shares,
            edge_pre_cost=signal.raw_edge,
            edge_post_cost=fill.effective_edge,
            slippage=fill.slippage,
            spread_cost=fill.spread_cost,
            fee_paid=fill.fee,
            winner_fee=winner_fee,
            outcome=signal.actual_outcome,
            pnl=pnl,
            won=won,
            trade_date=signal.end_date[:10] if signal.end_date else "",
            capital_before=self.capital - pnl,
            capital_after=self.capital,
        )

        return trade

    def run(
        self,
        markets_path: str | Path,
        cache_path: str | Path,
        entry_prices: Optional[list[float]] = None,
    ) -> SimulationReport:
        """
        Run the full simulation.

        Args:
            markets_path: Path to historical_markets.json
            cache_path: Path to claude_cache.json
            entry_prices: List of simulated entry prices to test per market.
                          Defaults to [0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80]
        """
        if entry_prices is None:
            entry_prices = [0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80]

        markets, cache = self.load_data(markets_path, cache_path)

        # Sort markets chronologically by end_date
        markets.sort(key=lambda m: m.get("end_date", ""))

        min_edge = self.config["execution"]["min_edge_threshold"]

        for market in markets:
            key = _cache_key(market["question"])
            if key not in cache:
                continue

            claude_estimate = cache[key]

            for entry_price in entry_prices:
                signal = generate_signal(
                    market=market,
                    claude_estimate=claude_estimate,
                    entry_price=entry_price,
                    yes_threshold=min_edge,
                    no_threshold=min_edge,
                )

                trade = self._process_signal(signal)
                if trade is not None:
                    self.trades.append(trade)

        # Build final report
        report = build_report(
            trades=self.trades,
            initial_capital=self.initial_capital,
            equity_curve=self.equity_curve,
        )

        # Compute assumption sensitivity
        report.assumptions_impact = self._compute_assumption_impact()

        return report

    def _compute_assumption_impact(self) -> dict:
        """Quantify which assumptions dominate results."""
        filled = [t for t in self.trades if t.outcome is not None]
        if not filled:
            return {}

        total_pnl = sum(t.pnl for t in filled)
        total_fees = sum(t.fee_paid + t.winner_fee for t in filled)
        total_slippage = sum(t.slippage * t.size_usd for t in filled)
        total_spread = sum(t.spread_cost * t.size_usd for t in filled)
        total_turnover = sum(t.size_usd for t in filled)

        gross_pnl = total_pnl + total_fees + total_slippage + total_spread

        return {
            "gross_pnl_before_costs": round(gross_pnl, 2),
            "net_pnl_after_costs": round(total_pnl, 2),
            "total_cost_drag": round(total_fees + total_slippage + total_spread, 2),
            "fee_impact": {
                "total_usd": round(total_fees, 2),
                "pct_of_gross": round(total_fees / gross_pnl * 100, 2) if gross_pnl else 0,
                "pct_of_turnover": round(total_fees / total_turnover * 100, 4) if total_turnover else 0,
            },
            "slippage_impact": {
                "total_usd": round(total_slippage, 2),
                "pct_of_gross": round(total_slippage / gross_pnl * 100, 2) if gross_pnl else 0,
                "pct_of_turnover": round(total_slippage / total_turnover * 100, 4) if total_turnover else 0,
            },
            "spread_impact": {
                "total_usd": round(total_spread, 2),
                "pct_of_gross": round(total_spread / gross_pnl * 100, 2) if gross_pnl else 0,
                "pct_of_turnover": round(total_spread / total_turnover * 100, 4) if total_turnover else 0,
            },
            "unfilled_trades": self.trade_counter - len(filled),
            "fill_rate_pct": round(len(filled) / self.trade_counter * 100, 2) if self.trade_counter else 0,
            "dominant_assumption": _identify_dominant(total_fees, total_slippage, total_spread),
        }

    def reset(self):
        """Reset simulator state for a fresh run."""
        self.capital = self.initial_capital
        self.trades = []
        self.equity_curve = [self.initial_capital]
        self.open_positions = {}
        self.trade_counter = 0
        self.rng = random.Random(self.config.get("random_seed", 42))


def _identify_dominant(fees: float, slippage: float, spread: float) -> str:
    """Identify which assumption has the largest impact."""
    costs = {"fees": fees, "slippage": slippage, "spread": spread}
    dominant = max(costs, key=costs.get)
    total = fees + slippage + spread
    pct = costs[dominant] / total * 100 if total > 0 else 0
    return f"{dominant} ({pct:.1f}% of total cost drag)"
