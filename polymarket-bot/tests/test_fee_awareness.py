from src.claude_analyzer import calculate_taker_fee


def test_crypto_taker_fee_formula():
    fee = calculate_taker_fee(0.5, "crypto")
    assert abs(fee - 0.00625) < 1e-9


def test_sports_taker_fee_formula():
    fee = calculate_taker_fee(0.5, "sports")
    assert abs(fee - 0.00175) < 1e-9


def test_politics_has_zero_taker_fee():
    assert calculate_taker_fee(0.5, "politics") == 0.0
