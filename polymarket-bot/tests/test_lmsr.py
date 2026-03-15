"""Tests for LMSR pricing and inefficiency detection module."""
import os
import math
import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///test.db")
os.environ.setdefault("POLYMARKET_PRIVATE_KEY", "test")
os.environ.setdefault("POLYMARKET_FUNDER_ADDRESS", "test")

from src.lmsr import (
    lmsr_cost,
    lmsr_prices,
    lmsr_trade_cost,
    lmsr_max_loss,
    lmsr_implied_quantities,
    detect_inefficiency,
    estimate_slippage,
)


class TestLMSRCost:
    """Tests for the LMSR cost function C(q) = b * ln(sum(e^(qi/b)))."""

    def test_equal_quantities_binary(self):
        """Equal quantities → cost = b * ln(2) for binary market."""
        b = 100_000
        cost = lmsr_cost([0, 0], b)
        expected = b * math.log(2)
        assert abs(cost - expected) < 0.01

    def test_cost_increases_with_quantity(self):
        """Adding to one outcome increases cost."""
        b = 1000
        c1 = lmsr_cost([100, 100], b)
        c2 = lmsr_cost([200, 100], b)
        assert c2 > c1

    def test_cost_shift_invariance(self):
        """Adding constant to all quantities shifts cost by b*constant/b = constant."""
        b = 1000
        c1 = lmsr_cost([100, 200], b)
        c2 = lmsr_cost([200, 300], b)
        # Shift by 100: cost increases by 100 (since shift adds b*ln(e^(shift/b)) uniformly)
        assert abs(c2 - c1 - 100) < 0.01

    def test_invalid_b_raises(self):
        """b <= 0 should raise ValueError."""
        with pytest.raises(ValueError):
            lmsr_cost([100, 100], 0)
        with pytest.raises(ValueError):
            lmsr_cost([100, 100], -1)

    def test_large_quantities_stable(self):
        """Should not overflow with large quantities (logsumexp trick)."""
        b = 100
        cost = lmsr_cost([10000, 9000], b)
        assert math.isfinite(cost)


class TestLMSRPrices:
    """Tests for the LMSR price function (softmax)."""

    def test_equal_quantities_equal_prices(self):
        """Equal quantities → equal prices (50/50 for binary)."""
        prices = lmsr_prices([0, 0], 1000)
        assert abs(prices[0] - 0.5) < 0.001
        assert abs(prices[1] - 0.5) < 0.001

    def test_prices_sum_to_one(self):
        """Prices must always sum to 1.0."""
        for q in [[100, 200], [500, 100, 300], [0, 0, 0, 0]]:
            prices = lmsr_prices(q, 1000)
            assert abs(sum(prices) - 1.0) < 1e-10

    def test_prices_in_unit_interval(self):
        """All prices must be in (0, 1)."""
        prices = lmsr_prices([1000, 0], 100)
        for p in prices:
            assert 0 < p < 1

    def test_higher_quantity_higher_price(self):
        """Outcome with more shares outstanding has higher price."""
        prices = lmsr_prices([200, 100], 1000)
        assert prices[0] > prices[1]

    def test_b_affects_spread(self):
        """Larger b → tighter spread (prices closer to each other)."""
        prices_tight = lmsr_prices([100, 200], 10000)
        prices_wide = lmsr_prices([100, 200], 100)
        spread_tight = abs(prices_tight[0] - prices_tight[1])
        spread_wide = abs(prices_wide[0] - prices_wide[1])
        assert spread_tight < spread_wide

    def test_three_outcomes(self):
        """Should work for n > 2 outcomes."""
        prices = lmsr_prices([100, 100, 100], 1000)
        assert len(prices) == 3
        for p in prices:
            assert abs(p - 1/3) < 0.001


class TestLMSRTradeCost:
    """Tests for trade cost calculation."""

    def test_buy_positive_cost(self):
        """Buying shares costs money (positive cost)."""
        cost = lmsr_trade_cost([100, 100], 0, 10, 1000)
        assert cost > 0

    def test_sell_negative_cost(self):
        """Selling shares returns money (negative cost)."""
        cost = lmsr_trade_cost([100, 100], 0, -10, 1000)
        assert cost < 0

    def test_zero_trade_zero_cost(self):
        """Zero delta → zero cost."""
        cost = lmsr_trade_cost([100, 100], 0, 0, 1000)
        assert abs(cost) < 1e-10

    def test_cost_approximates_price_times_delta(self):
        """For small trades, cost ≈ price * delta."""
        b = 100_000
        q = [0, 0]
        delta = 1  # very small trade
        cost = lmsr_trade_cost(q, 0, delta, b)
        price = lmsr_prices(q, b)[0]
        assert abs(cost - price * delta) < 0.01


