#!/usr/bin/env python3
"""Targeted tests for Stream 6 disagreement sizing."""

from __future__ import annotations

import asyncio
import math
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bot"))

from bot.jj_live import apply_disagreement_size_modifier  # noqa: E402
from bot.llm_ensemble import (  # noqa: E402
    LLMEnsemble,
    ModelEstimate,
    compute_disagreement,
    disagreement_kelly_modifier,
)


def test_compute_disagreement_matches_population_stddev():
    probs = [0.40, 0.60, 0.80]
    expected = math.sqrt(((0.40 - 0.60) ** 2 + (0.60 - 0.60) ** 2 + (0.80 - 0.60) ** 2) / 3)
    assert compute_disagreement(probs) == pytest.approx(expected)


def test_compute_disagreement_defaults_to_max_uncertainty_for_single_model():
    assert compute_disagreement([0.62]) == pytest.approx(0.20)


@pytest.mark.parametrize(
    ("std_dev", "expected"),
    [
        (0.01, 1.0),
        (0.05, 0.75),
        (0.10, 0.50),
        (0.15, 0.25),
    ],
)
def test_disagreement_kelly_modifier_lookup_table(std_dev: float, expected: float):
    assert disagreement_kelly_modifier(std_dev) == pytest.approx(expected)


def test_disagreement_kelly_modifier_handles_extreme_dispersion():
    extreme = compute_disagreement([0.01, 0.99])
    assert extreme > 0.15
    assert disagreement_kelly_modifier(extreme) == pytest.approx(0.25)


def test_compute_disagreement_zero_when_models_agree():
    assert compute_disagreement([0.55, 0.55, 0.55]) == pytest.approx(0.0)


def test_single_model_estimate_exposes_disagreement_and_reduced_kelly():
    ensemble = LLMEnsemble(
        enable_rag=False,
        enable_brier=False,
        enable_counter_narrative=False,
    )
    ensemble.models = ["claude-haiku"]

    with patch(
        "bot.llm_ensemble.call_claude",
        new=AsyncMock(return_value=ModelEstimate("claude-haiku", 0.62, "medium", "test")),
    ):
        result = asyncio.run(ensemble.estimate("Will X happen?", market_id="m1"))

    assert result.probability == pytest.approx(0.62)
    assert result.disagreement == pytest.approx(0.20)
    assert result.model_stddev == pytest.approx(0.20)
    assert result.kelly_multiplier == pytest.approx(0.25)


def test_apply_disagreement_size_modifier_scales_final_size():
    final_size, modifier = apply_disagreement_size_modifier(12.0, 0.12)
    assert modifier == pytest.approx(0.50)
    assert final_size == pytest.approx(6.0)


def test_apply_disagreement_size_modifier_respects_min_trade_floor():
    final_size, modifier = apply_disagreement_size_modifier(1.0, 0.20)
    assert modifier == pytest.approx(0.25)
    assert final_size == pytest.approx(0.0)
