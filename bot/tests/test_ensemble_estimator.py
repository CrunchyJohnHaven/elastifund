#!/usr/bin/env python3
"""Tests for the Instance 4 ensemble estimator."""

from __future__ import annotations

import asyncio
from datetime import datetime
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bot"))

from bot.ensemble_estimator import (  # noqa: E402
    EnsembleEstimator,
    LLMCostTracker,
    ModelEstimate,
)


def test_ensemble_estimator_aggregates_model_outputs(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai")

    tracker = LLMCostTracker(tmp_path / "llm_costs.db", daily_cap_usd=2.0)
    estimator = EnsembleEstimator(
        calibrate_fn=lambda probability: probability,
        min_edge=0.05,
        cost_tracker=tracker,
        enable_second_claude=False,
    )

    claude_result = ModelEstimate(
        model_name="claude-haiku",
        provider="anthropic",
        raw_probability=0.62,
        confidence="medium",
        reasoning="Claude reasoning",
        estimated_cost_usd=0.0,
    )
    openai_result = ModelEstimate(
        model_name="gpt-4o-mini",
        provider="openai",
        raw_probability=0.38,
        confidence="medium",
        reasoning="OpenAI reasoning",
        estimated_cost_usd=0.12,
    )

    with patch("bot.ensemble_estimator.call_claude", new=AsyncMock(return_value=claude_result)) as mock_claude:
        with patch("bot.ensemble_estimator.call_openai", new=AsyncMock(return_value=openai_result)) as mock_openai:
            result = asyncio.run(
                estimator.estimate(
                    "Will X happen?",
                    market_price=0.34,
                    market_id="m1",
                    category="politics",
                )
            )

    assert mock_claude.await_count == 1
    assert mock_openai.await_count == 1
    assert result.mean_estimate == pytest.approx(0.50)
    assert result.median_estimate == pytest.approx(0.50)
    assert result.range_estimate == pytest.approx(0.24)
    assert result.std_estimate == pytest.approx(0.12)
    assert result.confidence_multiplier == pytest.approx(0.75)
    assert result.disagreement_signal["signal_fired"] is True
    assert result.call_cost_usd == pytest.approx(0.12)
    assert result.daily_cost_usd == pytest.approx(0.12)
    assert result.fallback_mode == "ensemble"


def test_daily_cost_cap_triggers_haiku_only_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai")

    tracker = LLMCostTracker(tmp_path / "llm_costs.db", daily_cap_usd=0.10)
    tracker.record_usage(
        [
            ModelEstimate(
                model_name="gpt-4o-mini",
                provider="openai",
                raw_probability=0.50,
                confidence="medium",
                reasoning="seed cost",
                estimated_cost_usd=0.11,
            )
        ],
        market_id="seed",
        question="seed",
        fallback_mode="ensemble",
        event_time=datetime.now().astimezone(),
    )
    estimator = EnsembleEstimator(
        calibrate_fn=lambda probability: probability,
        min_edge=0.05,
        cost_tracker=tracker,
        enable_second_claude=False,
    )

    claude_result = ModelEstimate(
        model_name="claude-haiku",
        provider="anthropic",
        raw_probability=0.57,
        confidence="medium",
        reasoning="Claude only",
        estimated_cost_usd=0.0,
    )

    with patch("bot.ensemble_estimator.call_claude", new=AsyncMock(return_value=claude_result)) as mock_claude:
        with patch("bot.ensemble_estimator.call_openai", new=AsyncMock()) as mock_openai:
            result = asyncio.run(
                estimator.estimate(
                    "Will Y happen?",
                    market_price=0.49,
                    market_id="m2",
                    category="politics",
                )
            )

    assert mock_claude.await_count == 1
    assert mock_openai.await_count == 0
    assert result.cost_cap_triggered is True
    assert result.fallback_mode == "haiku_only_cost_cap"
    assert len(result.model_estimates) == 1
    assert result.confidence_multiplier == pytest.approx(1.0)


def test_missing_openai_key_gracefully_degrades_to_haiku_only(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    tracker = LLMCostTracker(tmp_path / "llm_costs.db", daily_cap_usd=2.0)
    estimator = EnsembleEstimator(
        calibrate_fn=lambda probability: probability,
        min_edge=0.05,
        cost_tracker=tracker,
        enable_second_claude=False,
    )

    claude_result = ModelEstimate(
        model_name="claude-haiku",
        provider="anthropic",
        raw_probability=0.55,
        confidence="medium",
        reasoning="Claude only",
        estimated_cost_usd=0.0,
    )

    with patch("bot.ensemble_estimator.call_claude", new=AsyncMock(return_value=claude_result)) as mock_claude:
        with patch("bot.ensemble_estimator.call_openai", new=AsyncMock()) as mock_openai:
            result = asyncio.run(
                estimator.estimate(
                    "Will Z happen?",
                    market_price=0.48,
                    market_id="m3",
                    category="politics",
                )
            )

    assert mock_claude.await_count == 1
    assert mock_openai.await_count == 0
    assert result.fallback_mode == "haiku_only_no_openai_key"
    assert result.cost_cap_triggered is False
    assert len(result.model_estimates) == 1
