#!/usr/bin/env python3
"""Tests for the strategy benchmark harness.

Validates strategy implementations, scenario construction, result computation,
admission rules, and edge cases using only synthetic data.

Author: JJ (autonomous)
Date: 2026-03-22
"""

from __future__ import annotations

import math
import sys
import os
import unittest

# Ensure the repo root is on sys.path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from scripts.strategy_benchmark import (
    DirectionalBTC5Strategy,
    MeanReversionStrategy,
    PriceObservation,
    ReplayScenario,
    StrategyResult,
    StructuralStrategy,
    Trade,
    build_march_11_winning_session,
    build_march_15_concentration_failure,
    build_march_22_loss_session,
    check_admission,
    format_report,
    get_mandatory_scenarios,
    run_benchmark,
    _compute_result,
)


# ---------------------------------------------------------------------------
# Helper to build minimal observations
# ---------------------------------------------------------------------------

def _obs(
    delta: float = -0.001,
    resolved: str = "DOWN",
    bid_down: float = 0.52,
    ask_down: float = 0.53,
    bid_up: float = 0.48,
    ask_up: float = 0.49,
    resolution_price: float | None = None,
    btc_base: float = 84000.0,
) -> PriceObservation:
    """Build a single PriceObservation with configurable delta."""
    candle_open = btc_base
    btc_spot = btc_base * (1 + delta)
    return PriceObservation(
        timestamp=1741651200.0,
        btc_spot=btc_spot,
        candle_open=candle_open,
        best_bid_down=bid_down,
        best_ask_down=ask_down,
        best_bid_up=bid_up,
        best_ask_up=ask_up,
        resolved_outcome=resolved,
        resolution_price=resolution_price,
    )


def _scenario(observations: list[PriceObservation], name: str = "test") -> ReplayScenario:
    return ReplayScenario(
        name=name,
        description="test scenario",
        start_ts=1741651200.0,
        end_ts=1741651200.0 + len(observations) * 300,
        market_data=observations,
    )


# ---------------------------------------------------------------------------
# StrategyResult dataclass tests
# ---------------------------------------------------------------------------

class TestStrategyResult(unittest.TestCase):
    """Tests for the StrategyResult dataclass."""

    def test_expectancy_with_trades(self):
        r = StrategyResult("test", trades=10, wins=6, losses=4,
                           gross_pnl=2.0, max_drawdown=0.5, sharpe=1.0,
                           profit_factor=1.5, fill_rate=1.0,
                           trapped_capital_pct=0.0)
        self.assertAlmostEqual(r.expectancy, 0.2)

    def test_expectancy_zero_trades(self):
        r = StrategyResult("test", trades=0, wins=0, losses=0,
                           gross_pnl=0.0, max_drawdown=0.0, sharpe=0.0,
                           profit_factor=0.0, fill_rate=0.0,
                           trapped_capital_pct=0.0)
        self.assertEqual(r.expectancy, 0.0)


# ---------------------------------------------------------------------------
# _compute_result tests
# ---------------------------------------------------------------------------

