#!/usr/bin/env python3
"""
Tests for bot/promotion_manager.py — Promotion Stage Manager
=============================================================
55+ tests covering registration, fills, binomial test, promotion gates,
demotion triggers, cool-off, capital allocation, position caps, persistence,
and edge cases.

March 2026 — Elastifund / JJ
"""

import math
import os
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

# Ensure bot/ is importable
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bot.promotion_manager import (
    PromotionStage,
    StageGate,
    StrategyRecord,
    PromotionManager,
    binomial_test,
    STAGE_GATES,
    POSITION_CAP,
    STAGE_ALLOCATION_PCT,
    COOLOFF_DAYS,
    RESERVE_PCT,
)


class TestPromotionStageEnum(unittest.TestCase):
    """Enum value and ordering tests."""

    def test_stage_values(self):
        self.assertEqual(PromotionStage.HYPOTHESIS, 0)
        self.assertEqual(PromotionStage.BACKTESTED, 1)
        self.assertEqual(PromotionStage.SHADOW, 2)
        self.assertEqual(PromotionStage.MICRO_LIVE, 3)
        self.assertEqual(PromotionStage.SEED, 4)
        self.assertEqual(PromotionStage.SCALE, 5)
        self.assertEqual(PromotionStage.CORE, 6)

    def test_stage_ordering(self):
        self.assertTrue(PromotionStage.HYPOTHESIS < PromotionStage.CORE)
        self.assertTrue(PromotionStage.MICRO_LIVE < PromotionStage.SEED)

    def test_all_seven_stages(self):
        self.assertEqual(len(PromotionStage), 7)


class TestStageGate(unittest.TestCase):
    """StageGate dataclass tests."""

    def test_micro_live_gate_exists(self):
        gate = STAGE_GATES[PromotionStage.MICRO_LIVE]
        self.assertEqual(gate.min_fills, 50)
        self.assertEqual(gate.min_days, 14)
        self.assertAlmostEqual(gate.min_win_rate, 0.52)
        self.assertAlmostEqual(gate.min_profit_factor, 1.05)
        self.assertAlmostEqual(gate.max_drawdown_pct, 0.20)
        self.assertAlmostEqual(gate.min_sharpe, 0.5)
        self.assertAlmostEqual(gate.min_fill_rate, 0.30)
        self.assertAlmostEqual(gate.binomial_p_threshold, 0.05)

    def test_seed_gate_exists(self):
        gate = STAGE_GATES[PromotionStage.SEED]
        self.assertEqual(gate.min_fills, 200)
        self.assertEqual(gate.min_days, 30)
        self.assertAlmostEqual(gate.min_win_rate, 0.53)
        self.assertAlmostEqual(gate.min_profit_factor, 1.10)
        self.assertAlmostEqual(gate.max_drawdown_pct, 0.15)
        self.assertAlmostEqual(gate.min_sharpe, 1.0)
        self.assertAlmostEqual(gate.min_kelly, 0.02)

    def test_gate_is_frozen(self):
        gate = STAGE_GATES[PromotionStage.MICRO_LIVE]
        with self.assertRaises(AttributeError):
            gate.min_fills = 999


class TestBinomialTest(unittest.TestCase):
    """Exact one-tailed binomial test correctness."""

    def test_known_value_n50_k32_significant(self):
        # n=50, k=32 should give p < 0.05 (per spec)
        p = binomial_test(50, 32, 0.50)
        self.assertLess(p, 0.05, f"p={p} should be < 0.05")

    def test_known_value_n50_k25_not_significant(self):
        # n=50, k=25 is exactly 50%, p should be > 0.05
        p = binomial_test(50, 25, 0.50)
        self.assertGreater(p, 0.05, f"p={p} should be > 0.05")

    def test_n50_k26_not_significant(self):
        # n=50, k=26: borderline, should be > 0.05
        p = binomial_test(50, 26, 0.50)
        self.assertGreater(p, 0.10)

    def test_all_wins(self):
        p = binomial_test(50, 50, 0.50)
        self.assertLess(p, 1e-10)

    def test_all_losses(self):
        p = binomial_test(50, 0, 0.50)
        self.assertAlmostEqual(p, 1.0, places=5)

    def test_zero_trials(self):
        p = binomial_test(0, 0, 0.50)
        self.assertEqual(p, 1.0)

    def test_k_greater_than_n(self):
        p = binomial_test(10, 15, 0.50)
        self.assertAlmostEqual(p, 0.0)

    def test_p0_zero(self):
        p = binomial_test(10, 5, 0.0)
        self.assertAlmostEqual(p, 0.0)

    def test_p0_one(self):
        p = binomial_test(10, 5, 1.0)
        self.assertAlmostEqual(p, 1.0)

    def test_n100_k59_significant(self):
        # Per spec: at N=100, K>=59 clears p<0.05
        p = binomial_test(100, 59, 0.50)
        self.assertLess(p, 0.05)

    def test_n200_k113_significant(self):
        # Per spec says K>=112 at N=200 but exact p(112)=0.0518; K=113 clears
        p = binomial_test(200, 113, 0.50)
        self.assertLess(p, 0.05)


