"""Fee-model helpers for tail-calibration research and execution planning.

This module keeps venue fee math in one place so signal and strategy layers can
reason about *tradable* probability bins instead of raw displayed prices.
"""

from __future__ import annotations

from dataclasses import dataclass
import math


def _clamp_probability(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def round_up_to_cent(value: float) -> float:
    """Round a dollar fee up to the next cent."""
    if value <= 0:
        return 0.0
    return math.ceil(float(value) * 100.0 - 1e-12) / 100.0


@dataclass(frozen=True)
class FeeEstimate:
    venue: str
    price: float
    contracts: float
    maker: bool
    fee_dollars: float
    fee_per_contract: float
    effective_fee_rate: float
    formula_key: str


def kalshi_fee_estimate(
    *,
    price: float,
    contracts: float,
    maker: bool = False,
    coefficient: float | None = None,
) -> FeeEstimate:
    """Estimate Kalshi fees using the February 2026 schedule.

    General schedule from the Feb. 5, 2026 fee PDF:
    - taker: round_up(0.07 * C * P * (1-P))
    - maker: round_up(0.0175 * C * P * (1-P))
    """
    p = _clamp_probability(price)
    c = max(0.0, float(contracts))
    coeff = float(coefficient if coefficient is not None else (0.0175 if maker else 0.07))
    raw_fee = coeff * c * p * (1.0 - p)
    fee = round_up_to_cent(raw_fee)
    notional = max(1e-12, c * p)
    return FeeEstimate(
        venue="kalshi",
        price=p,
        contracts=c,
        maker=bool(maker),
        fee_dollars=fee,
        fee_per_contract=fee / c if c > 0 else 0.0,
        effective_fee_rate=fee / notional,
        formula_key="kalshi_general_maker" if maker else "kalshi_general_taker",
    )


_POLYMARKET_SCHEDULES: dict[str, tuple[float, float]] = {
    "sports": (0.0175, 1.0),
    "crypto": (0.25, 2.0),
}


def polymarket_fee_estimate(
    *,
    price: float,
    contracts: float,
    market_type: str = "crypto",
    maker: bool = False,
    fee_rate: float | None = None,
    exponent: float | None = None,
) -> FeeEstimate:
    """Estimate Polymarket taker fees for fee-enabled categories.

    Confirmed schedules in the repo research:
    - sports: fee_rate=0.0175, exponent=1
    - crypto: fee_rate=0.25, exponent=2

    Resting maker orders are modeled as zero direct fee here; any rebates are
    market-program dependent and should be treated separately.
    """
    p = _clamp_probability(price)
    c = max(0.0, float(contracts))
    schedule_key = str(market_type or "crypto").strip().lower()
    default_rate, default_exponent = _POLYMARKET_SCHEDULES.get(schedule_key, (0.0, 0.0))
    resolved_fee_rate = default_rate if fee_rate is None else float(fee_rate)
    resolved_exponent = default_exponent if exponent is None else float(exponent)
    if maker or resolved_fee_rate <= 0.0:
        fee = 0.0
    else:
        fee = c * p * resolved_fee_rate * ((p * (1.0 - p)) ** resolved_exponent)
    notional = max(1e-12, c * p)
    return FeeEstimate(
        venue="polymarket",
        price=p,
        contracts=c,
        maker=bool(maker),
        fee_dollars=fee,
        fee_per_contract=fee / c if c > 0 else 0.0,
        effective_fee_rate=fee / notional,
        formula_key=f"polymarket_{schedule_key}_{'maker' if maker else 'taker'}",
    )


def breakeven_win_probability(*, entry_price: float, fee_dollars: float, contracts: float) -> float:
    """Return the minimum win probability needed to break even.

    For a binary contract that pays $1 on success, the breakeven probability is
    the all-in cost per contract.
    """
    c = max(1e-12, float(contracts))
    cost = float(entry_price) + (float(fee_dollars) / c)
    return _clamp_probability(cost)

