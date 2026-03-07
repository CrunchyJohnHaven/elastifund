"""Backward-compatibility shim — all sizing logic lives in src.risk.sizing."""
from src.risk.sizing import (  # noqa: F401
    kelly_fraction,
    position_size,
    position_usd,
    compute_sizing,
    expected_edge_after_fee,
    SizingCaps,
    SizingResult,
    BANKROLL_TIERS,
    KELLY_MULT_YES,
    KELLY_MULT_NO,
    MIN_POSITION_USD,
    MAX_POSITION_USD_DEFAULT,
    CATEGORY_CONCENTRATION_LIMIT,
    WINNER_FEE,
)
