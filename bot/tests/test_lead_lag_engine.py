#!/usr/bin/env python3
"""Tests for Semantic Lead-Lag Arbitrage Engine."""

import math
import time
import pytest
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from bot.lead_lag_engine import (
    MarketTimeSeries,
    LeadLagPair,
    LeadLagSignal,
    PairDirection,
    GrangerCausalityTest,
    LeadLagEngine,
    _f_pvalue_approx,
)


# ---------------------------------------------------------------------------
# MarketTimeSeries Tests
# ---------------------------------------------------------------------------

class TestMarketTimeSeries:
    def test_add_price(self):
        ts = MarketTimeSeries(market_id="m1", question="Test?")
        ts.add_price(1000.0, 0.50)
        assert ts.n_obs == 1
        assert ts.prices[-1] == 0.50
        assert ts.log_odds[-1] == pytest.approx(0.0, abs=0.01)

    def test_log_odds_transform_high(self):
        ts = MarketTimeSeries(market_id="m1", question="Test?")
        ts.add_price(1000.0, 0.80)
        # log(0.8/0.2) = log(4) ≈ 1.386
        assert ts.log_odds[-1] == pytest.approx(math.log(4), abs=0.01)

    def test_log_odds_transform_low(self):
        ts = MarketTimeSeries(market_id="m1", question="Test?")
        ts.add_price(1000.0, 0.20)
        # log(0.2/0.8) = log(0.25) ≈ -1.386
        assert ts.log_odds[-1] == pytest.approx(math.log(0.25), abs=0.01)

    def test_clamping_extremes(self):
        """Prices at 0 or 1 should be clamped to avoid log(0)."""
        ts = MarketTimeSeries(market_id="m1", question="Test?")
        ts.add_price(1000.0, 0.0)
        assert math.isfinite(ts.log_odds[-1])

        ts.add_price(1001.0, 1.0)
        assert math.isfinite(ts.log_odds[-1])

    def test_get_recent(self):
        ts = MarketTimeSeries(market_id="m1", question="Test?")
        for i in range(50):
            ts.add_price(float(i), 0.5 + (i % 10) * 0.01)

        timestamps, log_odds = ts.get_recent(10)
        assert len(timestamps) == 10
        assert len(log_odds) == 10


# ---------------------------------------------------------------------------
# LeadLagPair Tests
# ---------------------------------------------------------------------------

class TestLeadLagPair:
    def test_combined_score_no_semantic(self):
        pair = LeadLagPair(
            leader_id="l1", follower_id="f1",
            leader_question="L?", follower_question="F?",
            granger_p_value=0.001,
            semantic_valid=False,
        )
        pair.compute_combined_score()
        assert pair.combined_score == 0.0

    def test_combined_score_with_semantic(self):
        pair = LeadLagPair(
            leader_id="l1", follower_id="f1",
            leader_question="L?", follower_question="F?",
            granger_p_value=0.001,
            semantic_valid=True,
            semantic_confidence=0.8,
        )
        pair.compute_combined_score()
        assert pair.combined_score > 0.0

    def test_stronger_stat_higher_score(self):
        pair_strong = LeadLagPair(
            leader_id="l1", follower_id="f1",
            leader_question="L?", follower_question="F?",
            granger_p_value=0.0001,
            semantic_valid=True,
            semantic_confidence=0.8,
        )
        pair_weak = LeadLagPair(
            leader_id="l2", follower_id="f2",
            leader_question="L2?", follower_question="F2?",
            granger_p_value=0.04,
            semantic_valid=True,
            semantic_confidence=0.8,
        )
        pair_strong.compute_combined_score()
        pair_weak.compute_combined_score()
        assert pair_strong.combined_score > pair_weak.combined_score


# ---------------------------------------------------------------------------
# Granger Causality Tests
# ---------------------------------------------------------------------------

