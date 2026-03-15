"""Logarithmic Market Scoring Rule (LMSR) pricing and inefficiency detection.

Implements the Hanson LMSR automated market maker model for:
- Theoretical price computation from outstanding quantities
- Trade cost calculation
- Inefficiency signal detection (LMSR price vs CLOB orderbook divergence)

Reference: QR-PM-2026-0041, "LMSR Pricing Mechanism & Inefficiency Detection"

Key formulas:
    Cost function:  C(q) = b * ln(sum(e^(qi/b) for i in 1..n))
    Price function: pi(q) = e^(qi/b) / sum(e^(qj/b) for j in 1..n)  (softmax)
    Trade cost:     cost = C(q_after) - C(q_before)
    Max MM loss:    L_max = b * ln(n)

For binary markets (n=2) with b=100,000:
    L_max = 100,000 * ln(2) = $69,315
"""
from __future__ import annotations

import math
import logging
from dataclasses import dataclass
from typing import Optional

try:
    import structlog
    logger = structlog.get_logger(__name__)
    _USE_STRUCTLOG = True
except ImportError:
    logger = logging.getLogger(__name__)
    _USE_STRUCTLOG = False


def _log(level: str, msg: str, **kwargs) -> None:
    if _USE_STRUCTLOG:
        getattr(logger, level)(msg, **kwargs)
    else:
        extra = " ".join(f"{k}={v}" for k, v in kwargs.items())
        getattr(logger, level)(f"{msg} {extra}")


# ---------------------------------------------------------------------------
# LMSR Core Functions
# ---------------------------------------------------------------------------

def lmsr_cost(quantities: list[float], b: float) -> float:
    """LMSR cost function C(q) = b * ln(sum(e^(qi/b))).

    Args:
        quantities: Outstanding quantity vector q = [q1, q2, ..., qn]
        b: Liquidity parameter (larger b = more liquidity, tighter spreads,
           higher max market maker loss).

    Returns:
        Cost value C(q).
    """
    if b <= 0:
        raise ValueError(f"Liquidity parameter b must be positive, got {b}")

    # Use logsumexp trick for numerical stability
    scaled = [qi / b for qi in quantities]
    max_scaled = max(scaled)
    log_sum = max_scaled + math.log(sum(math.exp(s - max_scaled) for s in scaled))
    return b * log_sum


def lmsr_prices(quantities: list[float], b: float) -> list[float]:
    """LMSR price function (softmax over quantities).

    pi(q) = e^(qi/b) / sum(e^(qj/b))

    This is identical to the softmax function in neural network classifiers.
    The market is a neural network that prices beliefs.

    Critical properties: sum(pi) = 1 and pi in (0, 1) for all i.

    Args:
        quantities: Outstanding quantity vector.
        b: Liquidity parameter.

    Returns:
        Price vector [p1, p2, ..., pn] summing to 1.0.
    """
    if b <= 0:
        raise ValueError(f"Liquidity parameter b must be positive, got {b}")

    scaled = [qi / b for qi in quantities]
    max_scaled = max(scaled)
    exps = [math.exp(s - max_scaled) for s in scaled]
    total = sum(exps)
    return [e / total for e in exps]


def lmsr_trade_cost(
    quantities: list[float],
    outcome_index: int,
    delta: float,
    b: float,
) -> float:
    """Cost of moving outcome i by delta shares.

    Cost = C(q1,...,qi+delta,...,qn) - C(q1,...,qi,...,qn)

    Args:
        quantities: Current outstanding quantity vector.
        outcome_index: Which outcome to trade (0-indexed).
        delta: Number of shares to buy (positive) or sell (negative).
        b: Liquidity parameter.

    Returns:
        Cost of the trade in dollars. Positive = buyer pays.
    """
    cost_before = lmsr_cost(quantities, b)

    quantities_after = list(quantities)
    quantities_after[outcome_index] += delta
    cost_after = lmsr_cost(quantities_after, b)

    return cost_after - cost_before


def lmsr_max_loss(b: float, n: int = 2) -> float:
    """Maximum market maker loss: L_max = b * ln(n).

    For binary markets (n=2) with b=100,000: L_max = $69,315.

    Args:
        b: Liquidity parameter.
        n: Number of outcomes.

    Returns:
        Maximum possible loss for the market maker.
    """
    return b * math.log(n)


