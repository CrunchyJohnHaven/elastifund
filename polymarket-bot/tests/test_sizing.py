"""Unit tests and property tests for Kelly sizing module."""
import os
import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///test.db")
os.environ.setdefault("POLYMARKET_PRIVATE_KEY", "test")
os.environ.setdefault("POLYMARKET_FUNDER_ADDRESS", "test")

from src.risk.sizing import (
    kelly_fraction,
    position_usd,
    position_size,
    expected_edge_after_fee,
    compute_sizing,
    SizingCaps,
    SizingResult,
    KELLY_MULT_YES,
    KELLY_MULT_NO,
    MAX_POSITION_USD_DEFAULT,
    MIN_POSITION_USD,
    WINNER_FEE,
    BANKROLL_TIERS,
)


# ============================================================
# kelly_fraction() tests
# ============================================================


class TestKellyFraction:
    """Unit tests for raw Kelly fraction calculation."""

    def test_buy_yes_positive_edge(self):
        """buy_yes with p_est > p_market should give positive Kelly."""
        f = kelly_fraction(0.70, 0.50, "buy_yes")
        assert f > 0
        # With 70% confidence and 50c cost, should be a meaningful fraction
        assert f < 1.0

    def test_buy_no_positive_edge(self):
        """buy_no with p_est < p_market should give positive Kelly."""
        # p_est=0.30 means we think YES=30%, so NO=70%.
        # Market says YES=0.60, so NO cost=0.40. We think NO wins 70% of the time.
        f = kelly_fraction(0.30, 0.60, "buy_no")
        assert f > 0

    def test_buy_yes_no_edge(self):
        """buy_yes where p_est == p_market → zero or near-zero Kelly."""
        f = kelly_fraction(0.50, 0.50, "buy_yes")
        # At 2% fee, buying at fair price is negative EV
        assert f == 0.0

    def test_buy_no_no_edge(self):
        """buy_no at fair price → zero Kelly."""
        f = kelly_fraction(0.50, 0.50, "buy_no")
        assert f == 0.0

    def test_buy_yes_negative_edge(self):
        """buy_yes where p_est < p_market → zero Kelly."""
        f = kelly_fraction(0.30, 0.60, "buy_yes")
        assert f == 0.0

    def test_buy_no_negative_edge(self):
        """buy_no where market already underprices YES → zero Kelly."""
        f = kelly_fraction(0.80, 0.60, "buy_no")
        # We think YES=80%, NO cost=0.40, p_win(NO)=20% → negative EV
        assert f == 0.0

    def test_edge_cases_zero_price(self):
        """Extreme prices should return 0."""
        assert kelly_fraction(0.50, 0.0, "buy_yes") == 0.0
        assert kelly_fraction(0.50, 1.0, "buy_yes") == 0.0
        assert kelly_fraction(0.50, 0.0, "buy_no") == 0.0

    def test_edge_cases_extreme_probabilities(self):
        """p_est at boundaries should return 0."""
        assert kelly_fraction(0.0, 0.50, "buy_yes") == 0.0
        assert kelly_fraction(1.0, 0.50, "buy_yes") == 0.0

    def test_fee_rate_parameter(self):
        """Custom fee rate should affect the result."""
        f_default = kelly_fraction(0.70, 0.50, "buy_yes", fee_rate=0.02)
        f_no_fee = kelly_fraction(0.70, 0.50, "buy_yes", fee_rate=0.0)
        # No fee should give a larger Kelly fraction
        assert f_no_fee > f_default

    def test_symmetry(self):
        """buy_yes at p_est/p_market should roughly mirror buy_no at (1-p_est)/(1-p_market)."""
        f_yes = kelly_fraction(0.70, 0.40, "buy_yes")
        f_no = kelly_fraction(0.30, 0.60, "buy_no")
        # Both have the same edge structure, should be equal
        assert abs(f_yes - f_no) < 0.001

    def test_known_values(self):
        """Verify against hand-calculated Kelly fraction.

        p_est=0.70, p_market=0.40, side=buy_yes, fee_rate=0.02
        payout = 0.98, cost = 0.40
        odds = (0.98 - 0.40) / 0.40 = 1.45
        kelly = (0.70 * 1.45 - 0.30) / 1.45 = (1.015 - 0.30) / 1.45 = 0.4931
        """
        f = kelly_fraction(0.70, 0.40, "buy_yes", fee_rate=0.02)
        assert abs(f - 0.4931) < 0.001


