"""Quarter-Kelly position sizing with asymmetric NO-bias scaling.

Implements the Kelly criterion for binary prediction market position sizing,
with fee-aware edge gating, safety rails, and category-based haircuts.

All sizing decisions can be logged to DB via SizingDecision for audit.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, Optional

try:
    import structlog
    logger = structlog.get_logger(__name__)
    _USE_STRUCTLOG = True
except ImportError:
    logger = logging.getLogger(__name__)
    _USE_STRUCTLOG = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Bankroll scaling tiers: (threshold, kelly_multiplier)
BANKROLL_TIERS: list[tuple[float, float]] = [
    (500.0, 0.75),
    (300.0, 0.50),
    (150.0, 0.25),  # explicit lower tier per spec
    (0.0, 0.25),
]

# Base Kelly fractions by side
KELLY_MULT_YES = 0.25  # buy_yes: conservative
KELLY_MULT_NO = 0.35   # buy_no: structural NO-bias edge (76% win rate)

# Position limits
MIN_POSITION_USD = 0.50
MAX_POSITION_USD_DEFAULT = 10.0
CATEGORY_CONCENTRATION_LIMIT = 3  # >3 positions in same category → 50% haircut

# Winner fee on Polymarket (deducted from winning shares)
WINNER_FEE = 0.02

# Fee-aware edge gating defaults
DEFAULT_MIN_EDGE_BUFFER = 0.005  # 0.5% minimum edge after fees
DEFAULT_FEE_RATE = 0.02          # 2% winner fee

# Safe fallback when inputs are missing
SAFE_FALLBACK_USD = 1.0


# ---------------------------------------------------------------------------
# Logging helper
# ---------------------------------------------------------------------------

def _log(level: str, msg: str, **kwargs) -> None:
    if _USE_STRUCTLOG:
        getattr(logger, level)(msg, **kwargs)
    else:
        extra = " ".join(f"{k}={v}" for k, v in kwargs.items())
        getattr(logger, level)(f"{msg} {extra}")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SizingCaps:
    """Caps and configuration for position sizing."""
    max_position_usd: float = MAX_POSITION_USD_DEFAULT
    min_position_usd: float = MIN_POSITION_USD
    min_edge_buffer: float = DEFAULT_MIN_EDGE_BUFFER
    fee_rate: float = DEFAULT_FEE_RATE
    fallback_on_missing: bool = True  # True = use safe fallback; False = skip trade
    safe_fallback_usd: float = SAFE_FALLBACK_USD


@dataclass
class SizingResult:
    """Full sizing decision record — maps to SizingDecision DB table."""
    market_id: str = ""
    side: str = ""
    p_estimated: float = 0.0
    p_market: float = 0.0
    fee_rate: float = DEFAULT_FEE_RATE
    edge_raw: float = 0.0
    edge_after_fee: float = 0.0
    kelly_f: float = 0.0
    kelly_mult: float = 0.0
    bankroll: float = 0.0
    raw_size_usd: float = 0.0
    category_haircut: bool = False
    final_size_usd: float = 0.0
    decision: str = "skip"  # "trade" or "skip"
    skip_reason: str = ""
    extra: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def kelly_fraction(
    p_estimated: float,
    p_market: float,
    side: str,
    fee_rate: float = DEFAULT_FEE_RATE,
) -> float:
    """Compute raw Kelly fraction for a binary prediction market trade.

    Uses the standard Kelly formula adjusted for winner fees:
        f* = (p * odds - q) / odds
    where odds = (payout - cost) / cost, payout = 1 - fee_rate.

    Args:
        p_estimated: Our estimated probability of YES (0-1).
        p_market: Current market YES price (0-1).
        side: "buy_yes" or "buy_no".
        fee_rate: Winner fee rate (default 0.02 = 2%).

    Returns:
        Raw Kelly fraction (0-1). Returns 0 if trade has negative expected value.
    """
    payout = 1.0 - fee_rate

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


def expected_edge_after_fee(
    p_estimated: float,
    p_market: float,
    side: str,
    fee_rate: float = DEFAULT_FEE_RATE,
) -> float:
    """Compute expected edge after fees for a binary market trade.

    Edge = E[payout] - cost, where payout is reduced by the winner fee.

    Args:
        p_estimated: Our estimated probability of YES (0-1).
        p_market: Current market YES price (0-1).
        side: "buy_yes" or "buy_no".
        fee_rate: Winner fee rate.

    Returns:
        Expected edge after fees. Positive means profitable.
    """
    payout = 1.0 - fee_rate

    if side == "buy_yes":
        p_win = p_estimated
        cost = p_market
    else:
        p_win = 1.0 - p_estimated
        cost = 1.0 - p_market

    if cost <= 0 or cost >= 1:
        return -1.0

    # Expected value: p_win * payout + (1 - p_win) * 0 - cost
    ev = p_win * payout - cost
    return ev


def position_usd(
    bankroll: float,
    kelly_f: float,
    side: str,
    category: str = "",
    category_counts: Optional[Dict[str, int]] = None,
    caps: Optional[SizingCaps] = None,
) -> float:
    """Compute final position size in USD from Kelly fraction.

    Applies asymmetric YES/NO multiplier, bankroll scaling,
    and category concentration haircuts.

    Args:
        bankroll: Current total bankroll (cash + open position value).
        kelly_f: Raw Kelly fraction from kelly_fraction().
        side: "buy_yes" or "buy_no".
        category: Market category (e.g., "Politics", "Weather").
        category_counts: Dict of category -> number of open positions.
        caps: SizingCaps with limits. Uses defaults if None.

    Returns:
        Position size in USD. Returns 0.0 if trade should be skipped.
    """
    if caps is None:
        caps = SizingCaps()

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

    # 4. Category concentration haircut (>3 same category → 50%)
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
    final_size = min(raw_size, caps.max_position_usd)
    final_size = max(final_size, 0.0)

    # 6. Floor: skip if below minimum
    if final_size < caps.min_position_usd:
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


def compute_sizing(
    market_id: str,
    p_estimated: float,
    p_market: float,
    side: str,
    bankroll: float,
    category: str = "",
    category_counts: Optional[Dict[str, int]] = None,
    caps: Optional[SizingCaps] = None,
) -> SizingResult:
    """Full sizing pipeline: edge gate → Kelly → position size → decision.

    This is the main entry point that combines all sizing logic and returns
    a complete SizingResult for audit logging.

    Args:
        market_id: Market identifier for logging.
        p_estimated: Our estimated probability of YES (0-1).
        p_market: Current market YES price (0-1).
        side: "buy_yes" or "buy_no".
        bankroll: Current total bankroll.
        category: Market category.
        category_counts: Dict of category -> open position count.
        caps: SizingCaps configuration.

    Returns:
        SizingResult with full decision details.
    """
    if caps is None:
        caps = SizingCaps()

    result = SizingResult(
        market_id=market_id,
        side=side,
        p_estimated=p_estimated,
        p_market=p_market,
        fee_rate=caps.fee_rate,
        bankroll=bankroll,
    )

    # --- Safety: validate required inputs ---
    missing = []
    if bankroll is None or bankroll < 0:
        missing.append("bankroll")
    if p_market is None or not (0 < p_market < 1):
        missing.append("p_market")
    if p_estimated is None or not (0 < p_estimated < 1):
        missing.append("p_estimated")

    if missing:
        if caps.fallback_on_missing:
            result.final_size_usd = caps.safe_fallback_usd
            result.decision = "trade"
            result.skip_reason = f"fallback: missing {','.join(missing)}"
            _log("warning", "sizing_fallback", missing=missing, size=caps.safe_fallback_usd)
            return result
        else:
            result.decision = "skip"
            result.skip_reason = f"missing_inputs: {','.join(missing)}"
            return result

    # --- Edge calculation ---
    result.edge_raw = abs(p_estimated - p_market)
    result.edge_after_fee = expected_edge_after_fee(
        p_estimated, p_market, side, caps.fee_rate
    )

    # --- Fee-aware edge gate ---
    if result.edge_after_fee <= 0:
        result.decision = "skip"
        result.skip_reason = "negative_ev_after_fee"
        return result

    if result.edge_after_fee < caps.min_edge_buffer:
        result.decision = "skip"
        result.skip_reason = f"edge_below_buffer ({result.edge_after_fee:.4f} < {caps.min_edge_buffer})"
        return result

    # --- Kelly fraction ---
    result.kelly_f = kelly_fraction(p_estimated, p_market, side, caps.fee_rate)
    if result.kelly_f <= 0:
        result.decision = "skip"
        result.skip_reason = "kelly_zero"
        return result

    # --- Compute effective multiplier (for audit) ---
    base_mult = KELLY_MULT_NO if side == "buy_no" else KELLY_MULT_YES
    bankroll_mult = BANKROLL_TIERS[-1][1]
    for threshold, mult in BANKROLL_TIERS:
        if bankroll >= threshold:
            bankroll_mult = mult
            break
    result.kelly_mult = max(base_mult, bankroll_mult) if bankroll >= 300 else base_mult

    # --- Position size ---
    cat_counts = category_counts or {}
    result.raw_size_usd = result.kelly_f * result.kelly_mult * bankroll
    result.category_haircut = bool(
        category and cat_counts.get(category, 0) > CATEGORY_CONCENTRATION_LIMIT
    )

    result.final_size_usd = position_usd(
        bankroll=bankroll,
        kelly_f=result.kelly_f,
        side=side,
        category=category,
        category_counts=category_counts,
        caps=caps,
    )

    if result.final_size_usd <= 0:
        result.decision = "skip"
        result.skip_reason = "below_min_position"
        return result

    result.decision = "trade"
    return result


# ---------------------------------------------------------------------------
# Backward-compatible aliases (match old src/sizing.py API)
# ---------------------------------------------------------------------------

def position_size(
    bankroll: float,
    kelly_f: float,
    side: str,
    category: str = "",
    category_counts: Optional[Dict[str, int]] = None,
    max_position_override: Optional[float] = None,
) -> float:
    """Backward-compatible wrapper around position_usd()."""
    caps = SizingCaps()
    if max_position_override is not None:
        caps.max_position_usd = max_position_override
    return position_usd(
        bankroll=bankroll,
        kelly_f=kelly_f,
        side=side,
        category=category,
        category_counts=category_counts,
        caps=caps,
    )
