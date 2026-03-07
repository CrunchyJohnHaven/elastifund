#!/usr/bin/env python3
"""Tests for Automated Kill Rules."""

import math
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from bot.kill_rules import (
    KillReason,
    KillResult,
    polymarket_taker_fee,
    check_semantic_decay,
    check_toxicity_survival,
    check_cost_stress,
    check_calibration_enforcement,
    check_minimum_signals,
    check_oos_ev,
    run_full_kill_battery,
)


# ---------------------------------------------------------------------------
# Fee Model Tests
# ---------------------------------------------------------------------------

class TestPolymarketTakerFee:
    def test_crypto_fee_at_50(self):
        """Crypto fee at p=0.50: 0.50 * 0.50 * 0.025 = 0.00625."""
        fee = polymarket_taker_fee(0.50, "crypto")
        assert fee == pytest.approx(0.00625)

    def test_crypto_fee_at_extremes(self):
        """Fee approaches 0 at extreme prices."""
        fee_low = polymarket_taker_fee(0.05, "crypto")
        fee_high = polymarket_taker_fee(0.95, "crypto")
        assert fee_low < 0.002
        assert fee_high < 0.002

    def test_sports_fee(self):
        fee = polymarket_taker_fee(0.50, "sports")
        assert fee == pytest.approx(0.50 * 0.50 * 0.007)

    def test_default_no_fee(self):
        fee = polymarket_taker_fee(0.50, "default")
        assert fee == 0.0

    def test_unknown_category_no_fee(self):
        fee = polymarket_taker_fee(0.50, "politics")
        assert fee == 0.0


# ---------------------------------------------------------------------------
# Semantic Decay Tests
# ---------------------------------------------------------------------------

class TestSemanticDecay:
    def test_high_confidence_passes(self):
        result = check_semantic_decay(0.8)
        assert result.passed

    def test_low_confidence_kills(self):
        result = check_semantic_decay(0.1)
        assert not result.passed
        assert result.reason == KillReason.SEMANTIC_DECAY

    def test_threshold_boundary(self):
        result = check_semantic_decay(0.3, threshold=0.3)
        assert result.passed  # Exactly at threshold = pass

        result = check_semantic_decay(0.29, threshold=0.3)
        assert not result.passed

    def test_custom_threshold(self):
        result = check_semantic_decay(0.4, threshold=0.5)
        assert not result.passed


# ---------------------------------------------------------------------------
# Toxicity Survival Tests
# ---------------------------------------------------------------------------

class TestToxicitySurvival:
    def test_survives_toxic_flow(self):
        result = check_toxicity_survival(pnl_under_toxic=80.0, pnl_normal=100.0)
        assert result.passed  # 20% degradation < 50% limit

    def test_collapses_under_toxic(self):
        result = check_toxicity_survival(pnl_under_toxic=10.0, pnl_normal=100.0)
        assert not result.passed
        assert result.reason == KillReason.TOXICITY_SURVIVAL

    def test_negative_normal_pnl(self):
        result = check_toxicity_survival(pnl_under_toxic=-50.0, pnl_normal=-10.0)
        assert not result.passed

    def test_exact_threshold(self):
        result = check_toxicity_survival(
            pnl_under_toxic=50.0, pnl_normal=100.0, max_drawdown_pct=0.50
        )
        assert result.passed  # Exactly 50% = pass

    def test_zero_normal_pnl(self):
        result = check_toxicity_survival(pnl_under_toxic=0.0, pnl_normal=0.0)
        assert not result.passed


# ---------------------------------------------------------------------------
# Cost Stress Tests
# ---------------------------------------------------------------------------

class TestCostStress:
    def test_positive_ev_passes(self):
        result = check_cost_stress(gross_ev=0.05, avg_price=0.50, category="default")
        assert result.passed

    def test_crypto_fee_kills_small_edge(self):
        """Crypto taker fee at p=0.50 is 0.625% — kills edges below that."""
        result = check_cost_stress(gross_ev=0.005, avg_price=0.50, category="crypto")
        assert not result.passed
        assert result.reason == KillReason.COST_STRESS

    def test_maker_no_fee(self):
        """Default (non-crypto/sports) has zero taker fee."""
        result = check_cost_stress(gross_ev=0.001, avg_price=0.50, category="default")
        # Still has latency cost: 5ms * 0.0001 = 0.0005
        assert result.passed  # 0.001 > 0.0005

    def test_latency_cost_matters(self):
        """High latency should eat into edge."""
        result = check_cost_stress(
            gross_ev=0.001, avg_price=0.50, category="default",
            execution_latency_ms=20.0
        )
        # Latency cost: 20 * 0.0001 = 0.002 > 0.001
        assert not result.passed

    def test_zero_latency(self):
        result = check_cost_stress(
            gross_ev=0.001, avg_price=0.50, category="default",
            execution_latency_ms=0.0
        )
        assert result.passed


# ---------------------------------------------------------------------------
# Calibration Enforcement Tests
# ---------------------------------------------------------------------------

