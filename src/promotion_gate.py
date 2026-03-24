"""5-proof promotion gate system with Bronze/Silver/Gold/Platinum validation tiers.

A strategy must pass ALL five proofs to be promoted to live trading:
1. Mechanism proof  -- believable reason the edge exists (named counterparties/constraints/flows)
2. Data proof       -- signal built from data genuinely available at decision time (no look-ahead)
3. Statistical proof -- survives out-of-sample, multiple-testing corrections, regime slicing
4. Execution proof  -- still profitable after realistic fills, slippage, latency, fees
5. Live proof       -- paper/micro-live behavior tracks simulator closely enough

Validation tiers gate progress through increasingly expensive checks:
- Bronze:   cheap rejection (leakage, baseline, conservative costs, rolling sanity, sign consistency)
- Silver:   full research (walk-forward, regime decomposition, per-instrument, realistic costs, exposure)
- Gold:     false-discovery defense (purged/embargoed splits, locked holdout, multiple-testing, DSR/PBO, param stability)
- Platinum: reality check (shadow mode, paper trading, micro-live, sim-vs-live comparison)
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any
import json
import sqlite3
import time
from pathlib import Path

from .hypothesis_card import HypothesisCard, ProofStatus


class ValidationTier(Enum):
    """Validation tiers, ordered by cost and rigor."""
    BRONZE = "bronze"
    SILVER = "silver"
    GOLD = "gold"
    PLATINUM = "platinum"


class GateResult(Enum):
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"


@dataclass
class CheckResult:
    """Result of a single validation check within a tier."""
    check_name: str
    tier: ValidationTier
    result: GateResult
    details: str = ""
    metric_value: float | None = None
    threshold: float | None = None


@dataclass
class TierResult:
    """Aggregate result for an entire validation tier."""
    tier: ValidationTier
    passed: bool
    checks: list[CheckResult] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    @property
    def failed_checks(self) -> list[CheckResult]:
        return [c for c in self.checks if c.result == GateResult.FAIL]

    @property
    def pass_rate(self) -> float:
        evaluated = [c for c in self.checks if c.result != GateResult.SKIP]
        if not evaluated:
            return 0.0
        return sum(1 for c in evaluated if c.result == GateResult.PASS) / len(evaluated)


@dataclass
class PromotionGateResult:
    """Full promotion gate evaluation across all tiers."""
    hypothesis_id: str
    promoted: bool
    tier_results: dict[str, TierResult] = field(default_factory=dict)
    proof_statuses: dict[str, str] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "hypothesis_id": self.hypothesis_id,
            "promoted": self.promoted,
            "timestamp": self.timestamp,
            "notes": self.notes,
            "proof_statuses": self.proof_statuses,
            "tier_results": {},
        }
        for tier_name, tr in self.tier_results.items():
            d["tier_results"][tier_name] = {
                "passed": tr.passed,
                "pass_rate": tr.pass_rate,
                "checks": [
                    {
                        "check_name": c.check_name,
                        "result": c.result.value,
                        "details": c.details,
                        "metric_value": c.metric_value,
                        "threshold": c.threshold,
                    }
                    for c in tr.checks
                ],
            }
        return d


# ---------------------------------------------------------------------------
# Bronze tier checks -- cheap rejection
# ---------------------------------------------------------------------------

def _check_leakage(metrics: dict[str, Any]) -> CheckResult:
    """Reject if train performance is suspiciously better than test."""
    train_sharpe = metrics.get("train_sharpe", 0.0)
    test_sharpe = metrics.get("test_sharpe", 0.0)
    ratio = train_sharpe / test_sharpe if test_sharpe > 0 else float("inf")
    passed = ratio < 3.0
    return CheckResult(
        check_name="leakage_check",
        tier=ValidationTier.BRONZE,
        result=GateResult.PASS if passed else GateResult.FAIL,
        details=f"Train/test Sharpe ratio: {ratio:.2f} (threshold: <3.0)",
        metric_value=ratio,
        threshold=3.0,
    )


def _check_baseline_comparison(metrics: dict[str, Any]) -> CheckResult:
    """Strategy must beat a naive baseline (e.g. random, buy-and-hold)."""
    strategy_ev = metrics.get("ev_taker", 0.0)
    baseline_ev = metrics.get("baseline_ev", 0.0)
    passed = strategy_ev > baseline_ev
    return CheckResult(
        check_name="baseline_comparison",
        tier=ValidationTier.BRONZE,
        result=GateResult.PASS if passed else GateResult.FAIL,
        details=f"Strategy EV: {strategy_ev:.4f} vs baseline: {baseline_ev:.4f}",
        metric_value=strategy_ev - baseline_ev,
        threshold=0.0,
    )


def _check_conservative_costs(metrics: dict[str, Any]) -> CheckResult:
    """Still profitable under 2x cost assumptions."""
    ev_conservative = metrics.get("ev_conservative_costs", None)
    if ev_conservative is None:
        return CheckResult(
            check_name="conservative_costs",
            tier=ValidationTier.BRONZE,
            result=GateResult.SKIP,
            details="No conservative cost data available",
        )
    passed = ev_conservative > 0
    return CheckResult(
        check_name="conservative_costs",
        tier=ValidationTier.BRONZE,
        result=GateResult.PASS if passed else GateResult.FAIL,
        details=f"EV under 2x costs: {ev_conservative:.4f}",
        metric_value=ev_conservative,
        threshold=0.0,
    )


def _check_rolling_window_sanity(metrics: dict[str, Any]) -> CheckResult:
    """Rolling window Sharpe must not be negative in >50% of windows."""
    negative_pct = metrics.get("rolling_negative_window_pct", None)
    if negative_pct is None:
        return CheckResult(
            check_name="rolling_window_sanity",
            tier=ValidationTier.BRONZE,
            result=GateResult.SKIP,
            details="No rolling window data",
        )
    passed = negative_pct < 0.5
    return CheckResult(
        check_name="rolling_window_sanity",
        tier=ValidationTier.BRONZE,
        result=GateResult.PASS if passed else GateResult.FAIL,
        details=f"Negative windows: {negative_pct:.1%} (threshold: <50%)",
        metric_value=negative_pct,
        threshold=0.5,
    )


def _check_sign_consistency(metrics: dict[str, Any]) -> CheckResult:
    """Direction of edge must be consistent across major data splits."""
    sign_consistent = metrics.get("sign_consistent", None)
    if sign_consistent is None:
        return CheckResult(
            check_name="sign_consistency",
            tier=ValidationTier.BRONZE,
            result=GateResult.SKIP,
            details="No sign consistency data",
        )
    return CheckResult(
        check_name="sign_consistency",
        tier=ValidationTier.BRONZE,
        result=GateResult.PASS if sign_consistent else GateResult.FAIL,
        details=f"Sign consistent across splits: {sign_consistent}",
    )


def run_bronze(metrics: dict[str, Any]) -> TierResult:
    """Run all Bronze tier checks. Cheap rejection gate."""
    checks = [
        _check_leakage(metrics),
        _check_baseline_comparison(metrics),
        _check_conservative_costs(metrics),
        _check_rolling_window_sanity(metrics),
        _check_sign_consistency(metrics),
    ]
    evaluated = [c for c in checks if c.result != GateResult.SKIP]
    passed = all(c.result == GateResult.PASS for c in evaluated) and len(evaluated) > 0
    return TierResult(tier=ValidationTier.BRONZE, passed=passed, checks=checks)


# ---------------------------------------------------------------------------
# Silver tier checks -- full research validation
# ---------------------------------------------------------------------------

def _check_walk_forward(metrics: dict[str, Any]) -> CheckResult:
    """Walk-forward optimization must show positive out-of-sample."""
    wf_oos_sharpe = metrics.get("walk_forward_oos_sharpe", None)
    if wf_oos_sharpe is None:
        return CheckResult(
            check_name="walk_forward",
            tier=ValidationTier.SILVER,
            result=GateResult.SKIP,
            details="No walk-forward data",
        )
    passed = wf_oos_sharpe > 0
    return CheckResult(
        check_name="walk_forward",
        tier=ValidationTier.SILVER,
        result=GateResult.PASS if passed else GateResult.FAIL,
        details=f"Walk-forward OOS Sharpe: {wf_oos_sharpe:.3f}",
        metric_value=wf_oos_sharpe,
        threshold=0.0,
    )


def _check_regime_decomposition(metrics: dict[str, Any]) -> CheckResult:
    """Edge must survive across at least 2 of 3 regime types."""
    regimes_positive = metrics.get("regimes_with_positive_ev", None)
    if regimes_positive is None:
        return CheckResult(
            check_name="regime_decomposition",
            tier=ValidationTier.SILVER,
            result=GateResult.SKIP,
            details="No regime data",
        )
    passed = regimes_positive >= 2
    return CheckResult(
        check_name="regime_decomposition",
        tier=ValidationTier.SILVER,
        result=GateResult.PASS if passed else GateResult.FAIL,
        details=f"Regimes with positive EV: {regimes_positive}/3",
        metric_value=float(regimes_positive),
        threshold=2.0,
    )


def _check_per_instrument_attribution(metrics: dict[str, Any]) -> CheckResult:
    """Edge must not be concentrated in a single instrument."""
    concentration = metrics.get("top_instrument_concentration", None)
    if concentration is None:
        return CheckResult(
            check_name="per_instrument_attribution",
            tier=ValidationTier.SILVER,
            result=GateResult.SKIP,
            details="No instrument attribution data",
        )
    passed = concentration < 0.5
    return CheckResult(
        check_name="per_instrument_attribution",
        tier=ValidationTier.SILVER,
        result=GateResult.PASS if passed else GateResult.FAIL,
        details=f"Top instrument concentration: {concentration:.1%} (threshold: <50%)",
        metric_value=concentration,
        threshold=0.5,
    )


def _check_realistic_costs(metrics: dict[str, Any]) -> CheckResult:
    """Profitable after realistic transaction costs including slippage."""
    ev_realistic = metrics.get("ev_realistic_costs", None)
    if ev_realistic is None:
        return CheckResult(
            check_name="realistic_costs",
            tier=ValidationTier.SILVER,
            result=GateResult.SKIP,
            details="No realistic cost data",
        )
    passed = ev_realistic > 0
    return CheckResult(
        check_name="realistic_costs",
        tier=ValidationTier.SILVER,
        result=GateResult.PASS if passed else GateResult.FAIL,
        details=f"EV after realistic costs: {ev_realistic:.4f}",
        metric_value=ev_realistic,
        threshold=0.0,
    )


def _check_exposure_decomposition(metrics: dict[str, Any]) -> CheckResult:
    """Residual alpha after removing known factor exposures."""
    residual_alpha = metrics.get("residual_alpha", None)
    if residual_alpha is None:
        return CheckResult(
            check_name="exposure_decomposition",
            tier=ValidationTier.SILVER,
            result=GateResult.SKIP,
            details="No exposure decomposition data",
        )
    passed = residual_alpha > 0
    return CheckResult(
        check_name="exposure_decomposition",
        tier=ValidationTier.SILVER,
        result=GateResult.PASS if passed else GateResult.FAIL,
        details=f"Residual alpha: {residual_alpha:.4f}",
        metric_value=residual_alpha,
        threshold=0.0,
    )


def run_silver(metrics: dict[str, Any]) -> TierResult:
    """Run all Silver tier checks. Full research validation."""
    checks = [
        _check_walk_forward(metrics),
        _check_regime_decomposition(metrics),
        _check_per_instrument_attribution(metrics),
        _check_realistic_costs(metrics),
        _check_exposure_decomposition(metrics),
    ]
    evaluated = [c for c in checks if c.result != GateResult.SKIP]
    passed = all(c.result == GateResult.PASS for c in evaluated) and len(evaluated) > 0
    return TierResult(tier=ValidationTier.SILVER, passed=passed, checks=checks)


# ---------------------------------------------------------------------------
# Gold tier checks -- false-discovery defense
# ---------------------------------------------------------------------------

def _check_purged_splits(metrics: dict[str, Any]) -> CheckResult:
    """Purged/embargoed cross-validation must show positive alpha."""
    purged_alpha = metrics.get("purged_cv_alpha", None)
    if purged_alpha is None:
        return CheckResult(
            check_name="purged_embargoed_splits",
            tier=ValidationTier.GOLD,
            result=GateResult.SKIP,
            details="No purged CV data",
        )
    passed = purged_alpha > 0
    return CheckResult(
        check_name="purged_embargoed_splits",
        tier=ValidationTier.GOLD,
        result=GateResult.PASS if passed else GateResult.FAIL,
        details=f"Purged CV alpha: {purged_alpha:.4f}",
        metric_value=purged_alpha,
        threshold=0.0,
    )


def _check_locked_holdout(metrics: dict[str, Any]) -> CheckResult:
    """Never-touched holdout set must confirm the edge."""
    holdout_ev = metrics.get("locked_holdout_ev", None)
    if holdout_ev is None:
        return CheckResult(
            check_name="locked_holdout",
            tier=ValidationTier.GOLD,
            result=GateResult.SKIP,
            details="No locked holdout data",
        )
    passed = holdout_ev > 0
    return CheckResult(
        check_name="locked_holdout",
        tier=ValidationTier.GOLD,
        result=GateResult.PASS if passed else GateResult.FAIL,
        details=f"Locked holdout EV: {holdout_ev:.4f}",
        metric_value=holdout_ev,
        threshold=0.0,
    )


def _check_multiple_testing(metrics: dict[str, Any]) -> CheckResult:
    """p-value survives Bonferroni or BH correction for number of strategies tested."""
    corrected_p = metrics.get("corrected_p_value", None)
    if corrected_p is None:
        return CheckResult(
            check_name="multiple_testing_correction",
            tier=ValidationTier.GOLD,
            result=GateResult.SKIP,
            details="No corrected p-value",
        )
    passed = corrected_p < 0.05
    return CheckResult(
        check_name="multiple_testing_correction",
        tier=ValidationTier.GOLD,
        result=GateResult.PASS if passed else GateResult.FAIL,
        details=f"Corrected p-value: {corrected_p:.4f} (threshold: <0.05)",
        metric_value=corrected_p,
        threshold=0.05,
    )


def _check_deflated_sharpe(metrics: dict[str, Any]) -> CheckResult:
    """Deflated Sharpe Ratio / Probability of Backtest Overfitting."""
    dsr = metrics.get("deflated_sharpe_ratio", None)
    if dsr is None:
        return CheckResult(
            check_name="deflated_sharpe_pbo",
            tier=ValidationTier.GOLD,
            result=GateResult.SKIP,
            details="No DSR/PBO data",
        )
    passed = dsr > 0.5
    return CheckResult(
        check_name="deflated_sharpe_pbo",
        tier=ValidationTier.GOLD,
        result=GateResult.PASS if passed else GateResult.FAIL,
        details=f"Deflated Sharpe Ratio: {dsr:.3f} (threshold: >0.5)",
        metric_value=dsr,
        threshold=0.5,
    )


def _check_parameter_stability(metrics: dict[str, Any]) -> CheckResult:
    """Strategy must not be brittle to small parameter changes."""
    stability = metrics.get("parameter_stability", None)
    if stability is None:
        return CheckResult(
            check_name="parameter_stability",
            tier=ValidationTier.GOLD,
            result=GateResult.SKIP,
            details="No parameter stability data",
        )
    passed = stability >= 0.6
    return CheckResult(
        check_name="parameter_stability",
        tier=ValidationTier.GOLD,
        result=GateResult.PASS if passed else GateResult.FAIL,
        details=f"Parameter stability: {stability:.2f} (threshold: >=0.6)",
        metric_value=stability,
        threshold=0.6,
    )


def run_gold(metrics: dict[str, Any]) -> TierResult:
    """Run all Gold tier checks. False-discovery defense."""
    checks = [
        _check_purged_splits(metrics),
        _check_locked_holdout(metrics),
        _check_multiple_testing(metrics),
        _check_deflated_sharpe(metrics),
        _check_parameter_stability(metrics),
    ]
    evaluated = [c for c in checks if c.result != GateResult.SKIP]
    passed = all(c.result == GateResult.PASS for c in evaluated) and len(evaluated) > 0
    return TierResult(tier=ValidationTier.GOLD, passed=passed, checks=checks)


# ---------------------------------------------------------------------------
# Platinum tier checks -- reality check
# ---------------------------------------------------------------------------

def _check_shadow_mode(metrics: dict[str, Any]) -> CheckResult:
    """Shadow mode signals must match backtest expectations."""
    shadow_corr = metrics.get("shadow_sim_correlation", None)
    if shadow_corr is None:
        return CheckResult(
            check_name="shadow_mode",
            tier=ValidationTier.PLATINUM,
            result=GateResult.SKIP,
            details="No shadow mode data",
        )
    passed = shadow_corr >= 0.7
    return CheckResult(
        check_name="shadow_mode",
        tier=ValidationTier.PLATINUM,
        result=GateResult.PASS if passed else GateResult.FAIL,
        details=f"Shadow-sim correlation: {shadow_corr:.3f} (threshold: >=0.7)",
        metric_value=shadow_corr,
        threshold=0.7,
    )


def _check_paper_trading(metrics: dict[str, Any]) -> CheckResult:
    """Paper trading P&L must be positive over minimum window."""
    paper_pnl = metrics.get("paper_trading_pnl", None)
    paper_days = metrics.get("paper_trading_days", 0)
    if paper_pnl is None:
        return CheckResult(
            check_name="paper_trading",
            tier=ValidationTier.PLATINUM,
            result=GateResult.SKIP,
            details="No paper trading data",
        )
    min_days = 7
    if paper_days < min_days:
        return CheckResult(
            check_name="paper_trading",
            tier=ValidationTier.PLATINUM,
            result=GateResult.FAIL,
            details=f"Only {paper_days} paper days (minimum: {min_days})",
            metric_value=float(paper_days),
            threshold=float(min_days),
        )
    passed = paper_pnl > 0
    return CheckResult(
        check_name="paper_trading",
        tier=ValidationTier.PLATINUM,
        result=GateResult.PASS if passed else GateResult.FAIL,
        details=f"Paper P&L: ${paper_pnl:.2f} over {paper_days} days",
        metric_value=paper_pnl,
        threshold=0.0,
    )


def _check_micro_live(metrics: dict[str, Any]) -> CheckResult:
    """Micro-live trading with real money, tiny size."""
    micro_pnl = metrics.get("micro_live_pnl", None)
    micro_trades = metrics.get("micro_live_trades", 0)
    if micro_pnl is None:
        return CheckResult(
            check_name="micro_live",
            tier=ValidationTier.PLATINUM,
            result=GateResult.SKIP,
            details="No micro-live data",
        )
    min_trades = 30
    if micro_trades < min_trades:
        return CheckResult(
            check_name="micro_live",
            tier=ValidationTier.PLATINUM,
            result=GateResult.FAIL,
            details=f"Only {micro_trades} micro-live trades (minimum: {min_trades})",
            metric_value=float(micro_trades),
            threshold=float(min_trades),
        )
    passed = micro_pnl > 0
    return CheckResult(
        check_name="micro_live",
        tier=ValidationTier.PLATINUM,
        result=GateResult.PASS if passed else GateResult.FAIL,
        details=f"Micro-live P&L: ${micro_pnl:.2f} over {micro_trades} trades",
        metric_value=micro_pnl,
        threshold=0.0,
    )


def _check_sim_vs_live(metrics: dict[str, Any]) -> CheckResult:
    """Sim-vs-live discrepancy must be within tolerance."""
    discrepancy = metrics.get("sim_vs_live_discrepancy", None)
    if discrepancy is None:
        return CheckResult(
            check_name="sim_vs_live_comparison",
            tier=ValidationTier.PLATINUM,
            result=GateResult.SKIP,
            details="No sim-vs-live comparison data",
        )
    passed = discrepancy < 0.3
    return CheckResult(
        check_name="sim_vs_live_comparison",
        tier=ValidationTier.PLATINUM,
        result=GateResult.PASS if passed else GateResult.FAIL,
        details=f"Sim-vs-live discrepancy: {discrepancy:.1%} (threshold: <30%)",
        metric_value=discrepancy,
        threshold=0.3,
    )


def run_platinum(metrics: dict[str, Any]) -> TierResult:
    """Run all Platinum tier checks. Reality check."""
    checks = [
        _check_shadow_mode(metrics),
        _check_paper_trading(metrics),
        _check_micro_live(metrics),
        _check_sim_vs_live(metrics),
    ]
    evaluated = [c for c in checks if c.result != GateResult.SKIP]
    passed = all(c.result == GateResult.PASS for c in evaluated) and len(evaluated) > 0
    return TierResult(tier=ValidationTier.PLATINUM, passed=passed, checks=checks)


# ---------------------------------------------------------------------------
# Promotion Gate -- orchestrates all tiers and 5-proof evaluation
# ---------------------------------------------------------------------------

class PromotionGate:
    """Orchestrates the full promotion gate evaluation.

    Runs tiers in order (Bronze -> Silver -> Gold -> Platinum).
    Short-circuits: if a tier fails, higher tiers are not run.
    Also evaluates the 5-proof status from the hypothesis card.
    """

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path) if db_path else None
        if self.db_path:
            self._init_db()

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """CREATE TABLE IF NOT EXISTS promotion_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hypothesis_id TEXT NOT NULL,
                promoted INTEGER NOT NULL,
                result_json TEXT NOT NULL,
                timestamp REAL NOT NULL
            )"""
        )
        conn.commit()
        conn.close()

    def evaluate(
        self,
        card: HypothesisCard,
        metrics: dict[str, Any],
        short_circuit: bool = True,
    ) -> PromotionGateResult:
        """Run the full promotion gate.

        Args:
            card: hypothesis card with 5-proof statuses
            metrics: dict of all metric values used by tier checks
            short_circuit: if True, stop at the first failing tier

        Returns:
            PromotionGateResult with all tier results and final decision
        """
        tier_results: dict[str, TierResult] = {}

        # Run tiers in order
        tiers = [
            ("bronze", run_bronze),
            ("silver", run_silver),
            ("gold", run_gold),
            ("platinum", run_platinum),
        ]

        all_tiers_passed = True
        for tier_name, tier_fn in tiers:
            result = tier_fn(metrics)
            tier_results[tier_name] = result
            if not result.passed:
                all_tiers_passed = False
                if short_circuit:
                    break

        # Check 5-proof status
        all_proofs = card.all_proofs_passed()
        proof_statuses = {k: v.value for k, v in card.proof_statuses().items()}

        # Promoted only if all tiers pass AND all 5 proofs pass
        promoted = all_tiers_passed and all_proofs

        gate_result = PromotionGateResult(
            hypothesis_id=card.hypothesis_id,
            promoted=promoted,
            tier_results=tier_results,
            proof_statuses=proof_statuses,
            notes=self._build_notes(card, all_tiers_passed, all_proofs),
        )

        if self.db_path:
            self._persist(gate_result)

        return gate_result

    def _build_notes(self, card: HypothesisCard, tiers_ok: bool, proofs_ok: bool) -> str:
        parts: list[str] = []
        if not tiers_ok:
            parts.append("BLOCKED: one or more validation tiers failed")
        if not proofs_ok:
            failed = [k for k, v in card.proof_statuses().items() if v != ProofStatus.PASSED]
            parts.append(f"BLOCKED: proofs not passed: {', '.join(failed)}")
        if tiers_ok and proofs_ok:
            parts.append("ALL GATES PASSED: strategy cleared for live deployment")
        return "; ".join(parts)

    def _persist(self, result: PromotionGateResult) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO promotion_results (hypothesis_id, promoted, result_json, timestamp) VALUES (?, ?, ?, ?)",
            (result.hypothesis_id, int(result.promoted), json.dumps(result.to_dict()), result.timestamp),
        )
        conn.commit()
        conn.close()

    def history(self, hypothesis_id: str) -> list[dict[str, Any]]:
        """Retrieve promotion gate history for a hypothesis."""
        if not self.db_path:
            return []
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT result_json, timestamp FROM promotion_results WHERE hypothesis_id = ? ORDER BY timestamp DESC",
            (hypothesis_id,),
        ).fetchall()
        conn.close()
        return [json.loads(row[0]) for row in rows]
