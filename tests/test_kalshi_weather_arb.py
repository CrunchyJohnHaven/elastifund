import os
import sys
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))

from kalshi.weather_arb import (
    ForecastSnapshot,
    _current_hourly_usage,
    _normalize_mode,
    _resolve_hourly_budget_usd,
    _validate_args,
    build_weather_signal,
    extract_market_target_date,
    parse_temperature_contract,
    temperature_probability,
)


def test_parse_temperature_contract_above():
    c = parse_temperature_contract("Will NYC high be 60 or above?")
    assert c is not None
    assert c[0] == "above"
    assert c[1] == 60


def test_parse_temperature_contract_range():
    c = parse_temperature_contract("High temperature between 61 and 64 degrees")
    assert c is not None
    assert c[0] == "range"
    assert c[1] == 61
    assert c[2] == 64


def test_temperature_probability_monotonic():
    contract = ("above", 60.0, None)
    p_cold = temperature_probability(55.0, contract, std_f=3.0)
    p_warm = temperature_probability(70.0, contract, std_f=3.0)
    assert p_warm > p_cold
    assert 0.01 <= p_cold <= 0.99
    assert 0.01 <= p_warm <= 0.99


def test_build_rain_signal_yes_side():
    snapshot = ForecastSnapshot(
        city="NYC",
        target_date="2026-03-08",
        high_temp_f=55.0,
        pop_probability=0.75,
        source_period="Sunday",
    )
    market = {
        "ticker": "KXRAINNYCM-TEST",
        "event_ticker": "KXRAINNYC-26MAR08",
        "title": "Will it rain in NYC tomorrow?",
        "yes_ask": 58,
        "yes_bid": 56,
        "no_ask": 44,
        "no_bid": 42,
    }
    sig = build_weather_signal("NYC", snapshot, market, edge_threshold=0.10, max_spread=0.20)
    assert sig is not None
    assert sig.market_type == "rain"
    assert sig.side == "yes"
    assert sig.edge > 0.10
    assert sig.order_probability == 0.57


def test_build_temp_signal_no_side():
    snapshot = ForecastSnapshot(
        city="CHI",
        target_date="2026-03-08",
        high_temp_f=45.0,
        pop_probability=0.2,
        source_period="Sunday",
    )
    market = {
        "ticker": "KXHIGHCH-TEST",
        "event_ticker": "KXHIGHCHI-26MAR08",
        "title": "Will Chicago high be above 60?",
        "subtitle": "Above 60",
        "yes_ask": 70,
        "yes_bid": 68,
        "no_ask": 32,
        "no_bid": 30,
    }
    sig = build_weather_signal("CHI", snapshot, market, edge_threshold=0.10, max_spread=0.20)
    assert sig is not None
    assert sig.market_type == "temperature"
    assert sig.side == "no"
    assert sig.edge > 0.10
    assert sig.order_probability == 0.31


def test_build_temp_signal_skips_no_on_tight_range_when_point_forecast_in_range():
    snapshot = ForecastSnapshot(
        city="MIA",
        target_date="2026-03-08",
        high_temp_f=85.0,
        pop_probability=0.2,
        source_period="Sunday",
    )
    market = {
        "ticker": "KXHIGHMIA-TEST",
        "event_ticker": "KXHIGHMIA-26MAR08",
        "title": "Will the high temperature in Miami be between 84 and 85 degrees?",
        "yes_ask": 67,
        "yes_bid": 65,
        "no_ask": 35,
        "no_bid": 33,
    }
    assert build_weather_signal("MIA", snapshot, market, edge_threshold=0.10, max_spread=0.20) is None


def test_build_temp_signal_allows_no_on_tight_range_when_point_forecast_outside_range():
    snapshot = ForecastSnapshot(
        city="MIA",
        target_date="2026-03-08",
        high_temp_f=88.0,
        pop_probability=0.2,
        source_period="Sunday",
    )
    market = {
        "ticker": "KXHIGHMIA-TEST",
        "event_ticker": "KXHIGHMIA-26MAR08",
        "title": "Will the high temperature in Miami be between 84 and 85 degrees?",
        "yes_ask": 67,
        "yes_bid": 65,
        "no_ask": 35,
        "no_bid": 33,
    }
    sig = build_weather_signal("MIA", snapshot, market, edge_threshold=0.10, max_spread=0.20)
    assert sig is not None
    assert sig.side == "no"


def test_extract_market_target_date_from_event_ticker():
    market = {
        "ticker": "KXRAINNYC-26MAR08-T0",
        "event_ticker": "KXRAINNYC-26MAR08",
    }
    assert extract_market_target_date(market).isoformat() == "2026-03-08"


def test_build_signal_skips_mismatched_market_date():
    snapshot = ForecastSnapshot(
        city="NYC",
        target_date="2026-03-08",
        high_temp_f=55.0,
        pop_probability=0.75,
        source_period="Sunday",
    )
    market = {
        "ticker": "KXRAINNYC-26MAR09-T0",
        "event_ticker": "KXRAINNYC-26MAR09",
        "title": "Will it rain in New York City on Monday?",
        "yes_ask": 58,
        "yes_bid": 56,
        "no_ask": 44,
        "no_bid": 42,
    }
    assert build_weather_signal("NYC", snapshot, market, edge_threshold=0.10, max_spread=0.20) is None


def test_current_hourly_usage_counts_only_recent_executed_rows(tmp_path: Path):
    now = datetime(2026, 3, 9, 12, 0, tzinfo=timezone.utc)
    log = tmp_path / "orders.jsonl"
    rows = [
        {
            "timestamp": (now - timedelta(minutes=20)).isoformat(),
            "execution_result": "paper",
            "notional_usd": 12.5,
        },
        {
            "timestamp": (now - timedelta(minutes=40)).isoformat(),
            "execution_result": "live",
            "notional_usd": 7.0,
        },
        {
            "timestamp": (now - timedelta(minutes=80)).isoformat(),
            "execution_result": "live",
            "notional_usd": 100.0,
        },
        {
            "timestamp": (now - timedelta(minutes=10)).isoformat(),
            "execution_result": "rejected",
            "notional_usd": 9.0,
        },
    ]
    log.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    usage = _current_hourly_usage(now=now, orders_log=log)
    assert usage.order_count == 2
    assert usage.notional_usd == 19.5


def test_resolve_hourly_budget_prefers_explicit_then_runtime_env():
    env = {
        "JJ_HOURLY_NOTIONAL_BUDGET_USD": "41.25",
        "KALSHI_WEATHER_HOURLY_BUDGET_USD": "33.5",
    }
    assert _resolve_hourly_budget_usd(20.0, env=env) == 20.0
    assert _resolve_hourly_budget_usd(None, env=env) == 33.5
    assert _resolve_hourly_budget_usd(None, env={"JJ_HOURLY_BUDGET_USD": "11"}) == 11.0


def test_normalize_mode_sets_execute_for_live():
    args = SimpleNamespace(mode="live", execute=False)
    _normalize_mode(args)
    assert args.execute is True
    assert args.mode == "live"


def test_validate_args_rejects_invalid_hourly_limits():
    args = SimpleNamespace(
        edge_threshold=0.1,
        max_spread=0.2,
        temp_std_f=3.0,
        maker_offset_cents=1,
        bankroll_usd=100.0,
        max_order_usd=5.0,
        kelly_fraction=0.25,
        max_pages=2,
        max_signals=10,
        max_orders=1,
        max_orders_per_hour=-1,
        hourly_budget_usd=50.0,
        interval_seconds=60,
    )
    try:
        _validate_args(args)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "max-orders-per-hour" in str(exc)
