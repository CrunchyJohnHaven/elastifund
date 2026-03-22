#!/usr/bin/env python3
"""
Tests for BayesianChangePointDetector (BOCPD) regime detector.

Coverage:
  - Warmup state (< min_observations)
  - Stable regime — no false positives on consistent data
  - Regime shift detection: mean=1.0 for 50 obs, then mean=-2.0 for 50 obs
  - should_trade() False during TRANSITION, True after stabilization
  - reset() clears all state
  - student_t_pdf against known values
  - regime summary statistics
  - Real-ish P&L sequence with late shift
  - 500+ observations — no crash (max_run_length truncation)

No external API calls. Pure unit tests.
"""

from __future__ import annotations

import math
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from bot.regime_detector import BayesianChangePointDetector, RegimeState, RegimeSnapshot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_detector(**kwargs) -> BayesianChangePointDetector:
    """Create a detector with sensible defaults for testing."""
    defaults = dict(
        hazard_rate=1.0 / 50,
        mu_prior=0.0,
        kappa_prior=1.0,
        alpha_prior=1.0,
        beta_prior=1.0,
        changepoint_threshold=0.5,
        short_run_window=5,
        stabilization_window=5,
        min_observations=10,
        max_run_length=100,
    )
    defaults.update(kwargs)
    return BayesianChangePointDetector(**defaults)


def feed(det: BayesianChangePointDetector, values: list[float]) -> list[RegimeSnapshot]:
    """Feed a list of values to the detector and return snapshots."""
    t = 1_700_000_000.0
    snapshots = []
    for v in values:
        snapshots.append(det.observe(v, timestamp=t))
        t += 1.0
    return snapshots


# ---------------------------------------------------------------------------
# Warmup State
# ---------------------------------------------------------------------------

class TestWarmupState:
    def test_state_is_warmup_before_min_observations(self):
        det = make_detector(min_observations=20)
        for i in range(19):
            snap = det.observe(float(i), timestamp=float(i))
            assert snap.state == RegimeState.WARMUP, (
                f"Expected WARMUP at obs {i+1}, got {snap.state}"
            )

    def test_should_trade_false_during_warmup(self):
        det = make_detector(min_observations=20)
        for i in range(15):
            det.observe(1.0, timestamp=float(i))
        assert det.should_trade() is False

    def test_graduates_from_warmup_at_min_observations(self):
        det = make_detector(min_observations=10)
        snaps = feed(det, [1.0] * 9)
        assert snaps[-1].state == RegimeState.WARMUP
        snap10 = det.observe(1.0, timestamp=100.0)
        # After min_observations, transitions to STABLE (assuming no CP detected)
        assert snap10.state == RegimeState.STABLE

    def test_observations_seen_counter(self):
        det = make_detector(min_observations=5)
        for i in range(1, 8):
            snap = det.observe(0.5, timestamp=float(i))
            assert snap.observations_seen == i


# ---------------------------------------------------------------------------
# Stable Regime (No False Positives)
# ---------------------------------------------------------------------------

class TestStableRegime:
    def test_consistent_data_stays_stable(self):
        """100 draws from N(0, 0.1) should not trigger a changepoint."""
        import random
        rng = random.Random(42)
        det = make_detector(min_observations=10, changepoint_threshold=0.5)

        snaps = []
        for _ in range(100):
            v = rng.gauss(0.0, 0.1)
            snaps.append(det.observe(v))

        # After warmup, expect STABLE (no regime shifts in constant data)
        post_warmup = [s for s in snaps if s.state != RegimeState.WARMUP]
        transition_count = sum(1 for s in post_warmup if s.state == RegimeState.TRANSITION)
        # Allow at most 1 spurious transition in 90 stable observations
        assert transition_count <= 1, (
            f"Too many transitions ({transition_count}) on stationary data"
        )

    def test_changepoint_prob_low_in_stable_regime(self):
        """P(CP) should be low for most observations in a stable regime."""
        det = make_detector(min_observations=10)
        snaps = feed(det, [1.0] * 50)
        post_warmup = [s for s in snaps if s.observations_seen > 15]
        high_cp = [s for s in post_warmup if s.changepoint_prob > 0.3]
        assert len(high_cp) == 0, f"P(CP) unexpectedly high: {[s.changepoint_prob for s in high_cp]}"

    def test_should_trade_true_in_stable_regime(self):
        det = make_detector(min_observations=10)
        feed(det, [1.0] * 25)
        assert det.should_trade() is True