class TestStrategyRecord(unittest.TestCase):
    """StrategyRecord derived properties."""

    def test_win_rate_no_fills(self):
        rec = StrategyRecord("test", PromotionStage.HYPOTHESIS, time.time())
        self.assertEqual(rec.win_rate, 0.0)

    def test_win_rate_calculation(self):
        rec = StrategyRecord("test", PromotionStage.HYPOTHESIS, time.time(),
                             wins=60, losses=40)
        self.assertAlmostEqual(rec.win_rate, 0.60)

    def test_profit_factor_from_metadata(self):
        rec = StrategyRecord("test", PromotionStage.HYPOTHESIS, time.time(),
                             metadata={"gross_wins": 150.0, "gross_losses": 100.0})
        self.assertAlmostEqual(rec.profit_factor, 1.50)

    def test_profit_factor_zero_losses(self):
        rec = StrategyRecord("test", PromotionStage.HYPOTHESIS, time.time(),
                             metadata={"gross_wins": 100.0, "gross_losses": 0.0})
        self.assertEqual(rec.profit_factor, float("inf"))

    def test_profit_factor_no_data(self):
        rec = StrategyRecord("test", PromotionStage.HYPOTHESIS, time.time())
        self.assertEqual(rec.profit_factor, 0.0)

    def test_kelly_fraction(self):
        rec = StrategyRecord("test", PromotionStage.HYPOTHESIS, time.time(),
                             wins=60, losses=40,
                             metadata={"gross_wins": 120.0, "gross_losses": 80.0})
        # PF = 1.5, WR = 0.6
        # kelly = (b*p - q) / b = (1.5*0.6 - 0.4) / 1.5 = (0.9 - 0.4) / 1.5 = 0.333
        self.assertAlmostEqual(rec.kelly_fraction, 1/3, places=3)

    def test_drawdown_calculation(self):
        rec = StrategyRecord("test", PromotionStage.HYPOTHESIS, time.time(),
                             daily_pnl_history=[10, 5, -20, 3])
        # cum: 10, 15, -5, -2; peak=15; dd = 15 - (-2) = 17
        self.assertAlmostEqual(rec.current_drawdown, 17.0)

    def test_drawdown_no_history(self):
        rec = StrategyRecord("test", PromotionStage.HYPOTHESIS, time.time())
        self.assertEqual(rec.current_drawdown, 0.0)

    def test_peak_equity(self):
        rec = StrategyRecord("test", PromotionStage.HYPOTHESIS, time.time(),
                             daily_pnl_history=[10, 5, -20, 3])
        self.assertAlmostEqual(rec.peak_equity, 15.0)