class TestComputeResult(unittest.TestCase):
    """Tests for the _compute_result helper."""

    def test_empty_trades(self):
        r = _compute_result("empty", [], 0)
        self.assertEqual(r.trades, 0)
        self.assertEqual(r.wins, 0)
        self.assertEqual(r.gross_pnl, 0.0)
        self.assertEqual(r.sharpe, 0.0)
        self.assertEqual(r.fill_rate, 0.0)

    def test_all_wins(self):
        trades = [Trade("DOWN", 0.50, 1.0, 0.50) for _ in range(5)]
        r = _compute_result("allwin", trades, 5)
        self.assertEqual(r.wins, 5)
        self.assertEqual(r.losses, 0)
        self.assertAlmostEqual(r.gross_pnl, 2.5)
        self.assertEqual(r.max_drawdown, 0.0)

    def test_all_losses(self):
        trades = [Trade("DOWN", 0.50, 0.0, -0.50) for _ in range(5)]
        r = _compute_result("allloss", trades, 5)
        self.assertEqual(r.wins, 0)
        self.assertEqual(r.losses, 5)
        self.assertAlmostEqual(r.gross_pnl, -2.5)
        self.assertEqual(r.profit_factor, 0.0)

    def test_mixed_drawdown(self):
        # Win, win, lose, lose, win
        trades = [
            Trade("DOWN", 0.50, 1.0, 0.50),
            Trade("DOWN", 0.50, 1.0, 0.50),
            Trade("DOWN", 0.50, 0.0, -0.50),
            Trade("DOWN", 0.50, 0.0, -0.50),
            Trade("DOWN", 0.50, 1.0, 0.50),
        ]
        r = _compute_result("mixed", trades, 5)
        self.assertEqual(r.wins, 3)
        self.assertEqual(r.losses, 2)
        self.assertAlmostEqual(r.gross_pnl, 0.5)
        # Peak at 1.0, drops to 0.0 → drawdown = 1.0
        self.assertAlmostEqual(r.max_drawdown, 1.0)

    def test_unfilled_excluded(self):
        trades = [
            Trade("DOWN", 0.50, 1.0, 0.50, filled=True),
            Trade("DOWN", 0.50, 0.50, 0.0, filled=False),
        ]
        r = _compute_result("partial", trades, 2)
        self.assertEqual(r.trades, 1)  # only filled
        self.assertEqual(r.fill_rate, 0.5)

    def test_trapped_capital(self):
        trades = [
            Trade("DOWN", 0.50, 0.50, 0.0, filled=True, trapped=True),
            Trade("DOWN", 0.50, 1.0, 0.50, filled=True, trapped=False),
        ]
        r = _compute_result("trapped", trades, 2)
        self.assertAlmostEqual(r.trapped_capital_pct, 0.5)

    def test_profit_factor_inf_no_losses(self):
        trades = [Trade("UP", 0.40, 1.0, 0.60)]
        r = _compute_result("inf_pf", trades, 1)
        self.assertEqual(r.profit_factor, float("inf"))

    def test_single_trade_sharpe(self):
        trades = [Trade("DOWN", 0.50, 1.0, 0.50)]
        r = _compute_result("single", trades, 1)
        # With one trade, std=0 → sharpe=0
        self.assertEqual(r.sharpe, 0.0)


# ---------------------------------------------------------------------------
# Directional BTC5 tests
# ---------------------------------------------------------------------------

class TestDirectionalBTC5(unittest.TestCase):
    """Tests for DirectionalBTC5Strategy."""

    def test_valid_result_type(self):
        s = DirectionalBTC5Strategy()
        scenario = _scenario([_obs()])
        r = s.evaluate(scenario)
        self.assertIsInstance(r, StrategyResult)
        self.assertEqual(r.strategy_name, "DirectionalBTC5")

    def test_buys_down_on_negative_delta(self):
        # delta = -0.001 → BTC dropped → should buy DOWN
        obs = _obs(delta=-0.001, resolved="DOWN", bid_down=0.52)
        s = DirectionalBTC5Strategy(delta_threshold=0.0005)
        r = s.evaluate(_scenario([obs]))
        self.assertEqual(r.trades, 1)
        self.assertEqual(r.wins, 1)
        self.assertGreater(r.gross_pnl, 0)

    def test_buys_up_on_positive_delta(self):
        obs = _obs(delta=0.001, resolved="UP", bid_up=0.48)
        s = DirectionalBTC5Strategy(delta_threshold=0.0005)
        r = s.evaluate(_scenario([obs]))
        self.assertEqual(r.wins, 1)

    def test_skips_small_delta(self):
        obs = _obs(delta=0.0001)  # below threshold
        s = DirectionalBTC5Strategy(delta_threshold=0.0005)
        r = s.evaluate(_scenario([obs]))
        self.assertEqual(r.trades, 0)

    def test_march_11_scores_well(self):
        """Directional BTC5 should score well on March 11 (historically won)."""
        scenario = build_march_11_winning_session()
        s = DirectionalBTC5Strategy()
        r = s.evaluate(scenario)
        self.assertGreater(r.gross_pnl, 0, "BTC5 should be profitable on March 11")
        self.assertGreater(r.wins, r.losses, "BTC5 should have more wins than losses")

    def test_march_22_scores_poorly(self):
        """Directional BTC5 should score poorly on March 22 (historically lost)."""
        scenario = build_march_22_loss_session()
        s = DirectionalBTC5Strategy()
        r = s.evaluate(scenario)
        self.assertLess(r.gross_pnl, 0, "BTC5 should lose money on March 22")

    def test_handles_zero_candle_open(self):
        obs = _obs()
        obs.candle_open = 0
        s = DirectionalBTC5Strategy()
        r = s.evaluate(_scenario([obs]))
        self.assertEqual(r.trades, 0)

    def test_handles_unresolved_market(self):
        obs = _obs(delta=-0.001, resolved=None)  # type: ignore
        s = DirectionalBTC5Strategy(delta_threshold=0.0005)
        r = s.evaluate(_scenario([obs]))
        self.assertEqual(r.trades, 1)
        self.assertGreater(r.trapped_capital_pct, 0)