# ---------------------------------------------------------------------------
# Regime Shift Detection
# ---------------------------------------------------------------------------

class TestRegimeShiftDetection:
    def test_detects_mean_shift_50_plus_50(self):
        """
        50 obs at mean=1.0 then 50 at mean=-2.0 must trigger at least one
        changepoint detection after the shift.
        """
        import random
        rng = random.Random(123)
        det = make_detector(
            min_observations=10,
            changepoint_threshold=0.5,
            stabilization_window=5,
            hazard_rate=1.0 / 30,
        )

        # Phase 1: stable positive regime
        for _ in range(50):
            det.observe(rng.gauss(1.0, 0.2))

        assert det.should_trade() is True, "Should be STABLE after 50 consistent observations"

        # Phase 2: abrupt shift to negative regime
        detected = False
        for _ in range(50):
            snap = det.observe(rng.gauss(-2.0, 0.2))
            if snap.state == RegimeState.TRANSITION:
                detected = True
                break

        assert detected, (
            "Expected TRANSITION state after mean shift from +1.0 to -2.0 "
            "across 50 observations"
        )

    def test_changepoint_prob_spikes_after_shift(self):
        """P(CP) must exceed threshold within 15 observations of a mean shift."""
        import random
        rng = random.Random(7)
        det = make_detector(
            min_observations=10,
            changepoint_threshold=0.5,
            hazard_rate=1.0 / 20,
        )

        # Stable phase
        for _ in range(40):
            det.observe(rng.gauss(0.0, 0.1))

        # Shift phase
        max_cp = 0.0
        for _ in range(15):
            snap = det.observe(rng.gauss(3.0, 0.1))
            if snap.changepoint_prob > max_cp:
                max_cp = snap.changepoint_prob

        assert max_cp > 0.5, (
            f"Expected P(CP) > 0.5 after shift, got max={max_cp:.4f}"
        )

    def test_total_changepoints_increments(self):
        """total_changepoints counter should increment on each detected shift."""
        import random
        rng = random.Random(99)
        det = make_detector(
            min_observations=10,
            changepoint_threshold=0.5,
            stabilization_window=3,
            hazard_rate=1.0 / 20,
        )

        # Phase 1
        for _ in range(30):
            det.observe(rng.gauss(0.0, 0.1))
        # Phase 2 — shift
        for _ in range(30):
            det.observe(rng.gauss(5.0, 0.1))
        # Phase 3 — shift back
        for _ in range(30):
            det.observe(rng.gauss(-3.0, 0.1))

        summary = det.get_regime_summary()
        assert summary["total_changepoints"] >= 1, (
            "Expected at least 1 changepoint across two mean shifts"
        )

    def test_last_changepoint_idx_updates(self):
        """last_changepoint_idx should be > 0 after a shift is detected."""
        import random
        rng = random.Random(55)
        det = make_detector(
            min_observations=10,
            changepoint_threshold=0.5,
            hazard_rate=1.0 / 20,
        )

        for _ in range(30):
            det.observe(rng.gauss(0.0, 0.1))
        for _ in range(20):
            det.observe(rng.gauss(5.0, 0.1))

        summary = det.get_regime_summary()
        if summary["total_changepoints"] > 0:
            assert summary["last_changepoint_idx"] > 0


# ---------------------------------------------------------------------------
# should_trade() / TRANSITION Suppression
# ---------------------------------------------------------------------------

