#!/usr/bin/env python3
"""
Automated Kill Rules — Strategy Rejection Discipline
=====================================================
Dispatch: Updated kill criteria for structural alpha validation.

Kill rules are the most important part of the pipeline. A strategy that
passes all kill rules and survives is tradeable. A strategy that fails
any single rule is permanently rejected.

Updated rules per dispatch:
1. Semantic Decay: Lead-lag pair coherence drops below threshold
2. Toxicity Survival: Strategy must survive simulated high-VPIN periods
3. Cost Stress (Polynomial): Accurate fee simulation at extreme probabilities
4. Calibration Enforcement: All LLM probabilities must pass Platt scaling

Legacy rules (still enforced):
5. Minimum signal count (N >= 100 for candidates, 300 for validation)
6. OOS EV must be positive after cost adjustment
7. Regime decay: performance must not degrade under out-of-sample conditions

Author: JJ (autonomous)
Date: 2026-03-07
"""

import logging
import math
from dataclasses import dataclass
from enum import Enum
from typing import Optional

logger = logging.getLogger("JJ.kill_rules")


class KillReason(Enum):
    """Why a strategy was killed."""
    SEMANTIC_DECAY = "semantic_decay"
    TOXICITY_SURVIVAL = "toxicity_survival"
    COST_STRESS = "cost_stress_polynomial"
    CALIBRATION_MISSING = "calibration_not_applied"
    INSUFFICIENT_SIGNALS = "insufficient_signals"
    NEGATIVE_OOS_EV = "negative_oos_ev"
    REGIME_DECAY = "regime_decay"


@dataclass
class KillResult:
    """Result of running kill rules on a strategy."""
    passed: bool
    reason: Optional[KillReason] = None
    detail: str = ""
    metrics: dict = None

    def __post_init__(self):
        if self.metrics is None:
            self.metrics = {}

    def __str__(self):
        if self.passed:
            return "PASS"
        return f"KILL: {self.reason.value} — {self.detail}"


# ---------------------------------------------------------------------------
# Polymarket fee model (polynomial)
# ---------------------------------------------------------------------------

def polymarket_taker_fee(price: float, category: str = "default") -> float:
    """Calculate Polymarket taker fee using the polynomial formula.

    Fee = price * (1 - price) * rate
    Where rate depends on category:
        - crypto: 0.025 (polynomial, exp=2) → max ~1.56% at p=0.50
        - sports: 0.007 (linear, exp=1) → max ~0.44% at p=0.50
        - default: 0.0 (no taker fee on other categories)

    This is the fee the TAKER pays. Makers pay 0%.
    """
    FEE_RATES = {
        "crypto": 0.025,
        "sports": 0.007,
        "default": 0.0,
    }
    rate = FEE_RATES.get(category, 0.0)
    return price * (1.0 - price) * rate


# ---------------------------------------------------------------------------
# Kill Rule Implementations
# ---------------------------------------------------------------------------

def check_semantic_decay(
    semantic_confidence: float,
    threshold: float = 0.3,
) -> KillResult:
    """Kill Rule 1: Semantic Decay.

    If the LLM semantic coherence score for a lead-lag pair drops below
    the threshold, the pair is immediately terminated and liquidated.

    Args:
        semantic_confidence: Current LLM confidence in transmission mechanism
        threshold: Minimum acceptable confidence (default 0.3)
    """
    if semantic_confidence < threshold:
        return KillResult(
            passed=False,
            reason=KillReason.SEMANTIC_DECAY,
            detail=f"Semantic confidence {semantic_confidence:.3f} < {threshold}",
            metrics={"semantic_confidence": semantic_confidence, "threshold": threshold},
        )
    return KillResult(passed=True, metrics={"semantic_confidence": semantic_confidence})


