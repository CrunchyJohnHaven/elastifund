"""
Tests for bot/lmsr_engine.py — LMSR Bayesian Engine.

Covers: cost function, price function (softmax), Bayesian updater,
Kelly sizing, liquidity estimation, and signal generation.
"""

import math
import pytest
import sys
from pathlib import Path

# Ensure bot/ is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from lmsr_engine import (
    lmsr_cost,
    lmsr_prices,
    lmsr_trade_cost,
    lmsr_max_loss,
    _logsumexp,
    estimate_b_from_spread,
    estimate_b_from_volume,
    BayesianUpdater,
    compute_ev,
    kelly_fraction,
    LMSREngine,
    MAX_KELLY_FRACTION_FAST,
    MAX_KELLY_FRACTION_SLOW,
)


# ===== LMSR Cost Function =====

class TestLMSRCost:
    def test_equal_quantities_binary(self):
        """C([0,0], b) = b * ln(2)"""
        b = 100_000
        cost = lmsr_cost([0, 0], b)
        expected = b * math.log(2)
        assert abs(cost - expected) < 0.01

    def test_cost_increases_with_quantity(self):
        c1 = lmsr_cost([100, 100], 1000)
        c2 = lmsr_cost([200, 100], 1000)
        assert c2 > c1

    def test_shift_invariance(self):
        """Adding constant k to all q shifts cost by k."""
        b = 1000
        c1 = lmsr_cost([100, 200], b)
        c2 = lmsr_cost([200, 300], b)
        assert abs(c2 - c1 - 100) < 0.01

    def test_large_quantities_stable(self):
        """logsumexp prevents overflow on large quantities."""
        b = 100
        cost = lmsr_cost([10000, 9000], b)
        assert math.isfinite(cost)

    def test_negative_quantities(self):
        """Negative quantities (net selling) should work."""
        cost = lmsr_cost([-50, 50], 100)
        assert math.isfinite(cost)


# ===== LMSR Price Function (Softmax) =====

class TestLMSRPrices:
    def test_equal_quantities_50_50(self):
        prices = lmsr_prices([0, 0], 1000)
        assert abs(prices[0] - 0.5) < 1e-6
        assert abs(prices[1] - 0.5) < 1e-6

    def test_prices_sum_to_one(self):
        for q in [[100, 200], [500, 100, 300], [0, 0, 0, 0]]:
            prices = lmsr_prices(q, 1000)
            assert abs(sum(prices) - 1.0) < 1e-10

    def test_all_positive(self):
        prices = lmsr_prices([1000, 0], 100)
        for p in prices:
            assert p > 0

    def test_higher_quantity_higher_price(self):
        prices = lmsr_prices([200, 100], 1000)
        assert prices[0] > prices[1]

    def test_larger_b_tighter_spread(self):
        tight = lmsr_prices([100, 200], 10000)
        wide = lmsr_prices([100, 200], 100)
        assert abs(tight[0] - tight[1]) < abs(wide[0] - wide[1])

    def test_three_outcomes(self):
        prices = lmsr_prices([0, 0, 0], 1000)
        assert len(prices) == 3
        for p in prices:
            assert abs(p - 1/3) < 1e-6


# ===== LMSR Trade Cost =====

class TestLMSRTradeCost:
    def test_buy_positive_cost(self):
        cost = lmsr_trade_cost([100, 100], 1000, 0, 10)
        assert cost > 0

    def test_sell_negative_cost(self):
        cost = lmsr_trade_cost([100, 100], 1000, 0, -10)
        assert cost < 0

    def test_zero_trade_zero_cost(self):
        cost = lmsr_trade_cost([100, 100], 1000, 0, 0)
        assert abs(cost) < 1e-10

    def test_small_trade_approx_price_times_delta(self):
        """For small delta, cost ≈ price * delta."""
        b = 100_000
        q = [0, 0]
        delta = 1
        cost = lmsr_trade_cost(q, b, 0, delta)
        price = lmsr_prices(q, b)[0]
        assert abs(cost - price * delta) < 0.01


# ===== LMSR Max Loss =====

