"""Tests for bot/lmsr_engine.py — LMSR Bayesian pricing engine."""

import math
import pytest
from unittest.mock import patch, MagicMock

from bot.lmsr_engine import (
    _logsumexp,
    lmsr_cost,
    lmsr_prices,
    lmsr_trade_cost,
    lmsr_max_loss,
    estimate_b_from_spread,
    estimate_b_from_volume,
    BayesianUpdater,
    compute_ev,
    kelly_fraction,
    LMSREngine,
    LMSRState,
    MAX_KELLY_FRACTION_FAST,
    MAX_KELLY_FRACTION_SLOW,
    DEFAULT_B,
    MIN_B,
    MAX_B,
)


class TestLogsumexp:
    def test_empty(self):
        assert _logsumexp([]) == float('-inf')

    def test_single(self):
        assert abs(_logsumexp([2.0]) - 2.0) < 1e-10

    def test_equal_values(self):
        result = _logsumexp([1.0, 1.0])
        expected = 1.0 + math.log(2)
        assert abs(result - expected) < 1e-10

    def test_large_values_stable(self):
        result = _logsumexp([1000.0, 1001.0])
        assert math.isfinite(result)


class TestLMSRPrices:
    def test_equal_quantities(self):
        prices = lmsr_prices([0.0, 0.0], 100.0)
        assert abs(prices[0] - 0.5) < 1e-6
        assert abs(prices[1] - 0.5) < 1e-6

    def test_sum_to_one(self):
        prices = lmsr_prices([30.0, 10.0], 50.0)
        assert abs(sum(prices) - 1.0) < 1e-6

    def test_buying_increases_price(self):
        prices_before = lmsr_prices([0.0, 0.0], 100.0)
        prices_after = lmsr_prices([50.0, 0.0], 100.0)
        assert prices_after[0] > prices_before[0]


class TestLMSRCost:
    def test_zero_quantities(self):
        cost = lmsr_cost([0.0, 0.0], 100.0)
        expected = 100.0 * math.log(2)
        assert abs(cost - expected) < 1e-6

    def test_trade_cost_positive(self):
        cost = lmsr_trade_cost([0.0, 0.0], 100.0, 0, 10.0)
        assert cost > 0

    def test_max_loss(self):
        ml = lmsr_max_loss(100.0, 2)
        assert abs(ml - 100.0 * math.log(2)) < 1e-6


class TestLiquidityEstimation:
    def test_spread_zero(self):
        assert estimate_b_from_spread(0.5, 0.5) == DEFAULT_B

    def test_spread_negative(self):
        assert estimate_b_from_spread(0.6, 0.4) == DEFAULT_B

    def test_narrow_spread_high_b(self):
        b = estimate_b_from_spread(0.49, 0.51)
        assert b > estimate_b_from_spread(0.40, 0.60)

    def test_b_clamped_min(self):
        b = estimate_b_from_spread(0.01, 0.99)
        assert b >= MIN_B

    def test_volume_zero(self):
        assert estimate_b_from_volume(0) == DEFAULT_B

    def test_volume_positive(self):
        b = estimate_b_from_volume(10000)
        assert b == 1000.0

    def test_volume_clamped(self):
        b = estimate_b_from_volume(1e12)
        assert b <= MAX_B


class TestBayesianUpdater:
    def test_uniform_prior(self):
        u = BayesianUpdater([0.5, 0.5])
        post = u.get_posterior()
        assert abs(post[0] - 0.5) < 1e-6

    def test_yes_trade_increases_yes(self):
        u = BayesianUpdater([0.5, 0.5])
        u.update(0, 10.0, 0.6)
        post = u.get_posterior()
        assert post[0] > 0.5

    def test_no_trade_increases_no(self):
        u = BayesianUpdater([0.5, 0.5])
        u.update(1, 10.0, 0.7)
        post = u.get_posterior()
        assert post[1] > 0.5

    def test_posterior_sums_to_one(self):
        u = BayesianUpdater([0.5, 0.5])
        u.update(0, 5.0, 0.55)
        u.update(1, 3.0, 0.60)
        u.update(0, 8.0, 0.70)
        post = u.get_posterior()
        assert abs(sum(post) - 1.0) < 1e-6

    def test_invalid_outcome_ignored(self):
        u = BayesianUpdater([0.5, 0.5])
        post_before = u.get_posterior()
        u.update(5, 10.0, 0.6)  # Invalid index
        post_after = u.get_posterior()
        assert post_before == post_after

    def test_n_updates_tracked(self):
        u = BayesianUpdater([0.5, 0.5])
        u.update(0, 1.0, 0.5)
        u.update(1, 1.0, 0.5)
        assert u.n_updates == 2


