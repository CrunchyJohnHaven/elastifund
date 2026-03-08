#!/usr/bin/env python3
"""Tests for LLM Ensemble + Agentic RAG module."""

import asyncio
import math
import os
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import llm_ensemble
from llm_ensemble import (
    calibrate_probability,
    build_prompt,
    parse_llm_response,
    ModelEstimate,
    trimmed_mean,
    aggregate_probability_stats,
    compute_consensus,
    compute_stddev,
    confidence_from_spread,
    compute_agreement_score,
    kelly_multiplier_from_agreement,
    kelly_fraction_from_stddev,
    kelly_multiplier_from_stddev,
    BrierTracker,
    LLMEnsemble,
    EnsembleResult,
)


class TestCalibration(unittest.TestCase):
    """Test Platt scaling calibration."""

    def test_calibrate_90_pct(self):
        """90% raw should calibrate to ~71%."""
        cal = calibrate_probability(0.90)
        self.assertAlmostEqual(cal, 0.71, delta=0.02)

    def test_calibrate_80_pct(self):
        """80% raw should calibrate to ~60%."""
        cal = calibrate_probability(0.80)
        self.assertAlmostEqual(cal, 0.60, delta=0.02)

    def test_calibrate_50_pct(self):
        """50% should stay at 50%."""
        cal = calibrate_probability(0.50)
        self.assertEqual(cal, 0.50)

    def test_calibrate_symmetry(self):
        """Calibration should be symmetric around 0.5."""
        cal_high = calibrate_probability(0.80)
        cal_low = calibrate_probability(0.20)
        self.assertAlmostEqual(cal_high + cal_low, 1.0, delta=0.001)

    def test_calibrate_clamps(self):
        """Should clamp to [0.01, 0.99]."""
        self.assertGreaterEqual(calibrate_probability(0.001), 0.01)
        self.assertLessEqual(calibrate_probability(0.999), 0.99)


class TestBuildPrompt(unittest.TestCase):
    """Test prompt construction."""

    def test_prompt_no_context(self):
        prompt = build_prompt("Will X happen?")
        self.assertIn("Will X happen?", prompt)
        self.assertNotIn("RECENT CONTEXT", prompt)

    def test_prompt_with_context(self):
        prompt = build_prompt("Will X happen?", "Some search results here")
        self.assertIn("Will X happen?", prompt)
        self.assertIn("RECENT CONTEXT", prompt)
        self.assertIn("Some search results here", prompt)

    def test_prompt_contains_calibration_note(self):
        prompt = build_prompt("Will X happen?")
        self.assertIn("overestimate YES", prompt)
        self.assertIn("PROBABILITY:", prompt)


class TestParseResponse(unittest.TestCase):
    """Test LLM response parsing."""

    def test_standard_format(self):
        text = """PROBABILITY: 0.65
CONFIDENCE: high
REASONING: Based on historical data..."""
        result = parse_llm_response(text, "test-model")
        self.assertAlmostEqual(result.probability, 0.65, delta=0.001)
        self.assertEqual(result.confidence, "high")
        self.assertIn("historical", result.reasoning)
        self.assertEqual(result.model_name, "test-model")
        self.assertEqual(result.error, "")

    def test_percentage_format(self):
        text = "PROBABILITY: 65%\nCONFIDENCE: medium\nREASONING: test"
        result = parse_llm_response(text, "test")
        self.assertAlmostEqual(result.probability, 0.65, delta=0.001)

    def test_number_only(self):
        text = "PROBABILITY: 42\nCONFIDENCE: low\nREASONING: test"
        result = parse_llm_response(text, "test")
        self.assertAlmostEqual(result.probability, 0.42, delta=0.001)

    def test_clamp_high(self):
        text = "PROBABILITY: 0.999\nCONFIDENCE: high\nREASONING: very sure"
        result = parse_llm_response(text, "test")
        self.assertLessEqual(result.probability, 0.99)

    def test_clamp_low(self):
        text = "PROBABILITY: 0.001\nCONFIDENCE: low\nREASONING: unlikely"
        result = parse_llm_response(text, "test")
        self.assertGreaterEqual(result.probability, 0.01)

    def test_parse_failure(self):
        text = "I'm not sure about this question."
        result = parse_llm_response(text, "test")
        self.assertEqual(result.probability, 0.5)
        self.assertEqual(result.error, "parse_failure")

    def test_fallback_decimal_detection(self):
        text = "I estimate the probability at 0.72 based on evidence."
        result = parse_llm_response(text, "test")
        self.assertAlmostEqual(result.probability, 0.72, delta=0.001)

    def test_confidence_mapping(self):
        for conf_str, expected in [("high", "high"), ("medium", "medium"),
                                    ("low", "low"), ("very high", "high"),
                                    ("moderate", "medium")]:
            text = f"PROBABILITY: 0.5\nCONFIDENCE: {conf_str}\nREASONING: test"
            result = parse_llm_response(text, "test")
            self.assertEqual(result.confidence, expected,
                             f"Expected {expected} for '{conf_str}'")


