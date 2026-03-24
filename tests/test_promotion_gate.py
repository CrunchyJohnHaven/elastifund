"""Tests for the 5-proof promotion gate system."""

import json
import tempfile
from pathlib import Path

from src.hypothesis_card import HypothesisCard, ProofStatus
from src.promotion_gate import (
    CheckResult,
    GateResult,
    PromotionGate,
    TierResult,
    ValidationTier,
    run_bronze,
    run_gold,
    run_platinum,
    run_silver,
)


def _passing_bronze_metrics() -> dict:
    return {
        "train_sharpe": 1.5,
        "test_sharpe": 1.0,
        "ev_taker": 0.03,
        "baseline_ev": 0.0,
        "ev_conservative_costs": 0.01,
        "rolling_negative_window_pct": 0.2,
        "sign_consistent": True,
    }


def _passing_silver_metrics() -> dict:
    return {
        "walk_forward_oos_sharpe": 0.8,
        "regimes_with_positive_ev": 3,
        "top_instrument_concentration": 0.3,
        "ev_realistic_costs": 0.02,
        "residual_alpha": 0.01,
    }


def _passing_gold_metrics() -> dict:
    return {
        "purged_cv_alpha": 0.015,
        "locked_holdout_ev": 0.01,
        "corrected_p_value": 0.02,
        "deflated_sharpe_ratio": 0.7,
        "parameter_stability": 0.8,
    }


def _passing_platinum_metrics() -> dict:
    return {
        "shadow_sim_correlation": 0.85,
        "paper_trading_pnl": 50.0,
        "paper_trading_days": 14,
        "micro_live_pnl": 20.0,
        "micro_live_trades": 50,
        "sim_vs_live_discrepancy": 0.1,
    }


def _all_passing_metrics() -> dict:
    m: dict = {}
    m.update(_passing_bronze_metrics())
    m.update(_passing_silver_metrics())
    m.update(_passing_gold_metrics())
    m.update(_passing_platinum_metrics())
    return m


def _make_card(all_proofs_passed: bool = False) -> HypothesisCard:
    card = HypothesisCard(
        hypothesis_name="test_strat",
        hypothesis_id="hyp_test",
        family="btc5",
    )
    if all_proofs_passed:
        for proof in ("mechanism", "data", "statistical", "execution", "live"):
            card.update_proof(proof, ProofStatus.PASSED)
    return card


class TestBronzeTier:
    def test_all_pass(self):
        result = run_bronze(_passing_bronze_metrics())
        assert result.passed is True
        assert result.tier == ValidationTier.BRONZE

    def test_leakage_fails(self):
        m = _passing_bronze_metrics()
        m["train_sharpe"] = 10.0
        m["test_sharpe"] = 1.0
        result = run_bronze(m)
        assert result.passed is False
        failed = [c.check_name for c in result.failed_checks]
        assert "leakage_check" in failed

    def test_baseline_fails(self):
        m = _passing_bronze_metrics()
        m["ev_taker"] = -0.01
        m["baseline_ev"] = 0.0
        result = run_bronze(m)
        assert result.passed is False

    def test_skipped_checks_dont_block(self):
        # Only provide leakage and baseline data
        m = {"train_sharpe": 1.5, "test_sharpe": 1.0, "ev_taker": 0.03, "baseline_ev": 0.0}
        result = run_bronze(m)
        assert result.passed is True  # skipped checks dont fail


class TestSilverTier:
    def test_all_pass(self):
        result = run_silver(_passing_silver_metrics())
        assert result.passed is True

    def test_concentration_fails(self):
        m = _passing_silver_metrics()
        m["top_instrument_concentration"] = 0.8
        result = run_silver(m)
        assert result.passed is False

    def test_all_skipped_fails(self):
        result = run_silver({})
        assert result.passed is False


class TestGoldTier:
    def test_all_pass(self):
        result = run_gold(_passing_gold_metrics())
        assert result.passed is True

    def test_p_value_fails(self):
        m = _passing_gold_metrics()
        m["corrected_p_value"] = 0.15
        result = run_gold(m)
        assert result.passed is False

    def test_parameter_instability_fails(self):
        m = _passing_gold_metrics()
        m["parameter_stability"] = 0.3
        result = run_gold(m)
        assert result.passed is False