def lmsr_implied_quantities(
    prices: list[float],
    b: float,
) -> list[float]:
    """Reverse-engineer quantities from observed prices.

    Given prices (softmax output), invert to get quantity ratios.
    Since softmax is shift-invariant, we set q1=0 as reference.

    qi = b * ln(pi / p1)  (relative to outcome 1)

    Args:
        prices: Observed price vector [p1, p2, ..., pn].
        b: Liquidity parameter.

    Returns:
        Implied quantity vector (with q[0] = 0 as reference).
    """
    if any(p <= 0 for p in prices):
        raise ValueError("All prices must be positive")

    ref_price = prices[0]
    return [b * math.log(p / ref_price) for p in prices]


# ---------------------------------------------------------------------------
# Inefficiency Detection
# ---------------------------------------------------------------------------

@dataclass
class InefficiencySignal:
    """Result of LMSR inefficiency detection."""
    market_id: str
    lmsr_price_yes: float
    clob_price_yes: float
    divergence: float          # lmsr_price - clob_price
    abs_divergence: float
    is_inefficient: bool
    direction: str             # "buy_yes", "buy_no", or "hold"
    estimated_edge: float      # abs_divergence minus fees
    lmsr_b: float
    implied_quantities: list[float]


def detect_inefficiency(
    market_id: str,
    clob_price_yes: float,
    volume_yes: float,
    volume_no: float,
    b: float = 100_000.0,
    min_divergence: float = 0.03,
    fee_rate: float = 0.02,
) -> InefficiencySignal:
    """Detect LMSR vs CLOB price inefficiency.

    Compares the theoretical LMSR price (derived from cumulative volume
    as a proxy for outstanding quantities) against the live CLOB mid-price.
    Divergence beyond a threshold signals a tradeable inefficiency.

    Args:
        market_id: Market identifier.
        clob_price_yes: Current CLOB YES mid-price (0-1).
        volume_yes: Cumulative YES volume (proxy for outstanding YES quantity).
        volume_no: Cumulative NO volume (proxy for outstanding NO quantity).
        b: LMSR liquidity parameter.
        min_divergence: Minimum price divergence to signal inefficiency.
        fee_rate: Fee rate for edge calculation.

    Returns:
        InefficiencySignal with divergence analysis.
    """
    quantities = [volume_yes, volume_no]
    prices = lmsr_prices(quantities, b)
    lmsr_yes = prices[0]

    divergence = lmsr_yes - clob_price_yes
    abs_div = abs(divergence)

    # Fee at the trade price
    trade_price = clob_price_yes if divergence > 0 else (1 - clob_price_yes)
    fee = trade_price * (1 - trade_price) * fee_rate
    edge = abs_div - fee

    is_inefficient = abs_div >= min_divergence and edge > 0

    if is_inefficient:
        direction = "buy_yes" if divergence > 0 else "buy_no"
    else:
        direction = "hold"

    signal = InefficiencySignal(
        market_id=market_id,
        lmsr_price_yes=lmsr_yes,
        clob_price_yes=clob_price_yes,
        divergence=divergence,
        abs_divergence=abs_div,
        is_inefficient=is_inefficient,
        direction=direction,
        estimated_edge=max(0.0, edge),
        lmsr_b=b,
        implied_quantities=quantities,
    )

    if is_inefficient:
        _log(
            "info",
            "lmsr_inefficiency_detected",
            market_id=market_id,
            lmsr_yes=round(lmsr_yes, 4),
            clob_yes=round(clob_price_yes, 4),
            divergence=round(divergence, 4),
            edge=round(edge, 4),
            direction=direction,
        )

    return signal


def estimate_slippage(
    quantities: list[float],
    outcome_index: int,
    size_usd: float,
    b: float,
) -> float:
    """Estimate LMSR slippage for a given trade size.

    Computes the average execution price vs spot price for buying
    `size_usd` worth of shares.

    Args:
        quantities: Current outstanding quantities.
        outcome_index: Outcome to trade.
        size_usd: Dollar size of the trade.
        b: Liquidity parameter.

    Returns:
        Slippage as a fraction (e.g., 0.005 = 0.5% slippage).
    """
    spot_prices = lmsr_prices(quantities, b)
    spot = spot_prices[outcome_index]

    if spot <= 0 or spot >= 1:
        return 0.0

    # Approximate shares from dollar size
    approx_shares = size_usd / spot
    trade_cost = lmsr_trade_cost(quantities, outcome_index, approx_shares, b)

    if approx_shares <= 0:
        return 0.0

    avg_price = trade_cost / approx_shares
    slippage = (avg_price - spot) / spot
    return max(0.0, slippage)
