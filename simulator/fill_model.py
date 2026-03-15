"""
Fill model for paper-trade simulator.

Simulates order execution with configurable assumptions for:
- Taker fills (spread crossing, immediate, with slippage)
- Maker fills (passive limit orders, probabilistic fill)
- Slippage as a function of order size and liquidity
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Optional


@dataclass
class FillResult:
    """Result of attempting to fill an order."""
    filled: bool
    fill_price: float          # Actual execution price after slippage
    slippage: float            # Price impact in absolute terms
    spread_cost: float         # Cost of crossing spread (taker only)
    fee: float                 # Transaction fee in USD
    total_cost: float          # Total cost: size * fill_price + fee
    effective_edge: float      # Edge after all costs


def classify_market_tier(volume: float, liquidity: float) -> str:
    """Classify market into a spread tier based on volume and liquidity."""
    if liquidity >= 10000 and volume >= 50000:
        return "high_volume"
    elif liquidity >= 2000 and volume >= 5000:
        return "us_weather"
    elif liquidity >= 500:
        return "international"
    else:
        return "niche"


def get_half_spread(tier: str, spread_config: dict) -> float:
    """Get half-spread in price units (0-1 scale) for a market tier."""
    tier_config = spread_config.get(tier, spread_config["default"])
    return tier_config["half_spread_cents"] / 100.0


def compute_taker_slippage(
    order_size_usd: float,
    liquidity: float,
    config: dict,
) -> float:
    """
    Compute slippage for a taker order.

    Slippage = base + size_impact + liquidity_impact
    All in price units (0-1 scale).
    """
    base = config["base_slippage_bps"] / 10000.0
    size_impact = (config["size_impact_bps_per_dollar"] / 10000.0) * order_size_usd
    liquidity_impact = config["liquidity_impact_factor"] * (order_size_usd / max(liquidity, 1.0))
    return base + size_impact + liquidity_impact


def compute_maker_fill_probability(
    edge: float,
    config: dict,
) -> float:
    """
    Compute probability that a maker (passive) order gets filled.

    Higher edge → order is further from market → lower fill probability.
    Uses exponential decay: P(fill) = base * exp(-decay * |edge|)
    """
    base = config["base_fill_probability"]
    decay = config["distance_decay"]
    floor = config["min_fill_probability"]
    prob = base * math.exp(-decay * abs(edge))
    return max(prob, floor)


def simulate_taker_fill(
    market_price: float,
    direction: str,
    edge: float,
    order_size_usd: float,
    volume: float,
    liquidity: float,
    taker_config: dict,
    spread_config: dict,
    fee_rate: float,
    winner_fee_rate: float,
) -> FillResult:
    """
    Simulate a taker fill (market order that crosses the spread).

    For buy_yes: fill_price = market_price + half_spread + slippage
    For buy_no:  fill_price on NO side = (1 - market_price) + half_spread + slippage
    """
    tier = classify_market_tier(volume, liquidity)
    half_spread = get_half_spread(tier, spread_config)
    slippage = compute_taker_slippage(order_size_usd, liquidity, taker_config)

    if direction == "buy_yes":
        base_price = market_price
    else:  # buy_no
        base_price = 1.0 - market_price

    fill_price = base_price + half_spread + slippage
    fill_price = min(fill_price, 0.99)  # Can't exceed 0.99

    # Number of shares = order_size / fill_price
    shares = order_size_usd / fill_price if fill_price > 0 else 0

    # Fee on entry
    fee = order_size_usd * fee_rate

    # Effective edge: what's left after spread + slippage + fees
    cost_drag = half_spread + slippage + fee_rate
    # Winner fee reduces expected payout
    effective_edge = edge - cost_drag - (winner_fee_rate * max(edge, 0))

    total_cost = order_size_usd + fee

    return FillResult(
        filled=True,
        fill_price=fill_price,
        slippage=slippage,
        spread_cost=half_spread,
        fee=fee,
        total_cost=total_cost,
        effective_edge=effective_edge,
    )


def simulate_maker_fill(
    market_price: float,
    direction: str,
    edge: float,
    order_size_usd: float,
    volume: float,
    liquidity: float,
    maker_config: dict,
    spread_config: dict,
    fee_rate: float,
    winner_fee_rate: float,
    rng: Optional[random.Random] = None,
) -> FillResult:
    """
    Simulate a maker fill (passive limit order).

    Maker orders have no spread cost but only fill probabilistically.
    Price improvement is possible (fill at better price than mid).
    """
    if rng is None:
        rng = random.Random()

    fill_prob = compute_maker_fill_probability(edge, maker_config)
    filled = rng.random() < fill_prob

    if not filled:
        return FillResult(
            filled=False,
            fill_price=0.0,
            slippage=0.0,
            spread_cost=0.0,
            fee=0.0,
            total_cost=0.0,
            effective_edge=0.0,
        )

    # Maker gets price improvement (fills at or better than mid)
    improvement = maker_config["price_improvement_bps"] / 10000.0

    if direction == "buy_yes":
        fill_price = market_price - improvement
    else:
        fill_price = (1.0 - market_price) - improvement

    fill_price = max(fill_price, 0.01)  # Floor

    fee = order_size_usd * fee_rate  # Usually 0 for makers
    effective_edge = edge + improvement - fee_rate - (winner_fee_rate * max(edge, 0))

    total_cost = order_size_usd + fee

    return FillResult(
        filled=True,
        fill_price=fill_price,
        slippage=0.0,
        spread_cost=0.0,
        fee=fee,
        total_cost=total_cost,
        effective_edge=effective_edge,
    )


def simulate_fill(
    market_price: float,
    direction: str,
    edge: float,
    order_size_usd: float,
    volume: float,
    liquidity: float,
    config: dict,
    rng: Optional[random.Random] = None,
) -> FillResult:
    """
    Top-level fill simulation dispatcher.

    Reads execution mode from config and delegates to taker or maker model.
    """
    mode = config["execution"]["mode"]
    fee_config = config["fees"]
    fill_config = config["fill_model"]
    spread_config = fill_config["spreads"]

    if mode == "taker":
        return simulate_taker_fill(
            market_price=market_price,
            direction=direction,
            edge=edge,
            order_size_usd=order_size_usd,
            volume=volume,
            liquidity=liquidity,
            taker_config=fill_config["taker"],
            spread_config=spread_config,
            fee_rate=fee_config["taker_rate"],
            winner_fee_rate=fee_config["winner_fee"],
        )
    elif mode == "maker":
        return simulate_maker_fill(
            market_price=market_price,
            direction=direction,
            edge=edge,
            order_size_usd=order_size_usd,
            volume=volume,
            liquidity=liquidity,
            maker_config=fill_config["maker"],
            spread_config=spread_config,
            fee_rate=fee_config["maker_rate"],
            winner_fee_rate=fee_config["winner_fee"],
            rng=rng,
        )
    else:
        raise ValueError(f"Unknown execution mode: {mode}")