class TestTrimmedMean(unittest.TestCase):
    """Test trimmed mean aggregation."""

    def test_single_value(self):
        self.assertAlmostEqual(trimmed_mean([0.7]), 0.7)

    def test_two_values(self):
        self.assertAlmostEqual(trimmed_mean([0.6, 0.8]), 0.7)

    def test_three_values_drops_extremes(self):
        # Should drop 0.3 (low) and 0.9 (high), return 0.6
        result = trimmed_mean([0.3, 0.6, 0.9])
        self.assertAlmostEqual(result, 0.6)

    def test_four_values(self):
        # Drop 0.2 and 0.9, average 0.5 and 0.7 = 0.6
        result = trimmed_mean([0.2, 0.5, 0.7, 0.9])
        self.assertAlmostEqual(result, 0.6)

    def test_empty(self):
        self.assertAlmostEqual(trimmed_mean([]), 0.5)

    def test_outlier_resistance(self):
        """Trimmed mean should resist outlier models."""
        # One model says 0.9 (outlier), others say ~0.5
        with_outlier = trimmed_mean([0.45, 0.50, 0.55, 0.90])
        without_outlier = trimmed_mean([0.45, 0.50, 0.55])
        # Trimmed mean should be closer to 0.5 than raw mean
        self.assertAlmostEqual(with_outlier, 0.525, delta=0.01)


class TestProbabilityStats(unittest.TestCase):
    """Test aggregate mean/stddev helpers."""

    def test_stddev_matches_explicit_helper(self):
        probs = [0.40, 0.60, 0.80]
        mean_prob, stddev = aggregate_probability_stats(probs)
        self.assertAlmostEqual(mean_prob, 0.60, delta=1e-9)
        self.assertAlmostEqual(stddev, compute_stddev(probs), delta=1e-9)

    def test_empty_defaults(self):
        mean_prob, stddev = aggregate_probability_stats([])
        self.assertEqual(mean_prob, 0.5)
        self.assertEqual(stddev, 0.0)


class TestConsensus(unittest.TestCase):
    """Test consensus scoring."""

    def test_all_agree_yes(self):
        estimates = [
            ModelEstimate("a", 0.7, "high", ""),
            ModelEstimate("b", 0.8, "high", ""),
            ModelEstimate("c", 0.6, "medium", ""),
        ]
        self.assertAlmostEqual(compute_consensus(estimates), 1.0)

    def test_all_agree_no(self):
        estimates = [
            ModelEstimate("a", 0.2, "high", ""),
            ModelEstimate("b", 0.3, "high", ""),
        ]
        self.assertAlmostEqual(compute_consensus(estimates), 1.0)

    def test_split_vote(self):
        estimates = [
            ModelEstimate("a", 0.7, "high", ""),
            ModelEstimate("b", 0.3, "low", ""),
        ]
        self.assertAlmostEqual(compute_consensus(estimates), 0.5)

    def test_majority(self):
        estimates = [
            ModelEstimate("a", 0.7, "high", ""),
            ModelEstimate("b", 0.6, "medium", ""),
            ModelEstimate("c", 0.3, "low", ""),
        ]
        # 2 YES, 1 NO → 0.667
        self.assertAlmostEqual(compute_consensus(estimates), 2/3, delta=0.01)

    def test_empty(self):
        self.assertEqual(compute_consensus([]), 0.0)


