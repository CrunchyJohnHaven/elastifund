from __future__ import annotations

import pytest

from bot.btc_5min_maker import (
    analyze_maker_buy_price,
    apply_contract_cap,
    classify_recent_price_volatility,
    midpoint_defensive_shade_ticks,
    session_size_multiplier,
    should_skip_midpoint_kill_zone,
    summarize_book_microstructure,
)


def test_analyze_maker_buy_price_supports_defensive_shade_ticks() -> None:
    analysis = analyze_maker_buy_price(
        best_bid=0.49,
        best_ask=0.51,
        max_price=0.70,
        min_price=0.04,
        tick_size=0.01,
        aggression_ticks=1,
        defensive_shade_ticks=3,
    )

    assert analysis["reason_code"] == "ok"
    assert analysis["candidate_price"] == pytest.approx(0.47)
    assert analysis["price"] == pytest.approx(0.47)


def test_midpoint_guardrail_and_kill_zone_detection() -> None:
    shade_ticks = midpoint_defensive_shade_ticks(
        best_bid=0.49,
        best_ask=0.51,
        window_end_ts=1060,
        now_ts=1005,
        min_price=0.48,
        max_price=0.52,
        max_seconds_to_close=60,
        shade_ticks=3,
    )

    assert shade_ticks == 3
    assert should_skip_midpoint_kill_zone(
        order_price=0.50,
        window_end_ts=1060,
        now_ts=1005,
        min_price=0.48,
        max_price=0.52,
        max_seconds_to_close=60,
    )
    assert not should_skip_midpoint_kill_zone(
        order_price=0.47,
        window_end_ts=1060,
        now_ts=1005,
        min_price=0.48,
        max_price=0.52,
        max_seconds_to_close=60,
    )


def test_session_size_multiplier_marks_us_and_quiet_windows() -> None:
    us_open = session_size_multiplier(
        window_start_ts=1773235800,  # 2026-03-11 13:30:00 UTC
        adverse_start_minute_utc=810,
        adverse_end_minute_utc=960,
        adverse_multiplier=0.60,
        quiet_start_minute_utc=0,
        quiet_end_minute_utc=480,
        quiet_multiplier=1.15,
    )
    quiet = session_size_multiplier(
        window_start_ts=1773190800,  # 2026-03-11 01:00:00 UTC
        adverse_start_minute_utc=810,
        adverse_end_minute_utc=960,
        adverse_multiplier=0.60,
        quiet_start_minute_utc=0,
        quiet_end_minute_utc=480,
        quiet_multiplier=1.15,
    )

    assert us_open["label"] == "us_open_risk_reduced"
    assert us_open["multiplier"] == pytest.approx(0.60)
    assert quiet["label"] == "quiet_hours_boost"
    assert quiet["multiplier"] == pytest.approx(1.15)


def test_summarize_book_microstructure_surfaces_toxic_imbalance() -> None:
    snapshot = summarize_book_microstructure(
        {
            "bids": [
                {"price": 0.49, "size": 10},
                {"price": 0.48, "size": 8},
                {"price": 0.47, "size": 7},
            ],
            "asks": [
                {"price": 0.51, "size": 30},
                {"price": 0.52, "size": 25},
                {"price": 0.53, "size": 20},
            ],
        },
        depth=3,
    )

    assert snapshot["best_bid"] == pytest.approx(0.49)
    assert snapshot["best_ask"] == pytest.approx(0.51)
    assert snapshot["top_depth_shares"] == pytest.approx(100.0)
    assert snapshot["imbalance"] == pytest.approx(-0.5)
    assert snapshot["microprice"] == pytest.approx(0.4950, abs=1e-4)


def test_classify_recent_price_volatility_and_contract_cap() -> None:
    high_vol = classify_recent_price_volatility(
        [(1, 100000.0), (2, 100220.0), (3, 100350.0)],
        high_range_bps=20.0,
        extreme_range_bps=60.0,
    )
    extreme_vol = classify_recent_price_volatility(
        [(1, 100000.0), (2, 100800.0), (3, 100950.0)],
        high_range_bps=20.0,
        extreme_range_bps=60.0,
    )
    capped = apply_contract_cap(
        shares=24.65,
        order_price=0.49,
        required_shares=10.21,
        max_contracts=20.0,
        min_trade_usd=5.0,
    )
    skipped = apply_contract_cap(
        shares=40.0,
        order_price=0.10,
        required_shares=50.0,
        max_contracts=20.0,
        min_trade_usd=5.0,
    )

    assert high_vol["regime"] == "high"
    assert extreme_vol["regime"] == "extreme"
    assert capped["capped"] is True
    assert capped["skip"] is False
    assert capped["shares"] == pytest.approx(20.0)
    assert capped["size_usd"] == pytest.approx(9.8)
    assert skipped["skip"] is True
    assert skipped["reason"] == "inventory_cap_below_exchange_minimum"
