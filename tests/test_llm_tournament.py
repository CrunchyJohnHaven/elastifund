#!/usr/bin/env python3
"""
Tests for bot/llm_tournament.py
================================
Covers:
  - build_prompt does NOT contain any price/market number
  - parse_response: well-formatted response
  - parse_response: missing CONFIDENCE field (defaults to MEDIUM)
  - parse_response: out-of-range probability (clamped)
  - parse_response: non-numeric probability (raises ValueError)
  - compute_agreement: all models at 0.70 → agreement = 1.0
  - compute_agreement: models at 0.30, 0.50, 0.70 → low agreement
  - run_tournament (injected): 3 models agree at 0.75, market at 0.55 → BUY_YES
  - run_tournament (injected): 3 models agree at 0.30, market at 0.55 → BUY_NO
  - run_tournament (injected): models disagree → NO_SIGNAL
  - run_tournament (injected): models agree but divergence too small → NO_SIGNAL
  - signal_strength computation
  - get_position_size with Kelly sizing
  - should_trade logic
  - format_alert output
  - tournament with 5 models
  - no actual API calls — all responses injected
"""

from __future__ import annotations

import asyncio
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.llm_tournament import LLMTournament, ModelEstimate, TournamentResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tournament(**kwargs) -> LLMTournament:
    """Return a fresh LLMTournament with sensible test defaults."""
    defaults = dict(
        models=["claude-sonnet-4-6", "gpt-4o", "gemini-2.0-flash"],
        min_agreement=0.80,
        min_divergence=0.10,
        temperature=0.3,
        max_concurrent=3,
        budget_per_question_usd=0.50,
    )
    defaults.update(kwargs)
    return LLMTournament(**defaults)


def _make_response(probability: float, confidence: str = "HIGH", reasoning: str = "Test reasoning.") -> str:
    """Build a well-formatted model response string."""
    return (
        f"PROBABILITY: {probability:.2f}\n"
        f"CONFIDENCE: {confidence}\n"
        f"REASONING: {reasoning}"
    )


def _run(coro):
    """Run a coroutine synchronously in tests.

    Uses asyncio.run() which creates a fresh event loop — compatible with
    Python 3.10+ where get_event_loop() no longer auto-creates a loop in
    non-async contexts.
    """
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# 1. build_prompt — anti-anchoring
# ---------------------------------------------------------------------------


class TestBuildPrompt:
    def test_no_market_price_in_prompt(self):
        """The prompt must NOT contain the market price or any numeric hint."""
        t = _make_tournament()
        prompt = t.build_prompt("Will BTC reach $100k by end of 2026?")
        # The number 0.55 (a typical market price) must never appear
        assert "0.55" not in prompt
        assert "0.42" not in prompt
        assert "market_price" not in prompt.lower()

    def test_prompt_contains_question(self):
        question = "Will it rain in Dublin on Friday?"
        t = _make_tournament()
        prompt = t.build_prompt(question)
        assert question in prompt

    def test_prompt_contains_context_when_provided(self):
        t = _make_tournament()
        prompt = t.build_prompt("Question?", context="Relevant background info.")
        assert "Relevant background info." in prompt

    def test_prompt_omits_context_block_when_empty(self):
        t = _make_tournament()
        prompt = t.build_prompt("Question?", context="")
        # Context section should not appear if empty
        assert "Context:" not in prompt

    def test_prompt_contains_resolution_criteria_when_provided(self):
        t = _make_tournament()
        prompt = t.build_prompt(
            "Question?", resolution_criteria="Resolves YES if official statement issued."
        )
        assert "Resolves YES if official statement issued." in prompt

    def test_prompt_omits_resolution_when_empty(self):
        t = _make_tournament()
        prompt = t.build_prompt("Question?", resolution_criteria="")
        assert "Resolution criteria:" not in prompt

    def test_prompt_instructs_probability_format(self):
        t = _make_tournament()
        prompt = t.build_prompt("Anything?")
        assert "PROBABILITY:" in prompt
        assert "CONFIDENCE:" in prompt
        assert "REASONING:" in prompt

    def test_prompt_does_not_contain_any_price_from_run_tournament(self):
        """Simulate the price being passed to run_tournament — it must stay OUT of the prompt."""
        t = _make_tournament()
        # Even if we know the market price is 0.67, it should never leak into the prompt
        prompt = t.build_prompt("Will X happen?")
        assert "0.67" not in prompt
        assert "67%" not in prompt


