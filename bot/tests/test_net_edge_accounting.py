"""Tests for net_edge_accounting.py — Core EV formulas."""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from bot.net_edge_accounting import (
    BinCalibration,
    CostBreakdown,
    EdgeResult,
    FeeSchedule,
    Venue,
    bayesian_bin_calibration,
    capital_velocity,
    deflated_sharpe,
    evaluate_edge,
    impact_cost,
    kelly_binary,
    kelly_prediction_market,
    maker_ev,
    net_edge,
    polymarket_fee,
)


class TestNetEdge:
    def test_basic_net_edge(self):
        result = net_edge(gross_edge=10.0, fees=2.0, slippage=1.0)
        assert result == 7.0

    def test_net_edge_with_all_costs(self):
        result = net_edge(100.0, 20.0, 10.0, latency_penalty=5.0, non_fill_penalty=3.0)
        assert result == 62.0

    def test_net_edge_negative(self):
        result = net_edge(5.0, 10.0, 2.0)
        assert result == -7.0

    def test_net_edge_zero(self):
        result = net_edge(0.0, 0.0, 0.0)
        assert result == 0.0


class TestMakerEV:
    def test_perfect_fill_perfect_win(self):
        ev = maker_ev(p_fill=1.0, p_win_given_fill=1.0, payoff=10.0, loss=5.0)
        assert ev == 10.0

    def test_zero_fill(self):
        ev = maker_ev(p_fill=0.0, p_win_given_fill=0.8, payoff=10.0, loss=5.0)
        assert ev == 0.0

    def test_with_cancel_cost(self):
        ev = maker_ev(p_fill=0.5, p_win_given_fill=0.6, payoff=10.0, loss=5.0, cancel_cost=0.5)
        # 0.5 * (0.6 * 10 - 0.4 * 5) - 0.5 = 0.5 * (6 - 2) - 0.5 = 1.5
        assert abs(ev - 1.5) < 0.01

    def test_negative_ev(self):
        ev = maker_ev(p_fill=1.0, p_win_given_fill=0.3, payoff=5.0, loss=10.0)
        # 1.0 * (0.3 * 5 - 0.7 * 10) = 1.5 - 7.0 = -5.5
        assert ev < 0


class TestCapitalVelocity:
    def test_basic_velocity(self):
        cv = capital_velocity(expected_pnl=10.0, capital_locked=100.0, hours_locked=24.0)
        # hourly = 10 / (100 * 24) = 0.004167
        # annual = 0.004167 * 8760 = 36.5
        assert abs(cv - 36.5) < 0.1

    def test_zero_capital(self):
        assert capital_velocity(10.0, 0.0, 24.0) == 0.0

    def test_zero_hours(self):
        assert capital_velocity(10.0, 100.0, 0.0) == 0.0


class TestKellyBinary:
    def test_coin_flip_no_edge(self):
        # Fair coin, even odds: kelly = 0
        assert kelly_binary(0.5, 1.0) == 0.0

    def test_strong_edge(self):
        # 60% win rate, even odds: f = (0.6 * 1 - 0.4) / 1 = 0.20
        f = kelly_binary(0.6, 1.0)
        assert abs(f - 0.20) < 0.01

    def test_negative_edge(self):
        assert kelly_binary(0.4, 1.0) == 0.0

    def test_capped_at_quarter_kelly(self):
        # Very high edge: should cap at 0.25
        f = kelly_binary(0.95, 1.0)
        assert f == 0.25

    def test_edge_cases(self):
        assert kelly_binary(0.0, 1.0) == 0.0
        assert kelly_binary(1.0, 1.0) == 0.0
        assert kelly_binary(0.5, 0.0) == 0.0


class TestKellyPredictionMarket:
    def test_no_edge(self):
        # True prob matches market: no edge
        assert kelly_prediction_market(0.50, 0.50) == 0.0

    def test_flb_edge(self):
        # Market says 95% but true is 90% → edge for NO buyer
        f = kelly_prediction_market(0.90, 0.95)
        assert f > 0

    def test_boundary(self):
        assert kelly_prediction_market(0.0, 0.5) == 0.0
        assert kelly_prediction_market(0.5, 0.0) == 0.0


class TestImpactCost:
    def test_basic_impact(self):
        ic = impact_cost(order_size=100.0, adv=10000.0, sigma=0.02, k=0.1)
        # 0.1 * 0.02 * sqrt(100/10000) = 0.1 * 0.02 * 0.1 = 0.0002
        assert abs(ic - 0.0002) < 0.0001

    def test_zero_adv(self):
        assert impact_cost(100.0, 0.0, 0.02) == 0.0

    def test_large_order(self):
        small = impact_cost(10.0, 10000.0, 0.02)
        large = impact_cost(1000.0, 10000.0, 0.02)
        assert large > small  # larger order → more impact


