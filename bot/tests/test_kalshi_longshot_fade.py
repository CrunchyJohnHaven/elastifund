"""Tests for KalshiLongshotFadeStrategy (DISPATCH_109).

Covers:
- Fee computation with mandatory ceiling rounding
- Breakeven win rate calculation
- Posterior lower bound (pure Python Beta quantile)
- Robust Kelly computation
- Gate logic: price_range, rule_quality, basket_limits, fee_viability, time gates
- Kill condition triggers
- Signal generation from scan_candidates
- record_settlement lifecycle
"""
from __future__ import annotations

import math
import time
from typing import Any

import pytest

from src.strategies.kalshi_longshot_fade import (
    KalshiLongshotFadeStrategy,
    LongshotFadeConfig,
    LongshotCandidate,
    _regularized_incomplete_beta,
    compute_breakeven_win_rate,
    compute_kalshi_fee,
    compute_posterior_lower_bound,
    compute_robust_kelly,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_market(
    condition_id: str = "mkt-001",
    title: str = "Will X happen by December 31?",
    category: str = "economics",
    yes_price: float = 0.03,
    hours_to_close: float = 72.0,
    rules: str = "",
) -> dict[str, Any]:
    return {
        "condition_id": condition_id,
        "title": title,
        "category": category,
        "yes_price": yes_price,
        "hours_to_close": hours_to_close,
        "rules_primary": rules or title,
    }


def _default_strategy(overrides: dict | None = None) -> KalshiLongshotFadeStrategy:
    config = LongshotFadeConfig(**(overrides or {}))
    return KalshiLongshotFadeStrategy(config=config)


# ---------------------------------------------------------------------------
# 1. Fee computation — ceiling rounding
# ---------------------------------------------------------------------------


class TestComputeKalshiFee:
    """Validate that Kalshi's UP-rounding destroys small-edge trades."""

    def test_two_cent_yes_taker_fee_rounds_up(self):
        # 1 contract, YES=0.02, taker=7%: raw = 0.02 * 0.07 = 0.0014 cents/contract
        # 0.0014 * 100 = 0.14 → ceil → 1 → 0.01
        fee = compute_kalshi_fee(1, 0.02, is_maker=False)
        assert fee == 0.01, f"Expected 0.01, got {fee}"

    def test_three_cent_yes_taker_fee_rounds_up(self):
        # 0.03 * 0.07 = 0.0021 → 0.21 → ceil → 1 → 0.01
        fee = compute_kalshi_fee(1, 0.03, is_maker=False)
        assert fee == 0.01

    def test_five_cent_yes_taker_fee_rounds_up(self):
        # 0.05 * 0.07 = 0.0035 → 0.35 → ceil → 1 → 0.01
        fee = compute_kalshi_fee(1, 0.05, is_maker=False)
        assert fee == 0.01

    def test_maker_fee_lower_than_taker(self):
        # 0.03 * 0.0175 = 0.000525 → 0.0525 → ceil → 1 → 0.01
        taker = compute_kalshi_fee(1, 0.03, is_maker=False)
        maker = compute_kalshi_fee(1, 0.03, is_maker=True)
        # Both round to 0.01 at this price, but maker rate is lower
        assert maker <= taker
        assert maker == 0.01  # ceil(0.0525) = 1 → 0.01

    def test_fee_scales_with_contracts(self):
        # 10 contracts at 0.03 YES, taker: raw = 10 * 0.03 * 0.07 = 0.021
        # 0.021 * 100 = 2.1 → ceil → 3 → 0.03
        fee = compute_kalshi_fee(10, 0.03, is_maker=False)
        assert fee == 0.03, f"Expected 0.03, got {fee}"

    def test_zero_contracts_returns_zero(self):
        assert compute_kalshi_fee(0, 0.03) == 0.0

    def test_zero_price_returns_zero(self):
        assert compute_kalshi_fee(1, 0.0) == 0.0

    def test_ceiling_not_floor(self):
        # Verify we use ceil, not round or floor
        # 1 * 0.01 * 0.07 = 0.0007 → 0.07 → ceil(0.07) = 1 → 0.01
        fee = compute_kalshi_fee(1, 0.01, is_maker=False)
        # floor would give 0.00, round would give 0.01
        assert fee == 0.01  # ceil confirms charge, not zero


# ---------------------------------------------------------------------------
# 2. Breakeven win rate
# ---------------------------------------------------------------------------


class TestComputeBreakevenWinRate:

    def test_standard_case(self):
        # no_price=0.97, fee=0.01 → cost=0.98 → must win 98% of time
        wr = compute_breakeven_win_rate(no_price=0.97, fee=0.01)
        assert abs(wr - 0.98) < 1e-9

    def test_lower_yes_price_higher_wr(self):
        # YES=0.01 → NO=0.99, fee=0.01 → WR=1.00 (impossible to profit)
        wr = compute_breakeven_win_rate(no_price=0.99, fee=0.01)
        assert wr == 1.0

    def test_yes_5_cents_wr(self):
        # YES=0.05 → NO=0.95, fee=0.01 → WR=0.96
        wr = compute_breakeven_win_rate(no_price=0.95, fee=0.01)
        assert abs(wr - 0.96) < 1e-9

    def test_never_exceeds_one(self):
        wr = compute_breakeven_win_rate(no_price=0.99, fee=0.05)
        assert wr <= 1.0

    def test_zero_fee(self):
        # No fee → WR = no_price
        wr = compute_breakeven_win_rate(no_price=0.95, fee=0.0)
        assert abs(wr - 0.95) < 1e-9


# ---------------------------------------------------------------------------
# 3. Beta posterior lower bound
# ---------------------------------------------------------------------------


class TestComputePosteriorLowerBound:

    def test_uninformative_prior_returns_low_value(self):
        # With 0 data, prior Beta(2,1): lower 5th percentile should be < 0.5
        p_lower = compute_posterior_lower_bound(wins=0, losses=0, alpha=2.0, beta=1.0, credible=0.05)
        assert 0.0 < p_lower < 0.9

    def test_strong_win_evidence_raises_lower_bound(self):
        # 100 wins, 0 losses → lower bound should be very high
        p_weak = compute_posterior_lower_bound(wins=10, losses=0, alpha=1.0, beta=1.0, credible=0.05)
        p_strong = compute_posterior_lower_bound(wins=100, losses=0, alpha=1.0, beta=1.0, credible=0.05)
        assert p_strong > p_weak

    def test_loss_evidence_lowers_bound(self):
        # More losses → lower bound decreases
        p_no_loss = compute_posterior_lower_bound(wins=50, losses=0, alpha=1.0, beta=1.0, credible=0.05)
        p_with_loss = compute_posterior_lower_bound(wins=50, losses=10, alpha=1.0, beta=1.0, credible=0.05)
        assert p_no_loss > p_with_loss

    def test_credible_level_affects_bound(self):
        # Tighter credible level (lower percentile) → more conservative lower bound.
        # Use a diffuse posterior (fewer observations) so the quantiles are spread apart.
        p_5th = compute_posterior_lower_bound(wins=5, losses=5, credible=0.05)
        p_25th = compute_posterior_lower_bound(wins=5, losses=5, credible=0.25)
        assert p_5th < p_25th, f"5th percentile ({p_5th:.6f}) must be < 25th ({p_25th:.6f})"

    def test_returns_probability_in_unit_interval(self):
        for wins, losses in [(0, 0), (5, 1), (100, 0), (10, 90)]:
            p = compute_posterior_lower_bound(wins, losses)
            assert 0.0 <= p <= 1.0, f"Out of range for wins={wins}, losses={losses}"

    def test_regularized_beta_boundary_values(self):
        assert _regularized_incomplete_beta(0.0, 2.0, 1.0) == 0.0
        assert _regularized_incomplete_beta(1.0, 2.0, 1.0) == 1.0

    def test_regularized_beta_known_values(self):
        # Beta(2,1): I_x(2,1) = x^2 (analytic)
        for x in [0.3, 0.5, 0.7, 0.9]:
            val = _regularized_incomplete_beta(x, 2.0, 1.0)
            expected = x ** 2
            assert abs(val - expected) < 1e-8, f"I_{x}(2,1)={val}, expected {expected}"

    def test_regularized_beta_uniform(self):
        # Beta(1,1) is uniform; at a non-degenerate point I_0.3(1,1) = 0.3
        val = _regularized_incomplete_beta(0.3, 1.0, 1.0)
        assert abs(val - 0.3) < 1e-6


# ---------------------------------------------------------------------------
# 4. Robust Kelly computation
# ---------------------------------------------------------------------------


class TestComputeRobustKelly:

    def test_positive_edge_gives_positive_kelly(self):
        # p_lower=0.97, no_price=0.95, fee=0.01 → cost=0.96, WR_be=0.96
        # Net win = 0.04, b = 0.04/0.96 ≈ 0.0417
        # Kelly = (0.97 * 0.0417 - 0.03) / 0.0417 > 0
        k = compute_robust_kelly(p_lower=0.97, no_price=0.95, fee=0.01)
        assert k > 0.0

    def test_no_edge_returns_zero(self):
        # p_lower = breakeven WR exactly → Kelly = 0
        # no_price=0.95, fee=0.01 → cost=0.96 → WR_be=0.96
        k = compute_robust_kelly(p_lower=0.96, no_price=0.95, fee=0.01)
        assert k == 0.0

    def test_negative_edge_returns_zero(self):
        # p_lower < breakeven → Kelly < 0 → clipped to 0
        k = compute_robust_kelly(p_lower=0.90, no_price=0.95, fee=0.01)
        assert k == 0.0

    def test_kelly_never_exceeds_one(self):
        # Even with extreme edge, Kelly capped at 1
        k = compute_robust_kelly(p_lower=0.999, no_price=0.50, fee=0.01)
        assert k <= 1.0

    def test_higher_fee_reduces_kelly(self):
        k_low_fee = compute_robust_kelly(p_lower=0.97, no_price=0.95, fee=0.01)
        k_high_fee = compute_robust_kelly(p_lower=0.97, no_price=0.95, fee=0.04)
        assert k_low_fee > k_high_fee


# ---------------------------------------------------------------------------
# 5. Gate logic — price range
# ---------------------------------------------------------------------------


class TestPriceRangeGate:

    def test_price_at_lower_bound_passes(self):
        s = _default_strategy()
        market = _make_market(yes_price=0.01)
        candidate = s._evaluate_market(market)
        assert candidate is not None
        assert "price_range" not in candidate.gate_failures

    def test_price_at_upper_bound_passes(self):
        s = _default_strategy()
        market = _make_market(yes_price=0.05)
        candidate = s._evaluate_market(market)
        assert candidate is not None
        assert "price_range" not in candidate.gate_failures

    def test_price_below_range_fails(self):
        s = _default_strategy()
        market = _make_market(yes_price=0.005)
        candidate = s._evaluate_market(market)
        assert candidate is not None
        assert "price_range" in candidate.gate_failures

    def test_price_above_range_fails(self):
        s = _default_strategy()
        market = _make_market(yes_price=0.10)
        candidate = s._evaluate_market(market)
        assert candidate is not None
        assert "price_range" in candidate.gate_failures

    def test_midrange_price_passes(self):
        s = _default_strategy()
        market = _make_market(yes_price=0.03)
        candidate = s._evaluate_market(market)
        assert candidate is not None
        assert "price_range" not in candidate.gate_failures


# ---------------------------------------------------------------------------
# 6. Gate logic — rule quality (objective vs subjective)
# ---------------------------------------------------------------------------


class TestRuleQualityGate:

    def test_objective_title_passes(self):
        s = _default_strategy()
        market = _make_market(title="Will CPI be above 3.0% in March 2026?")
        candidate = s._evaluate_market(market)
        assert candidate is not None
        assert "rule_quality_subjective" not in candidate.gate_failures

    def test_subjective_title_blocked(self):
        s = _default_strategy()
        market = _make_market(title="Will the Fed's most significant rate action be a cut?")
        candidate = s._evaluate_market(market)
        assert candidate is not None
        assert "rule_quality_subjective" in candidate.gate_failures

    def test_subjective_marker_best_blocked(self):
        s = _default_strategy()
        market = _make_market(title="Will Apple be the best performing stock?")
        candidate = s._evaluate_market(market)
        assert "rule_quality_subjective" in candidate.gate_failures

    def test_subjective_marker_major_blocked(self):
        s = _default_strategy()
        market = _make_market(title="Will there be a major storm this month?")
        candidate = s._evaluate_market(market)
        assert "rule_quality_subjective" in candidate.gate_failures

    def test_classify_objective_returns_objective(self):
        s = _default_strategy()
        assert s._classify_rule_type("Will GDP exceed 2%?", "") == "objective"

    def test_classify_subjective_returns_subjective(self):
        s = _default_strategy()
        assert s._classify_rule_type("Will sentiment shift toward optimism?", "") == "subjective"


# ---------------------------------------------------------------------------
# 7. Gate logic — fee viability
# ---------------------------------------------------------------------------


class TestFeeViabilityGate:

    def test_high_fee_drag_blocked(self):
        # YES=0.01: NO=0.99, fee=0.01 → drag = 0.01/0.99 ≈ 1.01% — PASSES (< 20%)
        # YES=0.01 with aggressive config: we'll set max_fee_drag to 0.005 (0.5%)
        s = _default_strategy({"max_fee_drag_pct": 0.005})
        market = _make_market(yes_price=0.01)
        candidate = s._evaluate_market(market)
        assert candidate is not None
        assert "fee_drag_too_high" in candidate.gate_failures

    def test_reasonable_fee_drag_passes(self):
        # YES=0.05: NO=0.95, fee=0.01 → drag = 0.01/0.95 ≈ 1.05% << 20%
        s = _default_strategy()
        market = _make_market(yes_price=0.05)
        candidate = s._evaluate_market(market)
        assert candidate is not None
        assert "fee_drag_too_high" not in candidate.gate_failures

    def test_fee_drag_computed_correctly(self):
        s = _default_strategy()
        market = _make_market(yes_price=0.03)
        candidate = s._evaluate_market(market)
        assert candidate is not None
        expected_fee = compute_kalshi_fee(1, 0.03, is_maker=False)
        expected_drag = expected_fee / (1.0 - 0.03)
        assert abs(candidate.fee_drag_pct - expected_drag) < 1e-9


# ---------------------------------------------------------------------------
# 8. Gate logic — time to resolution
# ---------------------------------------------------------------------------


class TestTimeGate:

    def test_too_short_blocked(self):
        s = _default_strategy()
        market = _make_market(hours_to_close=0.5)  # 30 minutes
        candidate = s._evaluate_market(market)
        assert "time_too_short" in candidate.gate_failures

    def test_too_long_blocked(self):
        s = _default_strategy()
        market = _make_market(hours_to_close=31 * 24)  # 31 days
        candidate = s._evaluate_market(market)
        assert "time_too_long" in candidate.gate_failures

    def test_valid_time_passes(self):
        s = _default_strategy()
        market = _make_market(hours_to_close=48.0)
        candidate = s._evaluate_market(market)
        assert "time_too_short" not in candidate.gate_failures
        assert "time_too_long" not in candidate.gate_failures


# ---------------------------------------------------------------------------
# 9. Basket concentration limits
# ---------------------------------------------------------------------------


class TestBasketLimits:

    def test_category_cap_enforced(self):
        # max_per_category=2; provide 3 markets in the same category
        s = _default_strategy({"max_per_category": 2})
        markets = [
            _make_market(condition_id=f"mkt-{i}", yes_price=0.03, category="economics")
            for i in range(3)
        ]
        candidates = s.scan_candidates(markets)
        # Only 2 should pass the basket limit
        assert len(candidates) <= 2

    def test_different_categories_pass(self):
        s = _default_strategy({"max_per_category": 2})
        markets = [
            _make_market(condition_id="mkt-eco", yes_price=0.03, category="economics"),
            _make_market(condition_id="mkt-pol", yes_price=0.03, category="politics"),
            _make_market(condition_id="mkt-sci", yes_price=0.03, category="science"),
        ]
        candidates = s.scan_candidates(markets)
        assert len(candidates) == 3

    def test_existing_open_positions_count_against_cap(self):
        s = _default_strategy({"max_per_category": 1})
        # Pre-populate one open position in economics
        s._category_counts["economics"] = 1
        markets = [_make_market(condition_id="mkt-new", yes_price=0.03, category="economics")]
        candidates = s.scan_candidates(markets)
        # Category already at cap, should be blocked
        assert len(candidates) == 0


# ---------------------------------------------------------------------------
# 10. Kill condition triggers
# ---------------------------------------------------------------------------


class TestKillConditions:

    def test_no_kill_before_min_trades(self):
        s = _default_strategy()
        # Add 29 wins (below 30 threshold)
        for i in range(29):
            s._settled_trades.append({"outcome": "win", "pnl": 0.04})
        assert s.check_kill_conditions() is False
        assert s._killed is False

    def test_low_win_rate_triggers_kill(self):
        s = _default_strategy()
        # 30 trades: 20 wins, 10 losses → WR = 0.667 < 0.88 threshold
        for i in range(20):
            s._settled_trades.append({"outcome": "win", "pnl": 0.04})
        for i in range(10):
            s._settled_trades.append({"outcome": "loss", "pnl": -0.96})
        assert s.check_kill_conditions() is True
        assert s._killed is True

    def test_low_profit_factor_triggers_kill(self):
        s = _default_strategy()
        # 30 trades: all labeled "win" for WR, but pnl is mostly negative
        # WR = 1.0 (pass WR gate), PF = 0.5 (fail PF gate)
        for i in range(30):
            s._settled_trades.append({"outcome": "win", "pnl": -0.10})
        assert s.check_kill_conditions() is True
        assert s._killed is True

    def test_healthy_strategy_not_killed(self):
        s = _default_strategy()
        # 30 trades: 29 wins, 1 loss → WR=0.967>0.88, positive PF
        for i in range(29):
            s._settled_trades.append({"outcome": "win", "pnl": 0.04})
        s._settled_trades.append({"outcome": "loss", "pnl": -0.96})
        assert s.check_kill_conditions() is False
        assert s._killed is False

    def test_already_killed_returns_true_immediately(self):
        s = _default_strategy()
        s._killed = True
        s._kill_reason = "test"
        assert s.check_kill_conditions() is True

    def test_generate_signals_returns_empty_when_killed(self):
        s = _default_strategy()
        s._killed = True
        signals = s.generate_signals(
            [_make_market()], [], [], []
        )
        assert signals == []


# ---------------------------------------------------------------------------
# 11. Signal generation integration
# ---------------------------------------------------------------------------


class TestGenerateSignals:

    def test_valid_market_produces_no_signal(self):
        s = _default_strategy()
        markets = [_make_market(yes_price=0.03, hours_to_close=48.0)]
        signals = s.generate_signals(markets, [], [], [])
        assert len(signals) == 1
        assert signals[0].side == "NO"
        assert signals[0].strategy == s.name

    def test_signal_has_required_metadata(self):
        s = _default_strategy()
        markets = [_make_market(yes_price=0.03, hours_to_close=48.0)]
        signals = s.generate_signals(markets, [], [], [])
        assert len(signals) == 1
        meta = signals[0].metadata
        assert "yes_price" in meta
        assert "taker_fee" in meta
        assert "fee_drag_pct" in meta
        assert "breakeven_win_rate" in meta
        assert "p_lower" in meta
        assert "kelly_sized" in meta

    def test_position_limit_caps_signals(self):
        s = _default_strategy({"max_open_positions": 3})
        markets = [
            _make_market(condition_id=f"mkt-{i}", yes_price=0.03)
            for i in range(10)
        ]
        signals = s.generate_signals(markets, [], [], [])
        assert len(signals) <= 3

    def test_rejected_market_no_signal(self):
        s = _default_strategy()
        markets = [_make_market(yes_price=0.50)]  # Way outside 1-5 cent range
        signals = s.generate_signals(markets, [], [], [])
        assert len(signals) == 0

    def test_duplicate_condition_id_not_re_signalled(self):
        s = _default_strategy()
        market = _make_market(condition_id="mkt-001", yes_price=0.03)
        # First call generates signal
        sig1 = s.generate_signals([market], [], [], [])
        assert len(sig1) == 1
        # Second call with same condition_id — already open
        sig2 = s.generate_signals([market], [], [], [])
        assert len(sig2) == 0


# ---------------------------------------------------------------------------
# 12. Record settlement lifecycle
# ---------------------------------------------------------------------------


class TestRecordSettlement:

    def test_win_recorded(self):
        s = _default_strategy()
        s.record_settlement("mkt-001", "win", 0.04)
        assert len(s._settled_trades) == 1
        assert s._settled_trades[0]["outcome"] == "win"

    def test_loss_recorded(self):
        s = _default_strategy()
        s.record_settlement("mkt-001", "loss", -0.96)
        assert len(s._settled_trades) == 1
        assert s._settled_trades[0]["outcome"] == "loss"

    def test_invalid_outcome_ignored(self):
        s = _default_strategy()
        s.record_settlement("mkt-001", "unknown_outcome", 0.0)
        assert len(s._settled_trades) == 0

    def test_settlement_removes_from_open_positions(self):
        s = _default_strategy()
        # Inject a fake open position
        fake_candidate = LongshotCandidate(
            condition_id="mkt-001",
            title="Test",
            category="economics",
            yes_price=0.03,
            no_price=0.97,
            taker_fee=0.01,
            maker_fee=0.01,
            fee_drag_pct=0.0103,
            breakeven_win_rate=0.98,
            p_lower=0.97,
            kelly_fraction_raw=0.01,
            kelly_fraction_sized=0.0025,
            suggested_position_usd=0.25,
            hours_to_resolution=48.0,
            rule_type="objective",
        )
        s._open_positions["mkt-001"] = fake_candidate
        s._category_counts["economics"] = 1
        s.record_settlement("mkt-001", "win", 0.02)
        assert "mkt-001" not in s._open_positions
        assert s._category_counts.get("economics", 0) == 0

    def test_status_reflects_settlements(self):
        s = _default_strategy()
        for _ in range(5):
            s.record_settlement("mkt-win", "win", 0.04)
        for _ in range(2):
            s.record_settlement("mkt-loss", "loss", -0.96)
        status = s.status()
        assert status["settled_trades"] == 7
        assert abs(status["win_rate"] - 5 / 7) < 1e-9


# ---------------------------------------------------------------------------
# 13. Edge case: Kalshi cent-price normalisation
# ---------------------------------------------------------------------------


class TestPriceNormalization:

    def test_cent_price_normalised(self):
        # Some Kalshi API responses return prices as integers (3 = 3 cents)
        s = _default_strategy()
        market = {
            "condition_id": "mkt-norm",
            "title": "Will GDP exceed 2%?",
            "category": "economics",
            "yes_price": 3,  # 3 cents as integer
            "hours_to_close": 72.0,
            "rules_primary": "Will GDP exceed 2%?",
        }
        candidate = s._evaluate_market(market)
        assert candidate is not None
        # 3 > 1.0 so it should be divided by 100
        assert abs(candidate.yes_price - 0.03) < 1e-9
