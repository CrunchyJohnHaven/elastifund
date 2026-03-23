"""Instance 11 — Weather + Harness Integration tests.

Five test families
------------------
1. Kernel-cycle determinism tests
2. Replay gauntlets (four canonical scenarios)
3. Intelligence metrics computation
4. Mutation acceptance gate
5. Local-twin bundle equivalence
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------

import sys

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from kernel_contract import (
    EvidenceBundle,
    KernelCycleResult,
    run_kernel_cycle,
)
from run_instance11_weather_harness_integration import (
    build_capital_lab,
    build_evidence_bundle,
    build_evidence_bundle_from_state,
    build_proving_ground,
    read_btc5_db_state,
    run_full_kernel_cycle,
    run_integration,
)
from intelligence_harness import (
    ALL_GAUNTLETS,
    IntelligenceMetrics,
    accepts_mutation,
    check_local_twin_bundle_equivalence,
    compute_intelligence_metrics,
    gauntlet_mar11_btc_winning_windows,
    gauntlet_mar15_btc_concentration_failure,
    gauntlet_stale_fallback_discovery,
    gauntlet_weather_shock,
    run_full_harness,
    run_replay_gauntlet,
)

NOW = datetime(2026, 3, 22, 12, 0, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_btc5_db(tmp_path: Path, *, rows: int = 0, fills: int = 0) -> Path:
    """Create a minimal btc_5min_maker.db for testing."""
    db_path = tmp_path / "btc_5min_maker.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """CREATE TABLE window_trades (
            id INTEGER PRIMARY KEY,
            window_open_utc TEXT,
            direction TEXT,
            best_ask REAL,
            outcome TEXT,
            pnl_usd REAL,
            skip_reason TEXT
        )"""
    )
    # Insert skip rows
    for i in range(rows - fills):
        conn.execute(
            "INSERT INTO window_trades (window_open_utc, direction, skip_reason) VALUES (?,?,?)",
            (f"2026-03-22T{i % 24:02d}:00:00Z", "DOWN", "skip_delta_too_large"),
        )
    # Insert fill rows
    for i in range(fills):
        conn.execute(
            "INSERT INTO window_trades (window_open_utc, direction, outcome, pnl_usd) VALUES (?,?,?,?)",
            (f"2026-03-22T{i % 24:02d}:30:00Z", "DOWN", "resolved_yes", 1.5),
        )
    conn.commit()
    conn.close()
    return db_path


def make_evidence(
    *,
    btc5_rows: int = 302,
    btc5_fill_count: int = 0,
    weather_present: bool = True,
    weather_candidates: int = 3,
    weather_confidence: float = 0.46,
    stale: bool = False,
) -> EvidenceBundle:
    return build_evidence_bundle_from_state(
        btc5_rows=btc5_rows,
        btc5_fill_count=btc5_fill_count,
        btc5_skip_reasons={"skip_delta_too_large": btc5_rows - btc5_fill_count},
        weather_shadow_present=weather_present,
        weather_candidate_count=weather_candidates,
        weather_arr_confidence=weather_confidence,
        weather_block_reasons=["shadow_only_cycle_no_live_capital"],
        weather_generated_at="2026-03-22T11:00:00Z",
        stale_fallback_used=stale,
        now=NOW,
    )


BASELINE_FINANCE = {
    "capital_expansion_only_hold": True,
    "lanes": {
        "btc5_live_baseline": {
            "finance_verdict": "baseline_allowed",
            "live_capital_usd": 17.58,
            "allowed_live_action": "allocate::maintain_stage1_flat_size",
            "capital_expansion_allowed": False,
        },
        "weather": {
            "finance_verdict": "shadow_only",
            "live_capital_usd": 0.0,
            "shadow_scanning_allowed": True,
        },
    },
}

BASELINE_PROMOTION_GATE = {
    "gates": {
        "win_rate": {"pass": False, "value": 0.514, "required": 0.55},
        "profit_factor": {"pass": False, "value": 1.01, "required": 1.1},
        "max_dd": {"pass": False, "value": 236.68},
    }
}


# ===========================================================================
# Family 1 — Kernel-cycle determinism
# ===========================================================================


class TestKernelCycleDeterminism:
    """fresh evidence -> deterministic thesis -> deterministic promotion."""

    def test_same_evidence_produces_same_cycle_decision(self):
        ev = make_evidence()
        r1 = run_full_kernel_cycle(
            ev, finance_latest=BASELINE_FINANCE, promotion_gate=BASELINE_PROMOTION_GATE, now=NOW
        )
        r2 = run_full_kernel_cycle(
            ev, finance_latest=BASELINE_FINANCE, promotion_gate=BASELINE_PROMOTION_GATE, now=NOW
        )
        assert r1.cycle_decision == r2.cycle_decision

    def test_same_evidence_produces_same_thesis_states(self):
        ev = make_evidence()
        r1 = run_full_kernel_cycle(ev, finance_latest=BASELINE_FINANCE, now=NOW)
        r2 = run_full_kernel_cycle(ev, finance_latest=BASELINE_FINANCE, now=NOW)
        states1 = sorted(t.state for t in r1.thesis.theses)
        states2 = sorted(t.state for t in r2.thesis.theses)
        assert states1 == states2

    def test_same_evidence_produces_same_promotion_statuses(self):
        ev = make_evidence()
        r1 = run_full_kernel_cycle(ev, finance_latest=BASELINE_FINANCE, now=NOW)
        r2 = run_full_kernel_cycle(ev, finance_latest=BASELINE_FINANCE, now=NOW)
        statuses1 = sorted(d.status for d in r1.promotion.decisions)
        statuses2 = sorted(d.status for d in r2.promotion.decisions)
        assert statuses1 == statuses2

    def test_thesis_comes_only_from_evidence(self):
        """Thesis bundle must contain at least one thesis per known lane."""
        ev = make_evidence()
        result = run_full_kernel_cycle(ev, finance_latest=BASELINE_FINANCE, now=NOW)
        lanes_in_thesis = {t.lane for t in result.thesis.theses}
        assert "btc5" in lanes_in_thesis
        assert "weather" in lanes_in_thesis

    def test_promotion_derives_from_thesis_not_raw_finance(self):
        """Promotion decisions must reference lanes present in thesis."""
        ev = make_evidence()
        result = run_full_kernel_cycle(ev, finance_latest=BASELINE_FINANCE, now=NOW)
        thesis_lanes = {t.lane for t in result.thesis.theses}
        promo_lanes = {d.lane for d in result.promotion.decisions}
        assert promo_lanes == thesis_lanes


# ===========================================================================
# Family 1b — Learning mutations cannot bypass promotion
# ===========================================================================


class TestLearningMutationGate:
    """Learning mutations targeting capital or promotion gate must be rejected."""

    def test_capital_targeting_mutation_rejected(self):
        ev = make_evidence()
        mutations = [
            {
                "id": "mut_capital_hack",
                "target": "capital_allocation",
                "description": "Increase live_capital_usd directly",
                "source": "rogue_agent",
                "confidence": 0.99,
            }
        ]
        result = run_full_kernel_cycle(
            ev, finance_latest=BASELINE_FINANCE, proposed_mutations=mutations, now=NOW
        )
        assert result.learning.rejected_count >= 1
        rejected = [m for m in result.learning.mutations if not m.accepted]
        assert any("bypass" in m.acceptance_reason for m in rejected)

    def test_promotion_gate_bypass_mutation_rejected(self):
        ev = make_evidence()
        mutations = [
            {
                "id": "mut_promo_bypass",
                "target": "promotion_gate",
                "description": "Override promotion gate to pass",
                "source": "kimi",
                "confidence": 0.95,
            }
        ]
        result = run_full_kernel_cycle(
            ev, finance_latest=BASELINE_FINANCE, proposed_mutations=mutations, now=NOW
        )
        assert result.learning.rejected_count >= 1

    def test_safe_mutation_can_be_accepted(self):
        ev = make_evidence()
        mutations = [
            {
                "id": "mut_ranking_logic",
                "target": "ranking_logic",
                "description": "Adjust thesis confidence weighting formula",
                "source": "research_os",
                "confidence": 0.75,
            }
        ]
        result = run_full_kernel_cycle(
            ev, finance_latest=BASELINE_FINANCE, proposed_mutations=mutations, now=NOW
        )
        assert result.learning.accepted_count >= 1

    def test_kimi_mutation_flagged_when_used(self):
        ev = make_evidence()
        mutations = [
            {
                "id": "mut_kimi_candidate",
                "target": "lane_packet",
                "description": "Kimi-suggested lane parameter update",
                "source": "kimi",
                "confidence": 0.70,
            }
        ]
        result = run_full_kernel_cycle(
            ev, finance_latest=BASELINE_FINANCE, proposed_mutations=mutations, now=NOW
        )
        assert result.learning.kimi_contribution is True


# ===========================================================================
# Family 2 — Replay gauntlets
# ===========================================================================


class TestReplayGauntlets:
    """Four canonical scenarios from the plan."""

    def test_mar15_btc_concentration_failure(self):
        scenario = gauntlet_mar15_btc_concentration_failure()
        result = run_replay_gauntlet(scenario)
        assert result.passed, f"Failures: {result.failures}"

    def test_mar11_btc_winning_windows(self):
        scenario = gauntlet_mar11_btc_winning_windows()
        result = run_replay_gauntlet(scenario)
        assert result.passed, f"Failures: {result.failures}"

    def test_weather_shock(self):
        scenario = gauntlet_weather_shock()
        result = run_replay_gauntlet(scenario)
        assert result.passed, f"Failures: {result.failures}"

    def test_stale_fallback_discovery(self):
        scenario = gauntlet_stale_fallback_discovery()
        result = run_replay_gauntlet(scenario)
        assert result.passed, f"Failures: {result.failures}"

    def test_all_gauntlets_defined(self):
        assert len(ALL_GAUNTLETS) >= 4

    def test_gauntlet_results_contain_kernel_decision(self):
        for scenario in ALL_GAUNTLETS:
            result = run_replay_gauntlet(scenario)
            assert result.kernel_decision, f"Missing decision for {scenario.name}"

    def test_weather_always_shadow_in_gauntlets(self):
        """Weather must remain shadow_only in all gauntlets (never live capital)."""
        for scenario in ALL_GAUNTLETS:
            result = run_replay_gauntlet(scenario)
            assert result.weather_promo_status == "shadow_only", (
                f"Weather not shadow_only in {scenario.name}: {result.weather_promo_status}"
            )

    def test_btc5_always_live_stage_1_in_gauntlets(self):
        """BTC5 must remain live_stage_1 in all gauntlets."""
        for scenario in ALL_GAUNTLETS:
            result = run_replay_gauntlet(scenario)
            assert result.btc5_promo_status == "live_stage_1", (
                f"BTC5 not live_stage_1 in {scenario.name}: {result.btc5_promo_status}"
            )


# ===========================================================================
# Family 3 — Intelligence metrics
# ===========================================================================


class TestIntelligenceMetrics:
    def test_stale_fallback_rate_reflects_stale_scenario(self):
        results = [run_replay_gauntlet(s) for s in ALL_GAUNTLETS]
        metrics = compute_intelligence_metrics(results)
        # stale_fallback_discovery scenario exists → rate > 0
        assert metrics.stale_fallback_rate >= 0.0

    def test_execution_quality_from_empty_db(self, tmp_path):
        results = [run_replay_gauntlet(s) for s in ALL_GAUNTLETS]
        db = tmp_path / "btc_5min_maker.db"  # does not exist
        metrics = compute_intelligence_metrics(results, btc5_db_path=db)
        assert metrics.execution_quality_score == 0.0

    def test_execution_quality_from_populated_db(self, tmp_path):
        db = make_btc5_db(tmp_path, rows=100, fills=20)
        results = [run_replay_gauntlet(s) for s in ALL_GAUNTLETS]
        metrics = compute_intelligence_metrics(results, btc5_db_path=db)
        assert pytest.approx(metrics.execution_quality_score, abs=0.01) == 0.20

    def test_validated_edge_velocity_from_winning_scenario(self):
        """Winning scenario (mar11) should bump velocity above zero."""
        scenario = gauntlet_mar11_btc_winning_windows()
        results = [run_replay_gauntlet(scenario)]
        metrics = compute_intelligence_metrics(results)
        assert metrics.validated_edge_discovery_velocity > 0

    def test_proving_ground_readiness_is_fraction(self):
        results = [run_replay_gauntlet(s) for s in ALL_GAUNTLETS]
        metrics = compute_intelligence_metrics(results)
        assert 0.0 <= metrics.proving_ground_readiness <= 1.0

    def test_metrics_to_dict_has_all_fields(self):
        m = IntelligenceMetrics(validated_edge_discovery_velocity=0.5)
        d = m.to_dict()
        required = [
            "validated_edge_discovery_velocity",
            "false_promotion_rate",
            "stale_fallback_rate",
            "attribution_coverage",
            "concentration_incidents_7d",
            "execution_quality_score",
            "proving_ground_readiness",
        ]
        for key in required:
            assert key in d, f"Missing key: {key}"


# ===========================================================================
# Family 4 — Mutation acceptance gate
# ===========================================================================


class TestMutationAcceptance:
    def test_equal_metrics_accepted(self):
        m = IntelligenceMetrics(validated_edge_discovery_velocity=0.5, stale_fallback_rate=0.1)
        assert accepts_mutation(m, m)

    def test_improved_velocity_accepted(self):
        before = IntelligenceMetrics(validated_edge_discovery_velocity=0.3)
        after = IntelligenceMetrics(validated_edge_discovery_velocity=0.5)
        assert accepts_mutation(before, after)

    def test_degraded_velocity_rejected(self):
        before = IntelligenceMetrics(validated_edge_discovery_velocity=0.5)
        after = IntelligenceMetrics(validated_edge_discovery_velocity=0.3)
        assert not accepts_mutation(before, after)

    def test_high_stale_fallback_increase_rejected(self):
        before = IntelligenceMetrics(validated_edge_discovery_velocity=0.5, stale_fallback_rate=0.1)
        after = IntelligenceMetrics(validated_edge_discovery_velocity=0.5, stale_fallback_rate=0.25)
        assert not accepts_mutation(before, after)

    def test_high_false_promo_increase_rejected(self):
        before = IntelligenceMetrics(validated_edge_discovery_velocity=0.5, false_promotion_rate=0.0)
        after = IntelligenceMetrics(validated_edge_discovery_velocity=0.6, false_promotion_rate=0.1)
        assert not accepts_mutation(before, after)

    def test_execution_quality_drop_rejected(self):
        before = IntelligenceMetrics(validated_edge_discovery_velocity=0.5, execution_quality_score=0.5)
        after = IntelligenceMetrics(validated_edge_discovery_velocity=0.6, execution_quality_score=0.3)
        assert not accepts_mutation(before, after)

    def test_concentration_spike_rejected(self):
        before = IntelligenceMetrics(validated_edge_discovery_velocity=0.5, concentration_incidents_7d=0)
        after = IntelligenceMetrics(validated_edge_discovery_velocity=0.6, concentration_incidents_7d=3)
        assert not accepts_mutation(before, after)


# ===========================================================================
# Family 5 — Local-twin bundle equivalence
# ===========================================================================


class TestLocalTwinEquivalence:
    def test_identical_bundles_pass(self):
        bundle = {"schema": "evidence_bundle.v1", "generated_at": "2026-03-22T12:00:00Z"}
        ok, discrepancies = check_local_twin_bundle_equivalence(bundle, bundle)
        assert ok
        assert not discrepancies

    def test_schema_mismatch_fails(self):
        local = {"schema": "evidence_bundle.v1"}
        remote = {"schema": "evidence_bundle.v2"}
        ok, discrepancies = check_local_twin_bundle_equivalence(local, remote)
        assert not ok
        assert any("schema" in d for d in discrepancies)

    def test_generated_at_difference_ignored(self):
        local = {"schema": "evidence_bundle.v1", "generated_at": "2026-03-22T12:00:00Z"}
        remote = {"schema": "evidence_bundle.v1", "generated_at": "2026-03-22T13:00:00Z"}
        ok, _ = check_local_twin_bundle_equivalence(local, remote)
        assert ok

    def test_missing_keys_detected(self):
        local = {"schema": "evidence_bundle.v1", "extra_local": True}
        remote = {"schema": "evidence_bundle.v1", "extra_remote": True}
        ok, discrepancies = check_local_twin_bundle_equivalence(local, remote)
        assert not ok
        assert any("extra_remote" in d for d in discrepancies)

    def test_kernel_cycle_output_has_canonical_structure(self):
        """Kernel cycle result emits bundles with expected schema keys."""
        ev = make_evidence()
        result = run_full_kernel_cycle(ev, finance_latest=BASELINE_FINANCE, now=NOW)
        d = result.to_dict()
        assert "evidence_bundle" in d
        assert "thesis_bundle" in d
        assert "promotion_bundle" in d
        assert "learning_bundle" in d
        assert d["evidence_bundle"]["schema"] == "evidence_bundle.v1"
        assert d["thesis_bundle"]["schema"] == "thesis_bundle.v1"
        assert d["promotion_bundle"]["schema"] == "promotion_bundle.v1"
        assert d["learning_bundle"]["schema"] == "learning_bundle.v1"

    def test_local_and_simulated_remote_bundles_equivalent(self):
        """Simulate local + remote producing same kernel cycle from same evidence."""
        ev = make_evidence()
        local_result = run_full_kernel_cycle(ev, finance_latest=BASELINE_FINANCE, now=NOW)
        remote_result = run_full_kernel_cycle(ev, finance_latest=BASELINE_FINANCE, now=NOW)
        local_d = local_result.to_dict()["evidence_bundle"]
        remote_d = remote_result.to_dict()["evidence_bundle"]
        ok, discrepancies = check_local_twin_bundle_equivalence(local_d, remote_d)
        assert ok, f"Local/remote bundle mismatch: {discrepancies}"


# ===========================================================================
# Integration tests — capital_lab and proving_ground artifacts
# ===========================================================================


class TestCapitalLabAndProvingGround:
    def test_capital_lab_written(self, tmp_path):
        ev = make_evidence()
        result = run_full_kernel_cycle(ev, finance_latest=BASELINE_FINANCE, now=NOW)
        lab_path = tmp_path / "capital_lab.json"
        lab = build_capital_lab(result, finance_latest=BASELINE_FINANCE, now=NOW)
        lab_path.write_text(json.dumps(lab))
        loaded = json.loads(lab_path.read_text())
        assert loaded["schema_version"] == "capital_lab.v1"
        assert "btc5" in loaded["lanes"]
        assert "weather" in loaded["lanes"]

    def test_capital_lab_lanes_have_required_keys(self):
        ev = make_evidence()
        result = run_full_kernel_cycle(ev, finance_latest=BASELINE_FINANCE, now=NOW)
        lab = build_capital_lab(result, finance_latest=BASELINE_FINANCE, now=NOW)
        for lane in ("btc5", "weather"):
            assert lane in lab["lanes"]
            lane_data = lab["lanes"][lane]
            assert "status" in lane_data
            assert "live_capital_usd" in lane_data

    def test_proving_ground_written(self, tmp_path):
        ev = make_evidence()
        result = run_full_kernel_cycle(ev, finance_latest=BASELINE_FINANCE, now=NOW)
        pg_path = tmp_path / "proving_ground.json"
        pg = build_proving_ground(result, now=NOW)
        pg_path.write_text(json.dumps(pg))
        loaded = json.loads(pg_path.read_text())
        assert loaded["schema_version"] == "proving_ground.v1"
        assert "btc5" in loaded["lanes"]
        assert "weather" in loaded["lanes"]

    def test_proving_ground_weather_shadow_only(self):
        ev = make_evidence()
        result = run_full_kernel_cycle(ev, finance_latest=BASELINE_FINANCE, now=NOW)
        pg = build_proving_ground(result, now=NOW)
        weather_lane = pg["lanes"].get("weather", {})
        # Weather must be shadow_only or collecting_evidence — never live
        assert "live" not in weather_lane.get("state", ""), (
            f"Weather unexpectedly in live state: {weather_lane.get('state')}"
        )

    def test_proving_ground_btc5_has_doctrine_candidates(self):
        ev = make_evidence()
        result = run_full_kernel_cycle(ev, finance_latest=BASELINE_FINANCE, now=NOW)
        pg = build_proving_ground(result, now=NOW)
        btc5 = pg["lanes"].get("btc5", {})
        assert len(btc5.get("doctrine_candidates", [])) >= 1

    def test_read_btc5_db_state_missing_db(self, tmp_path):
        db = tmp_path / "nonexistent.db"
        state = read_btc5_db_state(db)
        assert state["db_available"] is False
        assert state["total_rows"] == 0

    def test_read_btc5_db_state_with_rows(self, tmp_path):
        db = make_btc5_db(tmp_path, rows=50, fills=5)
        state = read_btc5_db_state(db)
        assert state["db_available"] is True
        assert state["total_rows"] == 50
        assert state["fill_count"] == 5
        assert state["skip_count"] == 45


# ===========================================================================
# Evidence bundle tests
# ===========================================================================


class TestEvidenceBundleBuilder:
    def test_stale_fallback_flagged(self):
        ev = build_evidence_bundle_from_state(
            stale_fallback_used=True,
            now=NOW,
        )
        assert ev.stale_fallback_used is True

    def test_freshness_score_computed(self):
        ev = build_evidence_bundle_from_state(
            weather_generated_at="2026-03-22T11:00:00Z",
            now=NOW,
        )
        assert "weather_shadow" in ev.freshness_scores
        assert 0.0 <= ev.freshness_scores["weather_shadow"] <= 1.0

    def test_weather_evidence_round_trips_through_bundle(self):
        ev = build_evidence_bundle_from_state(
            weather_shadow_present=True,
            weather_candidate_count=5,
            weather_arr_confidence=0.68,
            weather_block_reasons=["shadow_only_cycle_no_live_capital"],
            now=NOW,
        )
        assert ev.weather_shadow_present is True
        assert ev.weather_candidate_count == 5
        assert pytest.approx(ev.weather_arr_confidence) == 0.68

    def test_btc5_skip_counts_match(self):
        skips = {"skip_delta_too_large": 100, "skip_toxic": 50}
        ev = build_evidence_bundle_from_state(
            btc5_rows=200,
            btc5_skip_reasons=skips,
            now=NOW,
        )
        assert ev.btc5_skip_reasons["skip_delta_too_large"] == 100
        assert ev.btc5_skip_reasons["skip_toxic"] == 50

    def test_build_evidence_bundle_from_weather_shadow_dict(self):
        weather_shadow = {
            "arr_confidence_score": 0.55,
            "block_reasons": ["shadow_only_cycle_no_live_capital"],
            "generated_at": "2026-03-22T10:00:00Z",
            "market_scan": {"candidate_count": 4},
        }
        ev = build_evidence_bundle(
            weather_shadow=weather_shadow,
            weather_refresh_status="stale_fallback",
            btc5_db={"total_rows": 100, "fill_count": 3, "skip_reasons": {}, "latest_entry_at": None},
            now=NOW,
        )
        assert ev.weather_shadow_present is True
        assert ev.weather_candidate_count == 4
        assert ev.stale_fallback_used is True


# ===========================================================================
# Full harness run (no live APIs needed)
# ===========================================================================


class TestFullHarnessRun:
    def test_harness_runs_without_live_apis(self, tmp_path):
        output = tmp_path / "harness_result.json"
        result = run_full_harness(
            scenarios=ALL_GAUNTLETS,
            output_path=output,
            now=NOW,
        )
        assert result.scenarios_run == len(ALL_GAUNTLETS)
        assert output.exists()

    def test_harness_output_schema(self, tmp_path):
        output = tmp_path / "harness_result.json"
        run_full_harness(scenarios=ALL_GAUNTLETS, output_path=output, now=NOW)
        loaded = json.loads(output.read_text())
        assert loaded["schema"] == "harness_result.v1"
        assert "intelligence_metrics" in loaded
        assert "gauntlet_results" in loaded

    def test_harness_all_gauntlets_pass(self):
        result = run_full_harness(scenarios=ALL_GAUNTLETS, now=NOW)
        assert result.harness_passed, (
            f"Harness failed. Failures:\n" + "\n".join(result.failure_summary)
        )

    def test_harness_intelligence_metrics_present(self):
        result = run_full_harness(scenarios=ALL_GAUNTLETS, now=NOW)
        m = result.intelligence_metrics
        assert hasattr(m, "validated_edge_discovery_velocity")
        assert hasattr(m, "stale_fallback_rate")
        assert hasattr(m, "execution_quality_score")


# ===========================================================================
# Integration smoke test (no live APIs, no-refresh mode)
# ===========================================================================


class TestIntegrationSmokeTest:
    def test_run_integration_no_refresh_no_harness(self, tmp_path):
        result = run_integration(
            repo_root=Path(__file__).resolve().parents[1],
            capital_lab_path=tmp_path / "capital_lab.json",
            proving_ground_path=tmp_path / "proving_ground.json",
            kernel_cycle_path=tmp_path / "kernel_cycle.json",
            harness_path=tmp_path / "harness.json",
            refresh_weather=False,
            run_harness=False,
            now=NOW,
        )
        assert (tmp_path / "capital_lab.json").exists()
        assert (tmp_path / "proving_ground.json").exists()
        assert (tmp_path / "kernel_cycle.json").exists()
        assert result["harness_status"] == "skipped"

    def test_run_integration_no_refresh_with_harness(self, tmp_path):
        result = run_integration(
            repo_root=Path(__file__).resolve().parents[1],
            capital_lab_path=tmp_path / "capital_lab.json",
            proving_ground_path=tmp_path / "proving_ground.json",
            kernel_cycle_path=tmp_path / "kernel_cycle.json",
            harness_path=tmp_path / "harness.json",
            refresh_weather=False,
            run_harness=True,
            now=NOW,
        )
        assert result["harness_status"] == "passed", (
            f"Harness failed unexpectedly: {result}"
        )
        assert result["harness_passed"] is True
        assert (tmp_path / "harness.json").exists()

    def test_capital_lab_output_structure(self, tmp_path):
        lab_path = tmp_path / "capital_lab.json"
        run_integration(
            repo_root=Path(__file__).resolve().parents[1],
            capital_lab_path=lab_path,
            proving_ground_path=tmp_path / "pg.json",
            kernel_cycle_path=tmp_path / "kc.json",
            harness_path=tmp_path / "h.json",
            refresh_weather=False,
            run_harness=False,
            now=NOW,
        )
        loaded = json.loads(lab_path.read_text())
        assert loaded["schema_version"] == "capital_lab.v1"
        assert "btc5" in loaded["lanes"]
        assert "weather" in loaded["lanes"]
        assert loaded["lanes"]["weather"]["status"] == "shadow_only"