class TestMaxLoss:
    def test_binary_known_value(self):
        """b=100000, n=2: Lmax = 100000 * ln(2) ≈ 69314.72"""
        loss = lmsr_max_loss(100_000, 2)
        assert abs(loss - 69_314.72) < 1.0

    def test_more_outcomes_more_loss(self):
        assert lmsr_max_loss(1000, 3) > lmsr_max_loss(1000, 2)
        assert lmsr_max_loss(1000, 10) > lmsr_max_loss(1000, 3)


# ===== logsumexp =====

class TestLogSumExp:
    def test_basic(self):
        result = _logsumexp([0, 0])
        assert abs(result - math.log(2)) < 1e-10

    def test_large_values(self):
        """Should not overflow."""
        result = _logsumexp([1000, 999])
        assert math.isfinite(result)
        assert result > 999

    def test_empty(self):
        result = _logsumexp([])
        assert result == float('-inf')

    def test_single(self):
        assert abs(_logsumexp([5.0]) - 5.0) < 1e-10


# ===== Liquidity Estimation =====

class TestLiquidityEstimation:
    def test_tighter_spread_larger_b(self):
        b_tight = estimate_b_from_spread(0.49, 0.51)
        b_wide = estimate_b_from_spread(0.40, 0.60)
        assert b_tight > b_wide

    def test_invalid_spread(self):
        from lmsr_engine import DEFAULT_B
        assert estimate_b_from_spread(0.5, 0.5) == DEFAULT_B
        assert estimate_b_from_spread(0.6, 0.4) == DEFAULT_B

    def test_volume_based(self):
        b_high = estimate_b_from_volume(100_000)
        b_low = estimate_b_from_volume(1_000)
        assert b_high > b_low

    def test_zero_volume(self):
        from lmsr_engine import DEFAULT_B
        assert estimate_b_from_volume(0) == DEFAULT_B


# ===== Bayesian Updater =====

class TestBayesianUpdater:
    def test_uniform_prior(self):
        u = BayesianUpdater([0.5, 0.5])
        post = u.get_posterior()
        assert abs(post[0] - 0.5) < 1e-6
        assert abs(post[1] - 0.5) < 1e-6

    def test_update_shifts_toward_evidence(self):
        u = BayesianUpdater([0.5, 0.5])
        u.update(0, 10.0, 0.7)  # Trade on outcome 0 at high price
        post = u.get_posterior()
        assert post[0] > 0.5, "Evidence for outcome 0 should increase its probability"

    def test_opposing_evidence(self):
        u = BayesianUpdater([0.5, 0.5])
        u.update(0, 10.0, 0.7)
        post1 = u.get_posterior()
        u.update(1, 20.0, 0.8)  # Stronger evidence for outcome 1
        post2 = u.get_posterior()
        assert post2[1] > post1[1], "Stronger opposing evidence should shift posterior"

    def test_posterior_sums_to_one(self):
        u = BayesianUpdater([0.3, 0.7])
        for _ in range(10):
            u.update(0, 5.0, 0.6)
        post = u.get_posterior()
        assert abs(sum(post) - 1.0) < 1e-10

    def test_many_updates_stable(self):
        u = BayesianUpdater([0.5, 0.5])
        for _ in range(100):
            u.update(0, 1.0, 0.55)
        post = u.get_posterior()
        assert all(math.isfinite(p) for p in post)
        assert all(0 < p < 1 for p in post)

    def test_prior_strength(self):
        """Stronger prior = slower updating."""
        weak = BayesianUpdater([0.5, 0.5], prior_strength=1.0)
        strong = BayesianUpdater([0.5, 0.5], prior_strength=50.0)
        weak.update(0, 10.0, 0.7)
        strong.update(0, 10.0, 0.7)
        # Weak prior should shift more
        assert weak.get_posterior()[0] > strong.get_posterior()[0]

    def test_invalid_outcome_ignored(self):
        u = BayesianUpdater([0.5, 0.5])
        post_before = u.get_posterior()
        u.update(5, 10.0, 0.7)  # Invalid index
        post_after = u.get_posterior()
        assert post_before == post_after


