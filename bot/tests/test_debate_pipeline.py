"""
Tests for bot/debate_pipeline.py.

Focus: split-conformal calibration logic and trade gating behavior.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure bot/ is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from debate_pipeline import ConformalWrapper


def test_conformal_rejects_invalid_coverage() -> None:
    with pytest.raises(ValueError):
        ConformalWrapper(coverage=0.0)
    with pytest.raises(ValueError):
        ConformalWrapper(coverage=1.0)
    with pytest.raises(ValueError):
        ConformalWrapper(coverage=-0.1)


def test_conformal_calibrate_requires_aligned_nonempty_inputs() -> None:
    c = ConformalWrapper(coverage=0.9)

    with pytest.raises(ValueError):
        c.calibrate([], [])
    with pytest.raises(ValueError):
        c.calibrate([0.2, 0.4], [1])


def test_conformal_calibrate_validates_prediction_and_actual_ranges() -> None:
    c = ConformalWrapper(coverage=0.9)

    with pytest.raises(ValueError):
        c.calibrate([0.1, 1.2], [0, 1])
    with pytest.raises(ValueError):
        c.calibrate([0.1, 0.9], [0, 2])


def test_conformal_uses_finite_sample_ceil_quantile_rank() -> None:
    """
    For n=5 and coverage=0.8:
      rank = ceil((n+1)*coverage) = ceil(4.8) = 5
    so quantile should pick the maximum nonconformity score.
    """
    c = ConformalWrapper(coverage=0.8)
    predictions = [0.1, 0.2, 0.3, 0.4, 0.5]  # actuals are all 0 -> same residuals
    actuals = [0, 0, 0, 0, 0]
    c.calibrate(predictions, actuals)

    assert c._quantile == pytest.approx(0.5, abs=1e-12)


def test_conformal_interval_and_trade_rule() -> None:
    c = ConformalWrapper(coverage=0.9)
    c.calibrate([0.1] * 10, [0] * 10)  # quantile = 0.1

    lo, hi = c.get_interval(0.6)
    assert lo == pytest.approx(0.5, abs=1e-12)
    assert hi == pytest.approx(0.7, abs=1e-12)

    assert c.should_trade(probability=0.6, market_price=0.49) is True
    assert c.should_trade(probability=0.6, market_price=0.50) is False
    assert c.should_trade(probability=0.6, market_price=0.65) is False
    assert c.should_trade(probability=0.6, market_price=0.71) is True


def test_conformal_uncalibrated_is_no_trade() -> None:
    c = ConformalWrapper(coverage=0.9)
    assert c.get_interval(0.6) == (0.0, 1.0)
    assert c.should_trade(probability=0.6, market_price=0.1) is False
    assert c.should_trade(probability=0.6, market_price=0.9) is False


def test_conformal_sizing_factor_monotonic_with_interval_width() -> None:
    narrow = ConformalWrapper(coverage=0.9)
    narrow.calibrate([0.1] * 10, [0] * 10)  # width = 0.2
    assert narrow.get_sizing_factor(0.55) == pytest.approx(0.75, abs=1e-12)

    wide = ConformalWrapper(coverage=0.9)
    wide.calibrate([0.45] * 10, [0] * 10)  # width = 0.9
    assert wide.get_sizing_factor(0.55) == 0.0