class TestLMSRMaxLoss:
    """Tests for maximum market maker loss."""

    def test_binary_known_value(self):
        """b=100,000, n=2: L_max = 100,000 * ln(2) ≈ 69,315."""
        loss = lmsr_max_loss(100_000, 2)
        assert abs(loss - 69_314.72) < 1.0

    def test_more_outcomes_more_loss(self):
        """More outcomes → higher max loss."""
        loss2 = lmsr_max_loss(1000, 2)
        loss3 = lmsr_max_loss(1000, 3)
        loss10 = lmsr_max_loss(1000, 10)
        assert loss3 > loss2
        assert loss10 > loss3


class TestInefficiencyDetection:
    """Tests for LMSR vs CLOB divergence detection."""

    def test_no_inefficiency_balanced(self):
        """Equal volumes → LMSR price = 50%, near 50% CLOB → no signal."""
        signal = detect_inefficiency(
            market_id="test_001",
            clob_price_yes=0.50,
            volume_yes=10000,
            volume_no=10000,
        )
        assert not signal.is_inefficient
        assert signal.direction == "hold"

    def test_inefficiency_detected(self):
        """Large volume imbalance vs CLOB price → inefficiency."""
        signal = detect_inefficiency(
            market_id="test_002",
            clob_price_yes=0.50,
            volume_yes=50000,
            volume_no=10000,
            b=10000,
            min_divergence=0.03,
        )
        # LMSR should price YES much higher than 50% due to volume imbalance
        assert signal.lmsr_price_yes > 0.50
        if signal.abs_divergence >= 0.03:
            assert signal.is_inefficient
            assert signal.direction == "buy_yes"

    def test_signal_fields_populated(self):
        """All fields should be populated."""
        signal = detect_inefficiency(
            market_id="test_003",
            clob_price_yes=0.60,
            volume_yes=1000,
            volume_no=1000,
        )
        assert signal.market_id == "test_003"
        assert 0 < signal.lmsr_price_yes < 1
        assert signal.clob_price_yes == 0.60
        assert signal.lmsr_b == 100_000

    def test_min_divergence_parameter(self):
        """Higher min_divergence → fewer signals."""
        signal_low = detect_inefficiency(
            market_id="t", clob_price_yes=0.50,
            volume_yes=20000, volume_no=10000,
            b=10000, min_divergence=0.01,
        )
        signal_high = detect_inefficiency(
            market_id="t", clob_price_yes=0.50,
            volume_yes=20000, volume_no=10000,
            b=10000, min_divergence=0.50,
        )
        # High threshold should be harder to trigger
        if signal_low.is_inefficient:
            assert not signal_high.is_inefficient or signal_high.abs_divergence >= 0.50


class TestSlippage:
    """Tests for LMSR slippage estimation."""

    def test_zero_trade_zero_slippage(self):
        """Zero trade size → zero slippage."""
        slip = estimate_slippage([100, 100], 0, 0, 1000)
        assert slip == 0.0

    def test_small_trade_small_slippage(self):
        """Small trade → small slippage."""
        slip = estimate_slippage([1000, 1000], 0, 1.0, 100_000)
        assert slip < 0.01  # Less than 1% slippage for tiny trade

    def test_larger_trade_more_slippage(self):
        """Larger trade → more slippage."""
        slip_small = estimate_slippage([1000, 1000], 0, 10.0, 10_000)
        slip_large = estimate_slippage([1000, 1000], 0, 1000.0, 10_000)
        assert slip_large >= slip_small

    def test_higher_b_less_slippage(self):
        """Higher b (more liquidity) → less slippage."""
        slip_low_b = estimate_slippage([1000, 1000], 0, 100.0, 1_000)
        slip_high_b = estimate_slippage([1000, 1000], 0, 100.0, 100_000)
        assert slip_high_b <= slip_low_b