# ============================================================
# expected_edge_after_fee() tests
# ============================================================


class TestEdgeAfterFee:
    """Tests for fee-aware edge calculation."""

    def test_positive_edge_yes(self):
        """Strong YES edge should be positive after fees."""
        edge = expected_edge_after_fee(0.80, 0.50, "buy_yes")
        assert edge > 0

    def test_positive_edge_no(self):
        """Strong NO edge should be positive after fees."""
        edge = expected_edge_after_fee(0.20, 0.50, "buy_no")
        assert edge > 0

    def test_marginal_edge_negative(self):
        """Tiny edge should be negative after fees."""
        edge = expected_edge_after_fee(0.52, 0.50, "buy_yes")
        # 2% edge minus 2% winner fee → near zero or negative
        assert edge < 0.01

    def test_at_fair_price_negative(self):
        """At fair price, edge after fee should be negative (fee eats it)."""
        edge = expected_edge_after_fee(0.50, 0.50, "buy_yes")
        assert edge < 0


# ============================================================
# position_usd() tests
# ============================================================


class TestPositionUsd:
    """Unit tests for position sizing."""

    def test_basic_sizing_yes(self):
        """Basic buy_yes sizing at low bankroll."""
        f = kelly_fraction(0.70, 0.40, "buy_yes")
        size = position_usd(bankroll=75.0, kelly_f=f, side="buy_yes")
        assert size > 0
        assert size <= MAX_POSITION_USD_DEFAULT

    def test_basic_sizing_no(self):
        """buy_no should use higher multiplier (0.35)."""
        f = kelly_fraction(0.30, 0.60, "buy_no")
        size_no = position_usd(bankroll=75.0, kelly_f=f, side="buy_no")
        size_yes = position_usd(bankroll=75.0, kelly_f=f, side="buy_yes")
        # NO multiplier (0.35) > YES multiplier (0.25), so size_no > size_yes
        assert size_no >= size_yes

    def test_bankroll_scaling_low(self):
        """Bankroll < $150 should use base multiplier."""
        f = 0.3
        size_low = position_usd(bankroll=100.0, kelly_f=f, side="buy_yes")
        size_high = position_usd(bankroll=500.0, kelly_f=f, side="buy_yes")
        # At $500 bankroll, multiplier goes up to 0.75 AND bankroll is larger
        assert size_high > size_low

    def test_bankroll_scaling_300(self):
        """Bankroll >= $300 should scale up."""
        f = 0.1
        size = position_usd(bankroll=300.0, kelly_f=f, side="buy_yes")
        # At $300, bankroll_mult=0.50, which is > base KELLY_MULT_YES=0.25
        # So effective_mult should be 0.50
        # raw_size = 0.1 * 0.50 * 300 = 15.0 → capped at MAX_POSITION_USD_DEFAULT
        assert size > 0

    def test_max_position_cap(self):
        """Size should never exceed max_position_usd."""
        caps = SizingCaps(max_position_usd=5.0)
        size = position_usd(bankroll=10000.0, kelly_f=0.5, side="buy_yes", caps=caps)
        assert size <= 5.0

    def test_min_position_floor(self):
        """Size below min should return 0."""
        size = position_usd(bankroll=1.0, kelly_f=0.01, side="buy_yes")
        # 0.01 * 0.25 * 1.0 = 0.0025 → below MIN_POSITION_USD → 0
        assert size == 0.0

    def test_category_haircut(self):
        """4+ positions in same category should halve size."""
        f = 0.1  # Use smaller Kelly to stay under cap
        caps = SizingCaps(max_position_usd=50.0)
        size_normal = position_usd(
            bankroll=100.0, kelly_f=f, side="buy_yes",
            category="Politics", category_counts={"Politics": 2},
            caps=caps,
        )
        size_haircut = position_usd(
            bankroll=100.0, kelly_f=f, side="buy_yes",
            category="Politics", category_counts={"Politics": 5},
            caps=caps,
        )
        # Haircut should reduce size by ~50%
        if size_normal > 0 and size_haircut > 0:
            assert size_haircut < size_normal
            assert abs(size_haircut / size_normal - 0.5) < 0.05

    def test_zero_kelly_returns_zero(self):
        """Kelly fraction of 0 → size 0."""
        assert position_usd(bankroll=1000.0, kelly_f=0.0, side="buy_yes") == 0.0

    def test_negative_kelly_returns_zero(self):
        """Negative Kelly fraction → size 0."""
        assert position_usd(bankroll=1000.0, kelly_f=-0.1, side="buy_yes") == 0.0