class TestConfidence(unittest.TestCase):
    """Test confidence mapping from spread and consensus."""

    def test_high_confidence(self):
        self.assertEqual(confidence_from_spread(0.05, 1.0), "high")

    def test_medium_confidence(self):
        self.assertEqual(confidence_from_spread(0.15, 0.8), "medium")

    def test_low_confidence(self):
        self.assertEqual(confidence_from_spread(0.30, 0.5), "low")


class TestAgreementAndSizing(unittest.TestCase):
    """Test disagreement-aware agreement and Kelly multiplier mapping."""

    def test_agreement_score_high_for_tight_ensemble(self):
        score = compute_agreement_score(spread=0.05, consensus=1.0)
        self.assertGreater(score, 0.75)

    def test_agreement_score_low_for_wide_or_split_ensemble(self):
        wide = compute_agreement_score(spread=0.30, consensus=1.0)
        split = compute_agreement_score(spread=0.05, consensus=0.50)
        self.assertLess(wide, 0.2)
        self.assertLess(split, 0.6)

    def test_kelly_multiplier_bounds(self):
        self.assertAlmostEqual(kelly_multiplier_from_agreement(0.0), 0.25, delta=1e-9)
        self.assertAlmostEqual(kelly_multiplier_from_agreement(1.0), 1.5, delta=1e-9)
        mid = kelly_multiplier_from_agreement(0.5)
        self.assertTrue(0.25 < mid < 1.5)

    def test_stddev_threshold_sizing(self):
        self.assertAlmostEqual(kelly_fraction_from_stddev(0.04), 0.25, delta=1e-9)
        self.assertAlmostEqual(kelly_fraction_from_stddev(0.15), 1.0 / 32.0, delta=1e-6)
        self.assertAlmostEqual(kelly_multiplier_from_stddev(0.15), 0.125, delta=1e-6)

    def test_stddev_sizing_interpolates(self):
        mid_fraction = kelly_fraction_from_stddev(0.10)
        self.assertGreater(mid_fraction, 1.0 / 32.0)
        self.assertLess(mid_fraction, 0.25)

    def test_model_stddev_zero_for_single_estimate(self):
        self.assertAlmostEqual(compute_stddev([0.62]), 0.0, delta=1e-12)

    def test_model_stddev_matches_population_std(self):
        std = compute_stddev([0.40, 0.50, 0.60])
        self.assertAlmostEqual(std, math.sqrt((0.01 + 0 + 0.01) / 3), delta=1e-9)

    def test_kelly_multiplier_from_stddev_thresholds(self):
        self.assertAlmostEqual(kelly_multiplier_from_stddev(0.01), 1.0, delta=1e-9)
        self.assertAlmostEqual(kelly_multiplier_from_stddev(0.20), 0.125, delta=1e-9)
        mid = kelly_multiplier_from_stddev(0.10)
        self.assertTrue(0.125 < mid < 1.0)