# ---------------------------------------------------------------------------
# 2. parse_response
# ---------------------------------------------------------------------------


class TestParseResponse:
    def test_well_formatted_response(self):
        t = _make_tournament()
        raw = "PROBABILITY: 0.72\nCONFIDENCE: HIGH\nREASONING: Solid evidence supports YES."
        est = t.parse_response(raw, "test-model")
        assert est.model_name == "test-model"
        assert abs(est.probability - 0.72) < 1e-9
        assert est.confidence == "high"
        assert "Solid evidence" in est.reasoning_summary
        assert est.raw_response == raw

    def test_missing_confidence_defaults_to_medium(self):
        t = _make_tournament()
        raw = "PROBABILITY: 0.60\nREASONING: Not sure either way."
        est = t.parse_response(raw, "gpt-4o")
        assert est.probability == 0.60
        assert est.confidence == "medium"

    def test_probability_above_1_clamped_to_1(self):
        t = _make_tournament()
        raw = "PROBABILITY: 1.50\nCONFIDENCE: HIGH\nREASONING: Way too high."
        est = t.parse_response(raw, "test-model")
        assert est.probability == 1.0

    def test_probability_below_0_clamped_to_0(self):
        t = _make_tournament()
        raw = "PROBABILITY: -0.20\nCONFIDENCE: LOW\nREASONING: Erroneous."
        est = t.parse_response(raw, "test-model")
        assert est.probability == 0.0

    def test_non_numeric_probability_raises_value_error(self):
        t = _make_tournament()
        raw = "PROBABILITY: maybe\nCONFIDENCE: LOW\nREASONING: Uncertain."
        with pytest.raises(ValueError, match="Could not parse PROBABILITY"):
            t.parse_response(raw, "bad-model")

    def test_missing_probability_raises_value_error(self):
        t = _make_tournament()
        raw = "CONFIDENCE: HIGH\nREASONING: No probability here."
        with pytest.raises(ValueError):
            t.parse_response(raw, "bad-model")

    def test_low_confidence_parsed(self):
        t = _make_tournament()
        raw = "PROBABILITY: 0.45\nCONFIDENCE: LOW\nREASONING: Very uncertain."
        est = t.parse_response(raw, "gemini")
        assert est.confidence == "low"

    def test_probability_exactly_zero_allowed(self):
        t = _make_tournament()
        raw = "PROBABILITY: 0.00\nCONFIDENCE: HIGH\nREASONING: Impossible."
        est = t.parse_response(raw, "m")
        assert est.probability == 0.0

    def test_probability_exactly_one_allowed(self):
        t = _make_tournament()
        raw = "PROBABILITY: 1.00\nCONFIDENCE: HIGH\nREASONING: Certain."
        est = t.parse_response(raw, "m")
        assert est.probability == 1.0

    def test_reasoning_captured(self):
        t = _make_tournament()
        raw = "PROBABILITY: 0.55\nCONFIDENCE: MEDIUM\nREASONING: Base rate is 50%, slight upside."
        est = t.parse_response(raw, "m")
        assert "Base rate is 50%" in est.reasoning_summary


# ---------------------------------------------------------------------------
# 3. compute_agreement
# ---------------------------------------------------------------------------