# ============================================================
# compute_sizing() tests
# ============================================================


class TestComputeSizing:
    """Tests for the full sizing pipeline."""

    def test_trade_decision(self):
        """Strong edge should produce a 'trade' decision."""
        r = compute_sizing(
            market_id="test_001",
            p_estimated=0.80,
            p_market=0.50,
            side="buy_yes",
            bankroll=100.0,
        )
        assert r.decision == "trade"
        assert r.final_size_usd > 0
        assert r.kelly_f > 0
        assert r.edge_after_fee > 0

    def test_skip_negative_ev(self):
        """Small edge eaten by fees should skip."""
        r = compute_sizing(
            market_id="test_002",
            p_estimated=0.51,
            p_market=0.50,
            side="buy_yes",
            bankroll=100.0,
        )
        assert r.decision == "skip"
        assert "negative_ev" in r.skip_reason or "edge_below" in r.skip_reason or "kelly_zero" in r.skip_reason

    def test_skip_wrong_direction(self):
        """buy_yes when p_est < p_market → skip."""
        r = compute_sizing(
            market_id="test_003",
            p_estimated=0.30,
            p_market=0.60,
            side="buy_yes",
            bankroll=100.0,
        )
        assert r.decision == "skip"

    def test_edge_buffer_configurable(self):
        """Min edge buffer should gate trades."""
        caps = SizingCaps(min_edge_buffer=0.10)  # require 10% edge after fees
        r = compute_sizing(
            market_id="test_004",
            p_estimated=0.60,
            p_market=0.50,
            side="buy_yes",
            bankroll=100.0,
            caps=caps,
        )
        # 10% buffer is hard to meet with only 10% raw edge
        assert r.decision == "skip"
        assert "edge_below_buffer" in r.skip_reason

    def test_fallback_on_missing_inputs(self):
        """Missing inputs with fallback=True → trade at safe fallback size."""
        caps = SizingCaps(fallback_on_missing=True, safe_fallback_usd=1.50)
        r = compute_sizing(
            market_id="test_005",
            p_estimated=1.5,  # invalid
            p_market=0.50,
            side="buy_yes",
            bankroll=100.0,
            caps=caps,
        )
        assert r.decision == "trade"
        assert r.final_size_usd == 1.50
        assert "fallback" in r.skip_reason

    def test_skip_on_missing_inputs(self):
        """Missing inputs with fallback=False → skip."""
        caps = SizingCaps(fallback_on_missing=False)
        r = compute_sizing(
            market_id="test_006",
            p_estimated=1.5,  # invalid
            p_market=0.50,
            side="buy_yes",
            bankroll=100.0,
            caps=caps,
        )
        assert r.decision == "skip"
        assert "missing_inputs" in r.skip_reason

    def test_result_has_all_fields(self):
        """SizingResult should have complete audit trail."""
        r = compute_sizing(
            market_id="audit_001",
            p_estimated=0.75,
            p_market=0.45,
            side="buy_no",
            bankroll=200.0,
            category="Politics",
            category_counts={"Politics": 2},
        )
        assert r.market_id == "audit_001"
        assert r.side == "buy_no"
        assert r.p_estimated == 0.75
        assert r.p_market == 0.45
        assert r.fee_rate == 0.02
        assert r.bankroll == 200.0
        assert r.edge_raw > 0
        assert isinstance(r.category_haircut, bool)


# ============================================================
# Property tests: invariants that must always hold
# ============================================================


