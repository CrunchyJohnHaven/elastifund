"""Quarter-Kelly position sizing with asymmetric NO-bias scaling.

Implements the Kelly criterion for binary prediction market position sizing,
with safety rails and category-based haircuts per COMMAND_NODE Section 3.
"""
from __future__ import annotations

import logging
import os
from typing import Dict, Optional

try:
    import structlog
    logger = structlog.get_logger(__name__)
    _USE_STRUCTLOG = True
except ImportError:
    logger = logging.getLogger(__name__)
    _USE_STRUCTLOG = False

# Bankroll scaling tiers: (threshold, kelly_multiplier)
BANKROLL_TIERS = [
    (500.0, 0.75),
    (300.0, 0.50),
    (0.0, 0.25),
]

# Base Kelly fractions by side
KELLY_MULT_YES = 0.25  # buy_yes: conservative
KELLY_MULT_NO = 0.35   # buy_no: structural NO-bias edge (76% win rate)

# Position limits
MIN_POSITION_USD = 0.50
MAX_POSITION_USD_DEFAULT = 10.0
CATEGORY_CONCENTRATION_LIMIT = 3  # >3 positions in same category → 50% haircut

# Winner fee on Polymarket
WINNER_FEE = 0.02


def _log(level: str, msg: str, **kwargs) -> None:
    """Log with structlog kwargs or stdlib formatting."""
    if _USE_STRUCTLOG:
        getattr(logger, level)(msg, **kwargs)
    else:
        extra = " ".join(f"{k}={v}" for k, v in kwargs.items())
        getattr(logger, level)(f"{msg} {extra}")


def kelly_fraction(p_estimated: float, p_market: float, side: str) -> float:
    """Compute raw Kelly fraction for a binary prediction market trade.

    Uses the standard Kelly formula adjusted for winner fees:
        f* = (p * odds - q) / odds
    where odds = (payout - cost) / cost, payout = 1 - winner_fee.

    Args:
        p_estimated: Our estimated probability of YES (0-1).
        p_market: Current market YES price (0-1).
        side: "buy_yes" or "buy_no".

    Returns:
        Raw Kelly fraction (0-1). Returns 0 if trade has negative expected value.
    """
    payout = 1.0 - WINNER_FEE  # Net $0.98 per winning share

    if side == "buy_yes":
        p_win = p_estimated
        cost = p_market
    else:  # buy_no
        p_win = 1.0 - p_estimated
        cost = 1.0 - p_market

    if cost <= 0 or cost >= payout or p_win <= 0 or p_win >= 1:
        return 0.0

    odds = (payout - cost) / cost
    if odds <= 0:
        return 0.0

    kelly = (p_win * odds - (1.0 - p_win)) / odds
    return max(0.0, kelly)


def position_size(
    bankroll: float,
    kelly_f: float,
    side: str,
    category: str = "",
    category_counts: Optional[Dict[str, int]] = None,
    max_position_override: Optional[float] = None,
) -> float:
    """Compute final position size in USD from Kelly fraction.

    Applies quarter-Kelly base, asymmetric NO-bias boost, bankroll scaling,
    and category concentration haircuts.

    Args:
        bankroll: Current total bankroll (cash + open position value).
        kelly_f: Raw Kelly fraction from kelly_fraction().
        side: "buy_yes" or "buy_no".
        category: Market category (e.g., "Politics", "Weather").
        category_counts: Dict of category -> number of open positions.
        max_position_override: Hard ceiling from .env MAX_POSITION_USD.

    Returns:
        Position size in USD. Returns 0.0 if trade should be skipped.
    """
    if kelly_f <= 0:
        return 0.0

    # 1. Base Kelly multiplier: asymmetric YES/NO
    base_mult = KELLY_MULT_NO if side == "buy_no" else KELLY_MULT_YES

    # 2. Bankroll scaling
    bankroll_mult = BANKROLL_TIERS[-1][1]  # default: smallest tier
    for threshold, mult in BANKROLL_TIERS:
        if bankroll >= threshold:
            bankroll_mult = mult
            break

    # Use the larger of base or bankroll multiplier (bankroll scaling overrides
    # the base only upward — at low bankroll we stick with base)
    effective_mult = max(base_mult, bankroll_mult) if bankroll >= 300 else base_mult

    # 3. Raw sized amount
    raw_size = kelly_f * effective_mult * bankroll

    # 4. Category concentration haircut
    if category_counts and category:
        count = category_counts.get(category, 0)
        if count > CATEGORY_CONCENTRATION_LIMIT:
            raw_size *= 0.50
            _log(
                "info",
                "category_haircut_applied",
                category=category,
                open_positions=count,
                size_after=round(raw_size, 2),
            )

    # 5. Apply hard limits
    max_pos = max_position_override or float(
        os.environ.get("MAX_POSITION_USD", MAX_POSITION_USD_DEFAULT)
    )

    final_size = min(raw_size, max_pos)
    final_size = max(final_size, 0.0)

    # 6. Floor: skip if below minimum
    if final_size < MIN_POSITION_USD:
        return 0.0

    # 7. Warning if Kelly suggests large position
    if raw_size > 5.0:
        _log(
            "warning",
            "kelly_large_position",
            kelly_f=round(kelly_f, 4),
            raw_size=round(raw_size, 2),
            final_size=round(final_size, 2),
            bankroll=round(bankroll, 2),
        )

    return round(final_size, 2)
