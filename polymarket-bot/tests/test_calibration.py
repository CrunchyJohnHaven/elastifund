import pytest

from src.claude_analyzer import calibrate_probability


@pytest.mark.parametrize(
    "raw_prob, expected",
    [
        (0.90, 0.71),
        (0.80, 0.60),
        (0.70, 0.53),
        (0.50, 0.50),
        (0.10, 0.29),
    ],
)
def test_platt_mapping_targets(raw_prob: float, expected: float):
    calibrated = calibrate_probability(raw_prob)
    assert abs(calibrated - expected) <= 0.02