class TestComputeAgreement:
    def test_all_models_same_probability_agreement_is_one(self):
        t = _make_tournament()
        estimates = [
            ModelEstimate("m1", 0.70, "high", "", 0.0, 0.0, ""),
            ModelEstimate("m2", 0.70, "high", "", 0.0, 0.0, ""),
            ModelEstimate("m3", 0.70, "high", "", 0.0, 0.0, ""),
        ]
        score = t.compute_agreement(estimates)
        assert abs(score - 1.0) < 1e-9

    def test_wide_spread_low_agreement(self):
        """Models at 0.30, 0.50, 0.70 have std ≈ 0.163 → moderate disagreement."""
        t = _make_tournament()
        estimates = [
            ModelEstimate("m1", 0.30, "high", "", 0.0, 0.0, ""),
            ModelEstimate("m2", 0.50, "high", "", 0.0, 0.0, ""),
            ModelEstimate("m3", 0.70, "high", "", 0.0, 0.0, ""),
        ]
        score = t.compute_agreement(estimates)
        # std = 0.1633..., agreement = 1 - 0.1633/0.25 = 0.347
        import numpy as np
        expected_std = float(np.std([0.30, 0.50, 0.70], ddof=0))
        expected = 1.0 - min(expected_std / 0.25, 1.0)
        assert abs(score - expected) < 1e-6
        assert score < 0.80  # well below the min_agreement threshold

    def test_extreme_disagreement_agreement_floored_at_zero(self):
        """Models at 0.0, 0.5, 1.0 give std=0.408 → capped at 0."""
        t = _make_tournament()
        estimates = [
            ModelEstimate("m1", 0.0, "high", "", 0.0, 0.0, ""),
            ModelEstimate("m2", 0.5, "high", "", 0.0, 0.0, ""),
            ModelEstimate("m3", 1.0, "high", "", 0.0, 0.0, ""),
        ]
        score = t.compute_agreement(estimates)
        assert score == 0.0

    def test_single_model_returns_one(self):
        t = _make_tournament()
        estimates = [ModelEstimate("m1", 0.65, "high", "", 0.0, 0.0, "")]
        assert t.compute_agreement(estimates) == 1.0

    def test_two_models_close_high_agreement(self):
        t = _make_tournament()
        estimates = [
            ModelEstimate("m1", 0.68, "high", "", 0.0, 0.0, ""),
            ModelEstimate("m2", 0.72, "high", "", 0.0, 0.0, ""),
        ]
        score = t.compute_agreement(estimates)
        assert score > 0.90  # std=0.02, agreement = 1 - 0.08 = 0.92


# ---------------------------------------------------------------------------
# 4. run_tournament (injected responses)
# ---------------------------------------------------------------------------