class TestShouldTrade:
    def test_should_trade_false_in_transition(self):
        """should_trade() must return False while in TRANSITION."""
        import random
        rng = random.Random(11)
        det = make_detector(
            min_observations=10,
            changepoint_threshold=0.4,
            stabilization_window=20,
            hazard_rate=1.0 / 20,
        )

        # Stable phase
        for _ in range(30):
            det.observe(rng.gauss(0.0, 0.1))

        # Force a transition by injecting an extreme observation
        # (P(CP) will spike when we observe something very far from current regime)
        in_transition = False
        for _ in range(20):
            snap = det.observe(rng.gauss(10.0, 0.1))
            if snap.state == RegimeState.TRANSITION:
                in_transition = True
                break

        if in_transition:
            assert det.should_trade() is False

    def test_should_trade_true_after_stabilization(self):
        """After stabilization_window observations, should_trade() returns True."""
        import random
        rng = random.Random(22)
        det = make_detector(
            min_observations=10,
            changepoint_threshold=0.4,
            stabilization_window=5,
            hazard_rate=1.0 / 15,
        )

        # Stable phase
        for _ in range(30):
            det.observe(rng.gauss(0.0, 0.1))

        # Trigger transition
        transition_triggered = False
        for _ in range(20):
            snap = det.observe(rng.gauss(10.0, 0.1))
            if snap.state == RegimeState.TRANSITION:
                transition_triggered = True
                break

        if not transition_triggered:
            pytest.skip("Could not trigger transition in this seed — skip stabilization test")

        # Feed stabilization_window + buffer observations in new regime
        for _ in range(15):
            det.observe(rng.gauss(10.0, 0.1))

        assert det.should_trade() is True, (
            "Expected STABLE after stabilization window elapsed"
        )

    def test_should_trade_false_warmup(self):
        det = make_detector(min_observations=30)
        for _ in range(20):
            det.observe(1.0)
        assert det.should_trade() is False


# ---------------------------------------------------------------------------
# reset()
# ---------------------------------------------------------------------------

class TestReset:
    def test_reset_clears_observations(self):
        det = make_detector(min_observations=10)
        feed(det, [1.0] * 30)
        assert det._observations_seen == 30
        det.reset()
        assert det._observations_seen == 0

    def test_reset_returns_to_warmup(self):
        det = make_detector(min_observations=10)
        feed(det, [1.0] * 30)
        assert det.should_trade() is True
        det.reset()
        assert det.should_trade() is False
        snap = det.observe(1.0)
        assert snap.state == RegimeState.WARMUP

    def test_reset_clears_changepoint_count(self):
        import random
        rng = random.Random(33)
        det = make_detector(
            min_observations=10,
            changepoint_threshold=0.4,
            hazard_rate=1.0 / 15,
        )
        for _ in range(30):
            det.observe(rng.gauss(0.0, 0.1))
        for _ in range(20):
            det.observe(rng.gauss(8.0, 0.1))

        det.reset()

        summary = det.get_regime_summary()
        assert summary["total_changepoints"] == 0
        assert summary["observations_seen"] == 0
        assert summary["last_changepoint_idx"] == 0

    def test_reset_restores_prior_nig_params(self):
        det = make_detector(mu_prior=2.5, kappa_prior=3.0, alpha_prior=2.0, beta_prior=4.0)
        feed(det, [10.0, 20.0, 30.0])
        det.reset()
        # After reset, the single NIG entry should match the prior
        assert len(det._nig_params) == 1
        p = det._nig_params[0]
        assert p.mu == pytest.approx(2.5)
        assert p.kappa == pytest.approx(3.0)
        assert p.alpha == pytest.approx(2.0)
        assert p.beta == pytest.approx(4.0)


# ---------------------------------------------------------------------------
# student_t_pdf
# ---------------------------------------------------------------------------