# ---------------------------------------------------------------------------
# Mean Reversion tests
# ---------------------------------------------------------------------------

class TestMeanReversion(unittest.TestCase):
    """Tests for MeanReversionStrategy."""

    def test_valid_result_type(self):
        s = MeanReversionStrategy()
        r = s.evaluate(_scenario([_obs()]))
        self.assertIsInstance(r, StrategyResult)
        self.assertEqual(r.strategy_name, "MeanReversion")

    def test_bets_against_direction(self):
        # BTC dropped → mean reversion buys UP
        obs = _obs(delta=-0.002, resolved="UP", bid_up=0.48)
        s = MeanReversionStrategy(reversion_threshold=0.001)
        r = s.evaluate(_scenario([obs]))
        self.assertEqual(r.wins, 1)

    def test_loses_when_trend_continues(self):
        # BTC dropped → MR buys UP → but DOWN wins
        obs = _obs(delta=-0.002, resolved="DOWN", bid_up=0.48)
        s = MeanReversionStrategy(reversion_threshold=0.001)
        r = s.evaluate(_scenario([obs]))
        self.assertEqual(r.losses, 1)
        self.assertLess(r.gross_pnl, 0)

    def test_skips_small_delta(self):
        obs = _obs(delta=-0.0005)
        s = MeanReversionStrategy(reversion_threshold=0.001)
        r = s.evaluate(_scenario([obs]))
        self.assertEqual(r.trades, 0)

    def test_opposite_of_directional_on_march_11(self):
        """On March 11 (strong trend), mean reversion should lose."""
        scenario = build_march_11_winning_session()
        directional = DirectionalBTC5Strategy().evaluate(scenario)
        mr = MeanReversionStrategy().evaluate(scenario)
        # If directional wins, mean reversion should lose (opposite bets)
        if directional.gross_pnl > 0:
            self.assertLess(mr.gross_pnl, directional.gross_pnl)


# ---------------------------------------------------------------------------
# Structural Strategy tests
# ---------------------------------------------------------------------------

class TestStructuralStrategy(unittest.TestCase):
    """Tests for StructuralStrategy."""

    def test_valid_result_type(self):
        s = StructuralStrategy()
        r = s.evaluate(_scenario([_obs()]))
        self.assertIsInstance(r, StrategyResult)
        self.assertEqual(r.strategy_name, "Structural")

    def test_buys_near_certain_outcome(self):
        obs = _obs(resolved="DOWN", ask_down=0.95, resolution_price=0.96)
        s = StructuralStrategy(max_entry=0.97)
        r = s.evaluate(_scenario([obs]))
        self.assertEqual(r.wins, 1)
        self.assertGreater(r.gross_pnl, 0)

    def test_skips_without_resolution_price(self):
        obs = _obs(resolved="DOWN", resolution_price=None)
        s = StructuralStrategy()
        r = s.evaluate(_scenario([obs]))
        self.assertEqual(r.trades, 0)

    def test_skips_low_confidence(self):
        obs = _obs(resolved="DOWN", resolution_price=0.80)
        s = StructuralStrategy(min_resolution_price=0.94)
        r = s.evaluate(_scenario([obs]))
        self.assertEqual(r.trades, 0)

    def test_skips_overpriced(self):
        obs = _obs(resolved="DOWN", ask_down=0.99, resolution_price=0.96)
        s = StructuralStrategy(max_entry=0.97)
        r = s.evaluate(_scenario([obs]))
        self.assertEqual(r.trades, 0)

    def test_never_negative_expectancy_on_resolution_sniping(self):
        """Structural should never have negative expectancy when sniping
        near-certain outcomes."""
        observations = []
        for i in range(20):
            observations.append(_obs(
                resolved="DOWN",
                ask_down=0.94 + (i % 3) * 0.01,  # 0.94, 0.95, 0.96
                resolution_price=0.96,
            ))
        s = StructuralStrategy(max_entry=0.97, min_resolution_price=0.94)
        r = s.evaluate(_scenario(observations))
        if r.trades > 0:
            self.assertGreaterEqual(r.expectancy, 0,
                                     "Structural should never lose on resolution sniping")

    def test_structural_on_march_scenarios(self):
        """Structural produces zero trades on non-structural scenarios."""
        for scenario in get_mandatory_scenarios():
            s = StructuralStrategy()
            r = s.evaluate(scenario)
            # March scenarios have no resolution_price set
            self.assertEqual(r.trades, 0)


