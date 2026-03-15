from src.signal_mapping import (
    compute_calibrated_signal,
    map_vps_signal_direction,
    normalize_confidence,
)


def test_buy_mapping_uses_prob_vs_price():
    d1 = map_vps_signal_direction({"signal": "BUY", "probability": 0.7}, 0.5)
    d2 = map_vps_signal_direction({"signal": "BUY", "probability": 0.3}, 0.5)

    assert d1 == "buy_yes"
    assert d2 == "buy_no"


def test_confidence_string_normalization():
    assert normalize_confidence("high") == 0.85
    assert normalize_confidence("medium") == 0.6
    assert normalize_confidence("low") == 0.3


def test_already_calibrated_prob_not_recalibrated():
    sig = compute_calibrated_signal(0.6, 0.5, "politics", already_calibrated=True)
    assert abs(sig["calibrated_prob"] - 0.6) < 1e-9