class TestCalibrationEnforcement:
    def test_correct_calibration_passes(self):
        """Verify Platt scaling: raw 0.80 → calibrated via A=0.5914, B=-0.3977."""
        raw = 0.80
        logit_in = math.log(raw / (1 - raw))
        logit_out = 0.5914 * logit_in + (-0.3977)
        expected = 1.0 / (1.0 + math.exp(-logit_out))

        result = check_calibration_enforcement(raw, expected)
        assert result.passed

    def test_uncalibrated_kills(self):
        """Raw prob used directly without Platt → killed."""
        result = check_calibration_enforcement(raw_prob=0.80, calibrated_prob=0.80)
        assert not result.passed
        assert result.reason == KillReason.CALIBRATION_MISSING

    def test_wrong_parameters(self):
        """Calibrated with wrong parameters → killed."""
        raw = 0.80
        # Grossly wrong params: A=1.0, B=0.5 (vs correct A=0.5914, B=-0.3977)
        wrong_cal = 1.0 / (1.0 + math.exp(-(1.0 * math.log(raw / (1-raw)) + 0.5)))
        result = check_calibration_enforcement(raw, wrong_cal)
        assert not result.passed

    def test_probability_at_50(self):
        """At p=0.50, logit is 0, so Platt output depends only on B."""
        raw = 0.50
        expected = 1.0 / (1.0 + math.exp(-(-0.3977)))
        result = check_calibration_enforcement(raw, expected)
        assert result.passed


# ---------------------------------------------------------------------------
# Minimum Signals Tests
# ---------------------------------------------------------------------------

class TestMinimumSignals:
    def test_candidate_sufficient(self):
        result = check_minimum_signals(150, "candidate")
        assert result.passed

    def test_candidate_insufficient(self):
        result = check_minimum_signals(50, "candidate")
        assert not result.passed

    def test_validated_threshold(self):
        result = check_minimum_signals(250, "validated")
        assert not result.passed  # Needs 300

        result = check_minimum_signals(300, "validated")
        assert result.passed


# ---------------------------------------------------------------------------
# OOS EV Tests
# ---------------------------------------------------------------------------

class TestOOSEV:
    def test_positive_oos_passes(self):
        result = check_oos_ev(oos_ev=0.05, in_sample_ev=0.10)
        assert result.passed  # 50% ratio > 30% threshold

    def test_negative_oos_kills(self):
        result = check_oos_ev(oos_ev=-0.01, in_sample_ev=0.10)
        assert not result.passed
        assert result.reason == KillReason.NEGATIVE_OOS_EV

    def test_regime_decay(self):
        """OOS EV too low relative to IS → regime decay."""
        result = check_oos_ev(oos_ev=0.01, in_sample_ev=0.10)
        assert not result.passed
        assert result.reason == KillReason.REGIME_DECAY

    def test_ratio_at_threshold(self):
        result = check_oos_ev(oos_ev=0.03, in_sample_ev=0.10, min_ratio=0.3)
        assert result.passed  # Exactly 30%


# ---------------------------------------------------------------------------
# Full Battery Tests
# ---------------------------------------------------------------------------

class TestFullBattery:
    def test_all_pass(self):
        """Strategy that passes all rules."""
        raw = 0.70
        logit_in = math.log(raw / (1 - raw))
        logit_out = 0.5914 * logit_in + (-0.3977)
        calibrated = 1.0 / (1.0 + math.exp(-logit_out))

        passed, results = run_full_kill_battery(
            semantic_confidence=0.8,
            pnl_under_toxic=80.0,
            pnl_normal=100.0,
            gross_ev=0.05,
            avg_price=0.50,
            category="default",
            raw_prob=raw,
            calibrated_prob=calibrated,
            signal_count=150,
            stage="candidate",
            oos_ev=0.04,
            in_sample_ev=0.10,
        )
        assert passed
        assert all(r.passed for r in results)

    def test_single_failure_kills(self):
        """One failed rule should kill the whole battery."""
        raw = 0.70
        logit_in = math.log(raw / (1 - raw))
        logit_out = 0.5914 * logit_in + (-0.3977)
        calibrated = 1.0 / (1.0 + math.exp(-logit_out))

        passed, results = run_full_kill_battery(
            semantic_confidence=0.1,  # FAIL: too low
            pnl_under_toxic=80.0,
            pnl_normal=100.0,
            gross_ev=0.05,
            avg_price=0.50,
            raw_prob=raw,
            calibrated_prob=calibrated,
            signal_count=150,
            oos_ev=0.04,
            in_sample_ev=0.10,
        )
        assert not passed

    def test_skip_optional_rules(self):
        """Can skip toxicity and semantic checks."""
        raw = 0.70
        logit_in = math.log(raw / (1 - raw))
        logit_out = 0.5914 * logit_in + (-0.3977)
        calibrated = 1.0 / (1.0 + math.exp(-logit_out))

        passed, results = run_full_kill_battery(
            gross_ev=0.05,
            avg_price=0.50,
            raw_prob=raw,
            calibrated_prob=calibrated,
            signal_count=150,
            oos_ev=0.04,
            in_sample_ev=0.10,
            skip_toxicity=True,
            skip_semantic=True,
        )
        assert passed