# ---------------------------------------------------------------------------
# Scenario construction tests
# ---------------------------------------------------------------------------

class TestScenarios(unittest.TestCase):
    """Tests for mandatory replay scenario construction."""

    def test_march_11_has_47_observations(self):
        s = build_march_11_winning_session()
        self.assertEqual(len(s.market_data), 47)
        self.assertEqual(s.name, "march_11_winning")

    def test_march_15_has_40_observations(self):
        s = build_march_15_concentration_failure()
        self.assertEqual(len(s.market_data), 40)

    def test_march_22_has_30_observations(self):
        s = build_march_22_loss_session()
        self.assertEqual(len(s.market_data), 30)

    def test_mandatory_scenarios_returns_three(self):
        scenarios = get_mandatory_scenarios()
        self.assertEqual(len(scenarios), 3)

    def test_all_scenarios_have_data(self):
        for s in get_mandatory_scenarios():
            self.assertGreater(len(s.market_data), 0)
            self.assertIsNotNone(s.name)
            self.assertIsNotNone(s.description)
            self.assertGreater(s.end_ts, s.start_ts)

    def test_march_11_outcome_distribution(self):
        s = build_march_11_winning_session()
        downs = sum(1 for o in s.market_data if o.resolved_outcome == "DOWN")
        ups = sum(1 for o in s.market_data if o.resolved_outcome == "UP")
        self.assertEqual(downs, 39)
        self.assertEqual(ups, 8)


# ---------------------------------------------------------------------------
# Benchmark runner tests
# ---------------------------------------------------------------------------

class TestRunBenchmark(unittest.TestCase):
    """Tests for the benchmark runner."""

    def test_returns_all_combinations(self):
        scenarios = get_mandatory_scenarios()
        strategies = [DirectionalBTC5Strategy(), MeanReversionStrategy(), StructuralStrategy()]
        results = run_benchmark(scenarios, strategies)
        self.assertEqual(len(results), 3)  # 3 scenarios
        for sname, strats in results.items():
            self.assertEqual(len(strats), 3)  # 3 strategies each

    def test_empty_scenarios(self):
        results = run_benchmark([], [DirectionalBTC5Strategy()])
        self.assertEqual(len(results), 0)

    def test_empty_strategies(self):
        scenarios = [_scenario([_obs()])]
        results = run_benchmark(scenarios, [])
        self.assertEqual(len(results), 1)
        self.assertEqual(len(results["test"]), 0)

    def test_empty_market_data(self):
        empty = ReplayScenario("empty", "empty scenario", 0, 0, [])
        strategies = [DirectionalBTC5Strategy(), MeanReversionStrategy(), StructuralStrategy()]
        results = run_benchmark([empty], strategies)
        for sname, r in results["empty"].items():
            self.assertEqual(r.trades, 0)
            self.assertEqual(r.gross_pnl, 0.0)


# ---------------------------------------------------------------------------
# Admission rule tests
# ---------------------------------------------------------------------------