class _PromotionManagerTestBase(unittest.TestCase):
    """Base class that creates a temp DB for each test."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self._tmpdir, "test_promo.db")
        self.pm = PromotionManager(self.db_path)

    def tearDown(self):
        self.pm.close()
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)
        os.rmdir(self._tmpdir)


class TestRegistration(_PromotionManagerTestBase):
    """Strategy registration tests."""

    def test_register_new(self):
        rec = self.pm.register_strategy("alpha_1")
        self.assertEqual(rec.strategy_id, "alpha_1")
        self.assertEqual(rec.current_stage, PromotionStage.HYPOTHESIS)
        self.assertEqual(rec.fills, 0)

    def test_register_at_specific_stage(self):
        rec = self.pm.register_strategy("btc5", PromotionStage.SHADOW)
        self.assertEqual(rec.current_stage, PromotionStage.SHADOW)

    def test_register_duplicate_returns_existing(self):
        rec1 = self.pm.register_strategy("alpha_1")
        rec2 = self.pm.register_strategy("alpha_1")
        self.assertIs(rec1, rec2)

    def test_register_multiple_strategies(self):
        self.pm.register_strategy("a")
        self.pm.register_strategy("b")
        self.pm.register_strategy("c")
        self.assertEqual(len(self.pm.get_all_strategies()), 3)

    def test_register_all_stages(self):
        for stage in PromotionStage:
            sid = f"strat_{stage.name}"
            rec = self.pm.register_strategy(sid, stage)
            self.assertEqual(rec.current_stage, stage)


class TestFillRecording(_PromotionManagerTestBase):
    """Fill recording and stat updates."""

    def test_record_win(self):
        self.pm.register_strategy("s1")
        rec = self.pm.record_fill("s1", won=True, pnl=2.50)
        self.assertEqual(rec.fills, 1)
        self.assertEqual(rec.wins, 1)
        self.assertEqual(rec.losses, 0)
        self.assertAlmostEqual(rec.gross_pnl, 2.50)

    def test_record_loss(self):
        self.pm.register_strategy("s1")
        rec = self.pm.record_fill("s1", won=False, pnl=-1.50)
        self.assertEqual(rec.fills, 1)
        self.assertEqual(rec.wins, 0)
        self.assertEqual(rec.losses, 1)
        self.assertAlmostEqual(rec.gross_pnl, -1.50)

    def test_multiple_fills_update_stats(self):
        self.pm.register_strategy("s1")
        for _ in range(30):
            self.pm.record_fill("s1", won=True, pnl=1.0)
        for _ in range(20):
            self.pm.record_fill("s1", won=False, pnl=-0.80)
        rec = self.pm.get_strategy("s1")
        self.assertEqual(rec.fills, 50)
        self.assertEqual(rec.wins, 30)
        self.assertEqual(rec.losses, 20)
        self.assertAlmostEqual(rec.win_rate, 0.60)

    def test_slippage_tracking(self):
        self.pm.register_strategy("s1")
        self.pm.record_fill("s1", won=True, pnl=1.0, fill_price=0.52, expected_price=0.50)
        rec = self.pm.get_strategy("s1")
        self.assertEqual(len(rec.slippage_values), 1)
        self.assertAlmostEqual(rec.slippage_values[0], 0.04)

    def test_fill_rate_with_submitted_orders(self):
        self.pm.register_strategy("s1")
        for _ in range(10):
            self.pm.record_order_submitted("s1")
        for _ in range(3):
            self.pm.record_fill("s1", won=True, pnl=1.0)
        rec = self.pm.get_strategy("s1")
        self.assertAlmostEqual(rec.fill_rate, 3 / 10)

    def test_gross_wins_losses_metadata(self):
        self.pm.register_strategy("s1")
        self.pm.record_fill("s1", won=True, pnl=5.0)
        self.pm.record_fill("s1", won=True, pnl=3.0)
        self.pm.record_fill("s1", won=False, pnl=-2.0)
        rec = self.pm.get_strategy("s1")
        self.assertAlmostEqual(rec.metadata["gross_wins"], 8.0)
        self.assertAlmostEqual(rec.metadata["gross_losses"], 2.0)
        self.assertAlmostEqual(rec.profit_factor, 4.0)


class TestDayClose(_PromotionManagerTestBase):
    """Day close recording and drawdown."""

    def test_day_close_updates_history(self):
        self.pm.register_strategy("s1")
        self.pm.record_day_close("s1", 10.0)
        self.pm.record_day_close("s1", -5.0)
        rec = self.pm.get_strategy("s1")
        self.assertEqual(len(rec.daily_pnl_history), 2)
        self.assertAlmostEqual(rec.daily_pnl_history[0], 10.0)
        self.assertAlmostEqual(rec.daily_pnl_history[1], -5.0)

    def test_max_drawdown_computation(self):
        self.pm.register_strategy("s1")
        for pnl in [10, 5, -20, 3]:
            self.pm.record_day_close("s1", pnl)
        rec = self.pm.get_strategy("s1")
        # cum: 10, 15, -5, -2; peak=15; max_dd = 15 - (-5) = 20
        self.assertAlmostEqual(rec.max_drawdown, 20.0)

    def test_sharpe_computation(self):
        self.pm.register_strategy("s1")
        # All positive days, low variance -> high Sharpe
        for _ in range(30):
            self.pm.record_day_close("s1", 1.0)
        rec = self.pm.get_strategy("s1")
        # mean=1, std=0 -> Sharpe is 0 (division by zero protection)
        # But with tiny variance from floating point, let's just check it's finite
        self.assertTrue(math.isfinite(rec.sharpe) or rec.sharpe == 0.0)


class TestPromotionEligibility(_PromotionManagerTestBase):
    """Promotion gate checking."""

    def _make_eligible_for_micro_live(self, sid: str):
        """Create a strategy with stats that pass all MICRO_LIVE gates."""
        self.pm.register_strategy(sid, PromotionStage.SHADOW)
        rec = self.pm.get_strategy(sid)
        # Backdate stage entry so min_days passes
        rec.stage_entered_at = time.time() - (15 * 86400)
        # Simulate 50 fills: 35 wins, 15 losses (WR=70%, binomial p << 0.05)
        rec.fills = 50
        rec.wins = 35
        rec.losses = 15
        rec.metadata["gross_wins"] = 70.0
        rec.metadata["gross_losses"] = 30.0
        rec.gross_pnl = 40.0
        rec.max_drawdown = 5.0
        rec.sharpe = 1.5
        rec.fill_rate = 0.50
        rec.orders_submitted = 100
        self.pm._save_record(rec)

    def test_eligible_for_micro_live(self):
        self._make_eligible_for_micro_live("s1")
        result = self.pm.check_promotion("s1")
        self.assertTrue(result["eligible"], f"Failed gates: {result['gates_failed']}")
        self.assertEqual(result["target_stage"], int(PromotionStage.MICRO_LIVE))

    def test_not_eligible_insufficient_fills(self):
        self.pm.register_strategy("s1", PromotionStage.SHADOW)
        rec = self.pm.get_strategy("s1")
        rec.stage_entered_at = time.time() - (15 * 86400)
        rec.fills = 10
        rec.wins = 8
        rec.losses = 2
        rec.metadata["gross_wins"] = 16.0
        rec.metadata["gross_losses"] = 4.0
        rec.sharpe = 1.0
        rec.fill_rate = 0.50
        rec.orders_submitted = 20
        self.pm._save_record(rec)

        result = self.pm.check_promotion("s1")
        self.assertFalse(result["eligible"])
        self.assertIn("min_fills", result["gates_failed"])

    def test_not_eligible_low_sharpe(self):
        self._make_eligible_for_micro_live("s1")
        rec = self.pm.get_strategy("s1")
        rec.sharpe = 0.1  # below 0.5 threshold
        self.pm._save_record(rec)

        result = self.pm.check_promotion("s1")
        self.assertFalse(result["eligible"])
        self.assertIn("min_sharpe", result["gates_failed"])

    def test_not_eligible_low_fill_rate(self):
        self._make_eligible_for_micro_live("s1")
        rec = self.pm.get_strategy("s1")
        rec.fill_rate = 0.10  # below 30%
        self.pm._save_record(rec)

        result = self.pm.check_promotion("s1")
        self.assertFalse(result["eligible"])
        self.assertIn("min_fill_rate", result["gates_failed"])

    def test_not_eligible_binomial_fail(self):
        self.pm.register_strategy("s1", PromotionStage.SHADOW)
        rec = self.pm.get_strategy("s1")
        rec.stage_entered_at = time.time() - (15 * 86400)
        # 50 fills, only 26 wins -> binomial p > 0.05
        rec.fills = 50
        rec.wins = 26
        rec.losses = 24
        rec.metadata["gross_wins"] = 28.0
        rec.metadata["gross_losses"] = 24.0
        rec.sharpe = 1.0
        rec.fill_rate = 0.50
        rec.orders_submitted = 100
        rec.max_drawdown = 5.0
        self.pm._save_record(rec)

        result = self.pm.check_promotion("s1")
        self.assertFalse(result["eligible"])
        self.assertIn("binomial_test", result["gates_failed"])

    def test_multiple_gates_fail(self):
        self.pm.register_strategy("s1", PromotionStage.SHADOW)
        rec = self.pm.get_strategy("s1")
        rec.fills = 5
        rec.wins = 2
        rec.losses = 3
        self.pm._save_record(rec)

        result = self.pm.check_promotion("s1")
        self.assertFalse(result["eligible"])
        self.assertGreater(len(result["gates_failed"]), 1)

    def test_already_at_core(self):
        self.pm.register_strategy("s1", PromotionStage.CORE)
        result = self.pm.check_promotion("s1")
        self.assertFalse(result["eligible"])
        self.assertIn("already_at_max_stage", result["gates_failed"])

    def test_core_requires_human_approval(self):
        self.pm.register_strategy("s1", PromotionStage.SCALE)
        result = self.pm.check_promotion("s1")
        self.assertFalse(result["eligible"])
        self.assertIn("requires_human_approval", result["gates_failed"])

    def test_hypothesis_to_backtested_no_quant_gate(self):
        self.pm.register_strategy("s1", PromotionStage.HYPOTHESIS)
        result = self.pm.check_promotion("s1")
        self.assertTrue(result["eligible"])
        self.assertEqual(result["target_stage"], int(PromotionStage.BACKTESTED))

    def test_backtested_to_shadow_no_quant_gate(self):
        self.pm.register_strategy("s1", PromotionStage.BACKTESTED)
        result = self.pm.check_promotion("s1")
        self.assertTrue(result["eligible"])


class TestPromotionExecution(_PromotionManagerTestBase):
    """Promote() actually advances stages."""

    def _make_eligible_for_micro_live(self, sid: str):
        self.pm.register_strategy(sid, PromotionStage.SHADOW)
        rec = self.pm.get_strategy(sid)
        rec.stage_entered_at = time.time() - (15 * 86400)
        rec.fills = 50
        rec.wins = 35
        rec.losses = 15
        rec.metadata["gross_wins"] = 70.0
        rec.metadata["gross_losses"] = 30.0
        rec.gross_pnl = 40.0
        rec.max_drawdown = 5.0
        rec.sharpe = 1.5
        rec.fill_rate = 0.50
        rec.orders_submitted = 100
        self.pm._save_record(rec)

    def test_promote_advances_stage(self):
        self._make_eligible_for_micro_live("s1")
        rec = self.pm.promote("s1")
        self.assertEqual(rec.current_stage, PromotionStage.MICRO_LIVE)

    def test_promote_resets_counters(self):
        self._make_eligible_for_micro_live("s1")
        rec = self.pm.promote("s1")
        self.assertEqual(rec.fills, 0)
        self.assertEqual(rec.wins, 0)
        self.assertEqual(rec.losses, 0)
        self.assertAlmostEqual(rec.gross_pnl, 0.0)

    def test_promote_changes_position_cap(self):
        self.pm.register_strategy("s1", PromotionStage.HYPOTHESIS)
        old_cap = self.pm.get_position_cap("s1")
        self.assertAlmostEqual(old_cap, 0.0)

        self.pm.promote("s1")  # -> BACKTESTED
        self.pm.promote("s1")  # -> SHADOW
        self._make_eligible_for_micro_live_from_shadow("s1")
        self.pm.promote("s1")  # -> MICRO_LIVE
        new_cap = self.pm.get_position_cap("s1")
        self.assertAlmostEqual(new_cap, 5.0)

    def _make_eligible_for_micro_live_from_shadow(self, sid: str):
        rec = self.pm.get_strategy(sid)
        rec.stage_entered_at = time.time() - (15 * 86400)
        rec.fills = 50
        rec.wins = 35
        rec.losses = 15
        rec.metadata["gross_wins"] = 70.0
        rec.metadata["gross_losses"] = 30.0
        rec.gross_pnl = 40.0
        rec.max_drawdown = 5.0
        rec.sharpe = 1.5
        rec.fill_rate = 0.50
        rec.orders_submitted = 100
        self.pm._save_record(rec)

    def test_promote_raises_if_not_eligible(self):
        self.pm.register_strategy("s1", PromotionStage.SHADOW)
        # No fills at all
        with self.assertRaises(ValueError):
            self.pm.promote("s1")

    def test_promote_logs_event(self):
        self._make_eligible_for_micro_live("s1")
        self.pm.promote("s1")
        events = self.pm.get_events("s1")
        promo_events = [e for e in events if e["event_type"] == "promotion"]
        self.assertGreaterEqual(len(promo_events), 1)
        self.assertEqual(promo_events[-1]["from_stage"], int(PromotionStage.SHADOW))
        self.assertEqual(promo_events[-1]["to_stage"], int(PromotionStage.MICRO_LIVE))


class TestDemotionTriggers(_PromotionManagerTestBase):
    """Demotion trigger detection."""

    def test_no_demotion_below_micro_live(self):
        self.pm.register_strategy("s1", PromotionStage.SHADOW)
        result = self.pm.check_demotion("s1")
        self.assertFalse(result["should_demote"])

    def test_severe_pf_collapse(self):
        self.pm.register_strategy("s1", PromotionStage.MICRO_LIVE)
        rec = self.pm.get_strategy("s1")
        rec.fills = 20
        rec.wins = 5
        rec.losses = 15
        rec.metadata["gross_wins"] = 5.0
        rec.metadata["gross_losses"] = 15.0  # PF = 0.33
        self.pm._save_record(rec)

        result = self.pm.check_demotion("s1")
        self.assertTrue(result["should_demote"])
        self.assertEqual(result["severity"], "severe")
        self.assertIn("profit_factor_collapse", result["triggers"])

    def test_severe_fill_rate_collapse(self):
        self.pm.register_strategy("s1", PromotionStage.MICRO_LIVE)
        rec = self.pm.get_strategy("s1")
        rec.orders_submitted = 100
        rec.fills = 5  # 5% fill rate
        rec.fill_rate = 0.05
        self.pm._save_record(rec)

        result = self.pm.check_demotion("s1")
        self.assertTrue(result["should_demote"])
        self.assertEqual(result["severity"], "severe")
        self.assertIn("fill_rate_collapse", result["triggers"])

    def test_moderate_three_losing_days(self):
        self.pm.register_strategy("s1", PromotionStage.MICRO_LIVE)
        self.pm.record_day_close("s1", -1.0)
        self.pm.record_day_close("s1", -2.0)
        self.pm.record_day_close("s1", -0.5)

        result = self.pm.check_demotion("s1")
        self.assertTrue(result["should_demote"])
        self.assertEqual(result["severity"], "moderate")
        self.assertIn("three_consecutive_losing_days", result["triggers"])

    def test_moderate_win_rate_below_min(self):
        self.pm.register_strategy("s1", PromotionStage.MICRO_LIVE)
        rec = self.pm.get_strategy("s1")
        rec.fills = 30
        rec.wins = 10
        rec.losses = 20  # WR = 33%
        rec.metadata["gross_wins"] = 10.0
        rec.metadata["gross_losses"] = 20.0
        self.pm._save_record(rec)

        result = self.pm.check_demotion("s1")
        self.assertTrue(result["should_demote"])
        self.assertIn("win_rate_below_minimum", result["triggers"])

    def test_no_demotion_healthy_strategy(self):
        self.pm.register_strategy("s1", PromotionStage.MICRO_LIVE)
        rec = self.pm.get_strategy("s1")
        rec.fills = 30
        rec.wins = 20
        rec.losses = 10
        rec.metadata["gross_wins"] = 40.0
        rec.metadata["gross_losses"] = 10.0
        rec.fill_rate = 0.50
        rec.orders_submitted = 60
        self.pm._save_record(rec)
        self.pm.record_day_close("s1", 5.0)
        self.pm.record_day_close("s1", 3.0)

        result = self.pm.check_demotion("s1")
        self.assertFalse(result["should_demote"])


class TestDemotionExecution(_PromotionManagerTestBase):
    """Demote() moves strategies down."""

    def test_demote_one_stage(self):
        self.pm.register_strategy("s1", PromotionStage.MICRO_LIVE)
        rec = self.pm.demote("s1", reason="test demotion")
        self.assertEqual(rec.current_stage, PromotionStage.SHADOW)

    def test_demote_pf_collapse_skips_stage(self):
        self.pm.register_strategy("s1", PromotionStage.SEED)
        rec = self.pm.demote("s1", reason="profit_factor_collapse")
        # Should skip one extra stage: SEED(4) -> SHADOW(2)
        self.assertEqual(rec.current_stage, PromotionStage.SHADOW)

    def test_demote_fill_rate_to_shadow(self):
        self.pm.register_strategy("s1", PromotionStage.SCALE)
        rec = self.pm.demote("s1", reason="fill_rate_collapse")
        self.assertEqual(rec.current_stage, PromotionStage.SHADOW)

    def test_demote_resets_stats(self):
        self.pm.register_strategy("s1", PromotionStage.MICRO_LIVE)
        rec = self.pm.get_strategy("s1")
        rec.fills = 30
        rec.wins = 20
        self.pm._save_record(rec)

        rec = self.pm.demote("s1", reason="test")
        self.assertEqual(rec.fills, 0)
        self.assertEqual(rec.wins, 0)

    def test_demote_records_reason(self):
        self.pm.register_strategy("s1", PromotionStage.MICRO_LIVE)
        rec = self.pm.demote("s1", reason="drawdown_breach")
        self.assertEqual(rec.demotion_reason, "drawdown_breach")

    def test_demote_logs_event(self):
        self.pm.register_strategy("s1", PromotionStage.MICRO_LIVE)
        self.pm.demote("s1", reason="test")
        events = self.pm.get_events("s1")
        demo_events = [e for e in events if e["event_type"] == "demotion"]
        self.assertGreaterEqual(len(demo_events), 1)

    def test_cannot_demote_below_hypothesis(self):
        self.pm.register_strategy("s1", PromotionStage.HYPOTHESIS)
        rec = self.pm.demote("s1", reason="test")
        self.assertEqual(rec.current_stage, PromotionStage.HYPOTHESIS)


class TestCoolOff(_PromotionManagerTestBase):
    """Cool-off enforcement."""

    def test_cooloff_blocks_promotion(self):
        self.pm.register_strategy("s1", PromotionStage.MICRO_LIVE)
        self.pm.demote("s1", reason="test")  # -> SHADOW, 7 day cooloff

        result = self.pm.check_promotion("s1")
        self.assertFalse(result["eligible"])
        self.assertIn("cooloff_active", result["gates_failed"])

    def test_cooloff_duration_stage3(self):
        self.pm.register_strategy("s1", PromotionStage.MICRO_LIVE)
        before = time.time()
        self.pm.demote("s1", reason="test")
        rec = self.pm.get_strategy("s1")
        expected_cooloff = before + (7 * 86400)
        self.assertAlmostEqual(rec.cooloff_until, expected_cooloff, delta=5.0)

    def test_cooloff_duration_stage4(self):
        self.pm.register_strategy("s1", PromotionStage.SEED)
        before = time.time()
        self.pm.demote("s1", reason="test")
        rec = self.pm.get_strategy("s1")
        expected_cooloff = before + (14 * 86400)
        self.assertAlmostEqual(rec.cooloff_until, expected_cooloff, delta=5.0)

    def test_cooloff_duration_stage5(self):
        self.pm.register_strategy("s1", PromotionStage.SCALE)
        before = time.time()
        self.pm.demote("s1", reason="test")
        rec = self.pm.get_strategy("s1")
        expected_cooloff = before + (21 * 86400)
        self.assertAlmostEqual(rec.cooloff_until, expected_cooloff, delta=5.0)

    def test_expired_cooloff_allows_promotion(self):
        self.pm.register_strategy("s1", PromotionStage.HYPOTHESIS)
        rec = self.pm.get_strategy("s1")
        rec.cooloff_until = time.time() - 100  # expired
        self.pm._save_record(rec)

        result = self.pm.check_promotion("s1")
        self.assertTrue(result["eligible"])


class TestCapitalAllocation(_PromotionManagerTestBase):
    """Capital allocation per stage."""

    def test_micro_live_allocation(self):
        self.pm.register_strategy("s1", PromotionStage.MICRO_LIVE)
        alloc = self.pm.get_capital_allocation("s1", bankroll=1000.0)
        self.assertAlmostEqual(alloc, 100.0)  # 10% of 1000

    def test_seed_allocation(self):
        self.pm.register_strategy("s1", PromotionStage.SEED)
        alloc = self.pm.get_capital_allocation("s1", bankroll=1000.0)
        self.assertAlmostEqual(alloc, 200.0)  # 20% of 1000

    def test_scale_allocation(self):
        self.pm.register_strategy("s1", PromotionStage.SCALE)
        alloc = self.pm.get_capital_allocation("s1", bankroll=2000.0)
        self.assertAlmostEqual(alloc, 1000.0)  # 50% of 2000

    def test_allocation_splits_among_strategies(self):
        self.pm.register_strategy("a", PromotionStage.MICRO_LIVE)
        self.pm.register_strategy("b", PromotionStage.MICRO_LIVE)
        alloc_a = self.pm.get_capital_allocation("a", bankroll=1000.0)
        alloc_b = self.pm.get_capital_allocation("b", bankroll=1000.0)
        self.assertAlmostEqual(alloc_a, 50.0)  # 10% / 2
        self.assertAlmostEqual(alloc_b, 50.0)

    def test_shadow_allocation_is_zero(self):
        self.pm.register_strategy("s1", PromotionStage.SHADOW)
        alloc = self.pm.get_capital_allocation("s1", bankroll=1000.0)
        self.assertAlmostEqual(alloc, 0.0)

    def test_hypothesis_allocation_is_zero(self):
        self.pm.register_strategy("s1", PromotionStage.HYPOTHESIS)
        alloc = self.pm.get_capital_allocation("s1", bankroll=5000.0)
        self.assertAlmostEqual(alloc, 0.0)

    def test_different_bankroll_levels(self):
        self.pm.register_strategy("s1", PromotionStage.MICRO_LIVE)
        self.assertAlmostEqual(self.pm.get_capital_allocation("s1", bankroll=500.0), 50.0)
        self.assertAlmostEqual(self.pm.get_capital_allocation("s1", bankroll=10000.0), 1000.0)


class TestPositionCap(_PromotionManagerTestBase):
    """Position cap per stage."""

    def test_hypothesis_cap(self):
        self.pm.register_strategy("s1", PromotionStage.HYPOTHESIS)
        self.assertAlmostEqual(self.pm.get_position_cap("s1"), 0.0)

    def test_shadow_cap(self):
        self.pm.register_strategy("s1", PromotionStage.SHADOW)
        self.assertAlmostEqual(self.pm.get_position_cap("s1"), 0.0)

    def test_micro_live_cap(self):
        self.pm.register_strategy("s1", PromotionStage.MICRO_LIVE)
        self.assertAlmostEqual(self.pm.get_position_cap("s1"), 5.0)

    def test_seed_cap(self):
        self.pm.register_strategy("s1", PromotionStage.SEED)
        self.assertAlmostEqual(self.pm.get_position_cap("s1"), 25.0)

    def test_scale_cap(self):
        self.pm.register_strategy("s1", PromotionStage.SCALE)
        self.assertAlmostEqual(self.pm.get_position_cap("s1"), 100.0)

    def test_core_cap_is_infinite(self):
        self.pm.register_strategy("s1", PromotionStage.CORE)
        self.assertEqual(self.pm.get_position_cap("s1"), float("inf"))


class TestStageSummary(_PromotionManagerTestBase):
    """Stage summary reporting."""

    def test_empty_summary(self):
        summary = self.pm.get_stage_summary(bankroll=1000.0)
        self.assertEqual(summary["total_strategies"], 0)
        self.assertAlmostEqual(summary["reserve"], 1000.0)

    def test_summary_with_strategies(self):
        self.pm.register_strategy("a", PromotionStage.MICRO_LIVE)
        self.pm.register_strategy("b", PromotionStage.MICRO_LIVE)
        self.pm.register_strategy("c", PromotionStage.SEED)

        summary = self.pm.get_stage_summary(bankroll=1000.0)
        self.assertEqual(summary["counts"]["MICRO_LIVE"], 2)
        self.assertEqual(summary["counts"]["SEED"], 1)
        self.assertEqual(summary["total_strategies"], 3)
        self.assertAlmostEqual(summary["capital"]["MICRO_LIVE"], 100.0)
        self.assertAlmostEqual(summary["capital"]["SEED"], 200.0)

    def test_reserve_minimum(self):
        self.pm.register_strategy("s1", PromotionStage.MICRO_LIVE)
        summary = self.pm.get_stage_summary(bankroll=1000.0)
        self.assertGreaterEqual(summary["reserve"], 100.0)


class TestSQLitePersistence(_PromotionManagerTestBase):
    """Close and reopen DB, data intact."""

    def test_persist_and_reload(self):
        self.pm.register_strategy("alpha")
        self.pm.record_fill("alpha", won=True, pnl=5.0)
        self.pm.record_day_close("alpha", 5.0)
        self.pm.close()

        # Reopen
        pm2 = PromotionManager(self.db_path)
        rec = pm2.get_strategy("alpha")
        self.assertIsNotNone(rec)
        self.assertEqual(rec.strategy_id, "alpha")
        self.assertEqual(rec.fills, 1)
        self.assertEqual(rec.wins, 1)
        self.assertAlmostEqual(rec.gross_pnl, 5.0)
        self.assertEqual(len(rec.daily_pnl_history), 1)
        pm2.close()

    def test_events_persist(self):
        self.pm.register_strategy("alpha")
        self.pm.close()

        pm2 = PromotionManager(self.db_path)
        events = pm2.get_events("alpha")
        self.assertGreaterEqual(len(events), 1)
        pm2.close()

    def test_multiple_strategies_persist(self):
        self.pm.register_strategy("a")
        self.pm.register_strategy("b", PromotionStage.SHADOW)
        self.pm.register_strategy("c", PromotionStage.MICRO_LIVE)
        self.pm.close()

        pm2 = PromotionManager(self.db_path)
        strats = pm2.get_all_strategies()
        self.assertEqual(len(strats), 3)
        ids = {s.strategy_id for s in strats}
        self.assertEqual(ids, {"a", "b", "c"})
        pm2.close()


class TestEdgeCases(_PromotionManagerTestBase):
    """Edge cases: zero fills, negative P&L, 100% win rate, etc."""

    def test_zero_fills_strategy(self):
        self.pm.register_strategy("empty")
        rec = self.pm.get_strategy("empty")
        self.assertEqual(rec.win_rate, 0.0)
        self.assertEqual(rec.profit_factor, 0.0)
        self.assertEqual(rec.kelly_fraction, 0.0)

    def test_100_percent_win_rate(self):
        self.pm.register_strategy("winner")
        for _ in range(10):
            self.pm.record_fill("winner", won=True, pnl=2.0)
        rec = self.pm.get_strategy("winner")
        self.assertAlmostEqual(rec.win_rate, 1.0)
        self.assertEqual(rec.profit_factor, float("inf"))

    def test_negative_pnl_only(self):
        self.pm.register_strategy("loser")
        for _ in range(10):
            self.pm.record_fill("loser", won=False, pnl=-1.0)
        rec = self.pm.get_strategy("loser")
        self.assertAlmostEqual(rec.win_rate, 0.0)
        self.assertAlmostEqual(rec.gross_pnl, -10.0)

    def test_get_nonexistent_strategy(self):
        rec = self.pm.get_strategy("does_not_exist")
        self.assertIsNone(rec)

    def test_large_number_of_fills(self):
        self.pm.register_strategy("bulk")
        for i in range(500):
            won = i % 3 != 0  # ~67% win rate
            self.pm.record_fill("bulk", won=won, pnl=1.0 if won else -1.0)
        rec = self.pm.get_strategy("bulk")
        self.assertEqual(rec.fills, 500)
        self.assertGreater(rec.win_rate, 0.60)


class TestConstantValues(unittest.TestCase):
    """Verify constants match the spec."""

    def test_position_caps(self):
        self.assertAlmostEqual(POSITION_CAP[PromotionStage.MICRO_LIVE], 5.0)
        self.assertAlmostEqual(POSITION_CAP[PromotionStage.SEED], 25.0)
        self.assertAlmostEqual(POSITION_CAP[PromotionStage.SCALE], 100.0)
        self.assertEqual(POSITION_CAP[PromotionStage.CORE], float("inf"))

    def test_allocation_pcts(self):
        self.assertAlmostEqual(STAGE_ALLOCATION_PCT[PromotionStage.MICRO_LIVE], 0.10)
        self.assertAlmostEqual(STAGE_ALLOCATION_PCT[PromotionStage.SEED], 0.20)
        self.assertAlmostEqual(STAGE_ALLOCATION_PCT[PromotionStage.SCALE], 0.50)

    def test_cooloff_days(self):
        self.assertEqual(COOLOFF_DAYS[PromotionStage.MICRO_LIVE], 7)
        self.assertEqual(COOLOFF_DAYS[PromotionStage.SEED], 14)
        self.assertEqual(COOLOFF_DAYS[PromotionStage.SCALE], 21)

    def test_reserve_pct(self):
        self.assertAlmostEqual(RESERVE_PCT, 0.10)


if __name__ == "__main__":
    unittest.main()