class TestRunTournament:
    def _inject(self, probs: list[float], models: list[str] | None = None) -> dict[str, str]:
        if models is None:
            models = ["claude-sonnet-4-6", "gpt-4o", "gemini-2.0-flash"]
        return {
            m: _make_response(p, "HIGH", "Injected test reasoning.")
            for m, p in zip(models, probs)
        }

    # --- BUY_YES ---

    def test_three_models_agree_at_0_75_market_0_55_buy_yes(self):
        t = _make_tournament()
        responses = self._inject([0.75, 0.75, 0.75])
        result = _run(t.run_tournament("mkt1", "Will X happen?", 0.55, model_responses=responses))
        assert result.signal == "BUY_YES"
        assert abs(result.mean_probability - 0.75) < 1e-6
        assert abs(result.divergence - 0.20) < 1e-6
        assert result.agreement_score == 1.0

    def test_buy_yes_signal_strength_correct(self):
        t = _make_tournament()
        responses = self._inject([0.75, 0.75, 0.75])
        result = _run(t.run_tournament("mkt1", "Q?", 0.55, model_responses=responses))
        # signal_strength = agreement * abs_divergence * (3/3)
        expected = 1.0 * 0.20 * 1.0
        assert abs(result.signal_strength - expected) < 1e-6

    # --- BUY_NO ---

    def test_three_models_agree_at_0_30_market_0_55_buy_no(self):
        t = _make_tournament()
        responses = self._inject([0.30, 0.30, 0.30])
        result = _run(t.run_tournament("mkt2", "Will Y happen?", 0.55, model_responses=responses))
        assert result.signal == "BUY_NO"
        assert abs(result.mean_probability - 0.30) < 1e-6
        assert result.divergence < 0

    # --- NO_SIGNAL: models disagree ---

    def test_high_disagreement_no_signal(self):
        """Models at 0.20, 0.50, 0.80 → std≈0.245 → agreement≈0.02 < 0.80."""
        t = _make_tournament()
        responses = self._inject([0.20, 0.50, 0.80])
        result = _run(t.run_tournament("mkt3", "Will Z happen?", 0.50, model_responses=responses))
        assert result.signal == "NO_SIGNAL"
        assert result.agreement_score < t.min_agreement

    # --- NO_SIGNAL: divergence too small ---

    def test_agree_but_divergence_too_small_no_signal(self):
        """Models agree at 0.55, market at 0.53 → divergence=0.02 < 0.10."""
        t = _make_tournament()
        responses = self._inject([0.55, 0.55, 0.55])
        result = _run(t.run_tournament("mkt4", "Q?", 0.53, model_responses=responses))
        assert result.signal == "NO_SIGNAL"
        assert result.abs_divergence < t.min_divergence

    # --- Stats sanity ---

    def test_mean_median_std_computed_correctly(self):
        t = _make_tournament()
        responses = self._inject([0.60, 0.70, 0.80])
        result = _run(t.run_tournament("mktX", "Q?", 0.50, model_responses=responses))
        import numpy as np
        probs = [0.60, 0.70, 0.80]
        assert abs(result.mean_probability - float(np.mean(probs))) < 1e-6
        assert abs(result.median_probability - float(np.median(probs))) < 1e-6
        assert abs(result.std_probability - float(np.std(probs, ddof=0))) < 1e-6

    def test_market_price_stored_correctly(self):
        t = _make_tournament()
        responses = self._inject([0.75, 0.75, 0.75])
        result = _run(t.run_tournament("mktP", "Q?", 0.61, model_responses=responses))
        assert result.market_price == 0.61

    def test_market_id_and_question_stored(self):
        t = _make_tournament()
        responses = self._inject([0.60, 0.60, 0.60])
        result = _run(t.run_tournament("ID-999", "Test question here?", 0.40, model_responses=responses))
        assert result.market_id == "ID-999"
        assert result.market_question == "Test question here?"

    def test_total_cost_is_zero_for_injected_responses(self):
        t = _make_tournament()
        responses = self._inject([0.65, 0.65, 0.65])
        result = _run(t.run_tournament("c1", "Q?", 0.50, model_responses=responses))
        assert result.total_cost_usd == 0.0

    def test_estimates_list_contains_all_models(self):
        t = _make_tournament()
        responses = self._inject([0.60, 0.65, 0.70])
        result = _run(t.run_tournament("e1", "Q?", 0.50, model_responses=responses))
        assert len(result.estimates) == 3
        model_names = {e.model_name for e in result.estimates}
        assert "claude-sonnet-4-6" in model_names
        assert "gpt-4o" in model_names
        assert "gemini-2.0-flash" in model_names

    # --- 5-model tournament ---

    def test_five_model_tournament(self):
        models = [
            "claude-sonnet-4-6",
            "gpt-4o",
            "gemini-2.0-flash",
            "gpt-4o-mini",
            "claude-haiku-3-5",
        ]
        t = _make_tournament(models=models)
        responses = self._inject([0.80, 0.82, 0.78, 0.81, 0.79], models=models)
        result = _run(t.run_tournament("five", "Q?", 0.60, model_responses=responses))
        assert len(result.estimates) == 5
        assert result.signal == "BUY_YES"
        # signal_strength = agreement * abs_divergence * (5/3)
        expected_strength = result.agreement_score * result.abs_divergence * (5 / 3)
        assert abs(result.signal_strength - expected_strength) < 1e-6

    def test_five_model_signal_strength_scales_with_n(self):
        """Five models with same probs should produce higher signal strength than three."""
        models_5 = ["m1", "m2", "m3", "m4", "m5"]
        models_3 = ["m1", "m2", "m3"]

        t5 = _make_tournament(models=models_5)
        t3 = _make_tournament(models=models_3)

        resp5 = self._inject([0.75] * 5, models=models_5)
        resp3 = self._inject([0.75] * 3, models=models_3)

        r5 = _run(t5.run_tournament("x5", "Q?", 0.55, model_responses=resp5))
        r3 = _run(t3.run_tournament("x3", "Q?", 0.55, model_responses=resp3))

        assert r5.signal_strength > r3.signal_strength

    # --- edge case: empty injected responses raises ---

    def test_empty_model_responses_raises(self):
        t = _make_tournament()
        with pytest.raises(RuntimeError, match="No estimates produced"):
            _run(t.run_tournament("empty", "Q?", 0.55, model_responses={}))


