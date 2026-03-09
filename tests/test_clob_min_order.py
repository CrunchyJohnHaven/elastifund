from __future__ import annotations

import pytest

import bot.jj_live as jj_live_module


def _live_order_sizes(position_usd: float, price: float) -> tuple[float, float, float]:
    order_price = round(price, 2)
    order_size = jj_live_module._round_up(position_usd / order_price, 2)
    min_order_size = jj_live_module.clob_min_order_size(
        order_price,
        min_shares=jj_live_module.POLY_MIN_ORDER_SHARES,
    )
    return order_price, order_size, min_order_size


def test_low_price_five_dollar_order_meets_clob_minimum() -> None:
    order_price, order_size, min_order_size = _live_order_sizes(5.00, 0.13)

    assert order_price == pytest.approx(0.13)
    assert order_size == pytest.approx(38.47)
    assert min_order_size == pytest.approx(38.47)
    assert order_size >= min_order_size


def test_low_price_fifty_cent_order_stays_below_clob_minimum() -> None:
    order_price, order_size, min_order_size = _live_order_sizes(0.50, 0.13)

    assert order_price == pytest.approx(0.13)
    assert order_size == pytest.approx(3.85)
    assert min_order_size == pytest.approx(38.47)
    assert order_size < min_order_size


def test_high_price_five_dollar_order_still_meets_five_dollar_notional_minimum() -> None:
    order_price, order_size, min_order_size = _live_order_sizes(5.00, 0.90)

    assert order_price == pytest.approx(0.90)
    assert order_size == pytest.approx(5.56)
    assert min_order_size == pytest.approx(5.56)
    assert order_size >= min_order_size