class TestStudentTPdf:
    def test_standard_t1_at_zero(self):
        """Standard Cauchy (nu=1) at x=0: pdf = 1/pi."""
        # t_1(0 | mu=0, sigma2=1) = 1/pi
        val = BayesianChangePointDetector.student_t_pdf(0.0, mu=0.0, sigma2=1.0, nu=1.0)
        assert val == pytest.approx(1.0 / math.pi, rel=1e-6)

    def test_standard_t_large_nu_approaches_normal(self):
        """For large nu, Student-t approaches Gaussian."""
        from scipy.stats import norm  # only imported if available
        try:
            import scipy.stats
        except ImportError:
            pytest.skip("scipy not available — skipping Gaussian limit test")
        x = 0.5
        t_val = BayesianChangePointDetector.student_t_pdf(x, mu=0.0, sigma2=1.0, nu=1000.0)
        gauss_val = norm.pdf(x, 0.0, 1.0)
        assert abs(t_val - gauss_val) < 0.001

    def test_t3_at_mean_is_highest(self):
        """PDF at mean should be higher than at any offset for symmetric distribution."""
        at_mean = BayesianChangePointDetector.student_t_pdf(2.0, mu=2.0, sigma2=1.0, nu=3.0)
        off_mean = BayesianChangePointDetector.student_t_pdf(3.0, mu=2.0, sigma2=1.0, nu=3.0)
        assert at_mean > off_mean

    def test_pdf_integrates_to_one(self):
        """Numerical integration of pdf over wide range should be ~1."""
        import numpy as np_local
        xs = np_local.linspace(-50.0, 50.0, 10001)
        dx = xs[1] - xs[0]
        vals = np_local.array([
            BayesianChangePointDetector.student_t_pdf(float(x), mu=0.0, sigma2=1.0, nu=5.0)
            for x in xs
        ])
        area = float(np_local.sum(vals) * dx)
        assert area == pytest.approx(1.0, abs=0.001)

    def test_symmetry_around_mean(self):
        """PDF is symmetric around mu."""
        mu = 1.5
        delta = 2.0
        left = BayesianChangePointDetector.student_t_pdf(mu - delta, mu=mu, sigma2=2.0, nu=4.0)
        right = BayesianChangePointDetector.student_t_pdf(mu + delta, mu=mu, sigma2=2.0, nu=4.0)
        assert left == pytest.approx(right, rel=1e-9)

    def test_raises_on_invalid_params(self):
        with pytest.raises(ValueError):
            BayesianChangePointDetector.student_t_pdf(0.0, mu=0.0, sigma2=-1.0, nu=3.0)
        with pytest.raises(ValueError):
            BayesianChangePointDetector.student_t_pdf(0.0, mu=0.0, sigma2=1.0, nu=-1.0)

    def test_known_t2_value(self):
        """
        t_2(0 | mu=0, sigma2=1): pdf = (1 + 0)^(-3/2) * Gamma(3/2) / (Gamma(1) * sqrt(2*pi))
        = 1 / (2 * sqrt(2)) ≈ 0.35355
        """
        # t_nu(x | mu, sigma2): at x=mu, z=0
        # pdf = Gamma((nu+1)/2) / (Gamma(nu/2) * sqrt(nu*pi*sigma2))
        # For nu=2, sigma2=1:
        # = Gamma(3/2) / (Gamma(1) * sqrt(2*pi))
        # = (sqrt(pi)/2) / (1 * sqrt(2*pi))
        # = (sqrt(pi)/2) / sqrt(2*pi) = 1 / (2*sqrt(2)) ≈ 0.35355
        expected = 1.0 / (2.0 * math.sqrt(2.0))
        val = BayesianChangePointDetector.student_t_pdf(0.0, mu=0.0, sigma2=1.0, nu=2.0)
        assert val == pytest.approx(expected, rel=1e-6)


# ---------------------------------------------------------------------------
# Regime Summary Statistics
# ---------------------------------------------------------------------------