class TestBrierTracker(unittest.TestCase):
    """Test Brier score tracking database."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tracker = BrierTracker(db_path=f"{self.tmpdir}/test_brier.db")

    def test_record_and_resolve(self):
        """Record estimate then resolution, verify Brier computed."""
        # Create a minimal EnsembleResult
        result = EnsembleResult(
            probability=0.70,
            calibrated_probability=0.53,
            confidence="medium",
            reasoning="test",
            n_models=2,
            model_spread=0.1,
            consensus=1.0,
            search_context_used=False,
            model_estimates=[
                ModelEstimate("model-a", 0.65, "medium", ""),
                ModelEstimate("model-b", 0.75, "high", ""),
            ],
        )

        self.tracker.record_estimate("market-1", "Test question?", result, "politics")
        self.tracker.record_resolution("market-1", 1)  # YES resolved

        summary = self.tracker.get_brier_summary()
        self.assertEqual(summary["total_resolved"], 1)
        self.assertTrue(len(summary["by_model"]) > 0)

        # Check Brier score: (0.70 - 1)^2 = 0.09, (0.53 - 1)^2 = 0.2209
        ensemble_brier = [m for m in summary["by_model"] if m["model"] == "ensemble"]
        self.assertEqual(len(ensemble_brier), 1)
        self.assertAlmostEqual(ensemble_brier[0]["brier_raw"], 0.09, delta=0.001)

    def test_no_resolution(self):
        """Summary should work with no resolutions."""
        summary = self.tracker.get_brier_summary()
        self.assertEqual(summary["total_resolved"], 0)
        self.assertEqual(summary["by_model"], [])

    def test_multiple_resolutions(self):
        """Track Brier across multiple markets."""
        for i, (prob, outcome) in enumerate([
            (0.8, 1),  # Good prediction: Brier = 0.04
            (0.2, 0),  # Good prediction: Brier = 0.04
            (0.9, 0),  # Bad prediction: Brier = 0.81
        ]):
            result = EnsembleResult(
                probability=prob,
                calibrated_probability=prob,  # Skip calibration for test
                confidence="medium",
                reasoning="",
                model_estimates=[],
            )
            self.tracker.record_estimate(f"m-{i}", f"Q{i}?", result, "test")
            self.tracker.record_resolution(f"m-{i}", outcome)

        summary = self.tracker.get_brier_summary()
        self.assertEqual(summary["total_resolved"], 3)
        # Average Brier = (0.04 + 0.04 + 0.81) / 3 ≈ 0.2967
        ensemble = [m for m in summary["by_model"] if m["model"] == "ensemble"]
        self.assertAlmostEqual(ensemble[0]["brier_raw"], 0.2967, delta=0.01)


class TestEnsembleResult(unittest.TestCase):
    """Test EnsembleResult dataclass."""

    def test_to_dict(self):
        result = EnsembleResult(
            probability=0.65,
            calibrated_probability=0.50,
            confidence="medium",
            reasoning="test",
            n_models=1,
            model_stddev=0.0,
            model_estimates=[ModelEstimate("test", 0.65, "medium", "")],
        )
        d = result.to_dict()
        self.assertEqual(d["probability"], 0.65)
        self.assertEqual(d["model_stddev"], 0.0)
        self.assertEqual(len(d["model_estimates"]), 1)
        self.assertEqual(d["model_estimates"][0]["model_name"], "test")


class TestCompatibilityWrapper(unittest.TestCase):
    """Ensure legacy imports delegate to the canonical estimator runtime."""

    def test_llm_ensemble_wraps_ensemble_estimator(self):
        runtime_result = SimpleNamespace(
            mean_estimate=0.62,
            calibrated_mean=0.58,
            confidence="medium",
            reasoning="wrapped result",
            range_estimate=0.08,
            std_estimate=0.04,
            confidence_multiplier=1.0,
            disagreement_signal={
                "signal_fired": False,
                "confirmation_signal": True,
                "uncertainty_reduction": False,
            },
            model_estimates=[
                SimpleNamespace(
                    model_name="claude-haiku",
                    raw_probability=0.62,
                    confidence="medium",
                    reasoning="wrapped model",
                    latency_ms=18.0,
                    error="",
                )
            ],
            errors=[],
        )

        with patch("llm_ensemble.EnsembleEstimator") as mock_estimator_cls:
            mock_estimator = mock_estimator_cls.return_value
            mock_estimator.models = ["claude-haiku"]
            mock_estimator.estimate = AsyncMock(return_value=runtime_result)

            ensemble = LLMEnsemble(enable_brier=False)
            result = asyncio.run(
                ensemble.estimate(
                    "Will X happen?",
                    category="politics",
                    market_id="m-1",
                    timeout=12.5,
                )
            )

        self.assertEqual(mock_estimator.timeout_seconds, 12.5)
        mock_estimator.estimate.assert_awaited_once_with(
            "Will X happen?",
            market_price=0.0,
            category="politics",
            market_id="m-1",
            context="",
            news_section="",
        )
        self.assertAlmostEqual(result.probability, 0.62, delta=1e-9)
        self.assertAlmostEqual(result.calibrated_probability, 0.58, delta=1e-9)
        self.assertEqual(result.n_models, 1)
        self.assertTrue(result.models_agree)


if __name__ == "__main__":
    unittest.main()