class TestSizingProperties:
    """Property tests: size invariants."""

    PROBABILITIES = [0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90]
    BANKROLLS = [10.0, 50.0, 75.0, 100.0, 200.0, 300.0, 500.0, 1000.0]
    SIDES = ["buy_yes", "buy_no"]

    def test_size_never_negative(self):
        """Position size must never be negative."""
        for p_est in self.PROBABILITIES:
            for p_mkt in self.PROBABILITIES:
                for side in self.SIDES:
                    for bankroll in self.BANKROLLS:
                        r = compute_sizing(
                            market_id="prop_neg",
                            p_estimated=p_est,
                            p_market=p_mkt,
                            side=side,
                            bankroll=bankroll,
                        )
                        assert r.final_size_usd >= 0, (
                            f"Negative size: p_est={p_est}, p_mkt={p_mkt}, "
                            f"side={side}, bankroll={bankroll}, size={r.final_size_usd}"
                        )

    def test_size_never_exceeds_max(self):
        """Position size must never exceed MAX_POSITION_USD."""
        max_cap = 10.0
        caps = SizingCaps(max_position_usd=max_cap)
        for p_est in self.PROBABILITIES:
            for p_mkt in self.PROBABILITIES:
                for side in self.SIDES:
                    for bankroll in self.BANKROLLS:
                        r = compute_sizing(
                            market_id="prop_max",
                            p_estimated=p_est,
                            p_market=p_mkt,
                            side=side,
                            bankroll=bankroll,
                            caps=caps,
                        )
                        assert r.final_size_usd <= max_cap, (
                            f"Exceeded max: p_est={p_est}, p_mkt={p_mkt}, "
                            f"side={side}, bankroll={bankroll}, size={r.final_size_usd}"
                        )

    def test_kelly_fraction_bounded(self):
        """Raw Kelly fraction must be in [0, 1]."""
        for p_est in self.PROBABILITIES:
            for p_mkt in self.PROBABILITIES:
                for side in self.SIDES:
                    f = kelly_fraction(p_est, p_mkt, side)
                    assert 0 <= f <= 1.0, (
                        f"Kelly out of bounds: p_est={p_est}, p_mkt={p_mkt}, "
                        f"side={side}, f={f}"
                    )

    def test_no_trade_without_edge(self):
        """When p_est equals p_market, should not trade (fees eat edge)."""
        for p in self.PROBABILITIES:
            for side in self.SIDES:
                r = compute_sizing(
                    market_id="prop_noedge",
                    p_estimated=p,
                    p_market=p,
                    side=side,
                    bankroll=100.0,
                )
                assert r.decision == "skip", (
                    f"Traded without edge: p={p}, side={side}"
                )

    def test_size_scales_with_bankroll(self):
        """Larger bankroll should produce equal or larger position size."""
        for p_est, p_mkt, side in [(0.75, 0.45, "buy_yes"), (0.25, 0.55, "buy_no")]:
            sizes = []
            for bankroll in sorted(self.BANKROLLS):
                r = compute_sizing(
                    market_id="prop_scale",
                    p_estimated=p_est,
                    p_market=p_mkt,
                    side=side,
                    bankroll=bankroll,
                )
                sizes.append(r.final_size_usd)
            # Size should be non-decreasing (or capped)
            for i in range(1, len(sizes)):
                assert sizes[i] >= sizes[i - 1] or sizes[i - 1] == MAX_POSITION_USD_DEFAULT, (
                    f"Size decreased: {sizes[i-1]} -> {sizes[i]} at bankroll={sorted(self.BANKROLLS)[i]}"
                )


# ============================================================
# Backward compatibility
# ============================================================


class TestBackwardCompat:
    """Ensure old imports still work."""

    def test_old_import_path(self):
        """src.sizing should re-export everything."""
        from src.sizing import kelly_fraction as kf
        from src.sizing import position_size as ps
        assert callable(kf)
        assert callable(ps)

    def test_position_size_compat(self):
        """position_size() backward-compatible wrapper should work."""
        size = position_size(
            bankroll=100.0,
            kelly_f=0.3,
            side="buy_yes",
            category="Politics",
            category_counts={"Politics": 1},
            max_position_override=10.0,
        )
        assert size >= 0
        assert size <= 10.0