def check_toxicity_survival(
    pnl_under_toxic: float,
    pnl_normal: float,
    max_drawdown_pct: float = 0.50,
) -> KillResult:
    """Kill Rule 2: Toxicity Survival.

    Simulate filling maker orders exclusively during periods where VPIN
    is in the top decile. If the strategy's profitability collapses
    under this simulated high toxicity, permanently reject.

    Args:
        pnl_under_toxic: P&L when only fills during VPIN > 80th percentile
        pnl_normal: P&L under normal conditions
        max_drawdown_pct: Maximum acceptable degradation (default 50%)
    """
    if pnl_normal <= 0:
        return KillResult(
            passed=False,
            reason=KillReason.TOXICITY_SURVIVAL,
            detail=f"Normal P&L is negative: ${pnl_normal:.2f}",
            metrics={"pnl_toxic": pnl_under_toxic, "pnl_normal": pnl_normal},
        )

    degradation = 1.0 - (pnl_under_toxic / pnl_normal) if pnl_normal > 0 else 1.0

    if degradation > max_drawdown_pct:
        return KillResult(
            passed=False,
            reason=KillReason.TOXICITY_SURVIVAL,
            detail=(
                f"Strategy collapses under toxic flow: "
                f"${pnl_under_toxic:.2f} vs ${pnl_normal:.2f} "
                f"({degradation:.0%} degradation > {max_drawdown_pct:.0%} limit)"
            ),
            metrics={
                "pnl_toxic": pnl_under_toxic,
                "pnl_normal": pnl_normal,
                "degradation": degradation,
            },
        )

    return KillResult(
        passed=True,
        metrics={"pnl_toxic": pnl_under_toxic, "pnl_normal": pnl_normal, "degradation": degradation},
    )


def check_cost_stress(
    gross_ev: float,
    avg_price: float,
    category: str = "default",
    execution_latency_ms: float = 5.0,
    slippage_per_ms: float = 0.0001,
) -> KillResult:
    """Kill Rule 3: Cost Stress (Polynomial Fee + Latency).

    Accurately simulates:
    - The polynomial fee scaling at extreme probabilities
    - A standard execution latency penalty (default 5ms)

    A strategy must survive with positive EV after full cost modeling.

    Args:
        gross_ev: Expected value before costs (per trade, dollars)
        avg_price: Average execution price (0-1 range)
        category: Market category for fee lookup
        execution_latency_ms: Expected execution latency in ms
        slippage_per_ms: Price slippage per ms of latency
    """
    # Taker fee at this price point
    taker_fee = polymarket_taker_fee(avg_price, category)

    # Latency cost: slippage proportional to execution delay
    latency_cost = execution_latency_ms * slippage_per_ms

    # Total cost
    total_cost = taker_fee + latency_cost

    # Net EV
    net_ev = gross_ev - total_cost

    if net_ev <= 0:
        return KillResult(
            passed=False,
            reason=KillReason.COST_STRESS,
            detail=(
                f"Negative net EV: gross={gross_ev:.4f} - fee={taker_fee:.4f} "
                f"- latency={latency_cost:.4f} = {net_ev:.4f}"
            ),
            metrics={
                "gross_ev": gross_ev,
                "taker_fee": taker_fee,
                "latency_cost": latency_cost,
                "net_ev": net_ev,
            },
        )

    return KillResult(
        passed=True,
        metrics={"gross_ev": gross_ev, "net_ev": net_ev, "total_cost": total_cost},
    )


def check_calibration_enforcement(
    raw_prob: float,
    calibrated_prob: float,
    platt_a: float = 0.5914,
    platt_b: float = -0.3977,
    tolerance: float = 0.01,
) -> KillResult:
    """Kill Rule 4: Calibration Enforcement.

    Any strategy relying on LLM probabilities that have NOT been passed
    through Platt scaling is automatically rejected.

    Verifies that the calibrated probability matches the expected output
    of the Platt scaling transform.

    Args:
        raw_prob: The raw LLM probability
        calibrated_prob: The probability actually used for sizing
        platt_a: Platt scaling parameter A
        platt_b: Platt scaling parameter B
        tolerance: Acceptable numerical tolerance
    """
    # Compute expected calibrated value
    raw_clamped = max(0.001, min(0.999, raw_prob))
    logit_in = math.log(raw_clamped / (1.0 - raw_clamped))
    logit_out = platt_a * logit_in + platt_b
    logit_out = max(-30, min(30, logit_out))
    expected = 1.0 / (1.0 + math.exp(-logit_out))

    diff = abs(calibrated_prob - expected)

    if diff > tolerance:
        return KillResult(
            passed=False,
            reason=KillReason.CALIBRATION_MISSING,
            detail=(
                f"Calibration mismatch: used={calibrated_prob:.4f} "
                f"expected={expected:.4f} (diff={diff:.4f} > {tolerance})"
            ),
            metrics={
                "raw_prob": raw_prob,
                "calibrated_prob": calibrated_prob,
                "expected_calibrated": expected,
                "diff": diff,
            },
        )

    return KillResult(
        passed=True,
        metrics={"raw_prob": raw_prob, "calibrated_prob": calibrated_prob},
    )