class TestPlatinumTier:
    def test_all_pass(self):
        result = run_platinum(_passing_platinum_metrics())
        assert result.passed is True

    def test_insufficient_paper_days(self):
        m = _passing_platinum_metrics()
        m["paper_trading_days"] = 3
        result = run_platinum(m)
        assert result.passed is False

    def test_insufficient_micro_trades(self):
        m = _passing_platinum_metrics()
        m["micro_live_trades"] = 10
        result = run_platinum(m)
        assert result.passed is False

    def test_sim_live_divergence_fails(self):
        m = _passing_platinum_metrics()
        m["sim_vs_live_discrepancy"] = 0.5
        result = run_platinum(m)
        assert result.passed is False


class TestPromotionGate:
    def test_full_promotion(self):
        card = _make_card(all_proofs_passed=True)
        gate = PromotionGate()
        result = gate.evaluate(card, _all_passing_metrics())
        assert result.promoted is True
        assert "ALL GATES PASSED" in result.notes

    def test_fails_without_proofs(self):
        card = _make_card(all_proofs_passed=False)
        gate = PromotionGate()
        result = gate.evaluate(card, _all_passing_metrics())
        assert result.promoted is False
        assert "proofs not passed" in result.notes

    def test_fails_with_bad_metrics(self):
        card = _make_card(all_proofs_passed=True)
        gate = PromotionGate()
        m = _all_passing_metrics()
        m["train_sharpe"] = 100.0  # extreme leakage
        m["test_sharpe"] = 1.0
        result = gate.evaluate(card, m)
        assert result.promoted is False

    def test_short_circuit(self):
        card = _make_card(all_proofs_passed=True)
        gate = PromotionGate()
        m = _all_passing_metrics()
        m["ev_taker"] = -1.0  # bronze fails
        m["baseline_ev"] = 0.0
        result = gate.evaluate(card, m, short_circuit=True)
        assert result.promoted is False
        # Silver/Gold/Platinum should not have been run
        assert "silver" not in result.tier_results

    def test_no_short_circuit(self):
        card = _make_card(all_proofs_passed=True)
        gate = PromotionGate()
        m = _all_passing_metrics()
        m["ev_taker"] = -1.0
        m["baseline_ev"] = 0.0
        result = gate.evaluate(card, m, short_circuit=False)
        assert result.promoted is False
        # All tiers should have been evaluated
        assert "silver" in result.tier_results

    def test_persistence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "gate.db"
            gate = PromotionGate(db_path=db_path)
            card = _make_card(all_proofs_passed=True)
            gate.evaluate(card, _all_passing_metrics())

            history = gate.history("hyp_test")
            assert len(history) == 1
            assert history[0]["promoted"] is True

    def test_to_dict_structure(self):
        card = _make_card(all_proofs_passed=True)
        gate = PromotionGate()
        result = gate.evaluate(card, _all_passing_metrics())
        d = result.to_dict()
        assert "hypothesis_id" in d
        assert "promoted" in d
        assert "tier_results" in d
        assert "proof_statuses" in d
        assert isinstance(d["tier_results"]["bronze"]["checks"], list)


class TestTierResult:
    def test_pass_rate(self):
        checks = [
            CheckResult("a", ValidationTier.BRONZE, GateResult.PASS),
            CheckResult("b", ValidationTier.BRONZE, GateResult.FAIL),
            CheckResult("c", ValidationTier.BRONZE, GateResult.SKIP),
        ]
        tr = TierResult(tier=ValidationTier.BRONZE, passed=False, checks=checks)
        assert tr.pass_rate == 0.5
        assert len(tr.failed_checks) == 1

    def test_all_skipped_pass_rate(self):
        checks = [
            CheckResult("a", ValidationTier.BRONZE, GateResult.SKIP),
        ]
        tr = TierResult(tier=ValidationTier.BRONZE, passed=False, checks=checks)
        assert tr.pass_rate == 0.0
