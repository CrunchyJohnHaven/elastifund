from src.risk.sizing import SizingCaps, kelly_fraction, position_usd


def test_kelly_zero_edge_returns_zero():
    assert kelly_fraction(0.5, 0.5, "buy_yes") == 0.0


def test_kelly_negative_edge_returns_zero():
    assert kelly_fraction(0.4, 0.6, "buy_yes") == 0.0


def test_bankroll_zero_returns_zero_position():
    size = position_usd(bankroll=0.0, kelly_f=0.4, side="buy_yes")
    assert size == 0.0


def test_position_never_exceeds_max_position_cap():
    caps = SizingCaps(max_position_usd=3.0)
    size = position_usd(bankroll=10000.0, kelly_f=0.9, side="buy_no", caps=caps)
    assert size <= 3.0
