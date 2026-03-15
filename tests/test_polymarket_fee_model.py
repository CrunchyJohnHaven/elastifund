from __future__ import annotations

import pytest

from src.polymarket_fee_model import build_fee_breakdown, maker_rebate_amount, taker_fee_amount


def test_crypto_fee_curve_matches_parabolic_midpoint_example() -> None:
    fee = taker_fee_amount(0.50, "crypto", shares=100.0)

    assert fee == pytest.approx(0.78125)


def test_crypto_maker_rebate_is_twenty_percent_of_taker_fee_pool() -> None:
    taker_fee = taker_fee_amount(0.50, "crypto", shares=100.0)
    rebate = maker_rebate_amount(0.50, "crypto", shares=100.0)

    assert rebate == pytest.approx(taker_fee * 0.20)


def test_fee_breakdown_exposes_rate_and_rebate_share() -> None:
    breakdown = build_fee_breakdown(0.25, "crypto")

    assert breakdown.effective_taker_rate > 0.0
    assert breakdown.taker_fee_amount > 0.0
    assert breakdown.maker_rebate_share == pytest.approx(0.20)
    assert breakdown.maker_rebate_amount == pytest.approx(breakdown.taker_fee_amount * 0.20)