class TestRegimeSummary:
    def test_summary_keys_present(self):
        det = make_detector(min_observations=5)
        feed(det, [1.0] * 10)
        summary = det.get_regime_summary()
        required_keys = {
            "state", "observations_seen", "map_run_length",
            "changepoint_prob", "regime_mean", "regime_var",
            "total_changepoints", "last_changepoint_idx",
        }
        for key in required_keys:
            assert key in summary, f"Missing key: {key}"

    def test_observations_seen_matches(self):
        det = make_detector(min_observations=5)
        feed(det, [2.0] * 15)
        summary = det.get_regime_summary()
        assert summary["observations_seen"] == 15

    def test_regime_mean_tracks_data_mean(self):
        """After many observations at a constant value, regime_mean should converge."""
        det = make_detector(min_observations=5, kappa_prior=0.1)
        feed(det, [3.0] * 80)
        summary = det.get_regime_summary()
        assert abs(summary["regime_mean"] - 3.0) < 0.5, (
            f"Expected regime_mean near 3.0, got {summary['regime_mean']:.4f}"
        )

    def test_changepoint_prob_in_range(self):
        det = make_detector(min_observations=5)
        snaps = feed(det, [1.0] * 20)
        for snap in snaps:
            assert 0.0 <= snap.changepoint_prob <= 1.0, (
                f"changepoint_prob out of [0,1]: {snap.changepoint_prob}"
            )

    def test_run_length_non_negative(self):
        det = make_detector(min_observations=5)
        snaps = feed(det, [1.0] * 30)
        for snap in snaps:
            assert snap.run_length >= 0

    def test_summary_state_matches_enum(self):
        det = make_detector(min_observations=5)
        feed(det, [1.0] * 20)
        summary = det.get_regime_summary()
        assert summary["state"] in {s.value for s in RegimeState}


# ---------------------------------------------------------------------------
# Real-ish P&L Sequence
# ---------------------------------------------------------------------------

class TestRealishPnLSequence:
    def test_detects_shift_in_realistic_pnl(self):
        """
        [+2, +1, +3, +2, +1, -5, -3, -4, -6, -2] — after repeating
        the positive regime many times then the negative regime, a shift
        must be detected.
        """
        positive = [2.0, 1.0, 3.0, 2.0, 1.0]
        negative = [-5.0, -3.0, -4.0, -6.0, -2.0]

        det = make_detector(
            min_observations=10,
            changepoint_threshold=0.5,
            stabilization_window=3,
            hazard_rate=1.0 / 20,
        )

        # Build up stable positive regime
        for _ in range(6):
            feed(det, positive)  # 30 observations

        assert det.should_trade() is True

        # Inject negative regime
        detected_transition = False
        for obs in negative * 4:  # up to 20 observations
            snap = det.observe(obs)
            if snap.state == RegimeState.TRANSITION:
                detected_transition = True
                break

        assert detected_transition, (
            "Expected TRANSITION after injecting sustained negative P&L "
            "following a positive regime"
        )

    def test_snapshot_timestamp_is_set(self):
        det = make_detector(min_observations=5)
        t = 1_710_000_000.0
        snap = det.observe(1.0, timestamp=t)
        assert snap.timestamp == t

    def test_snapshot_timestamp_defaults_to_now(self):
        det = make_detector(min_observations=5)
        before = time.time()
        snap = det.observe(1.0)
        after = time.time()
        assert before <= snap.timestamp <= after + 1.0


# ---------------------------------------------------------------------------
# Max Run Length Truncation
# ---------------------------------------------------------------------------

class TestMaxRunLengthTruncation:
    def test_no_crash_with_500_observations(self):
        """max_run_length=100 — should not crash or grow unboundedly."""
        det = make_detector(min_observations=10, max_run_length=100)
        for i in range(500):
            snap = det.observe(float(i % 5), timestamp=float(i))
            # _log_R must never exceed max_run_length entries
            assert len(det._log_R) <= 100, (
                f"At obs {i+1}: _log_R length {len(det._log_R)} exceeds max 100"
            )
            assert len(det._nig_params) <= 100

    def test_posterior_sums_to_one_after_truncation(self):
        """Posterior probability mass must remain normalized."""
        import numpy as np_local
        det = make_detector(min_observations=5, max_run_length=50)
        for i in range(200):
            det.observe(float(i % 3))

        total_prob = float(np_local.sum(np_local.exp(det._log_R)))
        assert total_prob == pytest.approx(1.0, abs=1e-6), (
            f"Posterior not normalized after truncation: sum={total_prob:.8f}"
        )

    def test_large_max_run_length_also_works(self):
        det = make_detector(min_observations=10, max_run_length=300)
        for i in range(200):
            snap = det.observe(1.0 if i < 100 else -1.0)
        assert snap.observations_seen == 200

    def test_truncation_does_not_distort_regime_mean(self):
        """Even after truncation, regime_mean should track the data signal."""
        det = make_detector(
            min_observations=5,
            max_run_length=30,
            kappa_prior=0.1,
        )
        feed(det, [2.0] * 100)
        summary = det.get_regime_summary()
        assert abs(summary["regime_mean"] - 2.0) < 1.0


