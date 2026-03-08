#!/usr/bin/env python3
"""Tests for Instance 4 disagreement sizing and signal logic."""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bot"))

from bot.disagreement_signal import (  # noqa: E402
    build_disagreement_signal,
    confidence_multiplier_from_std,
    population_stddev,
)
from bot.jj_live import apply_disagreement_size_modifier  # noqa: E402


def test_population_stddev_matches_manual_calculation():
    probs = [0.40, 0.60, 0.80]
    expected = math.sqrt(((0.40 - 0.60) ** 2 + (0.60 - 0.60) ** 2 + (0.80 - 0.60) ** 2) / 3)
    assert population_stddev(probs) == pytest.approx(expected)


def test_disagreement_signal_fires_when_std_and_edge_clear_thresholds():
    signal = build_disagreement_signal(
        {"claude-haiku": 0.62, "gpt-4o-mini": 0.38},
        calibrated_mean=0.50,
        market_price=0.34,
        min_edge=0.05,
    )

    assert signal.signal_fired is True
    assert signal.confirmation_signal is False
    assert signal.edge == pytest.approx(0.16)
    assert signal.confidence_multiplier == pytest.approx(0.75)


def test_confirmation_signal_marks_tight_ensembles():
    signal = build_disagreement_signal(
        {"claude-haiku": 0.54, "gpt-4o-mini": 0.56},
        calibrated_mean=0.55,
        market_price=0.52,
        min_edge=0.05,
    )

    assert signal.signal_fired is False
    assert signal.confirmation_signal is True
    assert signal.confidence_multiplier == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("std_dev", "model_count", "expected"),
    [
        (0.04, 2, 1.0),
        (0.05, 2, 0.75),
        (0.15, 2, 0.75),
        (0.16, 2, 0.5),
        (0.30, 1, 1.0),
    ],
)
def test_confidence_multiplier_bands(std_dev: float, model_count: int, expected: float):
    assert confidence_multiplier_from_std(std_dev, model_count) == pytest.approx(expected)


def test_apply_disagreement_size_modifier_uses_confidence_multiplier():
    final_size, modifier = apply_disagreement_size_modifier(12.0, 0.12, model_count=2)
    assert modifier == pytest.approx(0.75)
    assert final_size == pytest.approx(9.0)


def test_apply_disagreement_size_modifier_respects_min_trade_floor():
    final_size, modifier = apply_disagreement_size_modifier(0.9, 0.20, model_count=2)
    assert modifier == pytest.approx(0.5)
    assert final_size == pytest.approx(0.0)