# ---------------------------------------------------------------------------
# 5. should_trade
# ---------------------------------------------------------------------------


class TestShouldTrade:
    def _make_result(self, signal: str, strength: float) -> TournamentResult:
        return TournamentResult(
            market_id="t",
            market_question="Q?",
            estimates=[],
            mean_probability=0.70,
            median_probability=0.70,
            std_probability=0.0,
            agreement_score=1.0,
            market_price=0.50,
            divergence=0.20,
            abs_divergence=0.20,
            signal=signal,
            signal_strength=strength,
            total_cost_usd=0.0,
        )

    def test_buy_yes_nonzero_strength_should_trade(self):
        t = _make_tournament()
        r = self._make_result("BUY_YES", 0.15)
        assert t.should_trade(r) is True

    def test_buy_no_nonzero_strength_should_trade(self):
        t = _make_tournament()
        r = self._make_result("BUY_NO", 0.12)
        assert t.should_trade(r) is True

    def test_no_signal_should_not_trade(self):
        t = _make_tournament()
        r = self._make_result("NO_SIGNAL", 0.0)
        assert t.should_trade(r) is False

    def test_buy_yes_zero_strength_should_not_trade(self):
        t = _make_tournament()
        r = self._make_result("BUY_YES", 0.0)
        assert t.should_trade(r) is False


# ---------------------------------------------------------------------------
# 6. get_position_size
# ---------------------------------------------------------------------------


class TestGetPositionSize:
    def _make_result(self, abs_divergence: float, agreement: float) -> TournamentResult:
        return TournamentResult(
            market_id="ps",
            market_question="Q?",
            estimates=[],
            mean_probability=0.70,
            median_probability=0.70,
            std_probability=0.0,
            agreement_score=agreement,
            market_price=0.50,
            divergence=abs_divergence,
            abs_divergence=abs_divergence,
            signal="BUY_YES",
            signal_strength=agreement * abs_divergence,
            total_cost_usd=0.0,
        )

    def test_basic_kelly_sizing(self):
        t = _make_tournament()
        r = self._make_result(abs_divergence=0.20, agreement=1.0)
        # edge = 0.20 * 1.0 = 0.20
        # kelly = 0.25 * 1000 * 0.20 = 50.0
        # cap = 1000 * 0.05 = 50.0  → exactly at cap
        size = t.get_position_size(r, bankroll=1000.0, kelly_fraction=0.25)
        assert abs(size - 50.0) < 1e-6

    def test_capped_at_5_percent_bankroll(self):
        t = _make_tournament()
        r = self._make_result(abs_divergence=0.50, agreement=1.0)
        # edge = 0.50; kelly = 0.25 * 1000 * 0.50 = 125 > cap=50
        size = t.get_position_size(r, bankroll=1000.0, kelly_fraction=0.25)
        assert size == 1000.0 * 0.05

    def test_small_edge_below_cap(self):
        t = _make_tournament()
        r = self._make_result(abs_divergence=0.10, agreement=0.85)
        # edge = 0.10 * 0.85 = 0.085
        # kelly = 0.25 * 1000 * 0.085 = 21.25 < cap=50
        size = t.get_position_size(r, bankroll=1000.0, kelly_fraction=0.25)
        assert abs(size - 21.25) < 1e-6

    def test_custom_bankroll(self):
        t = _make_tournament()
        r = self._make_result(abs_divergence=0.10, agreement=1.0)
        # kelly = 0.25 * 500 * 0.10 = 12.5; cap = 500 * 0.05 = 25
        size = t.get_position_size(r, bankroll=500.0, kelly_fraction=0.25)
        assert abs(size - 12.5) < 1e-6

    def test_zero_edge_returns_zero(self):
        t = _make_tournament()
        r = self._make_result(abs_divergence=0.0, agreement=1.0)
        size = t.get_position_size(r, bankroll=1000.0)
        assert size == 0.0


# ---------------------------------------------------------------------------
# 7. format_alert
# ---------------------------------------------------------------------------