class TestPolymarketFee:
    def test_maker_is_free(self):
        assert polymarket_fee(0.50, is_maker=True) == 0.0

    def test_taker_at_50(self):
        # 0.50 * 0.50 * 0.02 = 0.005
        fee = polymarket_fee(0.50, fee_rate=0.02, is_maker=False)
        assert abs(fee - 0.005) < 0.001

    def test_taker_at_extremes(self):
        fee_low = polymarket_fee(0.05, fee_rate=0.02, is_maker=False)
        fee_mid = polymarket_fee(0.50, fee_rate=0.02, is_maker=False)
        assert fee_low < fee_mid  # peaks at 50/50


class TestBayesianBinCalibration:
    def test_basic_calibration(self):
        cal = bayesian_bin_calibration(wins=8, total=100, bin_center=0.05)
        assert cal.sample_size == 100
        assert 0.05 < cal.posterior_mean < 0.15
        assert cal.observed_rate == 0.08

    def test_perfect_calibration(self):
        cal = bayesian_bin_calibration(wins=50, total=1000, bin_center=0.05)
        assert abs(cal.observed_rate - 0.05) < 0.001
        assert abs(cal.bin_error) < 0.001

    def test_sparse_data_wide_intervals(self):
        cal = bayesian_bin_calibration(wins=1, total=2, bin_center=0.05)
        # Very sparse: wide credible interval
        interval_width = cal.credible_upper - cal.credible_lower
        assert interval_width > 0.10

    def test_flb_detection(self):
        # Market says 5% but 8% actually happen → positive FLB
        cal = bayesian_bin_calibration(wins=80, total=1000, bin_center=0.05)
        assert cal.bin_error > 0  # observed > expected
        assert cal.edge_bps > 0   # positive edge for YES buyer


class TestDeflatedSharpe:
    def test_single_trial(self):
        ds = deflated_sharpe(observed_sharpe=2.0, num_trials=1, T=252)
        assert ds > 0.5  # strong Sharpe with 1 trial should pass

    def test_many_trials_degrades(self):
        ds_1 = deflated_sharpe(observed_sharpe=1.5, num_trials=1, T=252)
        ds_100 = deflated_sharpe(observed_sharpe=1.5, num_trials=100, T=252)
        assert ds_100 < ds_1  # more trials → harder to be significant

    def test_zero_inputs(self):
        assert deflated_sharpe(1.0, 0, 252) == 0.0
        assert deflated_sharpe(1.0, 10, 0) == 0.0


class TestFeeSchedule:
    def test_polymarket_defaults(self):
        fs = FeeSchedule.polymarket()
        assert fs.maker_fee == 0.0
        assert fs.taker_fee == 0.02
        assert fs.maker_rebate == 0.20
        assert fs.venue == Venue.POLYMARKET

    def test_kalshi_defaults(self):
        fs = FeeSchedule.kalshi()
        assert fs.taker_fee == 0.07
        assert fs.venue == Venue.KALSHI

    def test_alpaca_defaults(self):
        fs = FeeSchedule.alpaca()
        assert fs.maker_fee == 0.0
        assert fs.taker_fee == 0.0
        assert fs.venue == Venue.ALPACA


class TestEvaluateEdge:
    def test_tradeable_edge(self):
        result = evaluate_edge(
            gross_edge_bps=100.0,
            p_fill=0.80,
            p_win=0.65,
            position_usd=10.0,
            hours_locked=24.0,
            fee_schedule=FeeSchedule.polymarket(),
            is_maker=True,
        )
        assert result.is_tradeable
        assert result.net_edge_bps > 0
        assert result.kelly_fraction > 0
        assert result.kill_reason == ""

    def test_killed_edge(self):
        result = evaluate_edge(
            gross_edge_bps=5.0,
            p_fill=0.50,
            p_win=0.52,
            position_usd=10.0,
            hours_locked=24.0,
            fee_schedule=FeeSchedule.kalshi(),
            is_maker=False,
            min_net_edge_bps=50.0,
        )
        assert not result.is_tradeable
        assert result.kill_reason != ""

    def test_cost_breakdown_populated(self):
        result = evaluate_edge(
            gross_edge_bps=200.0,
            p_fill=0.90,
            p_win=0.70,
            position_usd=20.0,
            hours_locked=48.0,
            fee_schedule=FeeSchedule.polymarket(),
        )
        assert isinstance(result.costs, CostBreakdown)
        assert result.costs.total >= 0