class TestKellySizing:
    def test_positive_ev(self):
        ev = compute_ev(0.55, 0.45)
        assert ev == pytest.approx(0.10)

    def test_negative_ev_returns_zero(self):
        f = kelly_fraction(-0.05, 0.50)
        assert f == 0.0

    def test_fast_market_capped(self):
        f = kelly_fraction(0.30, 0.40, fast_market=True)
        assert f <= MAX_KELLY_FRACTION_FAST + 1e-9

    def test_slow_market_capped(self):
        f = kelly_fraction(0.30, 0.40, fast_market=False)
        assert f <= MAX_KELLY_FRACTION_SLOW + 1e-9

    def test_zero_ev(self):
        f = kelly_fraction(0.0, 0.50)
        assert f == 0.0

    def test_fee_reduces_kelly(self):
        f_no_fee = kelly_fraction(0.10, 0.50, taker_fee=0.0)
        f_fee = kelly_fraction(0.10, 0.50, taker_fee=0.05)
        assert f_fee <= f_no_fee

    def test_edge_price_zero(self):
        assert kelly_fraction(0.10, 0.0) == 0.0

    def test_edge_price_one(self):
        assert kelly_fraction(0.10, 1.0) == 0.0


class TestLMSREngine:
    def test_init(self):
        engine = LMSREngine()
        assert engine.entry_threshold == 0.05
        assert len(engine.markets) == 0

    def test_get_or_create_state(self):
        engine = LMSREngine()
        state = engine._get_or_create_state("m1", "Test?", 0.5)
        assert state.market_id == "m1"
        assert "m1" in engine.updaters

    def test_get_or_create_idempotent(self):
        engine = LMSREngine()
        s1 = engine._get_or_create_state("m1", "Test?", 0.5)
        s2 = engine._get_or_create_state("m1", "Test?", 0.5)
        assert s1 is s2

    @patch.object(LMSREngine, "fetch_recent_trades", return_value=[])
    def test_get_signal_no_trades(self, mock_fetch):
        engine = LMSREngine()
        market = {"id": "m1", "question": "Test?", "outcomePrices": ["0.5", "0.5"]}
        signal = engine.get_signal(market)
        assert signal is None

    def test_get_signal_missing_prices(self):
        engine = LMSREngine()
        market = {"id": "m1", "question": "Test?"}
        signal = engine.get_signal(market)
        assert signal is None

    def test_reset_market(self):
        engine = LMSREngine()
        engine._get_or_create_state("m1", "Test?", 0.5)
        engine.reset_market("m1")
        assert "m1" not in engine.markets
        assert "m1" not in engine.updaters

    def test_cleanup_stale(self):
        engine = LMSREngine()
        state = engine._get_or_create_state("m1", "Test?", 0.5)
        state.created_at = 0  # Very old
        engine.cleanup_stale(max_age_seconds=1)
        assert "m1" not in engine.markets

    def test_get_timing_stats_empty(self):
        engine = LMSREngine()
        stats = engine.get_timing_stats()
        assert stats["cycles"] == 0

    def test_get_active_markets(self):
        engine = LMSREngine()
        engine._get_or_create_state("m1", "Test1?", 0.5)
        engine._get_or_create_state("m2", "Test2?", 0.5)
        assert set(engine.get_active_markets()) == {"m1", "m2"}

    def test_ingest_trades_updates_state(self):
        engine = LMSREngine()
        state = engine._get_or_create_state("m1", "Test?", 0.5, b=100.0)
        trades = [
            {"timestamp": "2026-03-14T12:00:01Z", "side": "BUY", "outcomeIndex": 0, "size": "10", "price": "0.55"},
            {"timestamp": "2026-03-14T12:00:02Z", "side": "BUY", "outcomeIndex": 1, "size": "5", "price": "0.45"},
        ]
        new = engine.ingest_trades(state, trades)
        assert new == 2
        assert state.trades_processed == 2

    def test_compute_signal_insufficient_trades(self):
        engine = LMSREngine()
        state = engine._get_or_create_state("m1", "Test?", 0.5)
        signal = engine.compute_signal(state, 0.5)
        assert signal is None