def check_minimum_signals(
    signal_count: int,
    stage: str = "candidate",
) -> KillResult:
    """Kill Rule 5: Minimum Signal Count.

    - Candidate stage: N >= 100
    - Validation stage: N >= 300
    """
    thresholds = {"candidate": 100, "validated": 300}
    required = thresholds.get(stage, 100)

    if signal_count < required:
        return KillResult(
            passed=False,
            reason=KillReason.INSUFFICIENT_SIGNALS,
            detail=f"Only {signal_count} signals ({stage} requires {required})",
            metrics={"signal_count": signal_count, "required": required, "stage": stage},
        )

    return KillResult(passed=True, metrics={"signal_count": signal_count})


def check_oos_ev(
    oos_ev: float,
    in_sample_ev: float,
    min_ratio: float = 0.3,
) -> KillResult:
    """Kill Rule 6: Out-of-Sample EV.

    OOS EV must be positive and at least 30% of in-sample EV.
    """
    if oos_ev <= 0:
        return KillResult(
            passed=False,
            reason=KillReason.NEGATIVE_OOS_EV,
            detail=f"Negative OOS EV: {oos_ev:.4f}",
            metrics={"oos_ev": oos_ev, "in_sample_ev": in_sample_ev},
        )

    if in_sample_ev > 0:
        ratio = oos_ev / in_sample_ev
        if ratio < min_ratio:
            return KillResult(
                passed=False,
                reason=KillReason.REGIME_DECAY,
                detail=(
                    f"OOS/IS ratio too low: {ratio:.2f} < {min_ratio} "
                    f"(OOS={oos_ev:.4f}, IS={in_sample_ev:.4f})"
                ),
                metrics={"oos_ev": oos_ev, "in_sample_ev": in_sample_ev, "ratio": ratio},
            )

    return KillResult(passed=True, metrics={"oos_ev": oos_ev, "in_sample_ev": in_sample_ev})


# ---------------------------------------------------------------------------
# Full Kill Rule Battery
# ---------------------------------------------------------------------------

def run_full_kill_battery(
    semantic_confidence: float = 1.0,
    pnl_under_toxic: float = 0.0,
    pnl_normal: float = 0.0,
    gross_ev: float = 0.0,
    avg_price: float = 0.5,
    category: str = "default",
    raw_prob: float = 0.5,
    calibrated_prob: float = 0.5,
    signal_count: int = 0,
    stage: str = "candidate",
    oos_ev: float = 0.0,
    in_sample_ev: float = 0.0,
    skip_toxicity: bool = False,
    skip_semantic: bool = False,
) -> tuple[bool, list[KillResult]]:
    """Run all kill rules. Returns (all_passed, results_list).

    Any single failure kills the strategy.
    """
    results = []

    if not skip_semantic:
        results.append(("semantic_decay", check_semantic_decay(semantic_confidence)))

    if not skip_toxicity:
        results.append(("toxicity_survival", check_toxicity_survival(pnl_under_toxic, pnl_normal)))

    results.append(("cost_stress", check_cost_stress(gross_ev, avg_price, category)))
    results.append(("calibration", check_calibration_enforcement(raw_prob, calibrated_prob)))
    results.append(("signal_count", check_minimum_signals(signal_count, stage)))
    results.append(("oos_ev", check_oos_ev(oos_ev, in_sample_ev)))

    all_passed = all(r.passed for _, r in results)

    for name, result in results:
        if not result.passed:
            logger.warning(f"KILL [{name}]: {result}")
        else:
            logger.debug(f"PASS [{name}]")

    return all_passed, [r for _, r in results]
