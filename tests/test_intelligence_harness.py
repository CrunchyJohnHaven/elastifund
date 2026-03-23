"""Tests for scripts/intelligence_harness.py"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.intelligence_harness import (
    ALL_GAUNTLETS,
    GauntletResult,
    HarnessResult,
    IntelligenceMetrics,
    ReplayScenario,
    accepts_mutation,
    check_local_twin_bundle_equivalence,
    compute_intelligence_metrics,
    gauntlet_mar15_btc_concentration_failure,
    gauntlet_mar11_btc_winning_windows,
    gauntlet_mar22_btc_daily_drawdown,
    gauntlet_stale_fallback_discovery,
    gauntlet_weather_shock,
    run_full_harness,
    run_replay_gauntlet,
)

_NOW = datetime(2026, 3, 22, 14, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# IntelligenceMetrics.is_better_than
# ---------------------------------------------------------------------------


class TestIntelligenceMetricsIsBetterThan:
    def test_identical_metrics_accepted(self):
        m = IntelligenceMetrics(validated_edge_discovery_velocity=1.0)
        assert m.is_better_than(m) is True

    def test_higher_velocity_accepted(self):
        before = IntelligenceMetrics(validated_edge_discovery_velocity=0.5)
        after = IntelligenceMetrics(validated_edge_discovery_velocity=1.0)
        assert after.is_better_than(before) is True

    def test_lower_velocity_rejected(self):
        before = IntelligenceMetrics(validated_edge_discovery_velocity=1.0)
        after = IntelligenceMetrics(validated_edge_discovery_velocity=0.5)
        assert after.is_better_than(before) is False

    def test_stale_fallback_within_tolerance_accepted(self):
        before = IntelligenceMetrics(validated_edge_discovery_velocity=1.0, stale_fallback_rate=0.10)
        after = IntelligenceMetrics(validated_edge_discovery_velocity=1.0, stale_fallback_rate=0.14)
        assert after.is_better_than(before) is True  # delta 0.04 <= 0.05

    def test_stale_fallback_over_tolerance_rejected(self):
        before = IntelligenceMetrics(validated_edge_discovery_velocity=1.0, stale_fallback_rate=0.10)
        after = IntelligenceMetrics(validated_edge_discovery_velocity=1.0, stale_fallback_rate=0.20)
        assert after.is_better_than(before) is False  # delta 0.10 > 0.05

    def test_false_promotion_within_tolerance_accepted(self):
        before = IntelligenceMetrics(validated_edge_discovery_velocity=1.0, false_promotion_rate=0.05)
        after = IntelligenceMetrics(validated_edge_discovery_velocity=1.0, false_promotion_rate=0.06)
        assert after.is_better_than(before) is True  # delta 0.01 <= 0.02

    def test_false_promotion_over_tolerance_rejected(self):
        before = IntelligenceMetrics(validated_edge_discovery_velocity=1.0, false_promotion_rate=0.05)
        after = IntelligenceMetrics(validated_edge_discovery_velocity=1.0, false_promotion_rate=0.10)
        assert after.is_better_than(before) is False  # delta 0.05 > 0.02

    def test_concentration_incidents_within_tolerance(self):
        before = IntelligenceMetrics(validated_edge_discovery_velocity=1.0, concentration_incidents_7d=2)
        after = IntelligenceMetrics(validated_edge_discovery_velocity=1.0, concentration_incidents_7d=3)
        assert after.is_better_than(before) is True  # delta 1 <= 1

    def test_concentration_incidents_over_tolerance(self):
        before = IntelligenceMetrics(validated_edge_discovery_velocity=1.0, concentration_incidents_7d=2)
        after = IntelligenceMetrics(validated_edge_discovery_velocity=1.0, concentration_incidents_7d=4)
        assert after.is_better_than(before) is False  # delta 2 > 1

    def test_execution_quality_within_tolerance(self):
        before = IntelligenceMetrics(validated_edge_discovery_velocity=1.0, execution_quality_score=0.80)
        after = IntelligenceMetrics(validated_edge_discovery_velocity=1.0, execution_quality_score=0.76)
        assert after.is_better_than(before) is True  # delta -0.04 >= -0.05

    def test_execution_quality_over_tolerance(self):
        before = IntelligenceMetrics(validated_edge_discovery_velocity=1.0, execution_quality_score=0.80)
        after = IntelligenceMetrics(validated_edge_discovery_velocity=1.0, execution_quality_score=0.70)
        assert after.is_better_than(before) is False  # delta -0.10 < -0.05

    def test_to_dict_has_all_keys(self):
        m = IntelligenceMetrics()
        d = m.to_dict()
        expected_keys = {
            "validated_edge_discovery_velocity",
            "false_promotion_rate",
            "stale_fallback_rate",
            "attribution_coverage",
            "concentration_incidents_7d",
            "execution_quality_score",
            "proving_ground_readiness",
            "daily_pnl_accounting_present",
        }
        assert expected_keys.issubset(d.keys())

    def test_daily_pnl_accounting_absent_fails(self):
        """A mutation that removes daily PnL accounting always fails."""
        before = IntelligenceMetrics(validated_edge_discovery_velocity=1.0)
        after = IntelligenceMetrics(
            validated_edge_discovery_velocity=1.5,
            daily_pnl_accounting_present=False,
        )
        assert after.is_better_than(before) is False

    def test_daily_pnl_accounting_present_passes(self):
        before = IntelligenceMetrics(validated_edge_discovery_velocity=1.0)
        after = IntelligenceMetrics(validated_edge_discovery_velocity=1.0)
        assert after.is_better_than(before) is True
        assert after.daily_pnl_accounting_present is True


# ---------------------------------------------------------------------------
# accepts_mutation
# ---------------------------------------------------------------------------


class TestAcceptsMutation:
    def test_improvement_accepted(self):
        before = IntelligenceMetrics(validated_edge_discovery_velocity=0.5)
        after = IntelligenceMetrics(validated_edge_discovery_velocity=1.0)
        assert accepts_mutation(before, after) is True

    def test_regression_rejected(self):
        before = IntelligenceMetrics(validated_edge_discovery_velocity=1.0)
        after = IntelligenceMetrics(validated_edge_discovery_velocity=0.5)
        assert accepts_mutation(before, after) is False


# ---------------------------------------------------------------------------
# compute_intelligence_metrics
# ---------------------------------------------------------------------------


class TestComputeIntelligenceMetrics:
    def _make_result(self, name: str, passed: bool, failures: list[str] | None = None) -> GauntletResult:
        return GauntletResult(
            scenario_name=name,
            passed=passed,
            failures=failures or [],
        )

    def test_empty_list_returns_zero_metrics(self):
        metrics = compute_intelligence_metrics([])
        assert metrics.validated_edge_discovery_velocity == 0.0
        assert metrics.stale_fallback_rate == 0.0
        assert metrics.proving_ground_readiness == 0.0

    def test_all_passing_readiness_is_one(self):
        results = [
            self._make_result("mar11_btc_winning_windows", True),
            self._make_result("weather_official_source_shock", True),
        ]
        metrics = compute_intelligence_metrics(results)
        assert metrics.proving_ground_readiness == pytest.approx(1.0)

    def test_half_passing_readiness(self):
        results = [
            self._make_result("mar11_btc_winning_windows", True),
            self._make_result("mar15_btc_concentration_failure", False, ["something failed"]),
        ]
        metrics = compute_intelligence_metrics(results)
        assert metrics.proving_ground_readiness == pytest.approx(0.5)

    def test_winning_scenario_boosts_velocity(self):
        results = [self._make_result("mar11_btc_winning_windows", True)]
        metrics = compute_intelligence_metrics(results)
        assert metrics.validated_edge_discovery_velocity > 0.0

    def test_stale_scenario_counts_in_rate(self):
        results = [
            self._make_result("stale_fallback_discovery", True),
            self._make_result("some_other", True),
        ]
        metrics = compute_intelligence_metrics(results)
        # stale_fallback_discovery always counts
        assert metrics.stale_fallback_rate == pytest.approx(0.5)

    def test_no_btc5_db_defaults_exec_quality_zero(self, tmp_path: Path):
        results = [self._make_result("a", True)]
        metrics = compute_intelligence_metrics(results, btc5_db_path=tmp_path / "missing.db")
        assert metrics.execution_quality_score == 0.0


# ---------------------------------------------------------------------------
# check_local_twin_bundle_equivalence
# ---------------------------------------------------------------------------


class TestCheckLocalTwinBundleEquivalence:
    def test_identical_bundles_pass(self):
        bundle = {"schema": "kernel.v1", "artifact": "test"}
        ok, discrepancies = check_local_twin_bundle_equivalence(bundle, bundle)
        assert ok is True
        assert discrepancies == []

    def test_schema_mismatch_fails(self):
        local = {"schema": "kernel.v1"}
        remote = {"schema": "kernel.v2"}
        ok, discrepancies = check_local_twin_bundle_equivalence(local, remote)
        assert ok is False
        assert any("schema" in d for d in discrepancies)

    def test_generated_at_difference_ignored(self):
        local = {"schema": "kernel.v1", "generated_at": "2026-03-01T00:00:00Z"}
        remote = {"schema": "kernel.v1", "generated_at": "2026-03-22T00:00:00Z"}
        ok, _ = check_local_twin_bundle_equivalence(local, remote)
        assert ok is True

    def test_missing_key_in_local_reported(self):
        local = {"schema": "kernel.v1"}
        remote = {"schema": "kernel.v1", "extra_key": "value"}
        ok, discrepancies = check_local_twin_bundle_equivalence(local, remote)
        assert ok is False
        assert any("missing_in_local" in d for d in discrepancies)

    def test_missing_key_in_remote_reported(self):
        local = {"schema": "kernel.v1", "extra_key": "value"}
        remote = {"schema": "kernel.v1"}
        ok, discrepancies = check_local_twin_bundle_equivalence(local, remote)
        assert ok is False
        assert any("missing_in_remote" in d for d in discrepancies)

    def test_custom_required_keys(self):
        local = {"artifact": "a", "version": "1"}
        remote = {"artifact": "b", "version": "1"}
        ok, discrepancies = check_local_twin_bundle_equivalence(
            local, remote, required_keys=["artifact"]
        )
        assert ok is False
        assert any("artifact" in d for d in discrepancies)

    def test_custom_required_keys_match(self):
        local = {"artifact": "x", "version": "1"}
        remote = {"artifact": "x", "version": "1"}
        ok, _ = check_local_twin_bundle_equivalence(
            local, remote, required_keys=["artifact"]
        )
        assert ok is True


# ---------------------------------------------------------------------------
# Gauntlet factory functions
# ---------------------------------------------------------------------------


class TestGauntletFactories:
    def test_mar15_scenario_fields(self):
        s = gauntlet_mar15_btc_concentration_failure()
        assert s.name == "mar15_btc_concentration_failure"
        assert s.btc5_rows == 302
        assert s.btc5_fill_count == 0
        assert s.stale_fallback_used is False
        assert "skip_delta_too_large" in s.btc5_skip_reasons

    def test_mar11_scenario_fields(self):
        s = gauntlet_mar11_btc_winning_windows()
        assert s.name == "mar11_btc_winning_windows"
        assert s.btc5_fill_count == 47
        assert s.stale_fallback_used is False

    def test_weather_shock_scenario(self):
        s = gauntlet_weather_shock()
        assert s.name == "weather_official_source_shock"
        assert s.weather_candidate_count == 8
        assert s.weather_arr_confidence == pytest.approx(0.70)

    def test_stale_fallback_scenario(self):
        s = gauntlet_stale_fallback_discovery()
        assert s.name == "stale_fallback_discovery"
        assert s.stale_fallback_used is True
        assert s.btc5_fill_count == 0

    def test_mar22_daily_drawdown_scenario(self):
        s = gauntlet_mar22_btc_daily_drawdown()
        assert s.name == "mar22_btc_daily_drawdown"
        assert s.btc5_fill_count == 35
        gate = s.promotion_gate_override.get("daily_pnl_gate", {})
        assert gate.get("pass") is False
        assert gate.get("et_day_pnl_usd", 0) < 0
        assert gate.get("rolling_24h_pnl_usd", 0) < 0

    def test_all_gauntlets_list(self):
        assert len(ALL_GAUNTLETS) == 5
        names = {g.name for g in ALL_GAUNTLETS}
        assert "mar15_btc_concentration_failure" in names
        assert "mar11_btc_winning_windows" in names
        assert "weather_official_source_shock" in names
        assert "stale_fallback_discovery" in names
        assert "mar22_btc_daily_drawdown" in names


# ---------------------------------------------------------------------------
# ReplayScenario defaults
# ---------------------------------------------------------------------------


class TestReplayScenario:
    def test_defaults_are_empty(self):
        s = ReplayScenario(name="test", description="desc")
        assert s.btc5_rows == 0
        assert s.btc5_fill_count == 0
        assert s.btc5_skip_reasons == {}
        assert s.weather_shadow_present is False
        assert s.proposed_mutations == []
        assert s.expected_accepted_mutations == 0

    def test_custom_fields(self):
        s = ReplayScenario(
            name="custom",
            description="custom scenario",
            btc5_rows=100,
            btc5_fill_count=10,
            weather_shadow_present=True,
            weather_arr_confidence=0.65,
        )
        assert s.btc5_rows == 100
        assert s.weather_arr_confidence == pytest.approx(0.65)


# ---------------------------------------------------------------------------
# run_replay_gauntlet — integration tests (no strict assertion checks)
# ---------------------------------------------------------------------------


class TestRunReplayGauntlet:
    """Run the gauntlet pipeline end-to-end; don't assert on kernel internals
    since expected state strings are subject to kernel logic changes."""

    def _minimal_scenario(self, name: str = "test_minimal") -> ReplayScenario:
        """A scenario with no expected assertions — will always pass."""
        return ReplayScenario(
            name=name,
            description="minimal test scenario",
            btc5_rows=100,
            btc5_fill_count=5,
            btc5_skip_reasons={"skip_delta_too_large": 80, "skip_other": 15},
            weather_shadow_present=True,
            weather_candidate_count=2,
            weather_arr_confidence=0.45,
            stale_fallback_used=False,
            # No expected_* fields — harness won't assert on them
        )

    def test_gauntlet_returns_gauntlet_result(self):
        scenario = self._minimal_scenario()
        result = run_replay_gauntlet(scenario)
        assert isinstance(result, GauntletResult)
        assert result.scenario_name == "test_minimal"

    def test_gauntlet_passes_with_no_assertions(self):
        scenario = self._minimal_scenario()
        result = run_replay_gauntlet(scenario)
        assert result.passed is True
        assert result.failures == []

    def test_gauntlet_has_kernel_decision(self):
        scenario = self._minimal_scenario()
        result = run_replay_gauntlet(scenario)
        assert isinstance(result.kernel_decision, str)
        assert len(result.kernel_decision) > 0

    def test_stale_fallback_scenario_runs(self):
        scenario = ReplayScenario(
            name="stale_test",
            description="stale fallback test",
            btc5_rows=0,
            btc5_fill_count=0,
            stale_fallback_used=True,
            expected_stale_fallback=True,  # must match actual
        )
        result = run_replay_gauntlet(scenario)
        assert isinstance(result, GauntletResult)
        assert result.passed is True

    def test_stale_fallback_assertion_fails_when_mismatched(self):
        scenario = ReplayScenario(
            name="stale_mismatch",
            description="expects stale but is not stale",
            btc5_rows=100,
            btc5_fill_count=5,
            stale_fallback_used=False,
            expected_stale_fallback=True,  # mismatch — should fail
        )
        result = run_replay_gauntlet(scenario)
        assert result.passed is False
        assert any("stale_fallback_used" in f for f in result.failures)

    def test_mutation_counts_with_no_mutations(self):
        scenario = self._minimal_scenario()
        result = run_replay_gauntlet(scenario)
        assert result.accepted_mutations == 0
        assert result.rejected_mutations == 0


# ---------------------------------------------------------------------------
# run_full_harness
# ---------------------------------------------------------------------------


class TestRunFullHarness:
    def _no_assertion_scenario(self, name: str) -> ReplayScenario:
        return ReplayScenario(name=name, description=f"harness test {name}")

    def test_empty_scenarios_list(self):
        result = run_full_harness(scenarios=[], now=_NOW)
        assert isinstance(result, HarnessResult)
        assert result.scenarios_run == 0
        assert result.scenarios_passed == 0
        assert result.harness_passed is True  # 0 failed

    def test_single_passing_scenario(self):
        scenarios = [self._no_assertion_scenario("h_test")]
        result = run_full_harness(scenarios=scenarios, now=_NOW)
        assert result.scenarios_run == 1
        assert result.scenarios_passed == 1
        assert result.scenarios_failed == 0
        assert result.harness_passed is True

    def test_returns_harness_result_dataclass(self):
        result = run_full_harness(scenarios=[], now=_NOW)
        assert isinstance(result, HarnessResult)
        assert isinstance(result.intelligence_metrics, IntelligenceMetrics)
        assert isinstance(result.gauntlet_results, list)

    def test_writes_output_file(self, tmp_path: Path):
        out = tmp_path / "harness_out.json"
        run_full_harness(scenarios=[], output_path=out, now=_NOW)
        assert out.exists()
        payload = json.loads(out.read_text())
        assert payload["schema"] == "harness_result.v1"
        assert "intelligence_metrics" in payload
        assert "gauntlet_results" in payload

    def test_output_has_generated_at(self, tmp_path: Path):
        out = tmp_path / "harness_out.json"
        run_full_harness(scenarios=[], output_path=out, now=_NOW)
        payload = json.loads(out.read_text())
        assert "2026-03-22" in payload["generated_at"]

    def test_multiple_scenarios_counted(self):
        scenarios = [
            self._no_assertion_scenario("s1"),
            self._no_assertion_scenario("s2"),
            self._no_assertion_scenario("s3"),
        ]
        result = run_full_harness(scenarios=scenarios, now=_NOW)
        assert result.scenarios_run == 3

    def test_harness_result_to_dict(self):
        result = run_full_harness(scenarios=[], now=_NOW)
        d = result.to_dict()
        assert d["schema"] == "harness_result.v1"
        assert isinstance(d["scenarios_run"], int)
        assert isinstance(d["harness_passed"], bool)

    def test_all_canonical_gauntlets_run(self, tmp_path: Path):
        """Run ALL_GAUNTLETS through the full harness."""
        out = tmp_path / "full.json"
        result = run_full_harness(output_path=out, now=_NOW)
        assert result.scenarios_run == 5
        scenario_names = {r.scenario_name for r in result.gauntlet_results}
        assert "mar15_btc_concentration_failure" in scenario_names
        assert "mar11_btc_winning_windows" in scenario_names
        assert "weather_official_source_shock" in scenario_names
        assert "stale_fallback_discovery" in scenario_names
        assert "mar22_btc_daily_drawdown" in scenario_names