class TestAdmission(unittest.TestCase):
    """Tests for the admission rule."""

    def _result(self, name, pnl=1.0, trades=10, dd=0.5, trapped=0.0):
        return StrategyResult(
            strategy_name=name, trades=trades,
            wins=max(0, trades // 2 + (1 if pnl > 0 else 0)),
            losses=max(0, trades // 2),
            gross_pnl=pnl, max_drawdown=dd, sharpe=1.0,
            profit_factor=1.5, fill_rate=1.0,
            trapped_capital_pct=trapped,
        )

    def test_admitted_when_beats_both(self):
        challenger = self._result("C", pnl=2.0, dd=0.3, trapped=0.0)
        directional = self._result("D", pnl=1.0, dd=0.5)
        structural = self._result("S", pnl=0.5, dd=0.5, trapped=0.1)
        admitted, reason = check_admission(challenger, directional, structural)
        self.assertTrue(admitted)

    def test_blocked_lower_expectancy(self):
        challenger = self._result("C", pnl=0.5)
        directional = self._result("D", pnl=1.0)
        structural = self._result("S", pnl=0.5, dd=1.0, trapped=0.5)
        admitted, reason = check_admission(challenger, directional, structural)
        self.assertFalse(admitted)
        self.assertIn("Expectancy", reason)

    def test_blocked_higher_drawdown(self):
        challenger = self._result("C", pnl=2.0, dd=1.0)
        directional = self._result("D", pnl=1.0, dd=0.5)
        structural = self._result("S", pnl=0.5, dd=0.3)
        admitted, reason = check_admission(challenger, directional, structural)
        self.assertFalse(admitted)
        self.assertIn("Drawdown", reason)

    def test_blocked_higher_trapped_capital(self):
        challenger = self._result("C", pnl=2.0, dd=0.1, trapped=0.5)
        directional = self._result("D", pnl=1.0, dd=0.5)
        structural = self._result("S", pnl=0.5, dd=0.5, trapped=0.1)
        admitted, reason = check_admission(challenger, directional, structural)
        self.assertFalse(admitted)
        self.assertIn("Trapped", reason)

    def test_admitted_when_structural_has_no_trades(self):
        challenger = self._result("C", pnl=2.0, dd=5.0, trapped=0.5)
        directional = self._result("D", pnl=1.0)
        structural = self._result("S", pnl=0.0, trades=0, dd=0.0)
        admitted, _ = check_admission(challenger, directional, structural)
        self.assertTrue(admitted)

    def test_admitted_when_directional_negative(self):
        challenger = self._result("C", pnl=-0.5)
        directional = self._result("D", pnl=-1.0)
        structural = self._result("S", pnl=0.0, trades=0)
        # Directional expectancy is negative, so rule 1 doesn't block
        admitted, _ = check_admission(challenger, directional, structural)
        self.assertTrue(admitted)

    def test_multiple_block_reasons(self):
        challenger = self._result("C", pnl=0.5, dd=2.0, trapped=0.8)
        directional = self._result("D", pnl=1.0)
        structural = self._result("S", pnl=0.5, dd=0.3, trapped=0.1)
        admitted, reason = check_admission(challenger, directional, structural)
        self.assertFalse(admitted)
        self.assertIn(";", reason)  # multiple reasons


# ---------------------------------------------------------------------------
# Report formatting tests
# ---------------------------------------------------------------------------

class TestFormatReport(unittest.TestCase):
    """Tests for report formatting."""

    def test_report_contains_all_scenarios(self):
        scenarios = get_mandatory_scenarios()
        strategies = [DirectionalBTC5Strategy(), MeanReversionStrategy(), StructuralStrategy()]
        results = run_benchmark(scenarios, strategies)
        report = format_report(results)
        for s in scenarios:
            self.assertIn(s.name, report)

    def test_report_contains_strategy_names(self):
        scenarios = [build_march_11_winning_session()]
        strategies = [DirectionalBTC5Strategy(), MeanReversionStrategy()]
        results = run_benchmark(scenarios, strategies)
        report = format_report(results)
        self.assertIn("DirectionalBTC5", report)
        self.assertIn("MeanReversion", report)

    def test_report_contains_winner(self):
        scenarios = [build_march_11_winning_session()]
        strategies = [DirectionalBTC5Strategy()]
        results = run_benchmark(scenarios, strategies)
        report = format_report(results)
        self.assertIn("Winner:", report)

    def test_report_contains_admission_checks(self):
        scenarios = [build_march_11_winning_session()]
        strategies = [DirectionalBTC5Strategy(), MeanReversionStrategy(), StructuralStrategy()]
        results = run_benchmark(scenarios, strategies)
        report = format_report(results)
        self.assertIn("ADMISSION CHECKS", report)

    def test_empty_results_no_crash(self):
        report = format_report({})
        self.assertIn("BENCHMARK REPORT", report)


# ---------------------------------------------------------------------------
# Integration: full benchmark flow
# ---------------------------------------------------------------------------

class TestIntegration(unittest.TestCase):
    """End-to-end integration tests."""

    def test_full_benchmark_runs_without_error(self):
        scenarios = get_mandatory_scenarios()
        strategies = [DirectionalBTC5Strategy(), MeanReversionStrategy(), StructuralStrategy()]
        results = run_benchmark(scenarios, strategies)
        report = format_report(results)
        self.assertGreater(len(report), 100)

    def test_directional_wins_march_11(self):
        scenario = build_march_11_winning_session()
        d = DirectionalBTC5Strategy().evaluate(scenario)
        m = MeanReversionStrategy().evaluate(scenario)
        self.assertGreater(d.gross_pnl, m.gross_pnl,
                           "Directional should beat mean reversion on trending day")

    def test_directional_loses_march_22(self):
        scenario = build_march_22_loss_session()
        d = DirectionalBTC5Strategy().evaluate(scenario)
        self.assertLess(d.gross_pnl, 0)


if __name__ == "__main__":
    unittest.main()
