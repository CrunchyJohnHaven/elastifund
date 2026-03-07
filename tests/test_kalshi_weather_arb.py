import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from kalshi.weather_arb import (
    ForecastSnapshot,
    build_weather_signal,
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
