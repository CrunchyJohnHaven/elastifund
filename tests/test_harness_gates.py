#!/usr/bin/env python3
"""
Tests for bot/harness_gates.py — Replay-Based Mutation Acceptance
=================================================================
40+ tests covering all mandatory cases, KEEP/DISCARD/CRASH rules,
naked directional blocking, promotion rules, and edge cases.

March 2026 — Elastifund / JJ
"""

import pytest
from typing import Any

from bot.harness_gates import (
    ReplayCase,
    GauntletResult,
    HarnessGate,
    PromotionRules,
    evaluate_promotion_rules,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def gate() -> HarnessGate:
    return HarnessGate()


def _strategy_passes_all(market_data: list[dict[str, Any]]) -> dict[str, Any]:
    """Strategy that produces results passing every mandatory case."""
    # Detect which case we're in by inspecting the data
    if not market_data:
        return {}

    first = market_data[0]

    # march_22_directional_bleed: abstain (must check before generic btc5_)
    if first.get("market_id", "").startswith("btc5_down_bleed"):
        return {"abstained": True, "traded_both_sides": False}

    # march_11_btc_winning: must have net_pnl >= 0
    if first.get("market_id", "").startswith("btc5_") and first.get("filled"):
        total_pnl = sum(r.get("pnl", 0.0) for r in market_data)
        sides = {r.get("side") for r in market_data}
        return {
            "net_pnl": total_pnl,
            "traded_both_sides": len(sides) > 1,
            "abstained": False,
        }

    # march_15_concentration: detect concentration, don't promote
    if first.get("market_id", "").startswith("btc5_skip_"):
        return {
            "concentration_detected": True,
            "auto_promoted": False,
        }

    # march_22_directional_bleed: abstain
    if first.get("market_id", "").startswith("btc5_down_bleed"):
        return {"abstained": True, "traded_both_sides": False}

    # stale_data_fallback: don't trade on stale
    if first.get("pipeline_age_hours", 0) > 24:
        return {"traded_on_stale": False}

    # wallet_address_contradiction: detect divergence
    if first.get("market_id") == "wallet_check":
        return {"divergence_detected": True}

    return {}


def _strategy_fails_all(market_data: list[dict[str, Any]]) -> dict[str, Any]:
    """Strategy that fails every mandatory case."""
    first = market_data[0] if market_data else {}

    if first.get("market_id", "").startswith("btc5_") and first.get("filled"):
        return {"net_pnl": -100.0}

    if first.get("market_id", "").startswith("btc5_skip_"):
        return {"concentration_detected": False, "auto_promoted": True}

    if first.get("market_id", "").startswith("btc5_down_bleed"):
        return {"abstained": False, "traded_both_sides": False}

    if first.get("pipeline_age_hours", 0) > 24:
        return {"traded_on_stale": True}

    if first.get("market_id") == "wallet_check":
        return {"divergence_detected": False}

    return {}


def _strategy_always_abstains(market_data: list[dict[str, Any]]) -> dict[str, Any]:
    """Strategy that always abstains — should pass some but not all."""
    first = market_data[0] if market_data else {}

    if first.get("market_id", "").startswith("btc5_") and first.get("filled"):
        return {"net_pnl": 0.0, "abstained": True, "traded_both_sides": False}

    if first.get("market_id", "").startswith("btc5_skip_"):
        return {"concentration_detected": True, "auto_promoted": False}

    if first.get("market_id", "").startswith("btc5_down_bleed"):
        return {"abstained": True, "traded_both_sides": False}

    if first.get("pipeline_age_hours", 0) > 24:
        return {"traded_on_stale": False}

    if first.get("market_id") == "wallet_check":
        return {"divergence_detected": True}

    return {}


def _strategy_naked_directional(market_data: list[dict[str, Any]]) -> dict[str, Any]:
    """Strategy that trades naked directional (DOWN only)."""
    first = market_data[0] if market_data else {}

    if first.get("market_id", "").startswith("btc5_down_bleed"):
        return {"abstained": False, "traded_both_sides": False}

    # Pass everything else
    return _strategy_passes_all(market_data)


# ---------------------------------------------------------------------------
# 1. Mandatory Cases Loaded
# ---------------------------------------------------------------------------


class TestMandatoryCasesLoaded:
    def test_five_cases_loaded(self, gate: HarnessGate) -> None:
        assert gate.case_count == 5

    def test_march_11_present(self, gate: HarnessGate) -> None:
        assert "march_11_btc_winning" in gate.case_ids

    def test_march_15_present(self, gate: HarnessGate) -> None:
        assert "march_15_concentration" in gate.case_ids

    def test_march_22_present(self, gate: HarnessGate) -> None:
        assert "march_22_directional_bleed" in gate.case_ids

    def test_stale_data_present(self, gate: HarnessGate) -> None:
        assert "stale_data_fallback" in gate.case_ids

    def test_wallet_contradiction_present(self, gate: HarnessGate) -> None:
        assert "wallet_address_contradiction" in gate.case_ids


# ---------------------------------------------------------------------------
# 2. Corpus Is Add-Only
# ---------------------------------------------------------------------------


class TestCorpusAddOnly:
    def test_add_case_increases_count(self, gate: HarnessGate) -> None:
        before = gate.case_count
        gate.add_case(ReplayCase(
            case_id="test_new",
            name="Test",
            description="A test case",
            market_data=[],
            expected_behavior="pass",
            pass_condition=lambda r: True,
        ))
        assert gate.case_count == before + 1

    def test_cases_never_removed(self, gate: HarnessGate) -> None:
        """No public method removes cases."""
        original_ids = set(gate.case_ids)
        gate.add_case(ReplayCase(
            case_id="extra",
            name="Extra",
            description="extra",
            market_data=[],
            expected_behavior="pass",
            pass_condition=lambda r: True,
        ))
        current_ids = set(gate.case_ids)
        assert original_ids.issubset(current_ids)

    def test_add_duplicate_updates_not_doubles(self, gate: HarnessGate) -> None:
        before = gate.case_count
        gate.add_case(ReplayCase(
            case_id="march_11_btc_winning",
            name="Updated March 11",
            description="updated",
            market_data=[],
            expected_behavior="updated",
            pass_condition=lambda r: True,
        ))
        assert gate.case_count == before
        assert gate.get_case("march_11_btc_winning").name == "Updated March 11"

    def test_mandatory_cases_survive_additions(self, gate: HarnessGate) -> None:
        for i in range(10):
            gate.add_case(ReplayCase(
                case_id=f"extra_{i}",
                name=f"Extra {i}",
                description="extra",
                market_data=[],
                expected_behavior="pass",
                pass_condition=lambda r: True,
            ))
        assert gate.case_count == 15
        assert "march_22_directional_bleed" in gate.case_ids


# ---------------------------------------------------------------------------
# 3. March 22 Directional Bleed Case
# ---------------------------------------------------------------------------


class TestMarch22DirectionalBleed:
    def test_march_22_data_has_two_rows(self, gate: HarnessGate) -> None:
        case = gate.get_case("march_22_directional_bleed")
        assert len(case.market_data) == 2

    def test_march_22_both_down(self, gate: HarnessGate) -> None:
        case = gate.get_case("march_22_directional_bleed")
        for row in case.market_data:
            assert row["side"] == "DOWN"

    def test_march_22_both_lost(self, gate: HarnessGate) -> None:
        case = gate.get_case("march_22_directional_bleed")
        for row in case.market_data:
            assert row["pnl"] < 0

    def test_march_22_blocks_naked_directional(self, gate: HarnessGate) -> None:
        result = gate.run_gauntlet(_strategy_naked_directional)
        failed_ids = [f.case_id for f in result["failures"]]
        assert "march_22_directional_bleed" in failed_ids

    def test_march_22_passes_with_abstain(self, gate: HarnessGate) -> None:
        case = gate.get_case("march_22_directional_bleed")
        result = {"abstained": True, "traded_both_sides": False}
        assert case.pass_condition(result) is True

    def test_march_22_passes_with_both_sides(self, gate: HarnessGate) -> None:
        case = gate.get_case("march_22_directional_bleed")
        result = {"abstained": False, "traded_both_sides": True}
        assert case.pass_condition(result) is True

    def test_march_22_fails_naked_one_side(self, gate: HarnessGate) -> None:
        case = gate.get_case("march_22_directional_bleed")
        result = {"abstained": False, "traded_both_sides": False}
        assert case.pass_condition(result) is False


# ---------------------------------------------------------------------------
# 4. KEEP / DISCARD / CRASH Rules
# ---------------------------------------------------------------------------


class TestMutationRules:
    def test_keep_when_all_improve(self, gate: HarnessGate) -> None:
        before = {"win_rate": 0.55, "pnl": 100.0, "sharpe": 1.2}
        after = {"win_rate": 0.58, "pnl": 110.0, "sharpe": 1.3}
        assert gate.check_mutation(before, after) == "KEEP"

    def test_keep_when_no_change(self, gate: HarnessGate) -> None:
        before = {"win_rate": 0.55, "pnl": 100.0}
        after = {"win_rate": 0.55, "pnl": 100.0}
        assert gate.check_mutation(before, after) == "KEEP"

    def test_keep_when_slight_improvement(self, gate: HarnessGate) -> None:
        before = {"win_rate": 0.55, "pnl": 100.0}
        after = {"win_rate": 0.56, "pnl": 105.0}
        assert gate.check_mutation(before, after) == "KEEP"

    def test_discard_when_one_metric_degrades_15pct(self, gate: HarnessGate) -> None:
        before = {"win_rate": 0.60, "pnl": 100.0, "sharpe": 1.0}
        after = {"win_rate": 0.60, "pnl": 85.0, "sharpe": 1.0}  # 15% drop
        assert gate.check_mutation(before, after) == "DISCARD"

    def test_discard_when_metric_degrades_25pct(self, gate: HarnessGate) -> None:
        before = {"win_rate": 0.60, "pnl": 100.0}
        after = {"win_rate": 0.60, "pnl": 75.0}  # 25% drop
        assert gate.check_mutation(before, after) == "DISCARD"

    def test_keep_when_metric_degrades_under_10pct(self, gate: HarnessGate) -> None:
        before = {"win_rate": 0.60, "pnl": 100.0}
        after = {"win_rate": 0.60, "pnl": 92.0}  # 8% drop
        assert gate.check_mutation(before, after) == "KEEP"

    def test_crash_on_new_failure_mode(self, gate: HarnessGate) -> None:
        before = {"win_rate": 0.55, "pnl": 100.0}
        after = {"win_rate": 0.55, "pnl": 100.0, "new_error_type": 1.0}
        assert gate.check_mutation(before, after) == "CRASH"

    def test_crash_on_multiple_new_keys(self, gate: HarnessGate) -> None:
        before = {"pnl": 100.0}
        after = {"pnl": 100.0, "error_a": 1.0, "error_b": 2.0}
        assert gate.check_mutation(before, after) == "CRASH"

    def test_keep_with_empty_metrics(self, gate: HarnessGate) -> None:
        assert gate.check_mutation({}, {}) == "KEEP"

    def test_crash_with_empty_before_and_new_after(self, gate: HarnessGate) -> None:
        assert gate.check_mutation({}, {"error": 1.0}) == "CRASH"

    def test_discard_at_exactly_20pct_boundary(self, gate: HarnessGate) -> None:
        before = {"pnl": 100.0}
        # 20% degradation means after = 80.0, which is > 0.20 threshold? No,
        # (100-80)/100 = 0.20. We use > 0.20, so 20% exact is not DISCARD.
        # But > 0.10 triggers DISCARD.
        after = {"pnl": 80.0}
        # degradation = (100 - 80) / 100 = 0.20, which is > 0.10 => DISCARD
        assert gate.check_mutation(before, after) == "DISCARD"

    def test_keep_at_exactly_10pct_degradation(self, gate: HarnessGate) -> None:
        before = {"pnl": 100.0}
        after = {"pnl": 90.0}
        # degradation = (100 - 90) / 100 = 0.10, which is NOT > 0.10 => KEEP
        assert gate.check_mutation(before, after) == "KEEP"

    def test_discard_just_over_10pct(self, gate: HarnessGate) -> None:
        before = {"pnl": 100.0}
        after = {"pnl": 89.9}  # degradation = 0.101
        assert gate.check_mutation(before, after) == "DISCARD"


# ---------------------------------------------------------------------------
# 5. Naked Directional Blocking
# ---------------------------------------------------------------------------


class TestNakedDirectionalBlocking:
    def test_blocked_when_alternatives_exist(self, gate: HarnessGate) -> None:
        assert gate.blocks_naked_directional(has_structural_alternatives=True) is True

    def test_allowed_when_no_alternatives(self, gate: HarnessGate) -> None:
        assert gate.blocks_naked_directional(has_structural_alternatives=False) is False

    def test_blocked_even_if_case_missing(self) -> None:
        """If March 22 case were somehow missing, block as safety fallback."""
        gate = HarnessGate()
        # Forcibly remove the case (simulating corruption)
        del gate._cases["march_22_directional_bleed"]
        assert gate.blocks_naked_directional(has_structural_alternatives=True) is True
        assert gate.blocks_naked_directional(has_structural_alternatives=False) is True


# ---------------------------------------------------------------------------
# 6. Gauntlet Execution
# ---------------------------------------------------------------------------


class TestGauntletExecution:
    def test_all_pass_strategy(self, gate: HarnessGate) -> None:
        result = gate.run_gauntlet(_strategy_passes_all)
        assert result["passed"] is True
        assert len(result["failures"]) == 0

    def test_all_fail_strategy(self, gate: HarnessGate) -> None:
        result = gate.run_gauntlet(_strategy_fails_all)
        assert result["passed"] is False
        assert len(result["failures"]) == 5

    def test_exception_in_strategy_is_failure(self, gate: HarnessGate) -> None:
        def exploding_strategy(data: list) -> dict:
            raise RuntimeError("boom")

        result = gate.run_gauntlet(exploding_strategy)
        assert result["passed"] is False
        assert len(result["failures"]) == 5
        for f in result["failures"]:
            assert "EXCEPTION" in f.detail

    def test_results_count_matches_cases(self, gate: HarnessGate) -> None:
        result = gate.run_gauntlet(_strategy_passes_all)
        assert len(result["results"]) == gate.case_count

    def test_empty_gauntlet(self) -> None:
        gate = HarnessGate()
        # Remove all cases (simulating an empty gauntlet for testing)
        gate._cases.clear()
        result = gate.run_gauntlet(_strategy_passes_all)
        assert result["passed"] is True
        assert len(result["results"]) == 0
        assert len(result["failures"]) == 0

    def test_abstain_strategy_passes(self, gate: HarnessGate) -> None:
        result = gate.run_gauntlet(_strategy_always_abstains)
        assert result["passed"] is True


# ---------------------------------------------------------------------------
# 7. Promotion Rules for Copied Strategies
# ---------------------------------------------------------------------------


class TestPromotionRules:
    def test_all_rules_pass(self, gate: HarnessGate) -> None:
        gauntlet = gate.run_gauntlet(_strategy_passes_all)
        rules = evaluate_promotion_rules(
            gauntlet_result=gauntlet,
            shadow_days=7,
            shadow_expectancy=0.05,
            daily_pnl_age_hours=12.0,
            max_single_direction_pct=0.50,
        )
        assert rules.all_passed() is True
        assert rules.failures() == []

    def test_replay_fail_blocks_promotion(self, gate: HarnessGate) -> None:
        gauntlet = gate.run_gauntlet(_strategy_fails_all)
        rules = evaluate_promotion_rules(
            gauntlet_result=gauntlet,
            shadow_days=30,
            shadow_expectancy=1.0,
            daily_pnl_age_hours=1.0,
            max_single_direction_pct=0.20,
        )
        assert rules.all_passed() is False
        assert "replay_pass" in rules.failures()

    def test_shadow_too_short(self, gate: HarnessGate) -> None:
        gauntlet = gate.run_gauntlet(_strategy_passes_all)
        rules = evaluate_promotion_rules(
            gauntlet_result=gauntlet,
            shadow_days=3,
            shadow_expectancy=0.10,
            daily_pnl_age_hours=12.0,
            max_single_direction_pct=0.50,
        )
        assert "shadow_pass" in rules.failures()

    def test_shadow_negative_expectancy(self, gate: HarnessGate) -> None:
        gauntlet = gate.run_gauntlet(_strategy_passes_all)
        rules = evaluate_promotion_rules(
            gauntlet_result=gauntlet,
            shadow_days=14,
            shadow_expectancy=-0.05,
            daily_pnl_age_hours=12.0,
            max_single_direction_pct=0.50,
        )
        assert "shadow_pass" in rules.failures()

    def test_stale_daily_pnl(self, gate: HarnessGate) -> None:
        gauntlet = gate.run_gauntlet(_strategy_passes_all)
        rules = evaluate_promotion_rules(
            gauntlet_result=gauntlet,
            shadow_days=7,
            shadow_expectancy=0.05,
            daily_pnl_age_hours=48.0,
            max_single_direction_pct=0.50,
        )
        assert "daily_pnl_truth_pass" in rules.failures()

    def test_null_daily_pnl(self, gate: HarnessGate) -> None:
        gauntlet = gate.run_gauntlet(_strategy_passes_all)
        rules = evaluate_promotion_rules(
            gauntlet_result=gauntlet,
            shadow_days=7,
            shadow_expectancy=0.05,
            daily_pnl_age_hours=0.0,
            max_single_direction_pct=0.50,
        )
        assert "daily_pnl_truth_pass" in rules.failures()

    def test_concentration_regression(self, gate: HarnessGate) -> None:
        gauntlet = gate.run_gauntlet(_strategy_passes_all)
        rules = evaluate_promotion_rules(
            gauntlet_result=gauntlet,
            shadow_days=7,
            shadow_expectancy=0.05,
            daily_pnl_age_hours=12.0,
            max_single_direction_pct=0.75,
        )
        assert "no_concentration_regression" in rules.failures()

    def test_concentration_at_60pct_boundary_fails(self, gate: HarnessGate) -> None:
        gauntlet = gate.run_gauntlet(_strategy_passes_all)
        rules = evaluate_promotion_rules(
            gauntlet_result=gauntlet,
            shadow_days=7,
            shadow_expectancy=0.05,
            daily_pnl_age_hours=12.0,
            max_single_direction_pct=0.60,
        )
        assert "no_concentration_regression" in rules.failures()

    def test_concentration_just_below_60pct(self, gate: HarnessGate) -> None:
        gauntlet = gate.run_gauntlet(_strategy_passes_all)
        rules = evaluate_promotion_rules(
            gauntlet_result=gauntlet,
            shadow_days=7,
            shadow_expectancy=0.05,
            daily_pnl_age_hours=12.0,
            max_single_direction_pct=0.59,
        )
        assert rules.no_concentration_regression is True


# ---------------------------------------------------------------------------
# 8. PromotionRules Dataclass
# ---------------------------------------------------------------------------


class TestPromotionRulesDataclass:
    def test_default_all_false(self) -> None:
        rules = PromotionRules()
        assert rules.all_passed() is False
        assert len(rules.failures()) == 4

    def test_all_true(self) -> None:
        rules = PromotionRules(
            replay_passed=True,
            shadow_passed=True,
            daily_pnl_truth_passed=True,
            no_concentration_regression=True,
        )
        assert rules.all_passed() is True
        assert rules.failures() == []


# ---------------------------------------------------------------------------
# 9. Edge Cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_gauntlet_result_detail_on_exception(self, gate: HarnessGate) -> None:
        def bad_fn(data: list) -> dict:
            raise ValueError("test error 42")

        result = gate.run_gauntlet(bad_fn)
        for f in result["failures"]:
            assert "test error 42" in f.detail

    def test_mutation_with_zero_baseline(self, gate: HarnessGate) -> None:
        before = {"pnl": 0.0, "win_rate": 0.5}
        after = {"pnl": 10.0, "win_rate": 0.6}
        assert gate.check_mutation(before, after) == "KEEP"

    def test_mutation_zero_baseline_negative_after(self, gate: HarnessGate) -> None:
        before = {"pnl": 0.0}
        after = {"pnl": -10.0}
        assert gate.check_mutation(before, after) == "DISCARD"

    def test_march_11_data_has_47_rows(self, gate: HarnessGate) -> None:
        case = gate.get_case("march_11_btc_winning")
        assert len(case.market_data) == 47

    def test_march_15_data_has_302_rows(self, gate: HarnessGate) -> None:
        case = gate.get_case("march_15_concentration")
        assert len(case.market_data) == 302

    def test_stale_data_has_pipeline_age(self, gate: HarnessGate) -> None:
        case = gate.get_case("stale_data_fallback")
        assert case.market_data[0]["pipeline_age_hours"] == 73.0

    def test_wallet_data_has_both_addresses(self, gate: HarnessGate) -> None:
        case = gate.get_case("wallet_address_contradiction")
        row = case.market_data[0]
        assert "address_queried" in row
        assert "address_correct" in row

    def test_get_nonexistent_case(self, gate: HarnessGate) -> None:
        assert gate.get_case("nonexistent") is None

    def test_mutation_reintroducing_naked_directional(self, gate: HarnessGate) -> None:
        """Mutation that reintroduces naked one-sided BTC fails when alternatives exist."""
        result = gate.run_gauntlet(_strategy_naked_directional)
        # The naked directional strategy fails the march_22 case
        assert result["passed"] is False
        # And naked directional is blocked
        assert gate.blocks_naked_directional(has_structural_alternatives=True) is True
