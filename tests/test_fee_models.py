from __future__ import annotations

from signals.fee_models import breakeven_win_probability, kalshi_fee_estimate, polymarket_fee_estimate


def test_kalshi_general_taker_fee_matches_pdf_examples() -> None:
    fee = kalshi_fee_estimate(price=0.50, contracts=100, maker=False)
    assert fee.fee_dollars == 1.75

    fee = kalshi_fee_estimate(price=0.05, contracts=100, maker=False)
    assert fee.fee_dollars == 0.34


def test_kalshi_general_maker_fee_matches_pdf_examples() -> None:
    fee = kalshi_fee_estimate(price=0.50, contracts=100, maker=True)
    assert fee.fee_dollars == 0.44

    fee = kalshi_fee_estimate(price=0.01, contracts=1, maker=True)
    assert fee.fee_dollars == 0.01


def test_polymarket_maker_fee_is_zero() -> None:
    fee = polymarket_fee_estimate(price=0.5, contracts=10, market_type="crypto", maker=True)
    assert fee.fee_dollars == 0.0


def test_breakeven_probability_includes_fee_drag() -> None:
    breakeven = breakeven_win_probability(entry_price=0.95, fee_dollars=0.02, contracts=10)
    assert round(breakeven, 4) == 0.952

