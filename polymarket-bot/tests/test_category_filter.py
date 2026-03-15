from src.claude_analyzer import CATEGORY_PRIORITY, classify_market_category


def test_crypto_and_sports_are_low_priority():
    assert classify_market_category("Will Bitcoin hit 200k by June?") == "crypto"
    assert classify_market_category("Will the NFL team win the Super Bowl?") == "sports"
    assert CATEGORY_PRIORITY["crypto"] == 0
    assert CATEGORY_PRIORITY["sports"] == 0


def test_politics_weather_economic_pass_priority_gate():
    assert CATEGORY_PRIORITY[classify_market_category("Will Biden win the election?")] >= 1
    assert CATEGORY_PRIORITY[classify_market_category("Will NYC temperature exceed 90F tomorrow?")] >= 1
    assert CATEGORY_PRIORITY[classify_market_category("Will CPI come in below 3%?")] >= 1