class TestGrangerCausality:
    def test_random_data_not_significant(self):
        """Random data should not show Granger causality."""
        import random
        random.seed(42)
        x = [random.gauss(0, 1) for _ in range(200)]
        y = [random.gauss(0, 1) for _ in range(200)]

        p_val, f_stat, lag = GrangerCausalityTest.test(x, y, max_lag=3)
        # Random data: p-value should be high (>0.05 most of the time)
        # Note: with random data there's a 5% chance of spurious significance
        # at any given lag, so we're lenient here
        assert p_val > 0.001  # At minimum, not extremely significant

    def test_causal_data_significant(self):
        """When x actually causes y (with lag), should detect it."""
        import random
        random.seed(42)
        n = 300
        x = [random.gauss(0, 1) for _ in range(n)]
        # y = 0.5 * x[t-1] + noise (x causes y with lag 1)
        y = [0.0] * n
        for t in range(1, n):
            y[t] = 0.5 * x[t-1] + random.gauss(0, 0.5)

        p_val, f_stat, lag = GrangerCausalityTest.test(x, y, max_lag=3)
        assert p_val < 0.05  # Should be significant
        assert lag == 1  # Should detect lag-1 causality

    def test_insufficient_data(self):
        """Very short series should return p=1 (not enough data)."""
        x = [0.1, 0.2, 0.3]
        y = [0.4, 0.5, 0.6]
        p_val, f_stat, lag = GrangerCausalityTest.test(x, y, max_lag=5)
        assert p_val == 1.0

    def test_reverse_direction(self):
        """Causality should be directional: x→y but not y→x."""
        import random
        random.seed(42)
        n = 300
        x = [random.gauss(0, 1) for _ in range(n)]
        y = [0.0] * n
        for t in range(1, n):
            y[t] = 0.6 * x[t-1] + random.gauss(0, 0.3)

        # x → y should be significant
        p_forward, _, _ = GrangerCausalityTest.test(x, y, max_lag=3)

        # y → x should not be significant (or much weaker)
        p_reverse, _, _ = GrangerCausalityTest.test(y, x, max_lag=3)

        assert p_forward < p_reverse  # Forward direction is stronger


class TestFPValueApprox:
    def test_zero_f_stat(self):
        assert _f_pvalue_approx(0.0, 2, 50) == 1.0

    def test_large_f_stat(self):
        p = _f_pvalue_approx(100.0, 2, 50)
        assert p < 0.01  # Should be very significant

    def test_moderate_f_stat(self):
        p = _f_pvalue_approx(3.0, 2, 50)
        assert 0.01 < p < 0.5  # Should be in moderate range


# ---------------------------------------------------------------------------
# LeadLagEngine Tests
# ---------------------------------------------------------------------------

class TestLeadLagEngine:
    def test_update_price(self):
        engine = LeadLagEngine()
        engine.update_price("m1", 1000.0, 0.50, "Market 1?")
        assert "m1" in engine._series
        assert engine._series["m1"].n_obs == 1

    def test_insufficient_data_no_pairs(self):
        """Scan with too few observations should return empty."""
        engine = LeadLagEngine()
        engine.update_price("m1", 1000.0, 0.50, "Market 1?")
        engine.update_price("m2", 1000.0, 0.60, "Market 2?")

        import asyncio
        pairs = asyncio.run(engine.scan_for_pairs())
        assert pairs == []

    def test_get_signals_empty(self):
        engine = LeadLagEngine()
        signals = engine.get_signals()
        assert signals == []

    def test_get_active_pairs_empty(self):
        engine = LeadLagEngine()
        assert engine.get_active_pairs() == []

    def test_get_status(self):
        engine = LeadLagEngine()
        engine.update_price("m1", 1000.0, 0.50, "Market 1?")
        status = engine.get_status()
        assert status["markets_tracked"] == 1
        assert status["active_pairs"] == 0

    def test_signal_generation_with_valid_pair(self):
        """Manually create a valid pair and verify signal generation."""
        engine = LeadLagEngine()

        # Feed enough price data — leader moves strongly, follower stays flat
        for i in range(30):
            # Leader moves from 0.30 to 0.70 (large log-odds shift)
            leader_price = 0.30 + i * 0.014
            engine.update_price("leader", float(i), leader_price, "Leader?")
            engine.update_price("follower", float(i), 0.50, "Follower?")

        # Manually inject a validated pair
        pair = LeadLagPair(
            leader_id="leader",
            follower_id="follower",
            leader_question="Leader?",
            follower_question="Follower?",
            granger_p_value=0.001,
            granger_f_stat=15.0,
            optimal_lag=1,
            semantic_valid=True,
            semantic_direction=PairDirection.ALIGNED,
            semantic_confidence=0.8,
            last_validated=time.time(),
        )
        pair.compute_combined_score()
        engine._pairs = [pair]

        signals = engine.get_signals()
        # Leader has moved significantly (30 * 0.005 = 0.15 in price, much more in log-odds)
        # Follower hasn't moved → should generate signal
        assert len(signals) > 0
        assert signals[0].follower_id == "follower"
        assert signals[0].direction == PairDirection.ALIGNED

    def test_pair_expiry(self):
        """Expired pairs should be deactivated."""
        engine = LeadLagEngine()

        for i in range(30):
            engine.update_price("leader", float(i), 0.50 + i * 0.005, "Leader?")
            engine.update_price("follower", float(i), 0.50, "Follower?")

        pair = LeadLagPair(
            leader_id="leader",
            follower_id="follower",
            leader_question="Leader?",
            follower_question="Follower?",
            granger_p_value=0.001,
            semantic_valid=True,
            semantic_direction=PairDirection.ALIGNED,
            semantic_confidence=0.8,
            last_validated=time.time() - 7200,  # 2 hours ago = expired
        )
        pair.compute_combined_score()
        engine._pairs = [pair]

        signals = engine.get_signals()
        # Pair should have been deactivated due to expiry
        assert not pair.active
