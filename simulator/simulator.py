"""
Paper-trade simulator engine.

Consumes detector output (Claude probability estimates) and historical market data,
simulates fills using configurable cost models, and produces reproducible PnL results.

Usage:
    engine = SimulatorEngine(config)
    report = engine.run(markets, claude_cache)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import random
from copy import deepcopy
from dataclasses import asdict
from typing import Optional

import yaml

from .fill_model import simulate_fill
from .metrics import TradeRecord, build_report
from .sizing import compute_position_size

logger = logging.getLogger(__name__)

# Same entry prices as the backtest engine for comparability
ENTRY_PRICES = [0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80]

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "backtest", "data")
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yaml")


def load_config(path: Optional[str] = None) -> dict:
    """Load simulator config from YAML."""
    path = path or CONFIG_PATH
    with open(path) as f:
        return yaml.safe_load(f)


def _cache_key(question: str) -> str:
    """SHA256 hash key matching backtest cache format."""
    return hashlib.sha256(question.encode()).hexdigest()[:16]


def load_inputs(
    markets_path: Optional[str] = None,
    cache_path: Optional[str] = None,
) -> tuple[list[dict], dict]:
    """Load historical markets and Claude estimate cache."""
    markets_path = markets_path or os.path.join(DATA_DIR, "historical_markets.json")
    cache_path = cache_path or os.path.join(DATA_DIR, "claude_cache.json")

    with open(markets_path) as f:
        markets_data = json.load(f)
    markets = markets_data.get("markets", [])

    claude_cache = {}
    if os.path.exists(cache_path):
        with open(cache_path) as f:
            claude_cache = json.load(f)

    logger.info(f"Loaded {len(markets)} markets, {len(claude_cache)} cached estimates")
    return markets, claude_cache


class SimulatorEngine:
    """
    Deterministic paper-trade simulator.

    Given detector output (Claude probability estimates) and market data,
    simulates fills with configurable fees, slippage, and fill probability,
    then resolves trades against actual outcomes.

    Same inputs + same config + same seed = same outputs.
    """

    def __init__(self, config: dict):
        self.config = config
        self.rng = random.Random(config.get("random_seed", 42))

    def run(
        self,
        markets: list[dict],
        claude_cache: dict,
        max_markets: int = 0,
    ) -> dict:
        """
        Run the full simulation.

        Args:
            markets: List of historical market dicts with actual outcomes.
            claude_cache: Dict mapping SHA256(question)[:16] -> estimate dict.
            max_markets: If >0, limit to first N markets.

        Returns:
            SimulationReport as dict with per-trade logs, daily summaries,
            and aggregate metrics.
        """
        if max_markets > 0:
            markets = markets[:max_markets]

        initial_capital = self.config["capital"]["initial"]
        capital = initial_capital
        equity_curve = [capital]
        trades: list[TradeRecord] = []
        trade_id = 0
        active_positions = 0
        max_concurrent = self.config["execution"]["max_concurrent_positions"]
        min_edge = self.config["execution"]["min_edge_threshold"]
        price_lo, price_hi = self.config["filters"]["price_range"]
        min_liquidity = self.config["filters"]["min_liquidity"]
        min_volume = self.config["filters"]["min_volume"]

        for i, market in enumerate(markets):
            question = market["question"]
            actual = market["actual_outcome"]
            market_id = market.get("id", str(i))
            volume = market.get("volume", 5000.0)
            liquidity = market.get("liquidity", 1000.0)
            end_date = market.get("end_date", "2026-01-01")[:10]

            # Filter: minimum liquidity/volume
            if liquidity < min_liquidity or volume < min_volume:
                continue

            # Look up detector output
            key = _cache_key(question)
            estimate = claude_cache.get(key)
            if estimate is None:
                continue

            claude_prob = estimate["probability"]

            # Simulate at each entry price
            for entry_price in ENTRY_PRICES:
                # Filter: price range
                if entry_price < price_lo or entry_price > price_hi:
                    continue

                # Position cap
                if active_positions >= max_concurrent:
                    break

                edge = claude_prob - entry_price
                abs_edge = abs(edge)

                if abs_edge < min_edge:
                    continue

                direction = "buy_yes" if edge > 0 else "buy_no"

                # Size the position
                size = compute_position_size(
                    capital=capital,
                    edge=abs_edge,
                    win_probability=claude_prob if direction == "buy_yes" else 1.0 - claude_prob,
                    config=self.config,
                )
                if size < 0.10:
                    continue

                # Simulate fill
                fill = simulate_fill(
                    market_price=entry_price,
                    direction=direction,
                    edge=abs_edge,
                    order_size_usd=size,
                    volume=volume,
                    liquidity=liquidity,
                    config=self.config,
                    rng=self.rng,
                )

                if not fill.filled:
                    # Record unfilled attempt
                    trade_id += 1
                    trades.append(TradeRecord(
                        trade_id=trade_id,
                        market_id=market_id,
                        question=question,
                        direction=direction,
                        entry_price=entry_price,
                        fill_price=0.0,
                        size_usd=size,
                        shares=0.0,
                        edge_pre_cost=abs_edge,
                        edge_post_cost=0.0,
                        slippage=0.0,
                        spread_cost=0.0,
                        fee_paid=0.0,
                        winner_fee=0.0,
                        outcome=actual,
                        pnl=0.0,
                        won=False,
                        trade_date=end_date,
                        capital_before=capital,
                        capital_after=capital,
                    ))
                    continue

                # Resolve trade (entry fee deducted from PnL)
                won, pnl, winner_fee_amt = self._resolve(
                    direction=direction,
                    fill_price=fill.fill_price,
                    size=size,
                    actual=actual,
                    entry_fee=fill.fee,
                )

                shares = size / fill.fill_price if fill.fill_price > 0 else 0.0
                capital_before = capital
                capital += pnl
                equity_curve.append(capital)

                trade_id += 1
                trades.append(TradeRecord(
                    trade_id=trade_id,
                    market_id=market_id,
                    question=question,
                    direction=direction,
                    entry_price=entry_price,
                    fill_price=fill.fill_price,
                    size_usd=size,
                    shares=shares,
                    edge_pre_cost=abs_edge,
                    edge_post_cost=fill.effective_edge,
                    slippage=fill.slippage,
                    spread_cost=fill.spread_cost,
                    fee_paid=fill.fee,
                    winner_fee=winner_fee_amt,
                    outcome=actual,
                    pnl=pnl,
                    won=won,
                    trade_date=end_date,
                    capital_before=capital_before,
                    capital_after=capital,
                ))

            if (i + 1) % 100 == 0:
                logger.info(
                    f"Processed {i + 1}/{len(markets)} markets, "
                    f"{len(trades)} trades, capital=${capital:.2f}"
                )

        report = build_report(trades, initial_capital, equity_curve)
        return asdict(report)

    def _resolve(
        self,
        direction: str,
        fill_price: float,
        size: float,
        actual: str,
        entry_fee: float = 0.0,
    ) -> tuple[bool, float, float]:
        """
        Resolve a filled trade against the actual outcome.

        Entry fee is deducted from PnL regardless of win/loss.
        Returns (won, net_pnl, winner_fee_amount).
        """
        winner_fee_rate = self.config["fees"]["winner_fee"]

        if direction == "buy_yes":
            won = actual == "YES_WON"
        else:
            won = actual == "NO_WON"

        if won:
            shares = size / fill_price
            gross_payout = shares * 1.0  # Each share pays $1 on win
            winner_fee_amt = gross_payout * winner_fee_rate
            pnl = gross_payout - winner_fee_amt - size - entry_fee
        else:
            pnl = -size - entry_fee
            winner_fee_amt = 0.0

        return won, pnl, winner_fee_amt


def run_simulation(
    config_path: Optional[str] = None,
    markets_path: Optional[str] = None,
    cache_path: Optional[str] = None,
    max_markets: int = 0,
) -> dict:
    """Convenience function: load config + data, run simulation, return report."""
    config = load_config(config_path)
    markets, cache = load_inputs(markets_path, cache_path)
    engine = SimulatorEngine(config)
    return engine.run(markets, cache, max_markets=max_markets)
