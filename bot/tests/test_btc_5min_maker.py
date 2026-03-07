#!/usr/bin/env python3
"""Unit tests for bot/btc_5min_maker.py."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from bot.btc_5min_maker import (  # noqa: E402
    calc_trade_size_usd,
    choose_maker_buy_price,
    choose_token_id_for_direction,
    current_window_start,
    deterministic_fill,
    direction_from_prices,
    market_slug_for_window,
    parse_json_list,
)


def test_current_window_start_alignment() -> None:
    assert current_window_start(1710000123) == 1710000000
    assert current_window_start(1710000300) == 1710000300


def test_market_slug_for_window() -> None:
    assert market_slug_for_window(1710000000) == "btc-updown-5m-1710000000"


def test_direction_from_prices_above_threshold() -> None:
    direction, delta = direction_from_prices(open_price=100.0, current_price=100.05, min_delta=0.0003)
    assert direction == "UP"
    assert delta == pytest.approx(0.0005)


def test_direction_from_prices_below_threshold() -> None:
    direction, delta = direction_from_prices(open_price=100.0, current_price=100.01, min_delta=0.0003)
    assert direction is None
    assert delta == pytest.approx(0.0001)


def test_choose_maker_buy_price_standard_case() -> None:
    price = choose_maker_buy_price(
        best_bid=0.91,
        best_ask=0.93,
        max_price=0.95,
        min_price=0.90,
        tick_size=0.01,
    )
    assert price == pytest.approx(0.92)


def test_choose_maker_buy_price_guardrails() -> None:
    # Ask already above max buy threshold => skip.
    assert (
        choose_maker_buy_price(
            best_bid=0.95,
            best_ask=0.96,
            max_price=0.95,
            min_price=0.90,
            tick_size=0.01,
        )
        is None
    )


def test_calc_trade_size_usd() -> None:
    assert calc_trade_size_usd(250.0, 0.01, 2.50) == pytest.approx(2.50)
    assert calc_trade_size_usd(100.0, 0.01, 2.50) == pytest.approx(1.00)


def test_parse_json_list() -> None:
    assert parse_json_list('["Up","Down"]') == ["Up", "Down"]
    assert parse_json_list(["Up", "Down"]) == ["Up", "Down"]
    assert parse_json_list("") == []
    assert parse_json_list("{bad}") == []


def test_choose_token_id_for_direction_tokens_field() -> None:
    market = {
        "tokens": [
            {"outcome": "Up", "token_id": "tok-up"},
            {"outcome": "Down", "token_id": "tok-down"},
        ]
    }
    assert choose_token_id_for_direction(market, "UP") == "tok-up"
    assert choose_token_id_for_direction(market, "DOWN") == "tok-down"


def test_choose_token_id_for_direction_fallback_binary_order() -> None:
    market = {
        "outcomes": '["Something odd","Something else"]',
        "clobTokenIds": '["tid0","tid1"]',
    }
    assert choose_token_id_for_direction(market, "UP") == "tid0"
    assert choose_token_id_for_direction(market, "DOWN") == "tid1"


def test_deterministic_fill_stable() -> None:
    a = deterministic_fill(1710000000, 0.2)
    b = deterministic_fill(1710000000, 0.2)
    assert a == b

