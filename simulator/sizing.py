"""
Position sizing rules for the paper-trade simulator.

Supports:
- Fixed fraction of capital
- Kelly criterion (fractional)
- Capped Kelly (Kelly with hard dollar cap)
"""

from __future__ import annotations

import math


def fixed_fraction_size(
    capital: float,
    fraction: float,
    **kwargs,
) -> float:
    """Size = capital * fraction. Simple and predictable."""
    return capital * fraction


def kelly_size(
    capital: float,
    edge: float,
    win_probability: float,
    kelly_fraction: float = 0.25,
    max_allocation: float = 0.20,
    min_size: float = 1.0,
    **kwargs,
) -> float:
    """
    Kelly criterion sizing with fractional Kelly for safety.

    Full Kelly: f* = (bp - q) / b
    where b = odds, p = win prob, q = 1 - p

    For binary markets: b = (1/entry_price - 1), p = win_probability
    We use fractional Kelly (default quarter-Kelly) and cap at max_allocation.
    """
    if edge <= 0 or win_probability <= 0 or win_probability >= 1:
        return 0.0

    q = 1.0 - win_probability
    # For binary outcome: odds = edge / cost_of_being_wrong
    # Simplified: Kelly fraction = edge / variance
    # But standard form: f* = p - q/b = p - q*(1/(odds))
    # With edge = p * payout - cost, for unit bet:
    # f* = edge (when odds are 1:1 on binary market)
    # More precisely: f* = (p * b - q) / b where b = net odds
    # For simplicity with calibrated edge:
    full_kelly = edge  # Approximation for small edge binary markets

    sized = capital * full_kelly * kelly_fraction
    capped = min(sized, capital * max_allocation)
    return max(capped, min_size) if capped >= min_size else 0.0


def capped_size(
    capital: float,
    edge: float,
    win_probability: float,
    kelly_fraction: float = 0.25,
    max_allocation: float = 0.20,
    max_position_usd: float = 5.0,
    min_position_usd: float = 1.0,
    **kwargs,
) -> float:
    """Kelly sizing with an additional hard dollar cap."""
    kelly = kelly_size(
        capital=capital,
        edge=edge,
        win_probability=win_probability,
        kelly_fraction=kelly_fraction,
        max_allocation=max_allocation,
        min_size=min_position_usd,
    )
    if kelly <= 0:
        return 0.0
    return min(kelly, max_position_usd)


def compute_position_size(
    capital: float,
    edge: float,
    win_probability: float,
    config: dict,
) -> float:
    """
    Dispatch to the configured sizing method.

    Returns position size in USD, or 0.0 if no trade.
    """
    sizing_config = config["sizing"]
    method = sizing_config["method"]

    if method == "fixed_fraction":
        return fixed_fraction_size(
            capital=capital,
            fraction=sizing_config["fixed_fraction"]["fraction"],
        )
    elif method == "kelly":
        kc = sizing_config["kelly"]
        return kelly_size(
            capital=capital,
            edge=edge,
            win_probability=win_probability,
            kelly_fraction=kc["kelly_fraction"],
            max_allocation=kc["max_allocation"],
            min_size=kc["min_size"],
        )
    elif method == "capped_kelly":
        kc = sizing_config["kelly"]
        cc = sizing_config["capped"]
        return capped_size(
            capital=capital,
            edge=edge,
            win_probability=win_probability,
            kelly_fraction=kc["kelly_fraction"],
            max_allocation=kc["max_allocation"],
            max_position_usd=cc["max_position_usd"],
            min_position_usd=cc["min_position_usd"],
        )
    else:
        raise ValueError(f"Unknown sizing method: {method}")