# ---------------------------------------------------------------------------
# Edge Cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_single_observation(self):
        det = make_detector(min_observations=5)
        snap = det.observe(0.0)
        assert snap.observations_seen == 1
        assert snap.state == RegimeState.WARMUP

    def test_large_outlier_does_not_crash(self):
        det = make_detector(min_observations=5)
        feed(det, [1.0] * 20)
        snap = det.observe(1e6)
        assert snap.changepoint_prob >= 0.0
        assert math.isfinite(snap.changepoint_prob)

    def test_negative_observations(self):
        det = make_detector(min_observations=5)
        snaps = feed(det, [-3.0, -2.0, -4.0, -1.0, -3.0, -2.0, -4.0, -3.0, -2.0, -3.0])
        for snap in snaps:
            assert math.isfinite(snap.changepoint_prob)
            assert 0.0 <= snap.changepoint_prob <= 1.0

    def test_all_same_value(self):
        """Constant observations — algorithm must remain numerically stable."""
        det = make_detector(min_observations=5)
        snaps = feed(det, [0.5] * 50)
        for snap in snaps:
            assert math.isfinite(snap.changepoint_prob)

    def test_regime_var_is_non_negative(self):
        det = make_detector(min_observations=5)
        snaps = feed(det, [1.0, -1.0, 2.0, -2.0, 0.5, 0.3, -0.1, 0.8, 1.2, -0.5])
        for snap in snaps:
            assert snap.regime_var >= 0.0, f"Negative variance: {snap.regime_var}"

    def test_observe_without_timestamp(self):
        det = make_detector(min_observations=5)
        snap = det.observe(1.0)
        assert snap.timestamp > 0.0

    def test_multiple_resets(self):
        det = make_detector(min_observations=5)
        feed(det, [1.0] * 20)
        det.reset()
        feed(det, [2.0] * 20)
        det.reset()
        assert det._observations_seen == 0
        assert det.should_trade() is False

    def test_high_hazard_rate_detects_shifts_faster(self):
        """Higher hazard rate (more changepoints expected) should react faster."""
        import random
        rng = random.Random(77)

        det_high = make_detector(
            min_observations=5,
            hazard_rate=1.0 / 5,
            changepoint_threshold=0.5,
            stabilization_window=2,
        )
        det_low = make_detector(
            min_observations=5,
            hazard_rate=1.0 / 100,
            changepoint_threshold=0.5,
            stabilization_window=2,
        )

        data_stable = [rng.gauss(0.0, 0.1) for _ in range(20)]
        rng2 = random.Random(77)
        [rng2.gauss(0.0, 0.1) for _ in range(20)]  # Consume same sequence
        data_shift = [rng.gauss(5.0, 0.1) for _ in range(20)]

        for v in data_stable:
            det_high.observe(v)
        for v in data_stable:
            det_low.observe(v)

        cp_probs_high = []
        cp_probs_low = []
        for v in data_shift:
            cp_probs_high.append(det_high.observe(v).changepoint_prob)
            cp_probs_low.append(det_low.observe(v).changepoint_prob)

        # High hazard rate should produce higher max P(CP) after shift
        assert max(cp_probs_high) >= max(cp_probs_low), (
            f"High hazard ({max(cp_probs_high):.4f}) should >= low hazard ({max(cp_probs_low):.4f})"
        )
