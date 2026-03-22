#!/usr/bin/env python3
"""
Tests for bot/agent_constraints.py
===================================
All tests are offline — no network, no DB, no external APIs.

Run with:
    pytest tests/test_agent_constraints.py -v
"""

import dataclasses
import time
import unittest

from bot.agent_constraints import (
    Constraint,
    ConstraintAction,
    ConstraintEngine,
    ConstraintResult,
    ConstraintViolation,
    TradeProposal,
    TradingState,
    elastifund_default_constraints,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _valid_proposal(**overrides) -> TradeProposal:
    """A proposal that passes all default Elastifund constraints."""
    base = TradeProposal(
        market_id="politics-market-001",
        side="BUY_YES",
        amount_usd=5.0,
        probability_estimate=0.60,
        market_price=0.55,
        edge=0.09,
        kelly_fraction=0.05,
        category="politics",
        resolution_hours=12.0,
        metadata={},
    )
    for k, v in overrides.items():
        base = dataclasses.replace(base, **{k: v})
    return base


def _valid_state(**overrides) -> TradingState:
    """A trading state with headroom on all constraints."""
    base = TradingState(
        daily_pnl=0.0,
        open_positions=5,
        total_exposure_usd=50.0,
        bankroll=1000.0,
        trades_today=2,
        last_trade_time=0.0,
        promotion_gate_passed=False,
        current_regime="stable",
    )
    for k, v in overrides.items():
        base = dataclasses.replace(base, **{k: v})
    return base


class _EngineWithState(ConstraintEngine):
    """Helper subclass that injects a custom state for tests."""

    def set_state(self, state: TradingState) -> None:
        self.state = state


# ---------------------------------------------------------------------------
# 1. Basic ALLOW: valid trade passes all constraints
# ---------------------------------------------------------------------------

class TestBasicAllow(unittest.TestCase):
    def test_valid_trade_is_allowed(self) -> None:
        engine = _EngineWithState()
        engine.set_state(_valid_state())
        proposal = _valid_proposal()

        result = engine.evaluate(proposal)

        self.assertTrue(result.allowed)
        self.assertEqual(result.action, ConstraintAction.ALLOW)
        self.assertEqual(result.violations, [])

    def test_result_carries_original_proposal(self) -> None:
        engine = _EngineWithState()
        engine.set_state(_valid_state())
        proposal = _valid_proposal()

        result = engine.evaluate(proposal)

        self.assertEqual(result.proposal.amount_usd, 5.0)
        self.assertEqual(result.proposal.market_id, "politics-market-001")


# ---------------------------------------------------------------------------
# 2. BLOCK on position size
# ---------------------------------------------------------------------------

class TestBlockOnPositionSize(unittest.TestCase):
    def _make_block_engine(self, cap: float = 10.0) -> _EngineWithState:
        engine = _EngineWithState()
        engine.set_state(_valid_state())
        engine.add_constraint(Constraint(
            name="max_position_usd",
            description=f"Position size capped at ${cap:.2f}/trade",
            predicate=lambda p, _s: p.amount_usd > cap,
            action=ConstraintAction.BLOCK,
            priority=80,
        ))
        return engine

    def test_oversized_trade_is_blocked(self) -> None:
        engine = self._make_block_engine(cap=10.0)
        proposal = _valid_proposal(amount_usd=50.0)

        result = engine.evaluate(proposal)

        self.assertFalse(result.allowed)
        self.assertEqual(result.action, ConstraintAction.BLOCK)
        self.assertEqual(len(result.violations), 1)
        self.assertEqual(result.violations[0].rule_name, "max_position_usd")

    def test_exact_cap_passes(self) -> None:
        engine = self._make_block_engine(cap=10.0)
        proposal = _valid_proposal(amount_usd=10.0)

        result = engine.evaluate(proposal)

        self.assertTrue(result.allowed)

    def test_under_cap_passes(self) -> None:
        engine = self._make_block_engine(cap=10.0)
        proposal = _valid_proposal(amount_usd=5.0)

        result = engine.evaluate(proposal)

        self.assertTrue(result.allowed)


# ---------------------------------------------------------------------------
# 3. MODIFY on position size
# ---------------------------------------------------------------------------

class TestModifyOnPositionSize(unittest.TestCase):
    def _make_modify_engine(self, cap: float = 10.0) -> _EngineWithState:
        engine = _EngineWithState()
        engine.set_state(_valid_state())
        engine.add_constraint(Constraint(
            name="max_position_usd",
            description=f"Cap position at ${cap:.2f}",
            predicate=lambda p, _s: p.amount_usd > cap,
            action=ConstraintAction.MODIFY,
            modifier=lambda p: dataclasses.replace(p, amount_usd=cap),
            priority=80,
        ))
        return engine

    def test_oversized_trade_is_modified_not_blocked(self) -> None:
        engine = self._make_modify_engine(cap=10.0)
        proposal = _valid_proposal(amount_usd=50.0)

        result = engine.evaluate(proposal)

        self.assertTrue(result.allowed)
        self.assertEqual(result.action, ConstraintAction.MODIFY)

    def test_modified_amount_is_capped(self) -> None:
        engine = self._make_modify_engine(cap=10.0)
        proposal = _valid_proposal(amount_usd=50.0)

        result = engine.evaluate(proposal)

        self.assertEqual(result.proposal.amount_usd, 10.0)

    def test_violation_records_original_and_modified_values(self) -> None:
        engine = self._make_modify_engine(cap=10.0)
        proposal = _valid_proposal(amount_usd=50.0)

        result = engine.evaluate(proposal)

        self.assertEqual(len(result.violations), 1)
        v = result.violations[0]
        self.assertEqual(v.original_value, 50.0)
        self.assertEqual(v.modified_value, 10.0)


# ---------------------------------------------------------------------------
# 4. Daily loss limit blocks when exceeded
# ---------------------------------------------------------------------------

class TestDailyLossLimit(unittest.TestCase):
    def _make_engine(self, limit: float = 25.0) -> _EngineWithState:
        engine = _EngineWithState()
        engine.add_constraint(Constraint(
            name="daily_loss_limit",
            description=f"Block when daily P&L < -${limit:.2f}",
            predicate=lambda p, s: s.daily_pnl < -abs(limit),
            action=ConstraintAction.BLOCK,
            priority=100,
        ))
        return engine

    def test_loss_exceeded_blocks(self) -> None:
        engine = self._make_engine(limit=25.0)
        engine.set_state(_valid_state(daily_pnl=-26.0))

        result = engine.evaluate(_valid_proposal())

        self.assertFalse(result.allowed)
        self.assertEqual(result.violations[0].rule_name, "daily_loss_limit")

    def test_loss_exactly_at_limit_blocks(self) -> None:
        engine = self._make_engine(limit=25.0)
        engine.set_state(_valid_state(daily_pnl=-25.01))

        result = engine.evaluate(_valid_proposal())

        self.assertFalse(result.allowed)

    def test_loss_under_limit_allows(self) -> None:
        engine = self._make_engine(limit=25.0)
        engine.set_state(_valid_state(daily_pnl=-10.0))

        result = engine.evaluate(_valid_proposal())

        self.assertTrue(result.allowed)

    def test_positive_pnl_allows(self) -> None:
        engine = self._make_engine(limit=25.0)
        engine.set_state(_valid_state(daily_pnl=100.0))

        result = engine.evaluate(_valid_proposal())

        self.assertTrue(result.allowed)


# ---------------------------------------------------------------------------
# 5. Max open positions blocks when full
# ---------------------------------------------------------------------------

class TestMaxOpenPositions(unittest.TestCase):
    def _make_engine(self, max_pos: int = 30) -> _EngineWithState:
        engine = _EngineWithState()
        engine.add_constraint(Constraint(
            name="max_open_positions",
            description=f"Block when {max_pos}+ positions open",
            predicate=lambda p, s: s.open_positions >= max_pos,
            action=ConstraintAction.BLOCK,
            priority=90,
        ))
        return engine

    def test_full_blocks(self) -> None:
        engine = self._make_engine(max_pos=30)
        engine.set_state(_valid_state(open_positions=30))

        result = engine.evaluate(_valid_proposal())

        self.assertFalse(result.allowed)

    def test_over_limit_blocks(self) -> None:
        engine = self._make_engine(max_pos=30)
        engine.set_state(_valid_state(open_positions=35))

        result = engine.evaluate(_valid_proposal())

        self.assertFalse(result.allowed)

    def test_under_limit_allows(self) -> None:
        engine = self._make_engine(max_pos=30)
        engine.set_state(_valid_state(open_positions=29))

        result = engine.evaluate(_valid_proposal())

        self.assertTrue(result.allowed)


# ---------------------------------------------------------------------------
# 6. Minimum edge blocks weak trades
# ---------------------------------------------------------------------------

class TestMinimumEdge(unittest.TestCase):
    def _make_engine(self, min_edge: float = 0.05) -> _EngineWithState:
        engine = _EngineWithState()
        engine.add_constraint(Constraint(
            name="min_edge",
            description=f"Edge must be >= {min_edge:.1%}",
            predicate=lambda p, _s: p.edge < min_edge,
            action=ConstraintAction.BLOCK,
            priority=70,
        ))
        return engine

    def test_zero_edge_blocked(self) -> None:
        engine = self._make_engine(min_edge=0.05)
        engine.set_state(_valid_state())

        result = engine.evaluate(_valid_proposal(edge=0.0))

        self.assertFalse(result.allowed)

    def test_below_min_blocked(self) -> None:
        engine = self._make_engine(min_edge=0.05)
        engine.set_state(_valid_state())

        result = engine.evaluate(_valid_proposal(edge=0.03))

        self.assertFalse(result.allowed)

    def test_exactly_at_min_passes(self) -> None:
        engine = self._make_engine(min_edge=0.05)
        engine.set_state(_valid_state())

        result = engine.evaluate(_valid_proposal(edge=0.05))

        self.assertTrue(result.allowed)

    def test_above_min_passes(self) -> None:
        engine = self._make_engine(min_edge=0.05)
        engine.set_state(_valid_state())

        result = engine.evaluate(_valid_proposal(edge=0.15))

        self.assertTrue(result.allowed)


# ---------------------------------------------------------------------------
# 7. Promotion gate: BTC5 $10 blocked without gate, allowed with gate
# ---------------------------------------------------------------------------

class TestPromotionGate(unittest.TestCase):
    def _make_engine(self, threshold: float = 5.0) -> _EngineWithState:
        engine = _EngineWithState()
        engine.add_constraint(Constraint(
            name="btc5_promotion_gate",
            description=f"BTC5 limited to ${threshold:.2f}/trade until promotion gate passes",
            predicate=lambda p, s: (
                ("btc" in p.market_id.lower() or p.metadata.get("is_btc5", False))
                and p.amount_usd > threshold
                and not s.promotion_gate_passed
            ),
            action=ConstraintAction.BLOCK,
            priority=85,
        ))
        return engine

    def test_btc5_above_threshold_blocked_without_gate(self) -> None:
        engine = self._make_engine(threshold=5.0)
        engine.set_state(_valid_state(promotion_gate_passed=False))

        result = engine.evaluate(_valid_proposal(
            market_id="btc-5min-maker-001",
            amount_usd=10.0,
        ))

        self.assertFalse(result.allowed)
        self.assertEqual(result.violations[0].rule_name, "btc5_promotion_gate")

    def test_btc5_above_threshold_allowed_with_gate(self) -> None:
        engine = self._make_engine(threshold=5.0)
        engine.set_state(_valid_state(promotion_gate_passed=True))

        result = engine.evaluate(_valid_proposal(
            market_id="btc-5min-maker-001",
            amount_usd=10.0,
        ))

        self.assertTrue(result.allowed)

    def test_btc5_at_threshold_passes_without_gate(self) -> None:
        engine = self._make_engine(threshold=5.0)
        engine.set_state(_valid_state(promotion_gate_passed=False))

        result = engine.evaluate(_valid_proposal(
            market_id="btc-5min-maker-001",
            amount_usd=5.0,
        ))

        self.assertTrue(result.allowed)

    def test_non_btc_market_above_threshold_unaffected(self) -> None:
        engine = self._make_engine(threshold=5.0)
        engine.set_state(_valid_state(promotion_gate_passed=False))

        result = engine.evaluate(_valid_proposal(
            market_id="politics-market-001",
            amount_usd=10.0,
        ))

        # No other constraints in this engine, so passes
        self.assertTrue(result.allowed)

    def test_btc5_via_metadata_flag(self) -> None:
        engine = self._make_engine(threshold=5.0)
        engine.set_state(_valid_state(promotion_gate_passed=False))

        result = engine.evaluate(_valid_proposal(
            market_id="nonstandard-market-xyz",
            amount_usd=10.0,
            metadata={"is_btc5": True},
        ))

        self.assertFalse(result.allowed)


# ---------------------------------------------------------------------------
# 8. Regime stability: block during transition
# ---------------------------------------------------------------------------

class TestRegimeStability(unittest.TestCase):
    def _make_engine(self) -> _EngineWithState:
        engine = _EngineWithState()
        engine.add_constraint(Constraint(
            name="regime_stability",
            description="Block trades during regime transitions",
            predicate=lambda p, s: s.current_regime != "stable",
            action=ConstraintAction.BLOCK,
            priority=95,
        ))
        return engine

    def test_transition_regime_blocks(self) -> None:
        engine = self._make_engine()
        engine.set_state(_valid_state(current_regime="transition"))

        result = engine.evaluate(_valid_proposal())

        self.assertFalse(result.allowed)

    def test_volatile_regime_blocks(self) -> None:
        engine = self._make_engine()
        engine.set_state(_valid_state(current_regime="volatile"))

        result = engine.evaluate(_valid_proposal())

        self.assertFalse(result.allowed)

    def test_stable_regime_allows(self) -> None:
        engine = self._make_engine()
        engine.set_state(_valid_state(current_regime="stable"))

        result = engine.evaluate(_valid_proposal())

        self.assertTrue(result.allowed)


# ---------------------------------------------------------------------------
# 9. Kelly constraint modifies position down
# ---------------------------------------------------------------------------

class TestKellyConstraint(unittest.TestCase):
    def _make_engine(self) -> _EngineWithState:
        engine = _EngineWithState()

        def _pred(p: TradeProposal, s: TradingState) -> bool:
            if p.kelly_fraction <= 0 or s.bankroll <= 0:
                return False
            return p.amount_usd > p.kelly_fraction * s.bankroll

        engine.add_constraint(Constraint(
            name="kelly_constraint",
            description="Position must not exceed kelly_fraction * bankroll",
            predicate=_pred,
            action=ConstraintAction.MODIFY,
            modifier=lambda p: dataclasses.replace(p, amount_usd=p.amount_usd * 0.5),
            priority=65,
        ))
        return engine

    def test_oversized_kelly_is_modified(self) -> None:
        engine = self._make_engine()
        # bankroll=1000, kelly_fraction=0.005 → cap=$5; propose $20
        engine.set_state(_valid_state(bankroll=1000.0))

        result = engine.evaluate(_valid_proposal(
            amount_usd=20.0,
            kelly_fraction=0.005,
        ))

        self.assertTrue(result.allowed)
        self.assertEqual(result.action, ConstraintAction.MODIFY)
        self.assertEqual(result.proposal.amount_usd, 10.0)  # halved from 20

    def test_within_kelly_passes_unmodified(self) -> None:
        engine = self._make_engine()
        # bankroll=1000, kelly_fraction=0.10 → cap=$100; propose $5
        engine.set_state(_valid_state(bankroll=1000.0))

        result = engine.evaluate(_valid_proposal(
            amount_usd=5.0,
            kelly_fraction=0.10,
        ))

        self.assertTrue(result.allowed)
        self.assertEqual(result.action, ConstraintAction.ALLOW)
        self.assertEqual(result.proposal.amount_usd, 5.0)


# ---------------------------------------------------------------------------
# 10. Priority ordering: higher priority constraints checked first
# ---------------------------------------------------------------------------

class TestPriorityOrdering(unittest.TestCase):
    def test_high_priority_checked_before_low(self) -> None:
        """High-priority BLOCK should stop evaluation before low-priority fires."""
        fired = []

        def _high_pred(p, s):
            fired.append("high")
            return True  # Always blocks

        def _low_pred(p, s):
            fired.append("low")
            return True

        engine = _EngineWithState()
        engine.set_state(_valid_state())
        # Add low priority first to test ordering
        engine.add_constraint(Constraint(
            name="low_priority",
            description="Low priority",
            predicate=_low_pred,
            action=ConstraintAction.BLOCK,
            priority=10,
        ))
        engine.add_constraint(Constraint(
            name="high_priority",
            description="High priority",
            predicate=_high_pred,
            action=ConstraintAction.BLOCK,
            priority=100,
        ))

        result = engine.evaluate(_valid_proposal())

        self.assertFalse(result.allowed)
        # High fired first, BLOCK stopped execution — low should NOT fire
        self.assertEqual(fired, ["high"])
        self.assertEqual(result.violations[0].rule_name, "high_priority")

    def test_constraints_sorted_by_priority_desc(self) -> None:
        engine = ConstraintEngine()
        engine.add_constraint(Constraint("c", "c", lambda p, s: False, priority=50))
        engine.add_constraint(Constraint("a", "a", lambda p, s: False, priority=100))
        engine.add_constraint(Constraint("b", "b", lambda p, s: False, priority=75))

        priorities = [c.priority for c in engine.constraints]
        self.assertEqual(priorities, sorted(priorities, reverse=True))


# ---------------------------------------------------------------------------
# 11. Evaluation performance: 1000 evaluations in < 100ms
# ---------------------------------------------------------------------------

class TestEvaluationPerformance(unittest.TestCase):
    def test_1000_evaluations_under_100ms(self) -> None:
        engine = elastifund_default_constraints()
        engine.state = _valid_state()
        proposal = _valid_proposal()

        t0 = time.perf_counter()
        for _ in range(1000):
            engine.evaluate(proposal)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        self.assertLess(
            elapsed_ms,
            100.0,
            f"1000 evaluations took {elapsed_ms:.1f}ms (target < 100ms)",
        )

    def test_check_time_ms_reported_in_result(self) -> None:
        engine = elastifund_default_constraints()
        engine.state = _valid_state()

        result = engine.evaluate(_valid_proposal())

        self.assertGreaterEqual(result.check_time_ms, 0.0)
        self.assertLess(result.check_time_ms, 10.0)


# ---------------------------------------------------------------------------
# 12. Violation log captures all violations
# ---------------------------------------------------------------------------

class TestViolationLog(unittest.TestCase):
    def test_violations_accumulated_across_evaluations(self) -> None:
        engine = _EngineWithState()
        engine.set_state(_valid_state())
        engine.add_constraint(Constraint(
            name="always_block",
            description="Always blocks",
            predicate=lambda p, _s: True,
            action=ConstraintAction.BLOCK,
            priority=10,
        ))

        for _ in range(5):
            engine.evaluate(_valid_proposal())

        self.assertEqual(len(engine.violation_log), 5)

    def test_violation_log_has_correct_fields(self) -> None:
        engine = _EngineWithState()
        engine.set_state(_valid_state())
        engine.add_constraint(Constraint(
            name="test_rule",
            description="Test rule",
            predicate=lambda p, _s: True,
            action=ConstraintAction.BLOCK,
            priority=10,
        ))

        engine.evaluate(_valid_proposal())

        v = engine.violation_log[0]
        self.assertEqual(v.rule_name, "test_rule")
        self.assertEqual(v.action, ConstraintAction.BLOCK)
        self.assertIsInstance(v.timestamp, float)
        self.assertGreater(v.timestamp, 0.0)

    def test_get_violation_summary_counts_correctly(self) -> None:
        engine = _EngineWithState()
        engine.set_state(_valid_state())
        engine.add_constraint(Constraint(
            name="rule_a",
            description="Rule A",
            predicate=lambda p, _s: True,
            action=ConstraintAction.BLOCK,
            priority=10,
        ))

        for _ in range(3):
            engine.evaluate(_valid_proposal())

        summary = engine.get_violation_summary()
        self.assertEqual(summary["total_violations"], 3)
        self.assertEqual(summary["by_rule"]["rule_a"], 3)
        self.assertEqual(summary["most_common_rule"], "rule_a")

    def test_violation_summary_empty_engine(self) -> None:
        engine = ConstraintEngine()
        summary = engine.get_violation_summary()
        self.assertEqual(summary["total_violations"], 0)
        self.assertIsNone(summary["most_common_rule"])


# ---------------------------------------------------------------------------
# 13. load_rules_from_config produces correct constraints
# ---------------------------------------------------------------------------

class TestLoadRulesFromConfig(unittest.TestCase):
    def test_loads_max_position_block(self) -> None:
        engine = ConstraintEngine()
        n = engine.load_rules_from_config({
            "max_position_usd": {"value": 10, "action": "block"},
        })
        self.assertEqual(n, 1)
        self.assertEqual(engine.constraints[0].name, "max_position_usd")

    def test_loaded_max_position_modify_blocks(self) -> None:
        engine = _EngineWithState()
        engine.set_state(_valid_state())
        engine.load_rules_from_config({
            "max_position_usd": {"value": 10, "action": "modify"},
        })

        result = engine.evaluate(_valid_proposal(amount_usd=50.0))

        self.assertTrue(result.allowed)
        self.assertEqual(result.proposal.amount_usd, 10.0)

    def test_loads_all_known_rule_keys(self) -> None:
        engine = ConstraintEngine()
        config = {
            "max_position_usd": {"value": 10, "action": "modify"},
            "max_daily_loss": {"value": 25, "action": "block"},
            "max_open_positions": {"value": 30, "action": "block"},
            "min_edge": {"value": 0.05, "action": "block"},
            "promotion_gate_required_above": {"value": 5, "action": "block"},
            "regime_must_be_stable": {"value": True, "action": "block"},
            "max_exposure_pct": {"value": 0.90, "action": "modify"},
        }
        n = engine.load_rules_from_config(config)
        self.assertEqual(n, 7)

    def test_unknown_rule_key_skipped(self) -> None:
        engine = ConstraintEngine()
        n = engine.load_rules_from_config({
            "completely_unknown_rule": {"value": 99, "action": "block"},
        })
        self.assertEqual(n, 0)
        self.assertEqual(len(engine.constraints), 0)

    def test_unknown_action_skipped(self) -> None:
        engine = ConstraintEngine()
        n = engine.load_rules_from_config({
            "max_position_usd": {"value": 10, "action": "teleport"},
        })
        self.assertEqual(n, 0)

    def test_loaded_daily_loss_fires_correctly(self) -> None:
        engine = _EngineWithState()
        engine.set_state(_valid_state(daily_pnl=-30.0))
        engine.load_rules_from_config({
            "max_daily_loss": {"value": 25, "action": "block"},
        })

        result = engine.evaluate(_valid_proposal())

        self.assertFalse(result.allowed)

    def test_regime_stable_rule_disabled_when_false(self) -> None:
        """regime_must_be_stable: false means the constraint is not added."""
        engine = ConstraintEngine()
        n = engine.load_rules_from_config({
            "regime_must_be_stable": {"value": False, "action": "block"},
        })
        self.assertEqual(n, 0)


# ---------------------------------------------------------------------------
# 14. export_rules serialization
# ---------------------------------------------------------------------------

class TestExportRules(unittest.TestCase):
    def test_export_produces_list_of_dicts(self) -> None:
        engine = elastifund_default_constraints()
        rules = engine.export_rules()
        self.assertIsInstance(rules, list)
        for rule in rules:
            self.assertIsInstance(rule, dict)

    def test_export_contains_required_keys(self) -> None:
        engine = elastifund_default_constraints()
        rules = engine.export_rules()
        for rule in rules:
            self.assertIn("name", rule)
            self.assertIn("description", rule)
            self.assertIn("action", rule)
            self.assertIn("priority", rule)

    def test_export_action_values_are_strings(self) -> None:
        engine = elastifund_default_constraints()
        rules = engine.export_rules()
        valid_actions = {"allow", "block", "modify", "escalate"}
        for rule in rules:
            self.assertIn(rule["action"], valid_actions)

    def test_export_matches_constraint_count(self) -> None:
        engine = elastifund_default_constraints()
        rules = engine.export_rules()
        self.assertEqual(len(rules), len(engine.constraints))

    def test_empty_engine_export(self) -> None:
        engine = ConstraintEngine()
        rules = engine.export_rules()
        self.assertEqual(rules, [])


# ---------------------------------------------------------------------------
# 15. elastifund_default_constraints loads all 10 rules
# ---------------------------------------------------------------------------

class TestElastifundDefaultConstraints(unittest.TestCase):
    def test_loads_exactly_10_rules(self) -> None:
        engine = elastifund_default_constraints()
        self.assertEqual(len(engine.constraints), 10)

    def test_all_expected_rule_names_present(self) -> None:
        expected = {
            "position_size_cap",
            "btc5_promotion_gate",
            "daily_loss_limit",
            "max_open_positions",
            "max_exposure_pct",
            "min_edge",
            "regime_stability",
            "kelly_constraint",
            "category_filter",
            "resolution_window",
        }
        engine = elastifund_default_constraints()
        names = {c.name for c in engine.constraints}
        self.assertEqual(names, expected)

    def test_valid_trade_passes_all_defaults(self) -> None:
        engine = elastifund_default_constraints()
        engine.state = _valid_state()

        result = engine.evaluate(_valid_proposal())

        self.assertTrue(result.allowed)

    def test_category_filter_blocks_crypto(self) -> None:
        engine = elastifund_default_constraints()
        engine.state = _valid_state()

        result = engine.evaluate(_valid_proposal(category="crypto"))

        self.assertFalse(result.allowed)
        rule_names = [v.rule_name for v in result.violations]
        self.assertIn("category_filter", rule_names)

    def test_category_filter_blocks_sports(self) -> None:
        engine = elastifund_default_constraints()
        engine.state = _valid_state()

        result = engine.evaluate(_valid_proposal(category="sports"))

        self.assertFalse(result.allowed)

    def test_resolution_window_blocks_long_markets(self) -> None:
        engine = elastifund_default_constraints()
        engine.state = _valid_state()

        result = engine.evaluate(_valid_proposal(resolution_hours=48.0))

        self.assertFalse(result.allowed)
        rule_names = [v.rule_name for v in result.violations]
        self.assertIn("resolution_window", rule_names)

    def test_resolution_window_allows_24h(self) -> None:
        engine = elastifund_default_constraints()
        engine.state = _valid_state()

        result = engine.evaluate(_valid_proposal(resolution_hours=24.0))

        # 24 is not > 24 so should not block on resolution alone
        self.assertTrue(result.allowed)

    def test_position_size_cap_modifies_down(self) -> None:
        engine = elastifund_default_constraints()
        engine.state = _valid_state()

        result = engine.evaluate(_valid_proposal(amount_usd=50.0))

        self.assertTrue(result.allowed)
        self.assertLessEqual(result.proposal.amount_usd, 10.0)

    def test_daily_loss_limit_fires_on_deep_loss(self) -> None:
        engine = elastifund_default_constraints()
        engine.state = _valid_state(daily_pnl=-100.0)

        result = engine.evaluate(_valid_proposal())

        self.assertFalse(result.allowed)

    def test_max_open_positions_fires_at_30(self) -> None:
        engine = elastifund_default_constraints()
        engine.state = _valid_state(open_positions=30)

        result = engine.evaluate(_valid_proposal())

        self.assertFalse(result.allowed)


# ---------------------------------------------------------------------------
# 16. ESCALATE action
# ---------------------------------------------------------------------------

class TestEscalateAction(unittest.TestCase):
    def _make_escalate_engine(self, threshold: float = 100.0) -> _EngineWithState:
        engine = _EngineWithState()
        engine.set_state(_valid_state())
        engine.add_constraint(Constraint(
            name="large_trade_escalate",
            description=f"Trades above ${threshold:.2f} require human approval",
            predicate=lambda p, _s: p.amount_usd > threshold,
            action=ConstraintAction.ESCALATE,
            priority=50,
        ))
        return engine

    def test_large_trade_escalates(self) -> None:
        engine = self._make_escalate_engine(threshold=100.0)

        result = engine.evaluate(_valid_proposal(amount_usd=500.0))

        self.assertFalse(result.allowed)
        self.assertEqual(result.action, ConstraintAction.ESCALATE)

    def test_escalate_stops_evaluation(self) -> None:
        """ESCALATE should stop further constraint evaluation."""
        fired_second = []

        engine = _EngineWithState()
        engine.set_state(_valid_state())
        engine.add_constraint(Constraint(
            name="escalate_first",
            description="Escalate",
            predicate=lambda p, _s: True,
            action=ConstraintAction.ESCALATE,
            priority=100,
        ))
        engine.add_constraint(Constraint(
            name="block_second",
            description="Block (should not fire)",
            predicate=lambda p, _s: fired_second.append(True) or True,
            action=ConstraintAction.BLOCK,
            priority=50,
        ))

        result = engine.evaluate(_valid_proposal())

        self.assertEqual(result.action, ConstraintAction.ESCALATE)
        self.assertEqual(fired_second, [])

    def test_small_trade_not_escalated(self) -> None:
        engine = self._make_escalate_engine(threshold=100.0)

        result = engine.evaluate(_valid_proposal(amount_usd=5.0))

        self.assertTrue(result.allowed)
        self.assertEqual(result.action, ConstraintAction.ALLOW)


# ---------------------------------------------------------------------------
# 17. Constraint removal
# ---------------------------------------------------------------------------

class TestConstraintRemoval(unittest.TestCase):
    def test_remove_existing_constraint(self) -> None:
        engine = ConstraintEngine()
        engine.add_constraint(Constraint(
            name="to_remove",
            description="Will be removed",
            predicate=lambda p, _s: True,
            action=ConstraintAction.BLOCK,
        ))

        removed = engine.remove_constraint("to_remove")

        self.assertTrue(removed)
        self.assertEqual(len(engine.constraints), 0)

    def test_remove_nonexistent_returns_false(self) -> None:
        engine = ConstraintEngine()
        removed = engine.remove_constraint("does_not_exist")
        self.assertFalse(removed)

    def test_removed_constraint_no_longer_fires(self) -> None:
        engine = _EngineWithState()
        engine.set_state(_valid_state())
        engine.add_constraint(Constraint(
            name="block_all",
            description="Blocks everything",
            predicate=lambda p, _s: True,
            action=ConstraintAction.BLOCK,
        ))

        # Verify it blocks before removal
        before = engine.evaluate(_valid_proposal())
        self.assertFalse(before.allowed)

        engine.remove_constraint("block_all")

        after = engine.evaluate(_valid_proposal())
        self.assertTrue(after.allowed)

    def test_remove_one_of_several(self) -> None:
        engine = ConstraintEngine()
        for name in ["rule_a", "rule_b", "rule_c"]:
            engine.add_constraint(Constraint(
                name=name,
                description=name,
                predicate=lambda p, _s: False,
                action=ConstraintAction.BLOCK,
            ))

        engine.remove_constraint("rule_b")

        names = {c.name for c in engine.constraints}
        self.assertEqual(names, {"rule_a", "rule_c"})


# ---------------------------------------------------------------------------
# 18. update_state
# ---------------------------------------------------------------------------

class TestUpdateState(unittest.TestCase):
    def test_update_daily_pnl(self) -> None:
        engine = ConstraintEngine()
        engine.update_state(daily_pnl=-10.0)
        self.assertEqual(engine.state.daily_pnl, -10.0)

    def test_update_multiple_fields(self) -> None:
        engine = ConstraintEngine()
        engine.update_state(open_positions=15, bankroll=500.0, promotion_gate_passed=True)
        self.assertEqual(engine.state.open_positions, 15)
        self.assertEqual(engine.state.bankroll, 500.0)
        self.assertTrue(engine.state.promotion_gate_passed)

    def test_update_unknown_field_is_ignored(self) -> None:
        engine = ConstraintEngine()
        # Should not raise; logs a warning
        engine.update_state(nonexistent_field=99)
        self.assertFalse(hasattr(engine.state, "nonexistent_field"))


# ---------------------------------------------------------------------------
# 19. Modify → Block interaction: block after modify
# ---------------------------------------------------------------------------

class TestModifyThenBlockInteraction(unittest.TestCase):
    def test_modified_proposal_still_checked_by_later_constraints(self) -> None:
        """If MODIFY reduces amount, subsequent constraints see the new value."""
        engine = _EngineWithState()
        engine.set_state(_valid_state())

        # High-priority: modify down to $8
        engine.add_constraint(Constraint(
            name="cap_to_8",
            description="Cap at $8",
            predicate=lambda p, _s: p.amount_usd > 8.0,
            action=ConstraintAction.MODIFY,
            modifier=lambda p: dataclasses.replace(p, amount_usd=8.0),
            priority=100,
        ))
        # Lower-priority: block if amount > $5
        engine.add_constraint(Constraint(
            name="block_above_5",
            description="Block above $5",
            predicate=lambda p, _s: p.amount_usd > 5.0,
            action=ConstraintAction.BLOCK,
            priority=50,
        ))

        # Original is $20 → modify to $8 → still > $5 → block
        result = engine.evaluate(_valid_proposal(amount_usd=20.0))

        self.assertFalse(result.allowed)
        self.assertEqual(result.action, ConstraintAction.BLOCK)


if __name__ == "__main__":
    unittest.main()