# ===== Position Sizing =====

class TestPositionSizing:
    def test_ev_formula(self):
        assert abs(compute_ev(0.55, 0.45) - 0.10) < 1e-10
        assert abs(compute_ev(0.40, 0.60) - (-0.20)) < 1e-10

    def test_negative_ev_zero_kelly(self):
        f = kelly_fraction(-0.05, 0.5, fast_market=True)
        assert f == 0.0

    def test_fast_market_cap(self):
        """1/16 Kelly cap on fast markets."""
        f = kelly_fraction(0.50, 0.3, fast_market=True)
        assert f <= MAX_KELLY_FRACTION_FAST + 1e-9

    def test_slow_market_cap(self):
        """Quarter-Kelly cap on slow markets."""
        f = kelly_fraction(0.50, 0.3, fast_market=False)
        assert f <= MAX_KELLY_FRACTION_SLOW + 1e-9

    def test_fee_reduces_kelly(self):
        f_no_fee = kelly_fraction(0.10, 0.5, fast_market=False, taker_fee=0.0)
        f_with_fee = kelly_fraction(0.10, 0.5, fast_market=False, taker_fee=0.05)
        assert f_with_fee < f_no_fee

    def test_fee_kills_edge(self):
        """Fee > EV → zero Kelly."""
        f = kelly_fraction(0.03, 0.5, fast_market=True, taker_fee=0.05)
        assert f == 0.0

    def test_edge_cases(self):
        assert kelly_fraction(0.10, 0.0, fast_market=True) == 0.0
        assert kelly_fraction(0.10, 1.0, fast_market=True) == 0.0


# ===== LMSREngine Integration =====

class TestLMSREngine:
    def test_init(self):
        engine = LMSREngine()
        assert engine.entry_threshold == 0.05
        assert len(engine.markets) == 0

    def test_get_signal_no_trades(self):
        """No trades → no signal."""
        engine = LMSREngine()
        market = {"id": "test-1", "question": "Test market?", "outcomePrices": "[0.5, 0.5]"}
        # With no trades fetched, should return None
        signal = engine.compute_signal(
            engine._get_or_create_state("test-1", "Test market?", 0.5),
            0.5
        )
        assert signal is None  # Not enough trades

    def test_timing_stats_empty(self):
        engine = LMSREngine()
        stats = engine.get_timing_stats()
        assert stats["cycles"] == 0
        assert stats["avg_ms"] == 0

    def test_cleanup_stale(self):
        engine = LMSREngine()
        state = engine._get_or_create_state("stale-1", "Stale", 0.5)
        state.created_at = 0  # Very old
        assert "stale-1" in engine.markets
        engine.cleanup_stale(max_age_seconds=1)
        assert "stale-1" not in engine.markets

    def test_reset_market(self):
        engine = LMSREngine()
        engine._get_or_create_state("m1", "Market 1", 0.5)
        assert "m1" in engine.markets
        engine.reset_market("m1")
        assert "m1" not in engine.markets

    def test_signal_output_format(self):
        """Verify signal dict has all required fields for jj_live.py."""
        engine = LMSREngine(entry_threshold=0.01)
        state = engine._get_or_create_state("test-fmt", "Format test?", 0.5)
        updater = engine.updaters["test-fmt"]

        # Simulate many trades pushing posterior away from 0.5
        for _ in range(20):
            updater.update(0, 10.0, 0.75)
            state.trades_processed += 1

        signal = engine.compute_signal(state, 0.40)
        assert signal is not None

        required_keys = [
            "market_id", "question", "direction", "market_price",
            "estimated_prob", "edge", "confidence", "reasoning",
            "source", "taker_fee", "category", "resolution_hours",
            "velocity_score", "kelly_fraction",
        ]
        for key in required_keys:
            assert key in signal, f"Missing key: {key}"

        assert signal["source"] == "lmsr"
        assert signal["direction"] in ("buy_yes", "buy_no")
        assert 0 < signal["confidence"] < 1
        assert signal["edge"] > 0