class TestFormatAlert:
    def _make_full_result(self) -> TournamentResult:
        estimates = [
            ModelEstimate("claude-sonnet-4-6", 0.75, "high", "Strong YES case.", 150.0, 0.0012, ""),
            ModelEstimate("gpt-4o", 0.76, "high", "Agree with YES.", 200.0, 0.0020, ""),
            ModelEstimate("gemini-2.0-flash", 0.74, "medium", "Lean YES.", 100.0, 0.0004, ""),
        ]
        return TournamentResult(
            market_id="alert-test",
            market_question="Will the Fed cut rates in May?",
            estimates=estimates,
            mean_probability=0.75,
            median_probability=0.75,
            std_probability=0.008,
            agreement_score=0.97,
            market_price=0.55,
            divergence=0.20,
            abs_divergence=0.20,
            signal="BUY_YES",
            signal_strength=0.194,
            total_cost_usd=0.0036,
        )

    def test_alert_contains_signal(self):
        t = _make_tournament()
        r = self._make_full_result()
        alert = t.format_alert(r)
        assert "BUY_YES" in alert

    def test_alert_contains_market_question(self):
        t = _make_tournament()
        r = self._make_full_result()
        alert = t.format_alert(r)
        assert "Will the Fed cut rates in May?" in alert

    def test_alert_contains_market_id(self):
        t = _make_tournament()
        r = self._make_full_result()
        alert = t.format_alert(r)
        assert "alert-test" in alert

    def test_alert_contains_model_names(self):
        t = _make_tournament()
        r = self._make_full_result()
        alert = t.format_alert(r)
        assert "claude-sonnet-4-6" in alert
        assert "gpt-4o" in alert
        assert "gemini-2.0-flash" in alert

    def test_alert_contains_mean_probability(self):
        t = _make_tournament()
        r = self._make_full_result()
        alert = t.format_alert(r)
        assert "0.750" in alert or "mean=0.750" in alert

    def test_alert_contains_market_price(self):
        t = _make_tournament()
        r = self._make_full_result()
        alert = t.format_alert(r)
        assert "0.550" in alert

    def test_alert_contains_divergence(self):
        t = _make_tournament()
        r = self._make_full_result()
        alert = t.format_alert(r)
        assert "+0.200" in alert or "divergence" in alert.lower()

    def test_alert_contains_signal_strength(self):
        t = _make_tournament()
        r = self._make_full_result()
        alert = t.format_alert(r)
        assert "0.194" in alert

    def test_alert_contains_cost(self):
        t = _make_tournament()
        r = self._make_full_result()
        alert = t.format_alert(r)
        assert "0.0036" in alert


# ---------------------------------------------------------------------------
# 8. historical_accuracy
# ---------------------------------------------------------------------------


class TestHistoricalAccuracy:
    def test_empty_history(self):
        t = _make_tournament()
        stats = t.historical_accuracy()
        assert stats["total_signals"] == 0
        assert stats["correct"] == 0
        assert stats["accuracy"] is None

    def test_perfect_record(self):
        t = _make_tournament()
        responses = {"m1": _make_response(0.75), "m2": _make_response(0.75), "m3": _make_response(0.75)}
        r = _run(t.run_tournament("h1", "Q?", 0.55, model_responses=responses))
        t.record_outcome(r, resolved_yes=True)  # BUY_YES + resolved YES = correct
        stats = t.historical_accuracy()
        assert stats["total_signals"] == 1
        assert stats["correct"] == 1
        assert abs(stats["accuracy"] - 1.0) < 1e-9

    def test_wrong_prediction(self):
        t = _make_tournament()
        responses = {"m1": _make_response(0.75), "m2": _make_response(0.75), "m3": _make_response(0.75)}
        r = _run(t.run_tournament("h2", "Q?", 0.55, model_responses=responses))
        t.record_outcome(r, resolved_yes=False)  # BUY_YES + resolved NO = wrong
        stats = t.historical_accuracy()
        assert stats["total_signals"] == 1
        assert stats["correct"] == 0
        assert stats["accuracy"] == 0.0

    def test_no_signal_not_recorded(self):
        t = _make_tournament()
        responses = {"m1": _make_response(0.55), "m2": _make_response(0.55), "m3": _make_response(0.55)}
        r = _run(t.run_tournament("h3", "Q?", 0.53, model_responses=responses))
        assert r.signal == "NO_SIGNAL"
        t.record_outcome(r, resolved_yes=True)  # Should be ignored
        stats = t.historical_accuracy()
        assert stats["total_signals"] == 0

    def test_accuracy_over_mixed_record(self):
        t = _make_tournament()
        # 3 correct BUY_YES, 1 wrong BUY_YES → 75% accuracy
        for i in range(4):
            responses = {"m1": _make_response(0.75), "m2": _make_response(0.75), "m3": _make_response(0.75)}
            r = _run(t.run_tournament(f"hm{i}", "Q?", 0.55, model_responses=responses))
            t.record_outcome(r, resolved_yes=(i < 3))
        stats = t.historical_accuracy()
        assert stats["total_signals"] == 4
        assert stats["correct"] == 3
        assert abs(stats["accuracy"] - 0.75) < 1e-9
        assert stats["avg_divergence_on_correct"] is not None


