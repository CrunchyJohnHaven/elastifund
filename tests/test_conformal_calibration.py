#!/usr/bin/env python3
"""
Tests for bot/conformal_calibration.py
=======================================
Covers:
  - Platt transform numerical correctness
  - Interval production with seeded residuals
  - Adaptive width behaviour (wider when miscalibrated, tighter when accurate)
  - decide() logic: BUY_YES, BUY_NO, ABSTAIN
  - Coverage guarantee over 200 synthetic observations
  - Edge cases: raw_prob = 0.0, 1.0, 0.5
  - Empty residual set returns wide default interval
  - seed_from_history produces correct residual count
"""

from __future__ import annotations

import math
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.conformal_calibration import (
    BetDecision,
    ConformalCalibrator,
    ConformalInterval,
    _WIDE_LOWER,
    _WIDE_UPPER,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_calibrator(**kwargs) -> ConformalCalibrator:
    """Return a fresh calibrator with default or overridden parameters."""
    return ConformalCalibrator(**kwargs)


def _synthetic_pairs(
    n: int,
    true_prob: float = 0.7,
    noise_std: float = 0.05,
    rng: random.Random = None,
) -> list[tuple[float, bool]]:
    """Generate (predicted_prob, outcome) pairs around a given true probability."""
    if rng is None:
        rng = random.Random(42)
    pairs = []
    for _ in range(n):
        p = max(0.01, min(0.99, true_prob + rng.gauss(0.0, noise_std)))
        outcome = rng.random() < true_prob
        pairs.append((p, outcome))
    return pairs


# ---------------------------------------------------------------------------
# 1. Platt transform
# ---------------------------------------------------------------------------

class TestPlattTransform:
    def test_known_value_raw_0_9(self):
        """raw=0.9 with A=0.5914, B=-0.3977 should produce ~0.711.

        Formula (matching adaptive_platt.py canonical implementation):
            logit_out = A * logit(raw_prob) + B
            calibrated = 1 / (1 + exp(-logit_out))
        """
        cal = _make_calibrator()
        result = cal.platt_transform(0.9)
        # Ground-truth: logit(0.9) = log(0.9/0.1) = 2.1972
        # logit_out = 0.5914 * 2.1972 + (-0.3977) = 0.9017
        # calibrated = 1 / (1 + exp(-0.9017)) ≈ 0.7113
        logit_09 = math.log(0.9 / 0.1)
        logit_out = 0.5914 * logit_09 + (-0.3977)
        expected = 1.0 / (1.0 + math.exp(-logit_out))
        assert abs(result - expected) < 1e-9
        # Approximately 0.71
        assert 0.68 < result < 0.74

    def test_known_value_raw_0_5(self):
        """raw=0.5 (logit=0) should return exactly 0.5 via symmetry shortcut."""
        cal = _make_calibrator()
        result = cal.platt_transform(0.5)
        assert abs(result - 0.5) < 1e-12

    def test_monotone(self):
        """Platt transform must be monotonically increasing."""
        cal = _make_calibrator()
        probs = [0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 0.8, 0.9, 0.95]
        transformed = [cal.platt_transform(p) for p in probs]
        for i in range(len(transformed) - 1):
            assert transformed[i] < transformed[i + 1], (
                f"Not monotone at index {i}: {transformed[i]:.4f} >= {transformed[i+1]:.4f}"
            )

    def test_raw_0_0_edge_case(self):
        """raw_prob=0.0 should return a very small positive value near 0 without error.

        With A=0.5914 > 0, Platt is a probability-increasing transform:
        low raw probabilities map to low calibrated probabilities.
        """
        cal = _make_calibrator()
        result = cal.platt_transform(0.0)
        # Via symmetry: platt(0.0) = 1 - platt(1.0) ≈ 1 - 0.9999 ≈ 0.0
        assert 0.0 <= result < 0.05

    def test_raw_1_0_edge_case(self):
        """raw_prob=1.0 should return a value very close to 1.0 without error."""
        cal = _make_calibrator()
        result = cal.platt_transform(1.0)
        assert 0.95 < result <= 1.0

    def test_raw_0_5_returns_float(self):
        """raw_prob=0.5 should return a valid float in (0,1)."""
        cal = _make_calibrator()
        result = cal.platt_transform(0.5)
        assert isinstance(result, float)
        assert 0.0 < result < 1.0


# ---------------------------------------------------------------------------
# 2. Interval production with seeded residuals
# ---------------------------------------------------------------------------

class TestIntervalProduction:
    def test_interval_bounds_in_range(self):
        """Lower and upper must both be in [0, 1] after seeding."""
        cal = _make_calibrator()
        pairs = _synthetic_pairs(50)
        cal.seed_from_history(pairs)
        iv = cal.predict_interval(0.7)
        assert 0.0 <= iv.lower <= iv.upper <= 1.0

    def test_interval_width_positive(self):
        """width == upper - lower must be positive."""
        cal = _make_calibrator()
        cal.seed_from_history(_synthetic_pairs(50))
        iv = cal.predict_interval(0.7)
        assert iv.width > 0.0
        assert abs(iv.width - (iv.upper - iv.lower)) < 1e-12

    def test_point_estimate_inside_interval(self):
        """The Platt-calibrated point estimate should lie within the interval."""
        cal = _make_calibrator()
        cal.seed_from_history(_synthetic_pairs(100))
        iv = cal.predict_interval(0.75)
        assert iv.lower <= iv.point_estimate <= iv.upper

    def test_straddles_property(self):
        """straddles should be True when [lower, upper] contains 0.5."""
        iv_straddle = ConformalInterval(lower=0.3, upper=0.7, point_estimate=0.5,
                                        coverage=0.9, width=0.4)
        assert iv_straddle.straddles is True

        iv_no_straddle = ConformalInterval(lower=0.6, upper=0.85, point_estimate=0.72,
                                           coverage=0.9, width=0.25)
        assert iv_no_straddle.straddles is False

    def test_straddles_boundary_lower_exactly_05(self):
        """lower == 0.5 means interval starts at the decision boundary: straddles=True."""
        iv = ConformalInterval(lower=0.5, upper=0.8, point_estimate=0.65,
                               coverage=0.9, width=0.3)
        assert iv.straddles is True

    def test_coverage_field_propagated(self):
        """Custom coverage arg should appear on returned interval."""
        cal = _make_calibrator()
        cal.seed_from_history(_synthetic_pairs(50))
        iv = cal.predict_interval(0.6, coverage=0.80)
        assert abs(iv.coverage - 0.80) < 1e-12


# ---------------------------------------------------------------------------
# 3. Adaptive width: wider when miscalibrated, tighter when accurate
# ---------------------------------------------------------------------------

class TestAdaptiveWidth:
    def test_accurate_predictions_produce_narrower_intervals_than_inaccurate(self):
        """
        A calibrator seeded with small-residual predictions should produce
        narrower intervals than one seeded with large-residual predictions.

        We use controlled residuals: (0.8, True) gives residual 0.2;
        (0.8, False) gives residual 0.8. The 90th-pct quantile of 0.2 residuals
        is 0.2, vs 0.8 for the inaccurate calibrator — so interval widths
        must be 0.4 vs 1.0 respectively.
        """
        # Accurate: predicted 0.8, actual True → residual = |0.8 - 1| = 0.2
        accurate_cal = _make_calibrator(alpha=0.10, gamma=0.001)
        accurate_pairs = [(0.8, True)] * 200
        accurate_cal.seed_from_history(accurate_pairs)

        # Inaccurate: predicted 0.8, actual False → residual = |0.8 - 0| = 0.8
        inaccurate_cal = _make_calibrator(alpha=0.10, gamma=0.001)
        inaccurate_pairs = [(0.8, False)] * 200
        inaccurate_cal.seed_from_history(inaccurate_pairs)

        acc_iv = accurate_cal.predict_interval(0.7)
        inacc_iv = inaccurate_cal.predict_interval(0.7)

        assert acc_iv.width < inacc_iv.width, (
            f"Expected accurate interval ({acc_iv.width:.4f}) narrower "
            f"than inaccurate ({inacc_iv.width:.4f})"
        )

    def test_alpha_adapts_upward_on_perfect_coverage(self):
        """
        ACI adaptive rule: alpha_{t+1} = alpha_t + gamma*(target - err_t).

        When err_t=0 (observation is covered), delta = +gamma*target > 0,
        so alpha INCREASES. A higher alpha means a tighter miscoverage target
        → the calibrator is becoming more confident (narrower future intervals).
        This is correct: if we're always covered we can afford to tighten.
        """
        cal = _make_calibrator(alpha=0.10, gamma=0.05)
        initial_alpha = cal._state.alpha

        # Seed with predictions that are always covered (residual=0 is always ≤ quantile=0.5)
        for _ in range(30):
            cal.update(1.0, True)   # residual=0, always covered → err=0

        # Alpha should have increased beyond its initial value
        assert cal._state.alpha > initial_alpha, (
            f"Expected alpha to grow from {initial_alpha:.4f}, "
            f"got {cal._state.alpha:.4f}"
        )

    def test_alpha_adapts_downward_on_systematic_miscoverage(self):
        """
        When observations are systematically NOT covered (err_t=1),
        alpha DECREASES: delta = gamma*(target - 1) < 0 since target << 1.
        Lower alpha = wider intervals = more coverage.

        Setup: first seed with 100 tiny residuals (0.01) so the calibrator
        establishes a tight quantile (~0.01). Then inject large residuals
        (0.9) that far exceed the tight quantile → systematic miscoverage
        → err_t=1 consistently → alpha must shrink.
        """
        cal = _make_calibrator(alpha=0.30, gamma=0.10)

        # Phase 1: establish tight residuals so q90 ≈ 0.01
        for _ in range(100):
            cal.update(0.99, True)  # residual = |0.99 - 1| = 0.01

        alpha_after_tight = cal._state.alpha

        # Phase 2: inject large outliers that exceed the tight quantile
        # Each has residual 0.9 >> q90 ≈ 0.01 → err_t=1 → alpha shrinks
        for _ in range(50):
            cal.update(0.99, False)  # residual = |0.99 - 0| = 0.99

        alpha_after_miscoverage = cal._state.alpha

        assert alpha_after_miscoverage < alpha_after_tight, (
            f"Expected alpha to shrink from {alpha_after_tight:.4f} "
            f"after miscoverage events, got {alpha_after_miscoverage:.4f}"
        )

    def test_alpha_clipped_to_bounds(self):
        """Adaptive alpha must stay within [_ALPHA_MIN, _ALPHA_MAX]."""
        from bot.conformal_calibration import _ALPHA_MIN, _ALPHA_MAX
        cal = _make_calibrator(alpha=0.10, gamma=0.5)
        # Drive alpha to extremes
        for _ in range(200):
            cal.update(0.5, True)   # 50% pred, True → residual 0.5 — borderline
        assert _ALPHA_MIN <= cal._state.alpha <= _ALPHA_MAX


# ---------------------------------------------------------------------------
# 4. decide() logic
# ---------------------------------------------------------------------------

class TestDecideLogic:
    def _seeded_cal(self, n: int = 150, true_prob: float = 0.7) -> ConformalCalibrator:
        cal = _make_calibrator(alpha=0.10, gamma=0.005)
        cal.seed_from_history(_synthetic_pairs(n, true_prob=true_prob))
        return cal

    def test_buy_yes_when_interval_clearly_above_market(self):
        """When the entire interval is well above market_price + min_edge → BUY_YES.

        Seed with (0.95, True)×200 → residuals all 0.05.
        At alpha=0.10, q90 of [0.05]*200 = 0.05.
        platt(0.99) ≈ 0.9999, interval ≈ [0.9499, 1.0].
        With market_price=0.30 and min_edge=0.05: threshold=0.35 < 0.9499 → BUY_YES.
        """
        cal = _make_calibrator(alpha=0.10, gamma=0.001)
        for _ in range(200):
            cal.update(0.95, True)  # residual = |0.95 - 1| = 0.05

        decision = cal.decide(raw_prob=0.99, market_price=0.30, min_edge=0.05)
        assert decision.action == "BUY_YES", (
            f"Expected BUY_YES but got {decision.action} "
            f"(interval=[{decision.interval.lower:.3f}, {decision.interval.upper:.3f}], "
            f"alpha={cal._state.alpha:.4f}, quantile={cal._current_quantile():.4f})"
        )
        assert decision.confidence > 0.0

    def test_buy_no_when_interval_clearly_below_market(self):
        """When (1-interval.upper) > (1-market_price)+min_edge → BUY_NO.

        Seed with (0.05, False)×200 → residuals all 0.05.
        At alpha=0.10, q90 = 0.05.
        platt(0.01) ≈ 0.0001, interval ≈ [0, 0.0501].
        NO side: (1 - 0.0501) = 0.9499 vs (1 - 0.30) + 0.05 = 0.75 → 0.9499 > 0.75 → BUY_NO.
        """
        cal = _make_calibrator(alpha=0.10, gamma=0.001)
        for _ in range(200):
            cal.update(0.05, False)  # residual = |0.05 - 0| = 0.05

        decision = cal.decide(raw_prob=0.01, market_price=0.30, min_edge=0.05)
        assert decision.action == "BUY_NO", (
            f"Expected BUY_NO but got {decision.action} "
            f"(interval=[{decision.interval.lower:.3f}, {decision.interval.upper:.3f}], "
            f"market={decision.market_price:.2f}, "
            f"alpha={cal._state.alpha:.4f}, quantile={cal._current_quantile():.4f})"
        )

    def test_abstain_when_interval_straddles_market(self):
        """Wide interval straddling the market price should produce ABSTAIN."""
        cal = _make_calibrator(alpha=0.10)
        # Create wide interval: seed with maximally noisy residuals
        import random as _random
        rng = _random.Random(7)
        for _ in range(100):
            p = rng.uniform(0.1, 0.9)
            cal.update(p, rng.random() < 0.5)  # noisy → wide interval

        # raw_prob near 0.5, market near 0.5 → interval straddles → ABSTAIN
        decision = cal.decide(raw_prob=0.5, market_price=0.5, min_edge=0.10)
        assert decision.action == "ABSTAIN"

    def test_abstain_on_empty_residuals(self):
        """With no residuals, the wide default interval should cause ABSTAIN."""
        cal = _make_calibrator()
        # No seeding — wide default interval [0.05, 0.95]
        decision = cal.decide(raw_prob=0.6, market_price=0.55, min_edge=0.05)
        assert decision.action == "ABSTAIN"

    def test_decision_fields_populated(self):
        """BetDecision fields must all be populated and self-consistent."""
        cal = _make_calibrator()
        cal.seed_from_history(_synthetic_pairs(50))
        d = cal.decide(raw_prob=0.7, market_price=0.50, min_edge=0.05)
        assert d.action in {"BUY_YES", "BUY_NO", "ABSTAIN"}
        assert isinstance(d.confidence, float)
        assert isinstance(d.interval, ConformalInterval)
        assert d.market_price == 0.50
        assert isinstance(d.edge_lower, float)
        assert isinstance(d.edge_upper, float)
        # edge_lower + market_price should equal interval.lower
        assert abs(d.edge_lower - (d.interval.lower - d.market_price)) < 1e-9
        assert abs(d.edge_upper - (d.interval.upper - d.market_price)) < 1e-9

    def test_raw_prob_0_does_not_crash(self):
        """raw_prob=0.0 must not raise an exception."""
        cal = _make_calibrator()
        cal.seed_from_history(_synthetic_pairs(20))
        d = cal.decide(raw_prob=0.0, market_price=0.5, min_edge=0.05)
        assert d.action in {"BUY_YES", "BUY_NO", "ABSTAIN"}

    def test_raw_prob_1_does_not_crash(self):
        """raw_prob=1.0 must not raise an exception."""
        cal = _make_calibrator()
        cal.seed_from_history(_synthetic_pairs(20))
        d = cal.decide(raw_prob=1.0, market_price=0.5, min_edge=0.05)
        assert d.action in {"BUY_YES", "BUY_NO", "ABSTAIN"}


# ---------------------------------------------------------------------------
# 5. Coverage guarantee
# ---------------------------------------------------------------------------

class TestCoverageGuarantee:
    def test_empirical_coverage_meets_target(self):
        """
        Over 200 synthetic observations, empirical coverage should be
        >= (1 - alpha) - 0.05.

        Uses a held-out test set: seed with first 150, test on next 50,
        checking whether the prediction interval (built from residuals so far)
        covers the true outcome.
        """
        rng = random.Random(123)
        true_prob = 0.65
        alpha = 0.10
        cal = _make_calibrator(alpha=alpha, gamma=0.005)

        all_pairs = _synthetic_pairs(250, true_prob=true_prob, rng=rng)
        train_pairs = all_pairs[:150]
        test_pairs = all_pairs[150:200]

        # Seed calibrator
        cal.seed_from_history(train_pairs)

        # Evaluate coverage on held-out set
        covered_count = 0
        for predicted_prob, actual_outcome in test_pairs:
            iv = cal.predict_interval(predicted_prob)
            y = 1.0 if actual_outcome else 0.0
            if iv.lower <= y <= iv.upper:
                covered_count += 1
            # Also update for sequential validity
            cal.update(predicted_prob, actual_outcome)

        empirical_coverage = covered_count / len(test_pairs)
        min_required = (1.0 - alpha) - 0.05

        assert empirical_coverage >= min_required, (
            f"Empirical coverage {empirical_coverage:.3f} below "
            f"minimum required {min_required:.3f} "
            f"(target={1-alpha:.2f}, n_test={len(test_pairs)})"
        )

    def test_coverage_stats_empirical_coverage_plausible(self):
        """coverage_stats() should return a plausible empirical coverage value."""
        cal = _make_calibrator(alpha=0.10)
        pairs = _synthetic_pairs(100, true_prob=0.6)
        cal.seed_from_history(pairs)
        stats = cal.coverage_stats()
        assert stats["residual_count"] == 100
        assert 0.0 <= stats["empirical_coverage"] <= 1.0
        assert stats["average_width"] > 0.0
        assert abs(stats["target_alpha"] - 0.10) < 1e-12

    def test_coverage_stats_empty(self):
        """coverage_stats() on empty calibrator should return None for coverage."""
        cal = _make_calibrator()
        stats = cal.coverage_stats()
        assert stats["residual_count"] == 0
        assert stats["empirical_coverage"] is None
        assert stats["average_width"] is None


# ---------------------------------------------------------------------------
# 6. Edge cases: raw_prob = 0.0, 1.0, 0.5
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_predict_interval_raw_0(self):
        """raw_prob=0.0 should produce a valid interval."""
        cal = _make_calibrator()
        cal.seed_from_history(_synthetic_pairs(30))
        iv = cal.predict_interval(0.0)
        assert 0.0 <= iv.lower <= iv.upper <= 1.0
        assert iv.width > 0.0

    def test_predict_interval_raw_1(self):
        """raw_prob=1.0 should produce a valid interval."""
        cal = _make_calibrator()
        cal.seed_from_history(_synthetic_pairs(30))
        iv = cal.predict_interval(1.0)
        assert 0.0 <= iv.lower <= iv.upper <= 1.0
        assert iv.width > 0.0

    def test_predict_interval_raw_half(self):
        """raw_prob=0.5 should produce a valid interval straddling near 0.5."""
        cal = _make_calibrator()
        cal.seed_from_history(_synthetic_pairs(30))
        iv = cal.predict_interval(0.5)
        assert 0.0 <= iv.lower <= iv.upper <= 1.0

    def test_interval_bounds_never_inverted(self):
        """upper must always be >= lower across many inputs."""
        cal = _make_calibrator()
        cal.seed_from_history(_synthetic_pairs(80))
        for raw in [0.0, 0.1, 0.3, 0.5, 0.7, 0.9, 1.0]:
            iv = cal.predict_interval(raw)
            assert iv.upper >= iv.lower, (
                f"Inverted interval for raw={raw}: [{iv.lower:.4f}, {iv.upper:.4f}]"
            )


# ---------------------------------------------------------------------------
# 7. Empty residual set returns wide default interval
# ---------------------------------------------------------------------------

class TestEmptyResiduals:
    def test_empty_returns_wide_interval(self):
        """With no calibration data, interval should be [WIDE_LOWER, WIDE_UPPER]."""
        cal = _make_calibrator()
        iv = cal.predict_interval(0.7)
        assert abs(iv.lower - _WIDE_LOWER) < 1e-12
        assert abs(iv.upper - _WIDE_UPPER) < 1e-12

    def test_empty_interval_straddles(self):
        """The wide default interval must straddle 0.5."""
        cal = _make_calibrator()
        iv = cal.predict_interval(0.7)
        assert iv.straddles is True

    def test_empty_decide_abstains(self):
        """With no residuals and default min_edge, decide() should ABSTAIN."""
        cal = _make_calibrator()
        d = cal.decide(raw_prob=0.8, market_price=0.5, min_edge=0.05)
        assert d.action == "ABSTAIN"


# ---------------------------------------------------------------------------
# 8. seed_from_history produces correct residual count
# ---------------------------------------------------------------------------

class TestSeedFromHistory:
    def test_residual_count_after_seeding(self):
        """After seeding with N pairs, residual window should contain N entries."""
        cal = _make_calibrator()
        n = 75
        pairs = _synthetic_pairs(n)
        cal.seed_from_history(pairs)
        assert len(cal._state.residuals) == n

    def test_residual_count_capped_at_max(self):
        """When seeding with more than max_residuals, window is capped."""
        max_r = 50
        cal = _make_calibrator(max_residuals=max_r)
        pairs = _synthetic_pairs(200)
        cal.seed_from_history(pairs)
        assert len(cal._state.residuals) == max_r

    def test_empty_seed_is_no_op(self):
        """Seeding with an empty list leaves calibrator in initial state."""
        cal = _make_calibrator()
        cal.seed_from_history([])
        assert len(cal._state.residuals) == 0

    def test_seed_affects_interval_width(self):
        """Seeded calibrator should produce different intervals from the empty default.

        The empty default is [0.05, 0.95] = width 0.90.
        After seeding with very accurate predictions (residual=0.05),
        the q90 is 0.05, so the interval is much narrower (width ~0.10).
        """
        cal_empty = _make_calibrator()
        cal_seeded = _make_calibrator(gamma=0.001)
        # Seed with small-residual pairs: predicted 0.95, actual True → residual 0.05
        accurate_pairs = [(0.95, True)] * 100
        cal_seeded.seed_from_history(accurate_pairs)

        iv_empty = cal_empty.predict_interval(0.9)
        iv_seeded = cal_seeded.predict_interval(0.9)

        # Seeded interval (q90 ≈ 0.05, width ≈ 0.10) is narrower than default (0.90)
        assert iv_seeded.width < iv_empty.width, (
            f"Seeded width={iv_seeded.width:.4f} should be < empty width={iv_empty.width:.4f}"
        )

    def test_sequential_equivalence(self):
        """seed_from_history(pairs) must equal calling update() in a loop."""
        pairs = _synthetic_pairs(60)

        cal_seed = _make_calibrator()
        cal_seed.seed_from_history(pairs)

        cal_loop = _make_calibrator()
        for p, o in pairs:
            cal_loop.update(p, o)

        # Residuals and alpha should match exactly
        assert list(cal_seed._state.residuals) == list(cal_loop._state.residuals)
        assert abs(cal_seed._state.alpha - cal_loop._state.alpha) < 1e-12