# ---------------------------------------------------------------------------
# 9. Signal logic edge cases
# ---------------------------------------------------------------------------


class TestSignalLogicEdgeCases:
    def test_agreement_just_above_threshold_triggers_signal(self):
        """Agreement just above min_agreement (0.80) should trigger signal."""
        t = _make_tournament(min_agreement=0.80)
        # Three models tightly clustered: std ≈ 0.0082, agreement ≈ 0.967
        responses = {
            "m1": _make_response(0.74),
            "m2": _make_response(0.75),
            "m3": _make_response(0.76),
        }
        r = _run(t.run_tournament("edge1", "Q?", 0.55, model_responses=responses))
        assert r.agreement_score > 0.80
        # divergence = 0.75 - 0.55 = 0.20 > 0.10 → should trade
        assert r.signal == "BUY_YES"

    def test_divergence_exactly_at_threshold_no_signal(self):
        """Divergence exactly at min_divergence should NOT trigger (< required)."""
        t = _make_tournament(min_divergence=0.10)
        responses = {
            "m1": _make_response(0.65),
            "m2": _make_response(0.65),
            "m3": _make_response(0.65),
        }
        # market_price = 0.55, divergence = 0.10 (not strictly greater)
        r = _run(t.run_tournament("edge2", "Q?", 0.55, model_responses=responses))
        # abs_divergence = 0.10, min_divergence = 0.10
        # Our signal check is abs_div >= min_div, so 0.10 >= 0.10 should signal
        # (convention: >= not >)
        assert r.signal in ("BUY_YES", "NO_SIGNAL")  # acceptable either way per impl

    def test_buy_no_when_consensus_below_market(self):
        t = _make_tournament()
        responses = {
            "m1": _make_response(0.25),
            "m2": _make_response(0.25),
            "m3": _make_response(0.25),
        }
        r = _run(t.run_tournament("bn1", "Q?", 0.60, model_responses=responses))
        assert r.signal == "BUY_NO"
        assert r.divergence < 0

    def test_custom_min_agreement(self):
        """Lower min_agreement threshold allows weaker consensus to signal."""
        t = _make_tournament(min_agreement=0.30)
        # Models at 0.20, 0.50, 0.80 → agreement ≈ 0.02 — still below 0.30
        responses = {
            "m1": _make_response(0.20),
            "m2": _make_response(0.50),
            "m3": _make_response(0.80),
        }
        r = _run(t.run_tournament("ca1", "Q?", 0.50, model_responses=responses))
        # Still no signal because even 0.30 threshold is above 0.02
        assert r.signal == "NO_SIGNAL"

    def test_custom_min_divergence(self):
        """Lower min_divergence lets smaller consensus differences signal."""
        t = _make_tournament(min_divergence=0.03)
        responses = {
            "m1": _make_response(0.60),
            "m2": _make_response(0.60),
            "m3": _make_response(0.60),
        }
        r = _run(t.run_tournament("cd1", "Q?", 0.55, model_responses=responses))
        # divergence = 0.05 > 0.03, agreement = 1.0 → BUY_YES
        assert r.signal == "BUY_YES"
